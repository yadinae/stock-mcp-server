"""中枢 — 缠论第四步

中枢 = 至少3笔重叠形成的密集成交区间。

定义：
- zg = 中枢上沿 = 区间内最高的低点（各笔低点中的最大值）
- zd = 中枢下沿 = 区间内最低的高点（各笔高点中的最小值）
- gg = 区间内最高价
- dd = 区间内最低价

条件：zg > zd（必须有重叠）
"""
from __future__ import annotations

from .types import Bi, ZS, Direction


def identify_zhongshus(bis: list[Bi]) -> list[ZS]:
    """从笔序列识别中枢

    算法：滑动窗口
    1. 取连续3笔，计算重叠区间
    2. 如果 zg > zd，则构成中枢
    3. 后续笔如果仍在中枢范围内（进入 zg~zd 区间），扩大中枢
    4. 笔完全脱离中枢后，该中枢确认完成

    Args:
        bis: 笔列表
    Returns:
        中枢列表
    """
    if len(bis) < 3:
        return []

    zhongshus: list[ZS] = []
    i = 0

    while i < len(bis) - 2:
        # 尝试从第 i 笔开始构建中枢
        b1, b2, b3 = bis[i], bis[i + 1], bis[i + 2]

        # 3笔的重叠区间
        zg, zd = _overlap_range([b1, b2, b3])
        if zg <= zd:
            i += 1
            continue

        # 找到中枢，尝试扩展
        zs_bis = [b1, b2, b3]
        gg = max(b.high for b in zs_bis)
        dd = min(b.low for b in zs_bis)
        j = i + 3

        while j < len(bis):
            bj = bis[j]
            # 笔是否进入中枢范围（与 zg~zd 有交集）
            if bj.low <= zg and bj.high >= zd:
                zs_bis.append(bj)
                gg = max(gg, bj.high)
                dd = min(dd, bj.low)
                j += 1
            else:
                break

        # 判断中枢是否已脱离
        confirmed = True
        if j < len(bis):
            next_bi = bis[j]
            # 未脱离：价格仍在中枢范围内
            if next_bi.low <= zg and next_bi.high >= zd:
                confirmed = False

        zhongshus.append(ZS(
            idx=len(zhongshus),
            zg=zg,
            zd=zd,
            gg=gg,
            dd=dd,
            lines=zs_bis,
            confirmed=confirmed,
        ))

        i = j  # 跳到中枢之后继续

    return zhongshus


def _overlap_range(bis: list[Bi]) -> tuple[float, float]:
    """计算多笔的重叠区间

    Returns:
        (zg, zd) — 上沿和下沿
        如果无重叠则 zg <= zd
    """
    if not bis:
        return 0.0, 0.0

    # zg = 各笔低点中的最大值（上沿）
    zg = min(b.high for b in bis)  # 各笔高点的最小值

    # zd = 各笔高点中的最小值（下沿）
    zd = max(b.low for b in bis)   # 各笔低点中的最大值

    return zg, zd
