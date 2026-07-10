"""技术分析模块 — 带缓存封装

从 daily_stock_analysis 抄逻辑：MA/MACD/RSI/Bollinger/趋势/量价分析
通过 core.cache 缓存分析结果（基于 K 线数据，变化慢）
"""

from __future__ import annotations

import math
from typing import Any

from core.cache import get_cache, make_cache_key, TTL_TECHNICAL


# ── 计算公式 ─────────────────────────────────────────────

def calc_ma(records: list[dict], period: int) -> float:
    """计算N日均线"""
    closes = [r["close"] for r in records if r.get("close")]
    if len(closes) < period:
        return 0.0
    return round(sum(closes[-period:]) / period, 2)


def calc_ema(closes: list[float], period: int) -> list[float]:
    """指数移动平均"""
    if not closes:
        return []
    multiplier = 2 / (period + 1)
    ema = [closes[0]]
    for price in closes[1:]:
        ema.append((price - ema[-1]) * multiplier + ema[-1])
    return ema


def calc_macd(closes: list[float]) -> dict[str, Any]:
    """MACD 指标 (12, 26, 9)"""
    if len(closes) < 26:
        return {"dif": 0, "dea": 0, "bar": 0, "status": "数据不足", "signal": ""}

    ema12 = calc_ema(closes, 12)
    ema26 = calc_ema(closes, 26)
    dif = [ema12[i] - ema26[i] for i in range(len(closes))]
    dea = calc_ema(dif, 9)
    bar = [dif[i] - dea[i] for i in range(len(closes))]

    latest_dif = round(dif[-1], 3)
    latest_dea = round(dea[-1], 3) if len(dea) == len(dif) else 0
    latest_bar = round(bar[-1], 3) if len(bar) == len(dif) else 0

    if latest_dif > 0 and latest_bar > 0:
        status = "多头加强" if len(bar) > 1 and latest_bar > abs(bar[-2]) else "多头"
    elif latest_dif > 0:
        status = "多头减弱"
    elif latest_dif < 0 and latest_bar < 0:
        status = "空头加强" if len(bar) > 1 and abs(latest_bar) > abs(bar[-2]) else "空头"
    elif latest_dif < 0:
        status = "空头减弱"
    else:
        status = "中性"

    signal = ""
    if len(dif) >= 2 and len(dea) >= 2:
        if dif[-2] < dea[-2] and latest_dif >= latest_dea:
            signal = "金叉"
        elif dif[-2] > dea[-2] and latest_dif <= latest_dea:
            signal = "死叉"

    return {"dif": latest_dif, "dea": latest_dea, "bar": latest_bar,
            "status": status, "signal": signal}


def calc_rsi(closes: list[float], period: int = 14) -> dict[str, Any]:
    """RSI 指标"""
    if len(closes) < period + 1:
        return {"value": 50, "status": "数据不足"}

    gains, losses = 0.0, 0.0
    for i in range(-period, 0):
        diff = closes[i] - closes[i - 1]
        if diff > 0:
            gains += diff
        else:
            losses -= diff

    avg_gain = gains / period
    avg_loss = losses / period

    if avg_loss == 0:
        rsi = 100.0
    else:
        rs = avg_gain / avg_loss
        rsi = round(100 - 100 / (1 + rs), 2)

    status = "超买" if rsi > 70 else "强势" if rsi > 50 else "弱势" if rsi > 30 else "超卖"
    return {"value": rsi, "status": status}


def calc_bollinger(records: list[dict], period: int = 20) -> dict[str, Any]:
    """布林带 (20, 2)"""
    closes = [r["close"] for r in records if r.get("close")]
    if len(closes) < period:
        return {"upper": 0, "middle": 0, "lower": 0,
                "bandwidth": 0, "position": "数据不足"}

    ma = sum(closes[-period:]) / period
    variance = sum((c - ma) ** 2 for c in closes[-period:]) / period
    std = math.sqrt(variance)

    upper = round(ma + 2 * std, 2)
    middle = round(ma, 2)
    lower = round(ma - 2 * std, 2)
    bandwidth = round((upper - lower) / middle * 100, 2) if middle else 0

    current = closes[-1]
    if current > upper:
        position = "上轨之上（超买）"
    elif current > middle:
        position = "中轨至上轨"
    elif current > lower:
        position = "下轨至中轨"
    else:
        position = "下轨之下（超卖）"

    return {"upper": upper, "middle": middle, "lower": lower,
            "bandwidth": bandwidth, "position": position}


