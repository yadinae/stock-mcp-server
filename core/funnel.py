"""
漏斗引擎 — 逐层收窄的选股流水线

MVP 两个核心 Stage:
  Stage 1: 基础筛选（流动性 + ST排除 + 停牌排除）
  Stage 2: 技术面多通道筛选（趋势/反转/突破/吸筹）

数据源:
  - 东财 push2: 全市场 A 股列表 + 实时行情
  - baostock 缓存: 历史 K 线（用于均线/量能计算）
"""
from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("stock-mcp.funnel")

_BAOSTOCK_DB = Path(__file__).parent.parent / "data" / "baostock_cache.db"


# ═══════════════════════════════════════════════════════════════
# 数据获取
# ═══════════════════════════════════════════════════════════════

def fetch_a_share_universe(page_size: int = 5000) -> List[dict]:
    """
    从东财 push2 API 获取全市场 A 股列表

    返回: [{code, name, price, change_pct, volume, amount, high, low, open, ...}]
    """
    import httpx

    url = "https://push2.eastmoney.com/api/qt/clist/get"
    params = {
        "pn": 1,
        "pz": page_size,
        "po": 1,  # 降序
        "np": 1,
        "fltt": 2,
        "invt": 2,
        "fid": "f6",  # 按成交额排序
        "fs": "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23",  # 沪深 A 股
        "fields": "f2,f3,f4,f5,f6,f7,f12,f14,f15,f16,f17,f18",
    }
    try:
        resp = httpx.get(url, params=params, timeout=15)
        data = resp.json().get("data", {})
        total = data.get("total", 0)
        diff = data.get("diff", [])

        stocks = []
        for item in diff:
            code = item.get("f12", "")
            if not code:
                continue
            stocks.append({
                "code": code,
                "name": item.get("f14", ""),
                "price": item.get("f2"),
                "change_pct": round(item["f3"] / 100, 2) if item.get("f3") is not None else None,
                "change_amount": item.get("f4"),
                "volume": item.get("f5"),
                "amount": item.get("f6"),
                "amplitude": round(item["f7"] / 100, 2) if item.get("f7") is not None else None,
                "high": item.get("f15"),
                "low": item.get("f16"),
                "open": item.get("f17"),
                "pre_close": item.get("f18"),
                "source": "eastmoney",
            })

        logger.info("Fetched %d A-shares (total: %d)", len(stocks), total)
        return stocks
    except Exception as e:
        logger.error("Failed to fetch A-share universe: %s", e)
        return []


def enrich_with_baostock(stocks: List[dict], min_bars: int = 60) -> List[dict]:
    """
    用 baostock 本地缓存补充均线和量能数据

    对每只股票查询最近 N 天 K 线，计算:
    - ma50, ma200: 均线
    - volume_avg_20: 20 日均量
    - volume_ratio: 量比（当日量 / 20日均量）
    - dist_from_year_low_pct: 距年低百分比
    """
    if not _BAOSTOCK_DB.exists():
        logger.warning("Baostock cache not found, skipping enrichment")
        return stocks

    conn = sqlite3.connect(str(_BAOSTOCK_DB))
    try:
        for s in stocks:
            code = s.get("code", "")
            try:
                rows = conn.execute(
                    "SELECT date, open, high, low, close, volume "
                    "FROM stock_daily WHERE symbol = ? ORDER BY date DESC LIMIT ?",
                    (code, 250),
                ).fetchall()

                if len(rows) < min_bars:
                    continue

                # 计算均线
                closes = [r[4] for r in rows if r[4]]
                volumes = [r[5] for r in rows if r[5]]

                if len(closes) >= 50:
                    s["ma50"] = sum(closes[:50]) / 50
                if len(closes) >= 200:
                    s["ma200"] = sum(closes[:200]) / 200

                # 量比
                if len(volumes) >= 20:
                    avg_vol_20 = sum(volumes[:20]) / 20
                    s["volume_avg_20"] = avg_vol_20
                    today_vol = volumes[0] if volumes else 0
                    s["volume_ratio"] = round(today_vol / avg_vol_20, 2) if avg_vol_20 > 0 else 0

                # 距年低
                year_lows = [r[3] for r in rows[:250] if r[3]]
                if year_lows:
                    min_low = min(year_lows)
                    current = s.get("price") or (closes[0] if closes else 0)
                    if min_low > 0 and current > 0:
                        s["dist_from_year_low_pct"] = round(
                            (current - min_low) / min_low * 100, 1
                        )

                # 20 日涨跌幅
                if len(closes) >= 20:
                    s["change_pct_20d"] = round(
                        (closes[0] - closes[19]) / closes[19] * 100, 2
                    ) if closes[19] else 0

                # RPS120（简化版：120日涨幅在全市场的排位百分比）
                if len(closes) >= 120:
                    s["return_120d"] = round(
                        (closes[0] - closes[119]) / closes[119] * 100, 2
                    ) if closes[119] else 0

            except Exception as e:
                logger.debug("Baostock enrichment failed for %s: %s", code, e)
                continue
    finally:
        conn.close()

    logger.info("Enriched %d stocks with baostock data", len(stocks))
    return stocks


