"""技术分析模块
从 daily_stock_analysis 抄逻辑：MA/MACD/RSI/Bollinger/趋势/量价分析
"""
from __future__ import annotations

import math
from typing import Any


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

    # 状态判断
    if latest_dif > 0 and latest_bar > 0:
        if latest_bar > abs(bar[-2] if len(bar) > 1 else 0):
            status = "多头加强"
        else:
            status = "多头"
    elif latest_dif > 0:
        status = "多头减弱"
    elif latest_dif < 0 and latest_bar < 0:
        if abs(latest_bar) > abs(bar[-2] if len(bar) > 1 else 0):
            status = "空头加强"
        else:
            status = "空头"
    elif latest_dif < 0:
        status = "空头减弱"
    else:
        status = "中性"

    # 金叉/死叉信号
    signal = ""
    if len(dif) >= 2 and len(dea) >= 2:
        if dif[-2] < dea[-2] and latest_dif >= latest_dea:
            signal = "金叉"
        elif dif[-2] > dea[-2] and latest_dif <= latest_dea:
            signal = "死叉"

    return {
        "dif": latest_dif,
        "dea": latest_dea,
        "bar": latest_bar,
        "status": status,
        "signal": signal,
    }


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

    if rsi > 70:
        status = "超买"
    elif rsi > 50:
        status = "强势"
    elif rsi > 30:
        status = "弱势"
    else:
        status = "超卖"

    return {"value": rsi, "status": status}


def calc_bollinger(records: list[dict], period: int = 20) -> dict[str, Any]:
    """布林带 (20, 2)"""
    closes = [r["close"] for r in records if r.get("close")]
    if len(closes) < period:
        return {"upper": 0, "middle": 0, "lower": 0, "bandwidth": 0, "position": "数据不足"}

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
    """乖离率：与均线的偏离百分比"""
    if not closes or ma == 0:
        return 0.0
    return round((closes[-1] - ma) / ma * 100, 2)


def calc_trend_status(records: list[dict]) -> dict[str, Any]:
    """趋势状态判断
    
    逻辑从 daily_stock_analysis 抄：
    - STRONG_BULL:   MA5 > MA10 > MA20，且间距扩大
    - BULL:          MA5 > MA10 > MA20
    - WEAK_BULL:     MA5 > MA10，但 MA10 < MA20
    - CONSOLIDATION: 均线纠缠
    - WEAK_BEAR:     MA5 < MA10，但 MA10 > MA20
    - BEAR:          MA5 < MA10 < MA20
    - STRONG_BEAR:   MA5 < MA10 < MA20，且间距扩大
    """
    closes = [r["close"] for r in records if r.get("close")]
    if len(closes) < 20:
        return {"status": "数据不足", "score": 50}

    ma5 = calc_ma(records, 5)
    ma10 = calc_ma(records, 10)
    ma20 = calc_ma(records, 20)
    ma60 = calc_ma(records, 60)

    # 获取更短的窗口来判断间距趋势
    closes_last10 = closes[-10:] if len(closes) >= 10 else closes
    ma5_short = calc_ma([{"close": c} for c in closes_last10[-5:]], 5)
    ma10_short = calc_ma([{"close": c} for c in closes_last10], 10)
    
    # MA5 与 MA10 的间距趋势
    spread_5_10 = abs(ma5 - ma10)
    spread_10_20 = abs(ma10 - ma20)

    if ma5 > ma10 > ma20:
        # 多头
        if spread_5_10 > 1.0 and spread_10_20 > 1.0:
            status = "强势多头"
            score = 85
        else:
            status = "多头排列"
            score = 70
    elif ma5 > ma10 and ma10 < ma20:
        status = "弱势多头"
        score = 55
    elif ma5 < ma10 and ma10 > ma20:
        status = "弱势空头"
        score = 45
    elif ma5 < ma10 < ma20:
        if spread_5_10 > 1.0 and spread_10_20 > 1.0:
            status = "强势空头"
            score = 15
        else:
            status = "空头排列"
            score = 30
    else:
        # 均线纠缠
        status = "震荡整理"
        score = 50

    return {
        "status": status,
        "score": score,
        "ma5": ma5,
        "ma10": ma10,
        "ma20": ma20,
        "ma60": ma60,
    }


def analyze(records: list[dict]) -> dict[str, Any]:
    """完整技术分析"""
    closes = [r["close"] for r in records if r.get("close")]
    if not closes:
        return {"error": "无数据"}

    trend = calc_trend_status(records)
    macd = calc_macd(closes)
    rsi = calc_rsi(closes)
    bollinger = calc_bollinger(records)
    volume_ratio = calc_volume_ratio(records)

    bias_ma5 = calc_bias(closes, trend.get("ma5", 0))
    bias_ma20 = calc_bias(closes, trend.get("ma20", 0))

    # 检查支撑：价格在 MA5/MA10 附近
    price = closes[-1]
    ma5 = trend.get("ma5", 0)
    ma10 = trend.get("ma10", 0)
    support_ma5 = ma5 > 0 and abs(price - ma5) / ma5 < 0.01
    support_ma10 = ma10 > 0 and abs(price - ma10) / ma10 < 0.01

    # 综合评分 (0-100)
    score = trend.get("score", 50)

    # MACD 加分/扣分
    if macd.get("signal") == "金叉":
        score += 10
    elif macd.get("signal") == "死叉":
        score -= 10

    # RSI 调整
    rsi_val = rsi.get("value", 50)
    if 40 <= rsi_val <= 60:
        score += 5  # 中性区间加分
    elif rsi_val > 80 or rsi_val < 20:
        score -= 10  # 极端区间扣分

    # 量比调整
    if 0.8 <= volume_ratio <= 1.5:
        score += 5  # 温和放量
    elif volume_ratio > 3:
        score -= 5  # 异常放量

    score = max(0, min(100, score))

    # 操作建议
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

    return {
        "trend": trend,
        "macd": macd,
        "rsi": rsi,
        "bollinger": bollinger,
        "volume_ratio": volume_ratio,
        "bias": {
            "ma5": bias_ma5,
            "ma20": bias_ma20,
        },
        "support": {
            "ma5": support_ma5,
            "ma10": support_ma10,
        },
        "price": price,
        "score": score,
        "advice": advice,
        "analysis_count": len(records),
    }
