"""
告警引擎
========
加载配置 → 获取数据 → 检查规则 → 发送通知 → 记录状态

独立运行入口: python -m webhook.alerter
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

# 允许从项目根目录导入
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from webhook.config import (
    AlertRules,
    Holding,
    load_rules,
    save_rules,
    load_notifier_config,
    DEFAULT_STATE_PATH,
)
from webhook.notifier import send_notification
from webhook.rules import (
    AlertResult,
    evaluate_all,
    format_alert_message,
)

logger = logging.getLogger("stock-mcp.webhook.alerter")

# A 股代码前缀映射
def code_to_tx_symbol(code: str) -> str:
    """将股票代码转为腾讯行情符号"""
    c = code.strip().upper()
    if c.startswith(("6", "5")):
        return f"sh{c}"
    elif c.startswith(("0", "3", "1")):
        return f"sz{c}"
    elif c.startswith(("4", "8")):
        return f"bj{c}"
    return c


def code_type(code: str) -> str:
    """判断市场类型"""
    c = code.strip().upper()
    if c.startswith(("6", "5", "0", "3", "1", "4", "8")):
        return "a"
    if c.startswith(("HK", "hk")):
        return "hk"
    # 美股字母代码
    if c.isalpha() and len(c) <= 5:
        return "us"
    return "unknown"


# ═══════════════════════════════════════════════════════════
# 数据获取
# ═══════════════════════════════════════════════════════════

def fetch_realtime(code: str) -> dict[str, Any]:
    """通过腾讯 API 获取实时行情"""
    import httpx
    symbol = code_to_tx_symbol(code)
    url = f"https://qt.gtimg.cn/q={symbol}"
    try:
        resp = httpx.get(url, headers={
            "User-Agent": "Mozilla/5.0",
        }, timeout=10)
        resp.encoding = "gbk"
        text = resp.text.strip()
        if "=\"" not in text:
            return {"code": code, "error": "行情数据为空"}

        fields = text.split("=\"")[1].rstrip("\";").split("~")
        if len(fields) < 40:
            return {"code": code, "error": f"字段不足: {len(fields)}"}

        name = fields[1]
        price = _safe_float(fields[3])
        pre_close = _safe_float(fields[4])
        change_pct = _safe_float(fields[32])
        change_amount = _safe_float(fields[31])
        volume = _safe_float(fields[6])  # 手
        amount = _safe_float(fields[37])  # 万
        high = _safe_float(fields[33])
        low = _safe_float(fields[34])
        open_price = _safe_float(fields[5])

        return {
            "code": code,
            "name": name,
            "price": price,
            "pre_close": pre_close,
            "change_pct": change_pct,
            "change_amount": change_amount,
            "volume": volume,
            "amount": amount,
            "high": high,
            "low": low,
            "open": open_price,
            "volume_ratio": _safe_float(fields[39]) if len(fields) > 39 else None,
            "source": "tencent",
        }
    except Exception as e:
        logger.error("获取实时行情失败 %s: %s", code, e)
        return {"code": code, "error": str(e)}


def fetch_kline(code: str, days: int = 120) -> list[dict[str, Any]]:
    """通过新浪 API 获取日 K 线数据"""
    import httpx
    symbol = code_to_tx_symbol(code)
    url = (
        f"https://quotes.sina.cn/cn/api/json_v2.php/"
        f"CN_MarketData.getKLineData?symbol={symbol}&scale=240&ma=no&datalen={days}"
    )
    try:
        resp = httpx.get(url, headers={
            "User-Agent": "Mozilla/5.0",
        }, timeout=15)
        data = resp.json()
        if isinstance(data, list):
            records = []
            for item in data:
                records.append({
                    "date": item.get("day", ""),
                    "open": float(item.get("open", 0)),
                    "high": float(item.get("high", 0)),
                    "low": float(item.get("low", 0)),
                    "close": float(item.get("close", 0)),
                    "volume": float(item.get("volume", 0)),
                })
            return records
        return []
    except Exception as e:
        logger.error("获取 K 线失败 %s: %s", code, e)
        return []


def compute_technical(records: list[dict[str, Any]]) -> dict[str, Any]:
    """简易技术指标计算（MA/MACD/RSI/布林带/评分）"""
    if not records:
        return {"error": "无 K 线数据"}

    closes = [r["close"] for r in records]
    highs = [r["high"] for r in records]
    lows = [r["low"] for r in records]
    volumes = [r["volume"] for r in records]
    price = closes[-1] if closes else 0

    def ma(n):
        return sum(closes[-n:]) / n if len(closes) >= n else closes[-1] if closes else 0

    def ema(n):
        if not closes:
            return []
        multiplier = 2 / (n + 1)
        result = [closes[0]]
        for p in closes[1:]:
            result.append((p - result[-1]) * multiplier + result[-1])
        return result

    # 均线
    ma5 = ma(5)
    ma10 = ma(10)
    ma20 = ma(20)
    ma60 = ma(60) if len(closes) >= 60 else ma20

    # 趋势判断
    if ma5 > ma10 > ma20 and (ma60 > 0 and ma20 > ma60):
        trend_status = "多头排列"
        trend_score = 75
    elif ma5 > ma10 and ma5 > ma20:
        trend_status = "弱势多头"
        trend_score = 55
    elif ma5 < ma10 < ma20:
        trend_status = "空头排列"
        trend_score = 30
    else:
        trend_status = "震荡"
        trend_score = 45

    # MACD
    ema12 = ema(12)
    ema26 = ema(26)
    dif = [ema12[i] - ema26[i] for i in range(min(len(ema12), len(ema26)))]
    dea = []
    if dif:
        multiplier = 2 / 10
        dea = [dif[0]]
        for d in dif[1:]:
            dea.append((d - dea[-1]) * multiplier + dea[-1])
    macd_bar = [dif[i] - dea[i] for i in range(min(len(dif), len(dea)))] if dea else []

    latest_dif = round(dif[-1], 4) if dif else 0
    latest_dea = round(dea[-1], 4) if dea else 0
    latest_bar = round(macd_bar[-1], 4) if macd_bar else 0

    # 金叉/死叉检测
    macd_signal = ""
    if len(dif) >= 2 and len(dea) >= 2:
        if dif[-2] <= dea[-2] and dif[-1] > dea[-1]:
            macd_signal = "金叉"
        elif dif[-2] >= dea[-2] and dif[-1] < dea[-1]:
            macd_signal = "死叉"

    if latest_dif > 0 and latest_bar > 0:
        macd_status = "多头加强" if len(macd_bar) > 1 and latest_bar > abs(macd_bar[-2]) else "多头"
    elif latest_dif > 0:
        macd_status = "多头减弱"
    elif latest_dif < 0 and latest_bar < 0:
        macd_status = "空头加强" if len(macd_bar) > 1 and abs(latest_bar) > abs(macd_bar[-2]) else "空头"
    elif latest_dif < 0:
        macd_status = "空头减弱"
    else:
        macd_status = "中性"

    # RSI(14)
    rsi_value = 50.0
    if len(closes) > 14:
        gains, losses = [], []
        for i in range(-14, 0):
            diff = closes[i] - closes[i - 1]
            gains.append(max(diff, 0))
            losses.append(max(-diff, 0))
        avg_gain = sum(gains) / 14
        avg_loss = sum(losses) / 14
        if avg_loss == 0:
            rsi_value = 100.0
        elif avg_gain == 0:
            rsi_value = 0.0
        else:
            rsi_value = 100 - (100 / (1 + avg_gain / avg_loss))

    rsi_status = "超买" if rsi_value >= 70 else "超卖" if rsi_value <= 30 else \
                 "强势" if rsi_value >= 60 else "弱势" if rsi_value <= 40 else "中性"

    # 布林带(20, 2)
    boll_mid = ma20
    std = 0
    if len(closes) >= 20:
        variance = sum((c - boll_mid) ** 2 for c in closes[-20:]) / 20
        std = variance ** 0.5
        boll_upper = boll_mid + 2 * std
        boll_lower = boll_mid - 2 * std
    else:
        boll_upper = boll_mid * 1.1
        boll_lower = boll_mid * 0.9

    if std and boll_mid:
        bandwidth = ((boll_upper - boll_lower) / boll_mid) * 100
    else:
        bandwidth = 0

    if price > boll_upper:
        boll_position = "上轨之上（超买）"
    elif price < boll_lower:
        boll_position = "下轨之下（超卖）"
    elif price >= boll_mid:
        boll_position = "中轨至上轨"
    else:
        boll_position = "下轨至中轨"

    # 量比（估算）
    avg_volume = sum(volumes[-5:]) / 5 if len(volumes) >= 5 else 1
    volume_ratio = round(volumes[-1] / avg_volume, 2) if avg_volume > 0 else 1.0

    # 乖离率
    bias_ma5 = round((price - ma5) / ma5 * 100, 2) if ma5 > 0 else 0

    # 综合评分
    score = 50
    score += trend_score - 50  # 趋势贡献
    score += 10 if rsi_value in (range(40, 61)) else (5 if rsi_value < 30 else -5)
    if macd_signal == "金叉":
        score += 10
    elif macd_signal == "死叉":
        score -= 10
    score += 5 if boll_position in ("下轨之下（超卖）", "下轨至中轨") else -5
    score = max(0, min(100, int(score)))

    # 建议
    if score >= 70:
        advice = "关注（偏多）"
    elif score >= 55:
        advice = "观望（偏多）"
    elif score >= 40:
        advice = "观望"
    else:
        advice = "谨慎（偏空）"

    return {
        "trend": {
            "status": trend_status,
            "score": int(trend_score),
            "ma5": round(ma5, 3),
            "ma10": round(ma10, 3),
            "ma20": round(ma20, 3),
            "ma60": round(ma60, 3),
        },
        "macd": {
            "dif": latest_dif,
            "dea": latest_dea,
            "bar": latest_bar,
            "status": macd_status,
            "signal": macd_signal,
        },
        "rsi": {
            "value": round(rsi_value, 1),
            "status": rsi_status,
        },
        "bollinger": {
            "upper": round(boll_upper, 3),
            "middle": round(boll_mid, 3),
            "lower": round(boll_lower, 3),
            "bandwidth": round(bandwidth, 2),
            "position": boll_position,
        },
        "volume_ratio": volume_ratio,
        "bias_ma5": bias_ma5,
        "price": price,
        "score": score,
        "advice": advice,
    }


def _safe_float(val: Any) -> Optional[float]:
    """安全转 float"""
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


# ═══════════════════════════════════════════════════════════
# 告警状态管理
# ═══════════════════════════════════════════════════════════

def _load_state(path: str = "") -> dict:
    """加载告警状态（上次触发时间等）"""
    path = path or DEFAULT_STATE_PATH
    try:
        if os.path.exists(path):
            with open(path, "r") as f:
                return json.load(f)
    except Exception as e:
        logger.warning("加载告警状态失败: %s", e)
    return {}


def _save_state(state: dict, path: str = ""):
    """保存告警状态"""
    path = path or DEFAULT_STATE_PATH
    try:
        with open(path, "w") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning("保存告警状态失败: %s", e)


def _should_suppress(
    alert_key: str,
    state: dict,
    cooldown_minutes: int = 60,
) -> bool:
    """检查是否需要抑制重复告警（冷却时间内不重复发）"""
    last_time = state.get("last_alerts", {}).get(alert_key)
    if last_time is None:
        return False
    elapsed = time.time() - last_time
    return elapsed < cooldown_minutes * 60


def _mark_alert_sent(alert_key: str, state: dict):
    """标记告警已发送"""
    state.setdefault("last_alerts", {})[alert_key] = time.time()
    _save_state(state)


# ═══════════════════════════════════════════════════════════
# 主告警流程
# ═══════════════════════════════════════════════════════════

def run_alert_check(
    rules: Optional[AlertRules] = None,
    dry_run: bool = False,
    channel: str = "auto",
) -> dict[str, Any]:
    """执行一次完整的告警检查

    Args:
        rules: 告警规则（默认从文件加载）
        dry_run: 仅检查不发送
        channel: 发送渠道 ("feishu" / "telegram" / "all" / "auto")

    Returns:
        检查结果字典
    """
    if rules is None:
        rules = load_rules()

    notifier_cfg = load_notifier_config()
    state = _load_state()
    now = datetime.now(timezone(timedelta(hours=8)))
    all_alerts = AlertResult()
    stats = {"checked": 0, "errors": 0, "alerts": 0, "suppressed": 0}

    # ── 检查持仓 + 观察池 ──
    targets = [(h, "holding") for h in rules.holdings]
    targets += [(h, "watchlist") for h in rules.watchlist]

    for holding, category in targets:
        code = holding.code
        stats["checked"] += 1

        try:
            # 获取实时行情
            quote = fetch_realtime(code)
            if "error" in quote and quote.get("price") is None:
                stats["errors"] += 1
                logger.warning("获取 %s 行情失败: %s", code, quote.get("error"))
                continue

            # 获取 K 线并计算技术指标
            records = fetch_kline(code, days=120)
            technical = compute_technical(records) if records else {"error": "无K线数据"}

            # 简易 ST 风险检查
            name = quote.get("name", holding.name)
            st_report = _simple_st_risk(name, quote)

            # 评估所有规则
            result = evaluate_all(holding, quote, st_report, technical, rules)

            # 应用抑制（同一只同类型告警 1 小时内不重复）
            for alert in result.alerts:
                alert_key = f"{alert.type}:{alert.code}"
                if _should_suppress(alert_key, state, 60):
                    stats["suppressed"] += 1
                    continue
                _mark_alert_sent(alert_key, state)
                all_alerts.add(alert)

        except Exception as e:
            stats["errors"] += 1
            logger.error("检查 %s 异常: %s", code, e)

    # ── 检查 ETF 池 ──
    for holding in rules.etf_pool:
        # 跳过已在持仓中的（避免重复）
        if any(h.code == holding.code for h in rules.holdings):
            continue
        if any(h.code == holding.code for h in rules.watchlist):
            continue

        code = holding.code
        stats["checked"] += 1

        try:
            quote = fetch_realtime(code)
            if "error" in quote and quote.get("price") is None:
                continue

            records = fetch_kline(code, days=120)
            technical = compute_technical(records) if records else {"error": "无K线数据"}
            name = quote.get("name", holding.name)
            st_report = _simple_st_risk(name, quote)

            result = evaluate_all(holding, quote, st_report, technical, rules)

            for alert in result.alerts:
                alert_key = f"{alert.type}:{alert.code}"
                if _should_suppress(alert_key, state, 120):  # ETF 信号冷却 2h
                    stats["suppressed"] += 1
                    continue
                _mark_alert_sent(alert_key, state)
                all_alerts.add(alert)

        except Exception as e:
            logger.error("检查 ETF %s 异常: %s", code, e)

    # ── 发送通知 ──
    stats["alerts"] = len(all_alerts.alerts)

    if all_alerts.has_alerts:
        title = "🚨 持仓预警"
        if all_alerts.max_level >= 3:
            title = "🔴 紧急预警"
        elif all_alerts.max_level >= 2:
            title = "🟠 重点预警"

        message = format_alert_message(all_alerts, title=title)

        if not dry_run:
            send_results = send_notification(
                content=message,
                title=title,
                channel=channel,
                config=notifier_cfg,
            )
            return {
                "status": "alerts_sent",
                "alerts": [
                    {
                        "type": a.type,
                        "level": a.level,
                        "code": a.code,
                        "name": a.name,
                        "detail": a.detail,
                    }
                    for a in all_alerts.alerts
                ],
                "stats": stats,
                "send_results": send_results,
                "message": message,
            }

        return {
            "status": "dry_run",
            "alerts": [
                {
                    "type": a.type,
                    "level": a.level,
                    "code": a.code,
                    "name": a.name,
                    "detail": a.detail,
                }
                for a in all_alerts.alerts
            ],
            "stats": stats,
            "message": message,
        }

    return {
        "status": "no_alerts",
        "alerts": [],
        "stats": stats,
        "message": "",
    }


def _simple_st_risk(
    name: str,
    quote: dict[str, Any],
) -> dict[str, Any]:
    """简易 ST 风险判断（基于名称和行情）"""
    name_upper = name.upper()
    st_status = None
    if "退市" in name_upper:
        st_status = "退市"
    elif name_upper.startswith("*ST"):
        st_status = "*ST"
    elif name_upper.startswith("ST"):
        st_status = "ST"

    signals = []

    if st_status:
        signals.append({
            "dimension": "ST/退市状态",
            "level": 3,
            "level_name": "高风险",
            "detail": f"股票当前状态为「{st_status}」",
            "suggestion": f"{st_status}股票风险极高，建议回避",
        })

    price = quote.get("price")
    if price is not None and price < 1.0 and price > 0:
        # ETF 不适用面值退市
        if not any(code in quote.get("code", "") for code in []):
            pass  # 不标记 ETF 面值退市

    if not signals:
        signals.append({
            "dimension": "综合评估",
            "level": 0,
            "level_name": "正常",
            "detail": f"{name} 当前无明显ST/退市风险信号",
            "suggestion": "正常交易",
        })

    return {
        "max_level": max((s["level"] for s in signals), default=0),
        "level_name": "正常",
        "is_st": bool(st_status),
        "signals": signals,
        "signal_count": len(signals),
    }


# ═══════════════════════════════════════════════════════════
# CLI 入口
# ═══════════════════════════════════════════════════════════

if __name__ == "__main__":
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    parser = argparse.ArgumentParser(description="stock-mcp 告警检查")
    parser.add_argument("--dry-run", action="store_true", help="仅检查不发送")
    parser.add_argument("--channel", default="auto", help="发送渠道")
    parser.add_argument("--config", default="", help="告警规则配置文件路径")
    parser.add_argument("--rules-path", default="", help="告警规则 JSON 路径")
    args = parser.parse_args()

    rules = load_rules(args.rules_path or args.config)
    result = run_alert_check(
        rules=rules,
        dry_run=args.dry_run,
        channel=args.channel,
    )

    print(json.dumps(result, ensure_ascii=False, indent=2))