# ═══════════════════════════════════════════════════════════════
# Stage 1: 基础筛选
# ═══════════════════════════════════════════════════════════════

def _is_st_stock(name: str) -> bool:
    """检测 ST 股票"""
    return "*ST" in name or "ST" in name or "st" in name.lower()


def _is_suspended(stock: dict) -> bool:
    """检测停牌（价格为 0 或 None）"""
    price = stock.get("price")
    return price is None or price == 0


def stage_basic_filter(stocks: List[dict], ctx: dict) -> List[dict]:
    """
    Stage 1: 基础筛选

    过滤条件:
    1. 排除 ST / *ST / 退市股
    2. 排除停牌股（价格为 0）
    3. 流动性过滤（成交额 > 阈值）
    4. 排除价格异常（价格 < 1 元的低价股）
    """
    min_amount = ctx.get("min_amount", 5_000_000)  # 默认 500 万
    min_price = ctx.get("min_price", 1.0)  # 默认 1 元

    results = []
    for s in stocks:
        name = s.get("name", "")
        price = s.get("price") or 0
        amount = s.get("amount") or 0

        # ST 排除
        if _is_st_stock(name):
            continue

        # 停牌排除
        if _is_suspended(s):
            continue

        # 价格过滤
        if price < min_price:
            continue

        # 流动性过滤
        if amount < min_amount:
            continue

        results.append(s)

    logger.info("[basic_filter] %d → %d (min_amount=%d)", len(stocks), len(results), min_amount)
    return results


# ═══════════════════════════════════════════════════════════════
# Stage 2: 技术面多通道筛选
# ═══════════════════════════════════════════════════════════════

def _check_trend_channel(s: dict) -> bool:
    """趋势通道：MA50 > MA200 + 120日涨幅排名靠前"""
    ma50 = s.get("ma50")
    ma200 = s.get("ma200")
    return_120d = s.get("return_120d", 0)

    if not ma50 or not ma200:
        return False

    return ma50 > ma200 and return_120d >= 20


def _check_reversal_channel(s: dict) -> bool:
    """反转通道：20日大跌后企稳"""
    change_pct_20d = s.get("change_pct_20d", 0)
    today_change = s.get("change_pct", 0)
    volume_ratio = s.get("volume_ratio", 1)

    # 20日跌幅 > 10% + 今日小涨 + 放量
    return (change_pct_20d or 0) < -10 and (today_change or 0) > 0 and volume_ratio > 1.2


def _check_breakout_channel(s: dict) -> bool:
    """突破通道：放量突破（量比 > 2 + 涨幅 > 3%）"""
    volume_ratio = s.get("volume_ratio", 0)
    change_pct = s.get("change_pct", 0)
    price = s.get("price") or 0
    high = s.get("high") or 0

    if not all([price, high]):
        return False

    # 价格接近最高价（回撤 < 1%）+ 放量
    near_high = (high - price) / high < 0.01 if high > 0 else False
    return volume_ratio > 2.0 and (change_pct or 0) > 3 and near_high


def _check_accumulation_channel(s: dict) -> bool:
    """吸筹通道：距年低 < 45% + 缩量"""
    dist = s.get("dist_from_year_low_pct", 100)
    volume_ratio = s.get("volume_ratio", 1)

    return (dist or 100) <= 45 and volume_ratio < 0.75


# 通道注册表
CHANNELS = {
    "trend": ("趋势通道", _check_trend_channel),
    "reversal": ("反转通道", _check_reversal_channel),
    "breakout": ("突破通道", _check_breakout_channel),
    "accumulation": ("吸筹通道", _check_accumulation_channel),
}


def stage_technical_multi_channel(stocks: List[dict], ctx: dict) -> List[dict]:
    """
    Stage 2: 技术面多通道筛选

    借鉴 Wyckoff 八通道思想：不同市场位置用不同策略。
    至少一个通道通过即入选，记录通过了哪些通道。
    """
    min_channels = ctx.get("min_channels", 1)

    results = []
    channel_counts = {name: 0 for name in CHANNELS}

    for s in stocks:
        passed = []
        for ch_name, (_, check_fn) in CHANNELS.items():
            try:
                if check_fn(s):
                    passed.append(ch_name)
                    channel_counts[ch_name] += 1
            except Exception as e:
                logger.debug("Channel %s check failed for %s: %s", ch_name, s.get("code"), e)

        if len(passed) >= min_channels:
            s["channels"] = passed
            s["channel_count"] = len(passed)
            results.append(s)

    logger.info("[technical] %d → %d", len(stocks), len(results))
    for ch_name, count in channel_counts.items():
        logger.info("  channel %s: %d passed", ch_name, count)

    return results


