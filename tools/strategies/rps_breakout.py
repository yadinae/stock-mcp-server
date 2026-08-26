"""RPS 极强动量突破策略：120日相对强度排位≥90% + 接近新高。

移植自 Sequoia-X rps_breakout.py，适配 MCP server。

选股条件：
1. RPS ≥ 90（120日涨幅排位在全市场前10%）
2. 当前价格 ≥ 120日最高价的 90%（接近新高）
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from .base import BaseStrategy, StrategyResult

logger = logging.getLogger("stock-mcp.strategy.rps_breakout")


class RpsBreakoutStrategy(BaseStrategy):
    """RPS 极强动量突破策略"""

    name = "rps_breakout"
    description = "欧奈尔RPS突破：120日相对强度Top10%+接近新高"
    min_bars = 120

    def run(self) -> StrategyResult:
        all_klines = self._get_all_klines_bulk()
        scan_count = len(all_klines)
        selected = []

        if not all_klines:
            return StrategyResult(
                strategy_name=self.name, selected=[],
                scan_count=0, select_count=0,
                error="缓存无数据，请先运行 baostock 回填",
            )

        # ── Phase 1: 全市场计算120日涨幅 ──
        pct_changes = {}
        roll_highs = {}
        last_prices = {}

        for symbol, df in all_klines.items():
            try:
                if len(df) < 120:
                    continue
                close_arr = df["close"].values
                high_arr = df["high"].values

                # 120日涨幅
                base = close_arr[-120]
                if base == 0 or pd.isna(base):
                    continue
                pct_change = float((close_arr[-1] - base) / base)
                pct_changes[symbol] = pct_change

                # 120日滚动最高价
                roll_high = float(np.max(high_arr[-120:]))
                roll_highs[symbol] = roll_high

                # 当前价
                last_prices[symbol] = float(close_arr[-1])
            except Exception:
                continue

        if not pct_changes:
            return StrategyResult(
                strategy_name=self.name, selected=[],
                scan_count=scan_count, select_count=0,
                error="无足够120日数据",
            )

        # ── Phase 2: 横向排位（RPS） ──
        sorted_symbols = sorted(pct_changes.keys(), key=lambda s: pct_changes[s])
        n = len(sorted_symbols)
        rps_map = {}
        for rank, sym in enumerate(sorted_symbols):
            rps_map[sym] = (rank + 1) / n * 100

        # ── Phase 3: 筛选 RPS ≥ 90 且接近新高 ──
        for symbol in rps_map:
            if rps_map[symbol] < 90:
                continue
            price = last_prices[symbol]
            rh = roll_highs[symbol]
            if rh == 0:
                continue
            # 接近新高：当前价 ≥ 120日最高价的 90%
            if price >= rh * 0.90:
                selected.append({
                    "code": symbol,
                    "close": round(price, 2),
                    "rps": round(rps_map[symbol], 1),
                    "roll_high_120d": round(rh, 2),
                    "pct_from_high": round((price / rh - 1) * 100, 1),
                    "return_120d_pct": round(pct_changes[symbol] * 100, 1),
                })

        # 按 RPS 排序
        selected.sort(key=lambda x: x["rps"], reverse=True)

        return StrategyResult(
            strategy_name=self.name,
            selected=selected,
            scan_count=scan_count,
            select_count=len(selected),
            details={
                "rps_threshold": 90,
                "rps_period": 120,
                "high_proximity": 0.90,
            },
        )