def calc_volume_ratio(records: list[dict]) -> float:
    """量比：当日成交量 / 5日均量"""
    volumes = [r["volume"] for r in records if r.get("volume", 0) > 0]
    if len(volumes) < 6:
        return 0.0
    current = volumes[-1]
    avg_5 = sum(volumes[-6:-1]) / 5
    return round(current / avg_5, 2) if avg_5 else 0


def calc_bias(closes: list[float], ma: float) -> float:
    """乖离率"""
    if not closes or ma == 0:
        return 0.0
    return round((closes[-1] - ma) / ma * 100, 2)


def calc_trend_status(records: list[dict]) -> dict[str, Any]:
    """趋势状态判断"""
    closes = [r["close"] for r in records if r.get("close")]
    if len(closes) < 20:
        return {"status": "数据不足", "score": 50}

    ma5 = calc_ma(records, 5)
    ma10 = calc_ma(records, 10)
    ma20 = calc_ma(records, 20)
    ma60 = calc_ma(records, 60)

    spread_5_10 = abs(ma5 - ma10)
    spread_10_20 = abs(ma10 - ma20)

    if ma5 > ma10 > ma20:
        if spread_5_10 > 1.0 and spread_10_20 > 1.0:
            status, score = "强势多头", 85
        else:
            status, score = "多头排列", 70
    elif ma5 > ma10 and ma10 < ma20:
        status, score = "弱势多头", 55
    elif ma5 < ma10 and ma10 > ma20:
        status, score = "弱势空头", 45
    elif ma5 < ma10 < ma20:
        if spread_5_10 > 1.0 and spread_10_20 > 1.0:
            status, score = "强势空头", 15
        else:
            status, score = "空头排列", 30
    else:
        status, score = "震荡整理", 50

    return {"status": status, "score": score,
            "ma5": ma5, "ma10": ma10, "ma20": ma20, "ma60": ma60}


# ── Ichimoku Kinko Hyo（一目均衡表）────────────────────


def calc_ichimoku(records: list[dict]) -> dict[str, Any]:
    """计算 Ichimoku 指标

    需要至少 52 个交易日数据。
    - Tenkan: (9日高+9日低)/2 — 短期趋势
    - Kijun: (26日高+26日低)/2 — 中期趋势/支撑压力
    - SpanA: (Tenkan+Kijun)/2 — 先行带A（未来26日）
    - SpanB: (52日高+52日低)/2 — 先行带B（未来26日）
    - Chiko: 当日收向后移26日 — 延迟线
    """
    highs = [r["high"] for r in records if r.get("high")]
    lows = [r["low"] for r in records if r.get("low")]
    closes = [r["close"] for r in records if r.get("close")]

    if len(closes) < 52:
        return {"status": "数据不足（需52个交易日）"}

    tenkan = (max(highs[-9:]) + min(lows[-9:])) / 2
    kijun = (max(highs[-26:]) + min(lows[-26:])) / 2
    span_a = (tenkan + kijun) / 2
    span_b = (max(highs[-52:]) + min(lows[-52:])) / 2
    chiko = closes[-26] if len(closes) >= 26 else closes[0]

    # 信号判断
    price = closes[-1]
    above_cloud = price > max(span_a, span_b)
    below_cloud = price < min(span_a, span_b)
    in_cloud = not above_cloud and not below_cloud

    if above_cloud and tenkan > kijun:
        trend = "多头（云上+金叉）"
    elif above_cloud:
        trend = "偏多（云上）"
    elif below_cloud and tenkan < kijun:
        trend = "空头（云下+死叉）"
    elif below_cloud:
        trend = "偏空（云下）"
    else:
        trend = "震荡（云中）"

    return {
        "tenkan": round(tenkan, 2),
        "kijun": round(kijun, 2),
        "span_a": round(span_a, 2),
        "span_b": round(span_b, 2),
        "chiko": round(chiko, 2),
        "trend": trend,
    }


# ── K 线形态识别 ─────────────────────────────────────


