"""高旗形整理策略：强动量后极度收敛缩量。

移植自 Sequoia-X high_tight_flag.py，适配 MCP server。

选股条件：
1. 强动量：过去40天区间最高价 / 最低价 > 1.6（涨幅超60%）
2. 极度收敛：最近10天区间最高价 / 最低价 < 1.15（振幅低于15%）
3. 高位抗跌：近10天最低点不得低于40天最高点的80%
4. 缩量：今日 volume < 过去20日 volume 均值的 0.6 倍
"""
from __future__ import annotations

import logging

import pandas as pd

from .base import BaseStrategy, StrategyResult

logger = logging.getLogger("stock-mcp.strategy.high_tight_flag")


class HighTightFlagStrategy(BaseStrategy):
    """高旗形整理策略"""

    name = "high_tight_flag"
    description = "高窄旗形整理：强动量后极度收敛+缩量，突破前形态"
    min_bars = 40

    def run(self) -> StrategyResult:
        all_klines = self._get_all_klines_bulk()
        scan_count = len(all_klines)
        selected = []

        for symbol, df in all_klines.items():
            try:
                tail40 = df.tail(40)
                tail10 = df.tail(10)

                high40 = tail40["high"].max()
                low40 = tail40["low"].min()
                high10 = tail10["high"].max()
                low10 = tail10["low"].min()

                if low40 == 0 or low10 == 0:
                    continue

                # 条件 1：强动量（40日振幅 > 60%）
                momentum = high40 / low40 > 1.6

                # 条件 2：极度收敛（10日振幅 < 15%）
                consolidation = high10 / low10 < 1.15

                # 条件 3：高位抗跌
                high_level = low10 >= high40 * 0.8

                # 条件 4：缩量
                vol_ma20 = df["volume"].iloc[-21:-1].mean()
                shrink = df["volume"].iloc[-1] < vol_ma20 * 0.6

                if momentum and consolidation and high_level and shrink:
                    last = df.iloc[-1]
                    selected.append({
                        "code": symbol,
                        "close": round(float(last["close"]), 2),
                        "range_40d": f"{round(float(low40),2)}-{round(float(high40),2)}",
                        "momentum_pct": round((high40 / low40 - 1) * 100, 1),
                        "range_10d": f"{round(float(low10),2)}-{round(float(high10),2)}",
                        "consolidation_pct": round((high10 / low10 - 1) * 100, 1),
                        "vol_shrink_ratio": round(float(df['volume'].iloc[-1]) / vol_ma20, 2),
                    })
            except Exception as e:
                logger.warning(f"[{symbol}] HighTightFlag 计算失败: {e}")
                continue

        # 按动量强度排序
        selected.sort(key=lambda x: x["momentum_pct"], reverse=True)

        return StrategyResult(
            strategy_name=self.name,
            selected=selected,
            scan_count=scan_count,
            select_count=len(selected),
        )
