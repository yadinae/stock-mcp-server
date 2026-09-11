"""买卖点信号 — 缠论第五步

缠论定义三类买点和三类卖点：

一类买点：下跌趋势末端，中枢下方力度衰减后的第一个低点
二类买点：一类买点后的回调不创新低
三类买点：回调不破中枢上沿

一类卖点：上涨趋势末端，中枢上方力度衰减后的第一个高点
二类卖点：一类卖点后的反弹不创新高
三类卖点：反弹不破中枢下沿
"""
from __future__ import annotations

from .types import Bi, ZS, MMD, Direction


def identify_signals(
    bis: list[Bi], zhongshus: list[ZS],
) -> list[MMD]:
    """识别买卖点信号

    Args:
        bis: 笔列表
        zhongshus: 中枢列表
    Returns:
        买卖点信号列表
    """
    signals: list[MMD] = []

    if not bis or not zhongshus:
        return signals

    # ── 一类买卖点：力度衰减 ──
    signals.extend(_find_1st_signals(bis, zhongshus))

    # ── 二类买卖点：回调不创新低/反弹不创新高 ──
    signals.extend(_find_2nd_signals(bis, zhongshus))

    # ── 三类买卖点：不进入中枢 ──
    signals.extend(_find_3rd_signals(bis, zhongshus))

    return signals


def _find_1st_signals(bis: list[Bi], zhongshus: list[ZS]) -> list[MMD]:
    """一类买卖点：力度衰减（需配合背驰判断）

    简化版：中枢下方的最后一笔力度 < 前一笔力度 → 一类买点
            中枢上方的最后一笔力度 < 前一笔力度 → 一类卖点
    """
    signals = []

    for zs_idx, zs in enumerate(zhongshus):
        if len(zs.lines) < 3:
            continue

        # 中枢前一笔（进入中枢的笔）
        pre_bi = None
        for b in bis:
            if b.end.idx == zs.lines[0].start.idx:
                pre_bi = b
                break

        # 中枢后一笔（离开中枢的笔）
        post_bi = None
        last_bi = zs.lines[-1]
        for b in bis:
            if b.start.idx == last_bi.end.idx:
                post_bi = b
                break

        if post_bi is None:
            continue

        # 一类买点：向下离开中枢后力度衰减
        if post_bi.direction == Direction.DOWN and pre_bi:
            pre_range = abs(pre_bi.high - pre_bi.low)
            post_range = abs(post_bi.high - post_bi.low)
            if post_range < pre_range * 0.7:
                signals.append(MMD(
                    type="1buy",
                    date=post_bi.end.date,
                    price=post_bi.end.value,
                    description=(f"一类买点: 中枢下方力度衰减 "
                                 f"(前笔振幅={pre_range:.2f}, "
                                 f"现笔振幅={post_range:.2f})"),
                    kline_idx=post_bi.end.kline_idx,
                ))

        # 一类卖点：向上离开中枢后力度衰减
        elif post_bi.direction == Direction.UP and pre_bi:
            pre_range = abs(pre_bi.high - pre_bi.low)
            post_range = abs(post_bi.high - post_bi.low)
            if post_range < pre_range * 0.7:
                signals.append(MMD(
                    type="1sell",
                    date=post_bi.end.date,
                    price=post_bi.end.value,
                    description=(f"一类卖点: 中枢上方力度衰减 "
                                 f"(前笔振幅={pre_range:.2f}, "
                                 f"现笔振幅={post_range:.2f})"),
                    kline_idx=post_bi.end.kline_idx,
                ))

    return signals


def _find_2nd_signals(bis: list[Bi], zhongshus: list[ZS]) -> list[MMD]:
    """二类买卖点：回调不创新低/反弹不创新高"""
    signals = []

    for zs_idx, zs in enumerate(zhongshus):
        if len(zs.lines) < 5:
            continue

        # 一类买点后，回调不创新低 → 二类买点
        first_buy_low = zs.dd  # 中枢区间最低点
        for b in zs.lines:
            if b.direction == Direction.DOWN and b.low > first_buy_low:
                # 找到一笔低点高于中枢最低点的 → 确认二类买点
                signals.append(MMD(
                    type="2buy",
                    date=b.end.date,
                    price=b.end.value,
                    description=f"二类买点: 回调不创新低 (低点={b.low:.2f} > 中枢低={first_buy_low:.2f})",
                    kline_idx=b.end.kline_idx,
                ))
                break  # 只取第一个

        # 一类卖点后，反弹不创新高 → 二类卖点
        first_sell_high = zs.gg
        for b in zs.lines:
            if b.direction == Direction.UP and b.high < first_sell_high:
                signals.append(MMD(
                    type="2sell",
                    date=b.end.date,
                    price=b.end.value,
                    description=f"二类卖点: 反弹不创新高 (高点={b.high:.2f} < 中枢高={first_sell_high:.2f})",
                    kline_idx=b.end.kline_idx,
                ))
                break

    return signals


def _find_3rd_signals(bis: list[Bi], zhongshus: list[ZS]) -> list[MMD]:
    """三类买卖点：回调不进入中枢"""
    signals = []

    for zs_idx, zs in enumerate(zhongshus):
        if not zs.lines:
            continue

        last_bi = zs.lines[-1]
        # 找中枢后的笔
        post_bis = [b for b in bis if b.start.idx >= last_bi.end.idx]
        if len(post_bis) < 2:
            continue

        # 三类买点：回调（向下笔）不破中枢上沿
        for b in post_bis:
            if b.direction == Direction.DOWN and b.low > zs.zg:
                signals.append(MMD(
                    type="3buy",
                    date=b.end.date,
                    price=b.end.value,
                    description=f"三类买点: 回调不破中枢上沿 (低点={b.low:.2f} > zg={zs.zg:.2f})",
                    kline_idx=b.end.kline_idx,
                ))
                break

        # 三类卖点：反弹（向上笔）不破中枢下沿
        for b in post_bis:
            if b.direction == Direction.UP and b.high < zs.zd:
                signals.append(MMD(
                    type="3sell",
                    date=b.end.date,
                    price=b.end.value,
                    description=f"三类卖点: 反弹不破中枢下沿 (高点={b.high:.2f} < zd={zs.zd:.2f})",
                    kline_idx=b.end.kline_idx,
                ))
                break

    return signals