def identify_candle_patterns(records: list[dict]) -> list[dict]:
    """识别常见 K 线形态

    返回最近 10 根 K 线的形态识别结果，按时间正序。
    形态列表: doji, hammer, shooting_star, engulfing
    """
    if len(records) < 3:
        return []

    patterns = []
    for i in range(max(0, len(records) - 10), len(records)):
        r = records[i]
        open_p = r.get("open", 0)
        close_p = r.get("close", 0)
        high_p = r.get("high", 0)
        low_p = r.get("low", 0)
        body = abs(close_p - open_p)
        upper_wick = high_p - max(open_p, close_p)
        lower_wick = min(open_p, close_p) - low_p
        total_range = high_p - low_p

        if total_range == 0:
            continue

        found = []
        bullish = close_p > open_p

        # Doji: 实体极小（<5% 振幅）
        if body / total_range < 0.05:
            found.append("doji")

        # Hammer: 下影线是实体的 2x+，上影线短（下跌后）
        if not bullish and lower_wick > body * 2 and upper_wick < body * 0.5:
            found.append("hammer")

        # Shooting Star: 上影线是实体的 2x+，下影线短（上涨后）
        if bullish and upper_wick > body * 2 and lower_wick < body * 0.5:
            found.append("shooting_star")

        # 吞没形态（与上一根比较）
        if i > 0:
            prev = records[i - 1]
            prev_open = prev.get("open", 0)
            prev_close = prev.get("close", 0)
            prev_bullish = prev_close > prev_open

            # Bullish Engulfing: 阴线后阳线完全覆盖前实体
            if bullish and not prev_bullish:
                if close_p > prev_open and open_p < prev_close:
                    found.append("bullish_engulfing")

            # Bearish Engulfing: 阳线后阴线完全覆盖前实体
            if not bullish and prev_bullish:
                if open_p > prev_close and close_p < prev_open:
                    found.append("bearish_engulfing")

        patterns.append({
            "date": r.get("date", ""),
            "patterns": found,
        })

    return patterns


def analyze(records: list[dict], code: str = "") -> dict[str, Any]:
    """完整技术分析（带缓存）

    基于K线数据计算所有技术指标，结果按（代码+记录摘要）缓存。

    Args:
        records: K线记录列表
        code: 股票代码（用于缓存key区分）
    """
    closes = [r["close"] for r in records if r.get("close")]
    if not closes:
        return {"error": "无数据"}

    # 生成缓存键：用代码+最后日期+记录数区分
    last_date = records[-1].get("date", "") if records else ""
    first_date = records[0].get("date", "") if records else ""
    cache_key = make_cache_key("technical", code, last_date, first_date, str(len(records)))
    cache = get_cache()
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    trend = calc_trend_status(records)
    macd = calc_macd(closes)
    rsi = calc_rsi(closes)
    bollinger = calc_bollinger(records)
    volume_ratio = calc_volume_ratio(records)

    bias_ma5 = calc_bias(closes, trend.get("ma5", 0))
    bias_ma20 = calc_bias(closes, trend.get("ma20", 0))

    price = closes[-1]
    ma5 = trend.get("ma5", 0)
    ma10 = trend.get("ma10", 0)
    support_ma5 = ma5 > 0 and abs(price - ma5) / ma5 < 0.01
    support_ma10 = ma10 > 0 and abs(price - ma10) / ma10 < 0.01

    score = trend.get("score", 50)
    if macd.get("signal") == "金叉":
        score += 10
    elif macd.get("signal") == "死叉":
        score -= 10

    rsi_val = rsi.get("value", 50)
    if 40 <= rsi_val <= 60:
        score += 5
    elif rsi_val > 80 or rsi_val < 20:
        score -= 10

    if 0.8 <= volume_ratio <= 1.5:
        score += 5
    elif volume_ratio > 3:
        score -= 5

    score = max(0, min(100, score))

    if score >= 75:
        advice = "买入"
    elif score >= 60:
        advice = "观望（偏多）"
    elif score >= 40:
        advice = "观望"
    elif score >= 25:
        advice = "观望（偏空）"
    else:
        advice = "卖出"

    # Ichimoku（需52个交易日）
    ichimoku = calc_ichimoku(records)

    # K线形态
    candle_patterns = identify_candle_patterns(records)

    result = {
        "trend": trend,
        "macd": macd,
        "rsi": rsi,
        "bollinger": bollinger,
        "volume_ratio": volume_ratio,
        "bias": {"ma5": bias_ma5, "ma20": bias_ma20},
        "support": {"ma5": support_ma5, "ma10": support_ma10},
        "ichimoku": ichimoku,
        "candle_patterns": candle_patterns,
        "price": price,
        "score": score,
        "advice": advice,
        "analysis_count": len(records),
    }

    cache.set(cache_key, result, TTL_TECHNICAL)
    return result
