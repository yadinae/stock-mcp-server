"""K 线合并（包含处理）— 缠论第一步

规则：相邻 K 线若存在包含关系，需合并。
- 向上趋势：取高的高、高的低
- 向下趋势：取低的高、低的低
"""
from __future__ import annotations

from .types import Kline, CLKline, Direction


def merge_klines(records: list[dict]) -> list[CLKline]:
    """将原始 K 线进行包含处理，生成缠论 K 线序列

    Args:
        records: 原始 K 线数据列表（按日期正序）
    Returns:
        合并后的 CLKline 列表
    """
    if not records:
        return []

    # 转为 Kline 对象
    klines = []
    for i, r in enumerate(records):
        klines.append(Kline(
            idx=i,
            date=r.get("date", ""),
            open=float(r.get("open", 0)),
            high=float(r.get("high", 0)),
            low=float(r.get("low", 0)),
            close=float(r.get("close", 0)),
            volume=float(r.get("volume", 0)),
        ))

    if len(klines) < 2:
        return [CLKline(
            idx=0, date=klines[0].date,
            high=klines[0].high, low=klines[0].low,
            direction=Direction.UP, raw_start=0, raw_end=0,
        )]

    merged: list[CLKline] = []

    # 初始化：用前两根确定初始方向
    first, second = klines[0], klines[1]
    init_dir = Direction.UP if second.high >= first.high else Direction.DOWN

    # 第一根直接加入
    merged.append(CLKline(
        idx=0, date=first.date,
        high=first.high, low=first.low,
        direction=init_dir, raw_start=0, raw_end=0,
    ))

    # 从第二根开始处理
    for i in range(1, len(klines)):
        k = klines[i]
        prev = merged[-1]

        # 判断包含关系：prev 包含 k 或 k 包含 prev
        has_inclusion = (
            (prev.high >= k.high and prev.low <= k.low) or
            (k.high >= prev.high and k.low <= prev.low)
        )

        if has_inclusion:
            # 包含处理：根据方向合并
            if prev.direction == Direction.UP:
                # 向上：取高的高、高的低
                new_high = max(prev.high, k.high)
                new_low = max(prev.low, k.low)
            else:
                # 向下：取低的高、低的低
                new_high = min(prev.high, k.high)
                new_low = min(prev.low, k.low)

            # 更新最后一根合并 K 线
            merged[-1] = CLKline(
                idx=prev.idx,
                date=prev.date,  # 保持第一根的日期
                high=new_high,
                low=new_low,
                direction=prev.direction,
                raw_start=prev.raw_start,
                raw_end=i,
            )
        else:
            # 无包含关系：直接加入
            new_dir = Direction.UP if k.high > prev.high else Direction.DOWN
            merged.append(CLKline(
                idx=len(merged),
                date=k.date,
                high=k.high,
                low=k.low,
                direction=new_dir,
                raw_start=i,
                raw_end=i,
            ))

    return merged
