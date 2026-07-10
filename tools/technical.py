"""技术分析模块 v2 — 向量化重写（参考 MyTT/mpquant 算法）

核心变化：
- 所有手写循环 → pandas rolling 向量化计算（10-100x 提速）
- 新增 SAR/DMI/ATR/KDJ/CCI/WR/OBV/MFI 指标
- 新增 HHV/LLV/CROSS/COUNT/EVERY/BARSLAST 工具函数
- 保持 analyze() 接口和输出格式向后兼容

参考：https://github.com/mpquant/MyTT (MIT)
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd

from core.cache import get_cache, make_cache_key, TTL_TECHNICAL


# ══════════════════════════════════════════════════════════
# 0级：核心工具函数（向量化，MyTT 风格）
# ══════════════════════════════════════════════════════════

def RD(N: float, D: int = 3) -> float:
    """四舍五入到 D 位小数"""
    return round(float(N), D)


def RET(S: np.ndarray, N: int = 1) -> float:
    """返回序列倒数第 N 个值"""
    return float(S[-N])


def REF(S: np.ndarray, N: int = 1) -> np.ndarray:
    """序列整体下移 N 位（前 N 个为 NaN）"""
    return pd.Series(S).shift(N).values


def DIFF(S: np.ndarray, N: int = 1) -> np.ndarray:
    """前 N 个值减后 N 个值"""
    return pd.Series(S).diff(N).values


def MA(S: np.ndarray, N: int) -> np.ndarray:
    """N 日简单移动平均（返回完整序列）"""
    return pd.Series(S).rolling(N).mean().values


def EMA(S: np.ndarray, N: int) -> np.ndarray:
    """指数移动平均 alpha=2/(N+1)"""
    return pd.Series(S).ewm(span=N, adjust=False).mean().values


def SMA(S: np.ndarray, N: int, M: int = 1) -> np.ndarray:
    """中国式 SMA alpha=M/N"""
    return pd.Series(S).ewm(alpha=M / N, adjust=False).mean().values


def STD(S: np.ndarray, N: int) -> np.ndarray:
    """N 日标准差"""
    return pd.Series(S).rolling(N).std(ddof=0).values


def SUM(S: np.ndarray, N: int) -> np.ndarray:
    """N 日累计和（N=0 对所有元素累计求和）"""
    if N > 0:
        return pd.Series(S).rolling(N).sum().values
    return np.cumsum(S)


def MAX(S1: np.ndarray, S2: np.ndarray) -> np.ndarray:
    """两个序列逐元素取最大值"""
    return np.maximum(S1, S2)


def MIN(S1: np.ndarray, S2: np.ndarray) -> np.ndarray:
    """两个序列逐元素取最小值"""
    return np.minimum(S1, S2)


def IF(S: np.ndarray, A: float | np.ndarray, B: float | np.ndarray) -> np.ndarray:
    """条件判断：S 为 True 时取 A，否则取 B"""
    return np.where(S, A, B)


def HHV(S: np.ndarray, N: int) -> np.ndarray:
    """N 日最高值"""
    return pd.Series(S).rolling(N).max().values


def LLV(S: np.ndarray, N: int) -> np.ndarray:
    """N 日最低值"""
    return pd.Series(S).rolling(N).min().values


def CROSS(S1: np.ndarray, S2: np.ndarray) -> np.ndarray:
    """金叉判断：S1 上穿 S2（前值<=, 现值>）"""
    return np.concatenate(([False], (S1[:-1] <= S2[:-1]) & (S1[1:] > S2[1:])))


def COUNT(S: np.ndarray, N: int) -> np.ndarray:
    """N 日内 S 为 True 的天数"""
    return SUM(S.astype(float), N)


def EVERY(S: np.ndarray, N: int) -> np.ndarray:
    """N 日内 S 是否全部为 True"""
    return SUM(S.astype(float), N) >= N


def BARSLAST(S: np.ndarray) -> np.ndarray:
    """上一次条件成立到当前的周期数"""
    M = np.concatenate(([0], np.where(S, 1, 0)))
    for i in range(1, len(M)):
        M[i] = 0 if M[i] else M[i - 1] + 1
    return M[1:].astype(int)


def AVEDEV(S: np.ndarray, N: int) -> np.ndarray:
    """平均绝对偏差"""
    return pd.Series(S).rolling(N).apply(lambda x: np.abs(x - x.mean()).mean(), raw=True).values


# ══════════════════════════════════════════════════════════
# 1级：指标函数（全部通过 0 级工具函数实现）
# ══════════════════════════════════════════════════════════

def calc_ma(records: list[dict], period: int) -> float:
    """计算 N 日均线（取最新值）"""
    closes = np.array([r["close"] for r in records if r.get("close")], dtype=float)
    if len(closes) < period:
        return 0.0
    return RD(MA(closes, period)[-1], 2)


def calc_macd(closes: np.ndarray) -> dict[str, Any]:
    """MACD (12,26,9) — 返回最新值 + 状态"""
    if len(closes) < 26:
        return {"dif": 0, "dea": 0, "bar": 0, "status": "数据不足", "signal": ""}

    dif = EMA(closes, 12) - EMA(closes, 26)
    dea = EMA(dif, 9)
    macd = (dif - dea) * 2

    latest_dif = RD(dif[-1], 3)
    latest_dea = RD(dea[-1], 3)
    latest_bar = RD(macd[-1], 3)
    prev_bar = RD(macd[-2], 3) if len(macd) > 1 else 0

    if latest_dif > 0 and latest_bar > 0:
        status = "多头加强" if latest_bar > abs(prev_bar) else "多头"
    elif latest_dif > 0:
        status = "多头减弱"
    elif latest_dif < 0 and latest_bar < 0:
        status = "空头加强" if abs(latest_bar) > abs(prev_bar) else "空头"
    elif latest_dif < 0:
        status = "空头减弱"
    else:
        status = "中性"

    signal = ""
    if len(dif) >= 2 and len(dea) >= 2:
        if dif[-2] < dea[-2] and dif[-1] >= dea[-1]:
            signal = "金叉"
        elif dif[-2] > dea[-2] and dif[-1] <= dea[-1]:
            signal = "死叉"

    return {"dif": latest_dif, "dea": latest_dea, "bar": latest_bar,
            "status": status, "signal": signal}


def calc_rsi(closes: np.ndarray, period: int = 14) -> dict[str, Any]:
    """RSI (14) — 返回最新值"""
    if len(closes) < period + 1:
        return {"value": 50.0, "status": "数据不足"}

    dif = closes - REF(closes, 1)
    # MyTT 公式: SMA(MAX(DIF,0), N) / SMA(ABS(DIF), N) * 100
    rsi_seq = SMA(MAX(dif, 0), period) / SMA(np.abs(dif), period) * 100
    rsi = RD(rsi_seq[-1], 2)

    status = "超买" if rsi > 70 else "强势" if rsi > 50 else "弱势" if rsi > 30 else "超卖"
    return {"value": rsi, "status": status}


def calc_bollinger(closes: np.ndarray, period: int = 20, p: int = 2) -> dict[str, Any]:
    """布林带 (20, 2) — 返回最新值"""
    if len(closes) < period:
        return {"upper": 0, "middle": 0, "lower": 0,
                "bandwidth": 0, "position": "数据不足"}

    mid_seq = MA(closes, period)
    std_seq = STD(closes, period)
    upper_seq = mid_seq + std_seq * p
    lower_seq = mid_seq - std_seq * p

    upper = RD(upper_seq[-1], 2)
    middle = RD(mid_seq[-1], 2)
    lower = RD(lower_seq[-1], 2)
    bandwidth = RD((upper - lower) / middle * 100, 2) if middle else 0

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


def calc_kdj(closes: np.ndarray, highs: np.ndarray, lows: np.ndarray,
             N: int = 9, M1: int = 3, M2: int = 3) -> dict[str, Any]:
    """KDJ 指标 — 返回最新值"""
    if len(closes) < N:
        return {"k": 50, "d": 50, "j": 50, "status": "数据不足"}

    hhv = HHV(highs, N)
    llv = LLV(lows, N)
    rsv = (closes - llv) / (hhv - llv + 1e-10) * 100

    k = EMA(rsv, M1 * 2 - 1)
    d = EMA(k, M2 * 2 - 1)
    j = k * 3 - d * 2

    kv = RD(k[-1], 2)
    dv = RD(d[-1], 2)
    jv = RD(j[-1], 2)

    # 信号
    if kv > 80 and jv > 100:
        signal = "超买（J值>100，警惕回调）"
    elif kv < 20 and jv < 0:
        signal = "超卖（J值<0，关注反弹）"
    elif len(k) >= 2 and len(d) >= 2:
        if k[-2] < d[-2] and k[-1] >= d[-1]:
            signal = "金叉"
        elif k[-2] > d[-2] and k[-1] <= d[-1]:
            signal = "死叉"
        else:
            signal = ""
    else:
        signal = ""

    return {"k": kv, "d": dv, "j": jv, "signal": signal}


def calc_cci(closes: np.ndarray, highs: np.ndarray, lows: np.ndarray,
             N: int = 14) -> dict[str, Any]:
    """CCI 顺势指标 — 返回最新值"""
    if len(closes) < N:
        return {"value": 0, "status": "数据不足"}

    tp = (highs + lows + closes) / 3
    cci_seq = (tp - MA(tp, N)) / (0.015 * AVEDEV(tp, N))
    cci = RD(cci_seq[-1], 2)

    if cci > 200:
        status = "超买（>200，顶背离风险）"
    elif cci > 100:
        status = "强势（>100，多头占优）"
    elif cci > -100:
        status = "震荡（±100之间）"
    elif cci > -200:
        status = "弱势（<-100，空头占优）"
    else:
        status = "超卖（<-200，底背离机会）"

    return {"value": cci, "status": status}


def calc_wr(closes: np.ndarray, highs: np.ndarray, lows: np.ndarray,
            N: int = 10, N1: int = 6) -> dict[str, Any]:
    """W&R 威廉指标 — 返回最新值"""
    if len(closes) < max(N, N1):
        return {"wr": 50, "wr1": 50, "status": "数据不足"}

    wr_seq = (HHV(highs, N) - closes) / (HHV(highs, N) - LLV(lows, N) + 1e-10) * 100
    wr1_seq = (HHV(highs, N1) - closes) / (HHV(highs, N1) - LLV(lows, N1) + 1e-10) * 100
    wr = RD(wr_seq[-1], 2)
    wr1 = RD(wr1_seq[-1], 2)

    # WR 和 WR1 都低于20为超买，都高于80为超卖
    if wr < 20 and wr1 < 20:
        signal = "超买"
    elif wr > 80 and wr1 > 80:
        signal = "超卖"
    else:
        signal = "正常"

    return {"wr": wr, "wr1": wr1, "signal": signal}


def calc_atr(closes: np.ndarray, highs: np.ndarray, lows: np.ndarray,
             N: int = 20) -> dict[str, Any]:
    """ATR 真实波动均值 — 返回最新值"""
    if len(closes) < N + 1:
        return {"value": 0, "status": "数据不足"}

    tr = MAX(MAX(highs - lows, np.abs(REF(closes, 1) - highs)),
             np.abs(REF(closes, 1) - lows))
    atr_seq = MA(tr, N)
    atr = RD(atr_seq[-1], 4)
    atr_pct = RD(atr / closes[-1] * 100, 2) if closes[-1] else 0

    return {"value": atr, "pct": atr_pct, "status": "正常"}


def calc_dmi(closes: np.ndarray, highs: np.ndarray, lows: np.ndarray,
             M1: int = 14, M2: int = 6) -> dict[str, Any]:
    """DMI 动向指标（含 ADX）— 返回最新值"""
    if len(closes) < M1 + M2:
        return {"pdi": 0, "mdi": 0, "adx": 0, "adxr": 0, "status": "数据不足"}

    tr = SUM(MAX(MAX(highs - lows, np.abs(highs - REF(closes, 1))),
                 np.abs(lows - REF(closes, 1))), M1)
    hd = highs - REF(highs, 1)
    ld = REF(lows, 1) - lows

    dmp = SUM(IF((hd > 0) & (hd > ld), hd, 0), M1)
    dmm = SUM(IF((ld > 0) & (ld > hd), ld, 0), M1)

    pdi = dmp * 100 / tr
    mdi = dmm * 100 / tr
    adx = MA(np.abs(mdi - pdi) / (pdi + mdi + 1e-10) * 100, M2)
    adxr = (adx + REF(adx, M2)) / 2

    pdi_v = RD(pdi[-1], 2)
    mdi_v = RD(mdi[-1], 2)
    adx_v = RD(adx[-1], 2)
    adxr_v = RD(adxr[-1], 2)

    # 信号判断
    if adx_v > 25:
        if pdi_v > mdi_v:
            trend = "强多头（ADX>25, PDI>MDI）"
        else:
            trend = "强空头（ADX>25, MDI>PDI）"
    elif adx_v > 20:
        trend = "趋势酝酿中"
    else:
        trend = "震荡无趋势"

    return {"pdi": pdi_v, "mdi": mdi_v, "adx": adx_v, "adxr": adxr_v, "trend": trend}


def calc_obv(closes: np.ndarray, volumes: np.ndarray) -> dict[str, Any]:
    """OBV 能量潮指标"""
    if len(closes) < 2:
        return {"value": 0, "obv_ma": 0, "status": "数据不足"}

    # 经典 OBV: 收盘涨加成交量，跌减成交量
    obv_seq = SUM(IF(closes > REF(closes, 1), volumes,
                     IF(closes < REF(closes, 1), -volumes, 0)), 0) / 10000
    obv_ma = MA(obv_seq, 20)

    obv = RD(obv_seq[-1], 2) if len(obv_seq) > 0 else 0
    obv_ma_v = RD(obv_ma[-1], 2) if len(obv_ma) > 0 else 0

    # 信号：OBV 方向确认价格趋势
    if obv > obv_ma_v:
        signal = "OBV在均线上方（量能支持上涨）"
    else:
        signal = "OBV在均线下方（量能不足）"

    return {"value": obv, "obv_ma": obv_ma_v, "signal": signal}


def calc_mfi(closes: np.ndarray, highs: np.ndarray, lows: np.ndarray,
             volumes: np.ndarray, N: int = 14) -> dict[str, Any]:
    """MFI 资金流量指标（带成交量的 RSI）"""
    if len(closes) < N + 1:
        return {"value": 50, "status": "数据不足"}

    tp = (highs + lows + closes) / 3
    mf = tp * volumes

    pos_flow = SUM(IF(tp > REF(tp, 1), mf, 0), N)
    neg_flow = SUM(IF(tp < REF(tp, 1), mf, 0), N)
    mfr = pos_flow / (neg_flow + 1e-10)
    mfi_seq = 100 - 100 / (1 + mfr)

    mfi = RD(mfi_seq[-1], 2)

    if mfi > 80:
        status = "超买（资金过热）"
    elif mfi > 60:
        status = "资金流入（偏多）"
    elif mfi > 40:
        status = "中性"
    elif mfi > 20:
        status = "资金流出（偏空）"
    else:
        status = "超卖（资金出逃后机会）"

    return {"value": mfi, "status": status}


def calc_sar(highs: np.ndarray, lows: np.ndarray,
             N: int = 10, S: float = 2, M: int = 20) -> dict[str, Any]:
    """SAR 抛物转向 — 返回最新值"""
    if len(highs) < N:
        return {"value": 0, "direction": "", "status": "数据不足"}

    step = S / 100
    max_step = M / 100
    length = len(highs)

    af = 0.0
    is_long = highs[N - 1] > highs[N - 2]
    b_first = True

    s_hhv = REF(HHV(highs, N), 1)
    s_llv = REF(LLV(lows, N), 1)
    sar_x = np.full(length, np.nan)

    for i in range(N, length):
        if b_first:
            af = step
            sar_x[i] = s_llv[i] if is_long else s_hhv[i]
            b_first = False
        else:
            ep = s_hhv[i] if is_long else s_llv[i]
            if (is_long and highs[i] > ep) or (not is_long and lows[i] < ep):
                af = min(af + step, max_step)

            sar_x[i] = sar_x[i - 1] + af * (ep - sar_x[i - 1])

            if (is_long and lows[i] < sar_x[i]) or (not is_long and highs[i] > sar_x[i]):
                is_long = not is_long
                b_first = True

    sar = RD(sar_x[-1], 4) if not np.isnan(sar_x[-1]) else 0
    direction = "多头" if is_long else "空头"
    # 是否刚翻转
    flipped = b_first  # 如果 b_first=True 说明本轮刚翻转

    return {"value": sar, "direction": direction,
            "flipped": bool(flipped), "status": "正常"}


# ── 原有指标（保持接口兼容）────────────────────────────

def calc_volume_ratio(records: list[dict]) -> float:
    """量比：当日成交量 / 5日均量"""
    volumes = np.array([r["volume"] for r in records if r.get("volume", 0) > 0], dtype=float)
    if len(volumes) < 6:
        return 0.0
    current = volumes[-1]
    avg_5 = np.mean(volumes[-6:-1])
    return RD(current / avg_5, 2) if avg_5 else 0


def calc_bias(closes: np.ndarray, ma_val: float) -> float:
    """乖离率"""
    if len(closes) == 0 or ma_val == 0:
        return 0.0
    return RD((closes[-1] - ma_val) / ma_val * 100, 2)


def calc_trend_status(closes: np.ndarray) -> dict[str, Any]:
    """趋势状态判断（基于均线排列）"""
    if len(closes) < 20:
        return {"status": "数据不足", "score": 50}

    ma5_a = MA(closes, 5)
    ma10_a = MA(closes, 10)
    ma20_a = MA(closes, 20)

    ma5 = RD(ma5_a[-1], 2)
    ma10 = RD(ma10_a[-1], 2)
    ma20 = RD(ma20_a[-1], 2)
    ma60 = RD(MA(closes, 60)[-1], 2) if len(closes) >= 60 else 0

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


def calc_ichimoku(records: list[dict]) -> dict[str, Any]:
    """一目均衡表（Ichimoku）— 保持兼容"""
    highs = np.array([r["high"] for r in records if r.get("high")], dtype=float)
    lows = np.array([r["low"] for r in records if r.get("low")], dtype=float)
    closes = np.array([r["close"] for r in records if r.get("close")], dtype=float)

    if len(closes) < 52:
        return {"status": "数据不足（需52个交易日）"}

    tenkan = (np.max(highs[-9:]) + np.min(lows[-9:])) / 2
    kijun = (np.max(highs[-26:]) + np.min(lows[-26:])) / 2
    span_a = (tenkan + kijun) / 2
    span_b = (np.max(highs[-52:]) + np.min(lows[-52:])) / 2
    chiko = closes[-26] if len(closes) >= 26 else closes[0]

    price = closes[-1]
    above_cloud = price > max(span_a, span_b)
    below_cloud = price < min(span_a, span_b)

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
        "tenkan": RD(tenkan, 2),
        "kijun": RD(kijun, 2),
        "span_a": RD(span_a, 2),
        "span_b": RD(span_b, 2),
        "chiko": RD(chiko, 2),
        "trend": trend,
    }


def identify_candle_patterns(records: list[dict]) -> list[dict]:
    """K 线形态识别（保持兼容）"""
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

        # Doji
        if body / total_range < 0.05:
            found.append("doji")
        # Hammer
        if not bullish and lower_wick > body * 2 and upper_wick < body * 0.5:
            found.append("hammer")
        # Shooting Star
        if bullish and upper_wick > body * 2 and lower_wick < body * 0.5:
            found.append("shooting_star")
        # Engulfing
        if i > 0:
            prev = records[i - 1]
            prev_open = prev.get("open", 0)
            prev_close = prev.get("close", 0)
            prev_bullish = prev_close > prev_open
            if bullish and not prev_bullish:
                if close_p > prev_open and open_p < prev_close:
                    found.append("bullish_engulfing")
            if not bullish and prev_bullish:
                if open_p > prev_close and close_p < prev_open:
                    found.append("bearish_engulfing")

        patterns.append({"date": r.get("date", ""), "patterns": found})

    return patterns


# ══════════════════════════════════════════════════════════
# 主入口
# ══════════════════════════════════════════════════════════

def analyze(records: list[dict], code: str = "") -> dict[str, Any]:
    """完整技术分析（带缓存）

    基于 K 线数据计算所有技术指标。

    Args:
        records: K线记录列表（每笔含 open/close/high/low/volume/date）
        code: 股票代码（用于缓存 key 区分）
    """
    if not records:
        return {"error": "无数据"}

    # 提取序列
    closes = np.array([r["close"] for r in records if r.get("close")], dtype=float)
    highs = np.array([r["high"] for r in records if r.get("high")], dtype=float)
    lows = np.array([r["low"] for r in records if r.get("low")], dtype=float)
    volumes = np.array([r["volume"] for r in records if r.get("volume", 0) > 0], dtype=float)

    if len(closes) == 0:
        return {"error": "无价格数据"}

    # 缓存
    last_date = records[-1].get("date", "") if records else ""
    first_date = records[0].get("date", "") if records else ""
    cache_key = make_cache_key("technical", code, last_date, first_date, str(len(records)))
    cache = get_cache()
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    # ── 基础指标（保持原输出格式） ──
    trend = calc_trend_status(closes)
    macd = calc_macd(closes)
    rsi = calc_rsi(closes)
    bollinger = calc_bollinger(closes)
    volume_ratio = calc_volume_ratio(records)

    bias_ma5 = calc_bias(closes, trend.get("ma5", 0))
    bias_ma20 = calc_bias(closes, trend.get("ma20", 0))

    price = closes[-1]
    ma5 = trend.get("ma5", 0)
    ma10 = trend.get("ma10", 0)
    support_ma5 = ma5 > 0 and abs(price - ma5) / ma5 < 0.01
    support_ma10 = ma10 > 0 and abs(price - ma10) / ma10 < 0.01

    # ── 综合评分（与原版逻辑一致） ──
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

    # ── Ichimoku + K线形态 ──
    ichimoku = calc_ichimoku(records)
    candle_patterns = identify_candle_patterns(records)

    # ══════════════════════════════════════════════════════
    # v2 新增指标
    # ══════════════════════════════════════════════════════
    kdj = calc_kdj(closes, highs, lows)
    cci = calc_cci(closes, highs, lows)
    wr = calc_wr(closes, highs, lows)
    atr = calc_atr(closes, highs, lows)
    dmi = calc_dmi(closes, highs, lows)
    obv = calc_obv(closes, volumes)
    mfi = calc_mfi(closes, highs, lows, volumes)

    new_indicators = {
        "kdj": kdj,
        "cci": cci,
        "wr": wr,
        "atr": atr,
        "dmi": dmi,
        "obv": obv,
        "mfi": mfi,
    }

    # ── SAR 需要额外计算（非向量化，有循环） ──
    if len(closes) >= 10:
        sar = calc_sar(highs, lows)
        new_indicators["sar"] = sar

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
        # v2 新增
        "indicators": new_indicators,
    }

    cache.set(cache_key, result, TTL_TECHNICAL)
    return result
