"""
漏斗引擎 v2 — 向量化重写

核心变化（参考 vectorbt 向量化思路）：
- enrich_with_baostock: 单次批量 SQL 查询 + pandas rolling 计算，替代 N 次逐股查询
- 所有 Stage 函数: DataFrame 布尔掩码替代 Python for 循环
- 均线/量比/涨跌幅计算全部使用 pandas 向量化操作

性能预期：
- enrich_with_baostock: ~10-50x 提速（消除 N 次 SQLite I/O + Python 循环）
- stage_basic_filter: ~5-10x 提速（布尔掩码 vs 逐条判断）
- stage_technical_multi_channel: ~3-5x 提速（向量化通道检测）
"""
from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

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
    向量化版：用 baostock 内存缓存补充均线和量能数据

    核心优化：
    1. 使用 BaostockMemoryCache 内存缓存（首次加载后 0 I/O）
    2. 用 pandas rolling 向量化计算均线/量比/涨跌幅
    3. 消除 N 次逐股 SQLite I/O + Python 循环
    """
    if not stocks:
        return stocks

    from core.baostock_cache import BaostockMemoryCache
    cache = BaostockMemoryCache.instance()

    if cache.symbol_count() == 0:
        logger.warning("Baostock memory cache empty, skipping enrichment")
        return stocks

    # ── 从内存缓存批量获取数据 ──
    codes = [s.get("code", "") for s in stocks if s.get("code")]
    if not codes:
        return stocks

    batch = cache.get_batch(codes)
    if not batch:
        logger.info("No baostock data found for %d codes", len(codes))
        return stocks

    # ── 向量化计算均线/量比/涨跌幅 ──
    enriched_map = {}

    for symbol, df in batch.items():
        # df 已按 date 降序排列，取最近 250 条
        df = df.head(250)
        closes = df["close"].values
        volumes = df["volume"].values
        lows = df["low"].values

        if len(closes) < min_bars:
            continue

        result = {}

        # MA50 / MA200（使用 pandas rolling 向量化）
        if len(closes) >= 50:
            result["ma50"] = round(float(pd.Series(closes).rolling(50).mean().iloc[-1]), 2)
        if len(closes) >= 200:
            result["ma200"] = round(float(pd.Series(closes).rolling(200).mean().iloc[-1]), 2)

        # 量比：当日量 / 20 日均量
        if len(volumes) >= 21:
            avg_vol_20 = float(np.nanmean(volumes[1:21]))
            today_vol = volumes[0] if not np.isnan(volumes[0]) else 0
            result["volume_avg_20"] = avg_vol_20
            result["volume_ratio"] = round(today_vol / avg_vol_20, 2) if avg_vol_20 > 0 else 0

        # 距年低百分比
        year_lows = lows[:250]
        valid_lows = year_lows[~np.isnan(year_lows)]
        if len(valid_lows) > 0:
            min_low = float(np.min(valid_lows))
            current = closes[0] if not np.isnan(closes[0]) else 0
            if min_low > 0 and current > 0:
                result["dist_from_year_low_pct"] = round((current - min_low) / min_low * 100, 1)

        # 20 日涨跌幅
        if len(closes) >= 20 and closes[19] and not np.isnan(closes[19]):
            result["change_pct_20d"] = round((closes[0] - closes[19]) / closes[19] * 100, 2)

        # RPS120（120 日涨幅）
        if len(closes) >= 120 and closes[119] and not np.isnan(closes[119]):
            result["return_120d"] = round((closes[0] - closes[119]) / closes[119] * 100, 2)

        enriched_map[symbol] = result

    # ── 合并回 stocks 列表 ──
    enriched_count = 0
    for s in stocks:
        code = s.get("code", "")
        if code in enriched_map:
            s.update(enriched_map[code])
            enriched_count += 1

    logger.info("Enriched %d/%d stocks from memory cache", enriched_count, len(stocks))
    return stocks


# ═══════════════════════════════════════════════════════════════
# Stage 1: 基础筛选（向量化版）
# ═══════════════════════════════════════════════════════════════

def _is_st_stock(name: str) -> bool:
    """检测 ST 股票"""
    return "*ST" in name or "ST" in name or "st" in name.lower()


def stage_basic_filter(stocks: List[dict], ctx: dict) -> List[dict]:
    """
    Stage 1: 基础筛选（向量化版）

    使用 DataFrame 布尔掩码替代逐条循环:
    - 排除 ST / *ST / 退市股
    - 排除停牌股（价格为 0）
    - 流动性过滤（成交额 > 阈值）
    - 排除价格异常（价格 < 1 元的低价股）
    """
    if not stocks:
        return []

    min_amount = ctx.get("min_amount", 5_000_000)
    min_price = ctx.get("min_price", 1.0)

    df = pd.DataFrame(stocks)

    # 确保数值列为数字
    for col in ["price", "amount"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    # 构建布尔掩码
    mask = pd.Series(True, index=df.index)

    # ST 排除
    if "name" in df.columns:
        name_upper = df["name"].fillna("").str.upper()
        mask &= ~name_upper.str.contains("ST", regex=False)

    # 停牌排除（价格为 0 或 NaN）
    mask &= df["price"] > 0

    # 价格过滤
    mask &= df["price"] >= min_price

    # 流动性过滤
    mask &= df["amount"] >= min_amount

    result_count = int(mask.sum())
    results = df[mask].to_dict("records")

    logger.info("[basic_filter] %d → %d (min_amount=%d)", len(stocks), result_count, min_amount)
    return results


# ═══════════════════════════════════════════════════════════════
# Stage 2: 技术面多通道筛选（向量化版）
# ═══════════════════════════════════════════════════════════════

def _vectorized_channel_checks(df: pd.DataFrame) -> pd.DataFrame:
    """
    向量化通道检测 — 一次性计算所有 4 个通道的通过状态

    返回: 原始 df 新增 4 列布尔值: _ch_trend, _ch_reversal, _ch_breakout, _ch_accumulation
    """
    # 确保数值列
    for col in ["ma50", "ma200", "return_120d", "change_pct_20d", "change_pct",
                "volume_ratio", "price", "high", "dist_from_year_low_pct"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    # 趋势通道: MA50 > MA200 + 120日涨幅 >= 20%
    df["_ch_trend"] = (df["ma50"] > df["ma200"]) & (df["return_120d"] >= 20)

    # 反转通道: 20日跌幅 > 10% + 今日小涨 + 放量
    df["_ch_reversal"] = (
        (df["change_pct_20d"] < -10) &
        (df["change_pct"] > 0) &
        (df["volume_ratio"] > 1.2)
    )

    # 突破通道: 放量 + 涨幅 > 3% + 价格接近最高价
    near_high = pd.Series(False, index=df.index)
    valid_high = df["high"] > 0
    near_high[valid_high] = ((df["high"][valid_high] - df["price"][valid_high]) / df["high"][valid_high]) < 0.01
    df["_ch_breakout"] = (df["volume_ratio"] > 2.0) & (df["change_pct"] > 3) & near_high

    # 吸筹通道: 距年低 <= 45% + 缩量
    df["_ch_accumulation"] = (df["dist_from_year_low_pct"] <= 45) & (df["volume_ratio"] < 0.75)

    return df


# 通道注册表
CHANNELS = {
    "trend": ("趋势通道", "_ch_trend"),
    "reversal": ("反转通道", "_ch_reversal"),
    "breakout": ("突破通道", "_ch_breakout"),
    "accumulation": ("吸筹通道", "_ch_accumulation"),
}


def stage_technical_multi_channel(stocks: List[dict], ctx: dict) -> List[dict]:
    """
    Stage 2: 技术面多通道筛选（向量化版）

    一次性计算所有通道的通过状态，然后按 min_channels 筛选。
    """
    if not stocks:
        return []

    min_channels = ctx.get("min_channels", 1)

    df = pd.DataFrame(stocks)
    df = _vectorized_channel_checks(df)

    # 统计每个通道通过数
    channel_counts = {}
    for ch_name, (_, col_name) in CHANNELS.items():
        count = int(df[col_name].sum())
        channel_counts[ch_name] = count

    # 计算通道数
    ch_cols = [col for _, (_, col) in CHANNELS.items() if col in df.columns]
    df["channel_count"] = df[ch_cols].sum(axis=1).astype(int)

    # 筛选通过 >= min_channels 通道的
    mask = df["channel_count"] >= min_channels
    filtered = df[mask].copy()

    # 记录通过了哪些通道
    def _get_channels(row):
        return [ch_name for ch_name, (_, col) in CHANNELS.items() if row.get(col, False)]

    filtered["channels"] = filtered.apply(_get_channels, axis=1)

    # 清理临时列，转回 dict 列表
    drop_cols = [col for _, (_, col) in CHANNELS.items()] + ["_ch_trend", "_ch_reversal", "_ch_breakout", "_ch_accumulation"]
    drop_cols = [c for c in drop_cols if c in filtered.columns]
    filtered = filtered.drop(columns=drop_cols, errors="ignore")

    results = filtered.to_dict("records")

    logger.info("[technical] %d → %d", len(stocks), len(results))
    for ch_name, count in channel_counts.items():
        logger.info("  channel %s: %d passed", ch_name, count)

    return results


# ═══════════════════════════════════════════════════════════════
# 综合评分（向量化版）
# ═══════════════════════════════════════════════════════════════

def stage_ranking(stocks: List[dict], ctx: dict) -> List[dict]:
    """
    Stage 3: 综合评分与排序（向量化版）

    MVP 简化版：按通道数 + 成交额加权排序
    使用 DataFrame 向量化评分。
    """
    if not stocks:
        return []

    df = pd.DataFrame(stocks)

    for col in ["channel_count", "amount"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    # 通道数权重 70% + 成交额权重 30%
    amount_score = (df["amount"] / 100_000_000).clip(upper=10)
    df["funnel_score"] = df["channel_count"] * 7 + amount_score * 3

    # 排序
    df = df.sort_values("funnel_score", ascending=False).reset_index(drop=True)

    # 行业分散：同名前缀最多 N 只
    max_per_prefix = ctx.get("max_per_prefix", 2)
    if "code" in df.columns:
        df["_prefix"] = df["code"].astype(str).str[:2]
        df["_rank"] = df.groupby("_prefix").cumcount()
        mask = df["_rank"] < max_per_prefix
        df = df[mask].drop(columns=["_prefix", "_rank"], errors="ignore")

    results = df.to_dict("records")
    logger.info("[ranking] %d → %d (diversified)", len(stocks), len(results))
    return results


# ═══════════════════════════════════════════════════════════════
# Stage 3: 资金面筛选（向量化版）
# ═══════════════════════════════════════════════════════════════

def stage_fund_flow(stocks: List[dict], ctx: dict) -> List[dict]:
    """
    Stage 3: 资金面筛选（向量化版）
    """
    if not stocks:
        return []

    min_amount = ctx.get("fund_min_amount", 100_000_000)
    min_volume_ratio = ctx.get("fund_min_volume_ratio", 1.0)

    df = pd.DataFrame(stocks)

    for col in ["amount", "volume_ratio", "amplitude"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    mask = (
        (df["amount"] >= min_amount) &
        (df["volume_ratio"] >= min_volume_ratio) &
        (df["amplitude"] <= 15)
    )

    results = df[mask].to_dict("records")
    logger.info("[fund_flow] %d → %d", len(stocks), len(results))
    return results


# ═══════════════════════════════════════════════════════════════
# Stage 4: 基本面筛选（向量化版）
# ═══════════════════════════════════════════════════════════════

def stage_fundamental(stocks: List[dict], ctx: dict) -> List[dict]:
    """
    Stage 4: 基本面筛选（向量化版）
    """
    if not stocks:
        return []

    min_price = ctx.get("fund_price_min", 5.0)
    max_return_120d = ctx.get("fund_max_return_120d", 100)

    df = pd.DataFrame(stocks)

    for col in ["price", "dist_from_year_low_pct", "return_120d"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    mask = (
        (df["price"] >= min_price) &
        (df["dist_from_year_low_pct"] >= 10) &
        (df["return_120d"] <= max_return_120d)
    )

    results = df[mask].to_dict("records")
    logger.info("[fundamental] %d → %d", len(stocks), len(results))
    return results


# ═══════════════════════════════════════════════════════════════
# 资金流数据补充（保持不变 — 此部分受 API 限流约束，无法批量向量化）
# ═══════════════════════════════════════════════════════════════

def enrich_with_fund_flow(stocks: List[dict], max_stocks: int = 50) -> List[dict]:
    """
    用东财资金流数据补充主力净流入信息

    只对前 N 只股票查询（避免 API 限流）
    注意：此函数因 API 限流约束，无法完全向量化，保持逐股查询。
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
                recent_flow = flow_data.get("flow", [])
                if isinstance(recent_flow, list):
                    s["main_net_5d"] = sum(f.get("main_net", 0) for f in recent_flow[:5])
                enriched += 1
        except Exception as e:
            logger.debug("Fund flow enrichment failed for %s: %s", code, e)

    logger.info("Enriched %d stocks with fund flow data", enriched)
    return stocks
