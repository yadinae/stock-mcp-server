"""
Pipeline Orchestrator — 串联各组件，管理漏斗执行生命周期

职责：
1. 按顺序执行 Pipeline 各阶段
2. 记录每个阶段的耗时和状态
3. 异常降级：某阶段失败时清空 candidates 并短路后续
4. 提供统一的结果格式
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, List, Optional

logger = logging.getLogger("stock-mcp.orchestrator")


class PhaseType(Enum):
    """Pipeline 阶段类型"""
    FUNNEL = "funnel"
    SIGNAL_CHECK = "signal_check"
    AUDIT = "audit"
    FEEDBACK = "feedback"


class StageStatus(Enum):
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class StageResult:
    """单个 Stage 的执行结果"""
    name: str
    status: StageStatus
    input_count: int
    output_count: int
    duration_ms: int = 0
    error: Optional[str] = None


@dataclass
class PipelineResult:
    """一次完整 Pipeline 执行的结果"""
    stages: List[StageResult] = field(default_factory=list)
    candidates: List[dict] = field(default_factory=list)
    total_ms: int = 0

    def summary(self) -> dict:
        return {
            "stages": len(self.stages),
            "candidates": len(self.candidates),
            "total_ms": self.total_ms,
            "pass_rates": {s.name: f"{s.output_count}/{s.input_count}"
                           for s in self.stages},
            "errors": [s.error for s in self.stages if s.error],
        }

    def report(self) -> str:
        """生成人类可读的执行报告"""
        lines = [
            f"Pipeline 执行报告",
            f"  总耗时: {self.total_ms}ms",
            f"  最终候选: {len(self.candidates)} 只",
            f"  阶段明细:",
        ]
        for s in self.stages:
            icon = "✓" if s.status == StageStatus.PASSED else "✗"
            err = f" [{s.error}]" if s.error else ""
            lines.append(
                f"    {icon} {s.name}: {s.input_count} → {s.output_count}"
                f" ({s.duration_ms}ms){err}"
            )
        return "\n".join(lines)


class Pipeline:
    """
    漏斗 Pipeline — 逐层收窄的选股流水线

    用法:
        pipe = Pipeline()
        pipe.add_stage("basic_filter", stage_basic_filter)
        pipe.add_stage("technical", stage_technical)
        result = pipe.run(universe, context={"min_amount": 5_000_000})
    """

    def __init__(self):
        self._stages: List[tuple] = []  # [(name, fn), ...]

    def add_stage(self, name: str, fn: Callable) -> Pipeline:
        """注册一个 Stage"""
        self._stages.append((name, fn))
        return self

    def run(self, universe: List[dict], context: Optional[dict] = None) -> PipelineResult:
        """
        执行漏斗

        Args:
            universe: 全市场股票列表
            context: 额外上下文（大盘水温、阈值参数等）

        Returns:
            PipelineResult: 各阶段统计和最终候选
        """
        result = PipelineResult()
        current = universe
        ctx = context or {}
        pipeline_start = time.time()

        for name, stage_fn in self._stages:
            input_count = len(current)
            stage_start = time.time()

            try:
                current = stage_fn(current, ctx)
                output_count = len(current)
                result.stages.append(StageResult(
                    name=name,
                    status=StageStatus.PASSED,
                    input_count=input_count,
                    output_count=output_count,
                    duration_ms=int((time.time() - stage_start) * 1000),
                ))
                logger.info(
                    "[%s] %d → %d (%dms)",
                    name, input_count, output_count,
                    result.stages[-1].duration_ms,
                )
            except Exception as e:
                logger.error("[%s] FAILED: %s", name, e, exc_info=True)
                result.stages.append(StageResult(
                    name=name,
                    status=StageStatus.FAILED,
                    input_count=input_count,
                    output_count=0,
                    duration_ms=int((time.time() - stage_start) * 1000),
                    error=str(e),
                ))
                # 降级：失败后清空，短路后续 Stage
                current = []
                break

        result.candidates = current
        result.total_ms = int((time.time() - pipeline_start) * 1000)
        return result
