"""分型识别 — 缠论第二步

顶分型：中间 K 线的高点 > 左右两根的高点
底分型：中间 K 线的低点 < 左右两根的低点
"""
from __future__ import annotations

from .types import CLKline, FX, FXType


def identify_fractals(klines: list[CLKline]) -> list[FX]:
    """识别顶分型和底分型

    Args:
        klines: 合并后的 K 线序列
    Returns:
        分型列表（按时间顺序）
    """
    if len(klines) < 3:
        return []

    fractals: list[FX] = []

    for i in range(1, len(klines) - 1):
        left, mid, right = klines[i - 1], klines[i], klines[i + 1]

        # 顶分型：中间最高
        if mid.high > left.high and mid.high > right.high:
            fractals.append(FX(
                idx=mid.idx,
                type=FXType.TOP,
                date=mid.date,
                high=mid.high,
                low=mid.low,
                value=mid.high,
                kline_idx=mid.raw_start,
            ))

        # 底分型：中间最低
        elif mid.low < left.low and mid.low < right.low:
            fractals.append(FX(
                idx=mid.idx,
                type=FXType.BOTTOM,
                date=mid.date,
                high=mid.high,
                low=mid.low,
                value=mid.low,
                kline_idx=mid.raw_start,
            ))

    return fractals
