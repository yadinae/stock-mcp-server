"""均线+成交量选股策略：5日均线上穿20日均线且成交量放大。

移植自 Sequoia-X ma_volume.py，适配 MCP server。

选股条件：
1. 5日收盘均线上穿20日收盘均线（金叉）
2. 当日成交量 > 20日均量的 1.5 倍（放量确认）
"""
from __future__ import annotations

import logging

import pandas as pd

from .base import BaseStrategy, StrategyResult

logger = logging.getLogger("stock-mcp.strategy.ma_volume")


class MaVolumeStrategy(BaseStrategy):
    """均线+成交量选股策略"""

    name = "ma_volume"
    description = "均线金叉放量：MA5上穿MA20+成交量放大1.5倍"
    min_bars = 20

    def run(self) -> StrategyResult:
        all_klines = self._get_all_klines_bulk()
        scan_count = len(all_klines)
        selected = []

        for symbol, df in all_klines.items():
            try:
                # 向量化计算均线和成交量均值
                df["ma5"] = df["close"].rolling(5).mean()
                df["ma20"] = df["close"].rolling(20).mean()
                df["vol_ma20"] = df["volume"].rolling(20).mean()

                last = df.iloc[-1]
                prev = df.iloc[-2]

                if pd.isna(last["ma5"]) or pd.isna(last["ma20"]) or pd.isna(last["vol_ma20"]):
                    continue

                # 条件 1：金叉（昨日 ma5 < ma20，今日 ma5 > ma20）
                golden_cross = prev["ma5"] < prev["ma20"] and last["ma5"] > last["ma20"]

                # 条件 2：放量
                volume_surge = last["volume"] > last["vol_ma20"] * 1.5

                if golden_cross and volume_surge:
                    selected.append({
                        "code": symbol,
                        "close": round(float(last["close"]), 2),
                        "ma5": round(float(last["ma5"]), 2),
                        "ma20": round(float(last["ma20"]), 2),
                        "volume_ratio": round(float(last["volume"]) / float(last["vol_ma20"]), 2),
                    })
            except Exception as e:
                logger.warning(f"[{symbol}] MaVolume 计算失败: {e}")
                continue

        return StrategyResult(
            strategy_name=self.name,
            selected=selected,
            scan_count=scan_count,
            select_count=len(selected),
        )