# ═══════════════════════════════════════════════════════════════
# 综合评分（MVP 简化版）
# ═══════════════════════════════════════════════════════════════

def stage_ranking(stocks: List[dict], ctx: dict) -> List[dict]:
    """
    Stage 3: 综合评分与排序

    MVP 简化版：按通道数 + 成交额加权排序
    """
    for s in stocks:
        channel_count = s.get("channel_count", 0)
        amount = s.get("amount") or 0
        # 通道数权重 70% + 成交额权重 30%
        amount_score = min(amount / 100_000_000, 10)  # 成交额标准化到 0-10
        s["funnel_score"] = channel_count * 7 + amount_score * 3

    stocks.sort(key=lambda x: x.get("funnel_score", 0), reverse=True)

    # 行业分散：同名前缀最多 2 只
    max_per_prefix = ctx.get("max_per_prefix", 2)
    prefix_count: Dict[str, int] = {}
    filtered = []
    for s in stocks:
        # 简化：用代码前两位作为"行业"近似
        prefix = s.get("code", "")[:2]
        if prefix_count.get(prefix, 0) < max_per_prefix:
            filtered.append(s)
            prefix_count[prefix] = prefix_count.get(prefix, 0) + 1

    logger.info("[ranking] %d → %d (diversified)", len(stocks), len(filtered))
    return filtered


# ═══════════════════════════════════════════════════════════════
# Stage 3: 资金面筛选（可选）
# ═══════════════════════════════════════════════════════════════

def stage_fund_flow(stocks: List[dict], ctx: dict) -> List[dict]:
    """
    Stage 3: 资金面筛选

    过滤条件:
    1. 成交额 > 阈值（流动性门槛）
    2. 量比 > 1（放量）
    3. 振幅合理（非异常波动）
    """
    min_amount = ctx.get("fund_min_amount", 100_000_000)  # 默认 1 亿
    min_volume_ratio = ctx.get("fund_min_volume_ratio", 1.0)

    results = []
    for s in stocks:
        amount = s.get("amount") or 0
        volume_ratio = s.get("volume_ratio") or 1
        amplitude = s.get("amplitude") or 0

        # 流动性门槛
        if amount < min_amount:
            continue

        # 放量确认
        if volume_ratio < min_volume_ratio:
            continue

        # 振幅过滤（排除异常波动 > 15%）
        if amplitude > 15:
            continue

        results.append(s)

    logger.info("[fund_flow] %d → %d", len(stocks), len(results))
    return results


# ═══════════════════════════════════════════════════════════════
# Stage 4: 基本面筛选（可选）
# ═══════════════════════════════════════════════════════════════

def stage_fundamental(stocks: List[dict], ctx: dict) -> List[dict]:
    """
    Stage 4: 基本面筛选

    过滤条件（简化版）:
    1. 价格 > 5 元（排除低价股）
    2. 距年低 > 10%（非深度套牢）
    3. 120日涨幅 < 100%（排除过度炒作）
    """
    min_price = ctx.get("fund_price_min", 5.0)
    max_return_120d = ctx.get("fund_max_return_120d", 100)

    results = []
    for s in stocks:
        price = s.get("price") or 0
        dist_low = s.get("dist_from_year_low_pct") or 0
        return_120d = s.get("return_120d") or 0

        if price < min_price:
            continue
        if dist_low < 10:
            continue
        if return_120d > max_return_120d:
            continue

        results.append(s)

    logger.info("[fundamental] %d → %d", len(stocks), len(results))
    return results


# ═══════════════════════════════════════════════════════════════
# 资金流数据补充（可选）
# ═══════════════════════════════════════════════════════════════

def enrich_with_fund_flow(stocks: List[dict], max_stocks: int = 50) -> List[dict]:
    """
    用东财资金流数据补充主力净流入信息

    只对前 N 只股票查询（避免 API 限流）
    """
    try:
        from data_sources.em_fundflow import get_fund_flow_120d
    except ImportError:
        logger.warning("em_fundflow not available, skipping fund flow enrichment")
        return stocks

    enriched = 0
    for s in stocks[:max_stocks]:
        code = s.get("code", "")
        if not code:
            continue
        try:
            flow_data = get_fund_flow_120d(code, days=20)
            if "error" not in flow_data:
                s["main_net_20d_yi"] = flow_data.get("total_main_net_yi", 0)
                # 最近5日主力净流入
                recent_flow = flow_data.get("flow", [])
                if isinstance(recent_flow, list):
                    s["main_net_5d"] = sum(f.get("main_net", 0) for f in recent_flow[:5])
                enriched += 1
        except Exception as e:
            logger.debug("Fund flow enrichment failed for %s: %s", code, e)

    logger.info("Enriched %d stocks with fund flow data", enriched)
    return stocks
