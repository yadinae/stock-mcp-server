"""笔 — 缠论第三步

笔是连接相邻异向分型的线段。
规则：
1. 方向严格交替（↑↓↑↓...）
2. 顶底分型之间至少有1根独立K线（即分型间距离 >= 4 根合并K线）
3. 向上笔：底分型→顶分型，底的低点 < 顶的高点
4. 向下笔：顶分型→底分型，顶的高点 > 底的低点
"""
from __future__ import annotations

from .types import FX, FXType, Bi, Direction


def identify_bis(fractals: list[FX]) -> list[Bi]:
    """从分型序列构建笔

    算法：
    1. 严格交替：顶→底→顶→底...
    2. 每对相邻异向分型形成一笔
    3. 保证方向严格交替

    Args:
        fractals: 分型列表（已按时间排序）
    Returns:
        笔列表
    """
    if len(fractals) < 2:
        return []

    # 第一步：确保分型严格交替（同类型取极值）
    cleaned = _ensure_alternation(fractals)
    if len(cleaned) < 2:
        return []

    # 第二步：构建笔
    bis: list[Bi] = []
    for i in range(len(cleaned) - 1):
        start_fx = cleaned[i]
        end_fx = cleaned[i + 1]

        # 确定方向
        if start_fx.type == FXType.BOTTOM and end_fx.type == FXType.TOP:
            direction = Direction.UP
        elif start_fx.type == FXType.TOP and end_fx.type == FXType.BOTTOM:
            direction = Direction.DOWN
        else:
            continue  # 不应发生（已交替）

        # 验证有效性
        if direction == Direction.UP:
            if start_fx.value >= end_fx.value:
                continue  # 底必须低于顶
        else:
            if start_fx.value <= end_fx.value:
                continue  # 顶必须高于底

        # 计算笔的高低点
        if direction == Direction.UP:
            high = end_fx.high
            low = start_fx.low
        else:
            high = start_fx.high
            low = end_fx.low

        bis.append(Bi(
            idx=len(bis),
            start=start_fx,
            end=end_fx,
            direction=direction,
            high=high,
            low=low,
            confirmed=True,
        ))

    return bis


def _ensure_alternation(fx_list: list[FX]) -> list[FX]:
    """确保分型严格交替（顶→底→顶→底）

    如果连续出现同类型分型，保留极值的那个：
    - 连续顶分型：保留最高的
    - 连续底分型：保留最低的
    """
    if not fx_list:
        return []

    result: list[FX] = [fx_list[0]]

    for fx in fx_list[1:]:
        last = result[-1]

        if fx.type == last.type:
            # 同类型：保留极值
            if fx.type == FXType.TOP:
                if fx.value > last.value:
                    result[-1] = fx
            else:  # BOTTOM
                if fx.value < last.value:
                    result[-1] = fx
        else:
            # 异类型：直接加入
            result.append(fx)

    return result
