"""海龟交易策略：20日新高突破 + 成交额过亿 + 动量阳线过滤。

移植自 Sequoia-X turtle_trade.py，适配 MCP server。

选股条件：
1. 突破新高：今日 close > 前20个交易日 high 的最大值
2. 流动性：今日 turnover > 1亿
3. 防诱多：今日必须是实体阳线（close > open），且真涨（close > 昨日 close）
"""
from __future__ import annotations

import logging

import pandas as pd

from .base import BaseStrategy, StrategyResult

logger = logging.getLogger("stock-mcp.strategy.turtle")


class TurtleTradeStrategy(BaseStrategy):
    """海龟交易策略（A股防诱多改良版）"""

    name = "turtle_trade"
    description = "海龟突破：20日新高+成交额过亿+阳线防诱多"
    min_bars = 21

    def run(self) -> StrategyResult:
        all_klines = self._get_all_klines_bulk()
        scan_count = len(all_klines)
        selected = []

        for symbol, df in all_klines.items():
            try:
                # 向量化：前20日 high 的滚动最大值（不含当日）
                df["high_20"] = df["high"].shift(1).rolling(20).max()

                last = df.iloc[-1]
                prev = df.iloc[-2]

                if pd.isna(last["high_20"]):
                    continue

                # 核心条件 1：突破前 20 天最高点
                breakout = last["close"] > last["high_20"]

                # 核心条件 2：流动性过亿
                liquid = last["turnover"] > 100_000_000

                # 防守条件：实体阳线 + 真涨
                is_yang = last["close"] > last["open"]
                is_up = last["close"] > prev["close"]

                if breakout and liquid and is_yang and is_up:
                    selected.append({
                        "code": symbol,
                        "close": round(float(last["close"]), 2),
                        "turnover_yi": round(float(last["turnover"]) / 1e8, 2),
                        "high_20": round(float(last["high_20"]), 2),
                        "breakout_pct": round(
                            (float(last["close"]) / float(last["high_20"]) - 1) * 100, 2
                        ),
                    })
            except Exception as e:
                logger.warning(f"[{symbol}] TurtleTrade 计算失败: {e}")
                continue

        # 按成交额排序（流动性优先）
        selected.sort(key=lambda x: x["turnover_yi"], reverse=True)

        return StrategyResult(
            strategy_name=self.name,
            selected=selected,
            scan_count=scan_count,
            select_count=len(selected),
        )
