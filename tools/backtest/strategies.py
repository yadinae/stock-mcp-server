"""
策略信号生成器 — 5 种内置策略

所有策略接收 K 线数据 (records)，返回买卖信号列表。
信号格式: {"date": str, "action": "buy"|"sell", "price": float, "reason": str}

策略命名规范：
- 函数名 = 策略标识（用于 strategy 参数匹配）
- 返回值永远为 list[dict]
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from tools.technical import calc_ma, calc_macd, calc_rsi, calc_bollinger

logger = logging.getLogger("stock-mcp.backtest.strategies")

# ── 信号类型 ──────────────────────────────────────────────

Signal = dict[str, Any]
# {"date": str, "action": "buy"|"sell", "price": float, "reason": str}


def _safe_close(records: list[dict], idx: int) -> float:
    """安全获取收盘价"""
    try:
        return float(records[idx].get("close", 0))
    except (IndexError, TypeError, ValueError):
        return 0.0


# ── 策略 1: MA 金叉/死叉 ─────────────────────────────────


def ma_crossover(records: list[dict], fast: int = 5, slow: int = 20) -> list[Signal]:
    """MA 金叉/死叉策略

    - 快线上穿慢线 (fast > slow 且昨日 fast <= slow) → 买入信号 (收盘确认)
    - 快线下穿慢线 (fast < slow 且昨日 fast >= slow) → 卖出信号 (收盘确认)
    - 信号在当日收盘确认，交易在次日开盘执行

    最少需要 slow+1 条数据。
    """
    if len(records) < slow + 2:
        return [{"action": "hold", "reason": f"数据不足（需要{slow+2}条）"}]

    signals = []
    # 从 slow 索引开始计算（确保有前值）
    for i in range(slow, len(records)):
        current_window = records[:i + 1]
        prev_window = records[:i]

        ma_fast = calc_ma(current_window, fast)
        ma_slow = calc_ma(current_window, slow)
        ma_fast_prev = calc_ma(prev_window, fast)
        ma_slow_prev = calc_ma(prev_window, slow)

        if ma_fast == 0 or ma_slow == 0:
            continue

        price = _safe_close(records, i)
        if price == 0:
            continue

        prev_cross = ma_fast_prev - ma_slow_prev
        curr_cross = ma_fast - ma_slow

        # 金叉：之前 fast <= slow，现在 fast > slow
        if prev_cross <= 0 < curr_cross:
            signals.append({
                "date": records[i].get("date", ""),
                "action": "buy",
                "price": price,
                "reason": f"MA金叉: MA{fast}={ma_fast:.2f} 上穿 MA{slow}={ma_slow:.2f}",
            })

        # 死叉：之前 fast >= slow，现在 fast < slow
        elif prev_cross >= 0 > curr_cross:
            signals.append({
                "date": records[i].get("date", ""),
                "action": "sell",
                "price": price,
                "reason": f"MA死叉: MA{fast}={ma_fast:.2f} 下穿 MA{slow}={ma_slow:.2f}",
            })

    return signals


# ── 策略 2: MACD ─────────────────────────────────────────


def macd_crossover(records: list[dict]) -> list[Signal]:
    """MACD 策略

    - DIF 上穿 DEA (金叉) → 买入
    - DIF 下穿 DEA (死叉) → 卖出
    """
    closes = [r["close"] for r in records if r.get("close")]
    if len(closes) < 26:
        return [{"action": "hold", "reason": "数据不足（需要26条）"}]

    signals = []
    # 利用 calc_macd 每次调用计算当前值，逐日检测金叉/死叉
    for i in range(25, len(closes)):
        current_closes = closes[:i + 1]
        prev_closes = closes[:i]

        cur = calc_macd(current_closes)
        prev = calc_macd(prev_closes)

        if cur.get("signal") == "金叉" and prev.get("signal") != "金叉":
            signals.append({
                "date": records[i].get("date", ""),
                "action": "buy",
                "price": closes[i],
                "reason": f"MACD金叉: DIF={cur['dif']:.3f} 上穿 DEA={cur['dea']:.3f}",
            })
        elif cur.get("signal") == "死叉" and prev.get("signal") != "死叉":
            signals.append({
                "date": records[i].get("date", ""),
                "action": "sell",
                "price": closes[i],
                "reason": f"MACD死叉: DIF={cur['dif']:.3f} 下穿 DEA={cur['dea']:.3f}",
            })

    return signals


# ── 策略 3: RSI 均值回归 ───────────────────────────────


def rsi_mean_reversion(records: list[dict], oversold: int = 30,
                       overbought: int = 70) -> list[Signal]:
    """RSI 均值回归策略

    - RSI 从超卖区(<30)回升 → 买入
    - RSI 从超买区(>70)回落 → 卖出
    """
    closes = [r["close"] for r in records if r.get("close")]
    if len(closes) < 15:
        return [{"action": "hold", "reason": "数据不足（需要15条）"}]

    signals = []
    for i in range(14, len(closes)):
        cur = calc_rsi(closes[:i + 1], 14)
        prev = calc_rsi(closes[:i], 14)
        cur_val = cur.get("value", 50)
        prev_val = prev.get("value", 50)

        # 从超卖回升
        if prev_val < oversold and cur_val >= oversold:
            signals.append({
                "date": records[i].get("date", ""),
                "action": "buy",
                "price": closes[i],
                "reason": f"RSI回升: {prev_val:.1f}→{cur_val:.1f} 突破超卖线{oversold}",
            })
        # 从超买回落
        elif prev_val > overbought and cur_val <= overbought:
            signals.append({
                "date": records[i].get("date", ""),
                "action": "sell",
                "price": closes[i],
                "reason": f"RSI回落: {prev_val:.1f}→{cur_val:.1f} 跌破超买线{overbought}",
            })

    return signals


# ── 策略 4: 布林带反击 ─────────────────────────────────


def bollinger_bounce(records: list[dict]) -> list[Signal]:
    """布林带反弹策略

    - 价格触下轨后反弹 (当日 close >= lower 且前日 < lower) → 买入
    - 价格触上轨后回落 (当日 close <= upper 且前日 > upper) → 卖出
    """
    if len(records) < 21:
        return [{"action": "hold", "reason": "数据不足（需要21条）"}]

    signals = []
    for i in range(20, len(records)):
        cur_window = records[:i + 1]
        prev_window = records[:i]

        cur_bb = calc_bollinger(cur_window, 20)
        prev_bb = calc_bollinger(prev_window, 20)

        price = _safe_close(records, i)
        prev_price = _safe_close(records, i - 1)

        upper = cur_bb.get("upper", 0)
        lower = cur_bb.get("lower", 0)
        prev_upper = prev_bb.get("upper", 0)
        prev_lower = prev_bb.get("lower", 0)

        if lower == 0 or upper == 0:
            continue

        # 触下轨反弹
        if prev_price < prev_lower and price >= lower:
            signals.append({
                "date": records[i].get("date", ""),
                "action": "buy",
                "price": price,
                "reason": f"布林带下轨反弹: 下轨={lower:.2f}",
            })
        # 触上轨回落
        elif prev_price > prev_upper and price <= upper:
            signals.append({
                "date": records[i].get("date", ""),
                "action": "sell",
                "price": price,
                "reason": f"布林带上轨回落: 上轨={upper:.2f}",
            })

    return signals


# ── 策略 5: 组合信号 ────────────────────────────────────


def combined_signals(records: list[dict]) -> list[Signal]:
    """组合信号策略（多信号加权）

    权重分配:
    - MA趋势: 40%  (MA5>MA20 偏多, MA5<MA20 偏空)
    - MACD:   30%  (金叉/死叉信号)
    - RSI:    30%  (RSI<40偏多, RSI>60偏空)

    总分 > 60 → 买入, 总分 < 40 → 卖出
    仅在有显著变化时发信号（减少假信号）。
    """
    closes = [r["close"] for r in records if r.get("close")]
    if len(closes) < 26:
        return [{"action": "hold", "reason": "数据不足"}]

    signals = []
    prev_score = 50  # 中性

    for i in range(25, len(records)):
        window = records[:i + 1]
        price = _safe_close(records, i)

        # MA 贡献
        ma5 = calc_ma(window, 5)
        ma20 = calc_ma(window, 20)
        ma_score = 0
        if ma5 > ma20 and ma20 > 0:
            # 多头，值越大越多: 40-80
            ratio = min((ma5 - ma20) / ma20 * 100, 10) / 10  # 0~1
            ma_score = 40 + ratio * 40
        elif ma20 > 0:
            ratio = min((ma20 - ma5) / ma20 * 100, 10) / 10
            ma_score = 40 - ratio * 40

        # MACD 贡献
        macd = calc_macd(closes[:i + 1])
        macd_score = 0
        if macd.get("signal") == "金叉":
            macd_score = 30
        elif macd.get("signal") == "死叉":
            macd_score = 0
        else:
            macd_score = 15  # 中性

        # RSI 贡献
        rsi = calc_rsi(closes[:i + 1], 14)
        rsi_val = rsi.get("value", 50)
        if rsi_val < 30:
            rsi_score = 30  # 超卖 = 买入机会
        elif rsi_val < 50:
            rsi_score = 20
        elif rsi_val < 70:
            rsi_score = 10
        else:
            rsi_score = 0  # 超买 = 卖出机会

        total_score = ma_score * 0.4 + macd_score * 0.3 + rsi_score * 0.3

        # 仅在跨过阈值并且变化显著时发信号
        if prev_score <= 60 and total_score > 60:
            signals.append({
                "date": records[i].get("date", ""),
                "action": "buy",
                "price": price,
                "reason": f"组合信号看多: 总分{total_score:.0f} (MA={ma_score:.0f} MACD={macd_score:.0f} RSI={rsi_score:.0f})",
            })
        elif prev_score >= 40 and total_score < 40:
            signals.append({
                "date": records[i].get("date", ""),
                "action": "sell",
                "price": price,
                "reason": f"组合信号看空: 总分{total_score:.0f} (MA={ma_score:.0f} MACD={macd_score:.0f} RSI={rsi_score:.0f})",
            })

        prev_score = total_score

    return signals


# ── 策略注册表 ──────────────────────────────────────────

STRATEGY_REGISTRY: dict[str, Callable] = {
    "ma_crossover": ma_crossover,
    "macd": macd_crossover,
    "rsi": rsi_mean_reversion,
    "bollinger": bollinger_bounce,
    "combined": combined_signals,
}

STRATEGY_NAMES = {
    "ma_crossover": "MA金叉/死叉",
    "macd": "MACD金叉/死叉",
    "rsi": "RSI均值回归",
    "bollinger": "布林带反弹",
    "combined": "组合信号",
}

STRATEGY_DEFAULT_PARAMS = {
    "ma_crossover": {"fast": 5, "slow": 20},
    "macd": {},
    "rsi": {"oversold": 30, "overbought": 70},
    "bollinger": {},
    "combined": {},
}


def list_strategies() -> list[dict[str, Any]]:
    """列出所有可用策略"""
    return [
        {
            "id": sid,
            "name": STRATEGY_NAMES.get(sid, sid),
            "params": STRATEGY_DEFAULT_PARAMS.get(sid, {}),
        }
        for sid in sorted(STRATEGY_REGISTRY.keys())
    ]


def get_strategy(sid: str) -> Callable | None:
    """按 ID 获取策略函数"""
    return STRATEGY_REGISTRY.get(sid)


def run_strategy(sid: str, records: list[dict], **kwargs) -> list[Signal]:
    """运行指定策略，返回信号列表"""
    fn = get_strategy(sid)
    if fn is None:
        return [{"action": "hold", "reason": f"未知策略: {sid}"}]
    return fn(records, **kwargs)
