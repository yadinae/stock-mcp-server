"""背驰检测 — 缠论第六步

背驰 = 力度衰减信号，表明当前走势动力正在减弱。

类型：
- 笔背驰 (bi)：同向相邻两笔比较，后一笔力度 < 前一笔
- 盘整背驰 (pz)：同一中枢内，末笔力度 < 首笔力度
- 趋势背驰 (qs)：两个同向中枢之间比较，后一中枢离开力度 < 前一中枢

力度计算：使用笔的振幅（high - low）近似 MACD 面积
"""
from __future__ import annotations

from .types import Bi, ZS, BC, BCType, Direction


def identify_divergences(
    bis: list[Bi], zhongshus: list[ZS],
) -> list[BC]:
    """检测背驰信号

    Args:
        bis: 笔列表
        zhongshus: 中枢列表
    Returns:
        背驰信号列表
    """
    divergences: list[BC] = []

    # 笔背驰
    divergences.extend(_bi_divergence(bis))

    # 盘整背驰
    divergences.extend(_panzheng_divergence(zhongshus))

    # 趋势背驰
    divergences.extend(_qushi_divergence(zhongshus))

    return divergences


def _bi_force(bi: Bi) -> float:
    """计算笔的力度（振幅）"""
    return abs(bi.high - bi.low)


def _bi_divergence(bis: list[Bi]) -> list[BC]:
    """笔背驰：同向相邻两笔比较

    后一笔力度 < 前一笔力度 → 该方向动力减弱
    """
    divergences = []

    if len(bis) < 3:
        return divergences

    for i in range(2, len(bis)):
        curr = bis[i]
        # 找同方向的前一笔
        prev = None
        for j in range(i - 1, -1, -1):
            if bis[j].direction == curr.direction:
                prev = bis[j]
                break

        if prev is None:
            continue

        force_curr = _bi_force(curr)
        force_prev = _bi_force(prev)

        if force_prev > 0 and force_curr < force_prev * 0.8:
            divergences.append(BC(
                type=BCType.BI,
                date=curr.end.date,
                confirmed=True,
                description=(f"笔背驰: 笔[{curr.idx}] 力度={force_curr:.2f} < "
                             f"笔[{prev.idx}] 力度={force_prev:.2f}"),
            ))

    return divergences


def _panzheng_divergence(zhongshus: list[ZS]) -> list[BC]:
    """盘整背驰：同一中枢内，末笔力度 < 首笔力度"""
    divergences = []

    for zs in zhongshus:
        if len(zs.lines) < 4:
            continue

        first_bi = zs.lines[0]
        last_bi = zs.lines[-1]

        force_first = _bi_force(first_bi)
        force_last = _bi_force(last_bi)

        if force_first > 0 and force_last < force_first * 0.7:
            divergences.append(BC(
                type=BCType.PANZHENG,
                date=last_bi.end.date,
                confirmed=True,
                description=(f"盘整背驰: 中枢[{zs.idx}] 内末笔力度={force_last:.2f} < "
                             f"首笔力度={force_first:.2f}"),
            ))

    return divergences


def _qushi_divergence(zhongshus: list[ZS]) -> list[BC]:
    """趋势背驰：两个同向中枢之间比较

    后一中枢离开力度 < 前一中枢离开力度 → 趋势可能终结
    """
    divergences = []

    if len(zhongshus) < 2:
        return divergences

    for i in range(1, len(zhongshus)):
        prev_zs = zhongshus[i - 1]
        curr_zs = zhongshus[i]

        if not prev_zs.lines or not curr_zs.lines:
            continue

        # 前一中枢的离开笔
        prev_leave = prev_zs.lines[-1]
        # 当前中枢的进入笔（第一笔）
        curr_enter = curr_zs.lines[0]

        force_prev = _bi_force(prev_leave)
        force_curr = _bi_force(curr_enter)

        if force_prev > 0 and force_curr < force_prev * 0.7:
            # 判断方向
            if prev_leave.direction == Direction.UP:
                divergences.append(BC(
                    type=BCType.QUSHI_UP,
                    date=curr_enter.start.date,
                    confirmed=True,
                    description=(f"趋势背驰(上): 中枢[{prev_zs.idx}] 离开力度={force_prev:.2f} < "
                                 f"中枢[{curr_zs.idx}] 进入力度={force_curr:.2f}"),
                ))
            else:
                divergences.append(BC(
                    type=BCType.QUSHI_DOWN,
                    date=curr_enter.start.date,
                    confirmed=True,
                    description=(f"趋势背驰(下): 中枢[{prev_zs.idx}] 离开力度={force_prev:.2f} < "
                                 f"中枢[{curr_zs.idx}] 进入力度={force_curr:.2f}"),
                ))

    return divergences
