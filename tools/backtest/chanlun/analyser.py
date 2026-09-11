"""缠论分析器 — 串联完整流水线

K线合并 → 分型识别 → 笔 → 中枢 → 线段 → 买卖点 → 背驰
"""
from __future__ import annotations

from typing import Any

from .types import ChanlunResult
from .merge import merge_klines
from .fractal import identify_fractals
from .bi import identify_bis
from .zhongshu import identify_zhongshus
from .signal import identify_signals
from .divergence import identify_divergences


class ChanlunAnalyser:
    """缠论分析器 — 一键完成全流水线分析

    用法::

        analyser = ChanlunAnalyser(code="000001", frequency="DAILY")
        result = analyser.analyse(records)
        print(result.to_dict())
    """

    def __init__(self, code: str = "", frequency: str = "DAILY"):
        self.code = code
        self.frequency = frequency

    def analyse(self, records: list[dict]) -> ChanlunResult:
        """执行完整缠论分析

        Args:
            records: K线数据（按日期正序，每条含 date/open/high/low/close/volume）
        Returns:
            ChanlunResult 完整分析结果
        """
        raw_count = len(records)

        # Step 1: K线合并
        merged = merge_klines(records)

        # Step 2: 分型识别
        fractals = identify_fractals(merged)

        # Step 3: 笔
        bis = identify_bis(fractals)

        # Step 4: 中枢
        zhongshus = identify_zhongshus(bis)

        # Step 5: 买卖点信号
        signals = identify_signals(bis, zhongshus)

        # Step 6: 背驰
        divergences = identify_divergences(bis, zhongshus)

        return ChanlunResult(
            code=self.code,
            frequency=self.frequency,
            raw_klines=raw_count,
            merged_klines=len(merged),
            fractals=fractals,
            bis=bis,
            zhongshus=zhongshus,
            xianduans=[],  # 线段为高级别分析，暂不实现
            signals=signals,
            divergences=divergences,
        )
