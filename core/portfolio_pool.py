#!/usr/bin/env python3
"""Portfolio Worker Pool — 并发执行 + 分阶段进度 + Graceful Degradation

灵感来自 easy-stock (https://github.com/jundizhou/easy-stock) portfolioinspection，但适配 stock-mcp-server 的 MCP 工具场景。

核心设计：
1. ThreadPoolExecutor 并发执行多只股票的分析
2. 每只股票独立结果（成功/失败/降级）
3. Coverage 计算：成功权重 / 总权重
4. Coverage ≥ 阈值 → 生成完整报告；否则降级
5. 实时进度追踪（已分析 N/M）
"""
from __future__ import annotations

import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Optional


# ─── 配置常量 ──────────────────────────────────────────────────
DEFAULT_CONCURRENCY = 5       # 默认并发数（东财/Tencent 限流友好）
MAX_CONCURRENCY = 10          # 最大并发数
DEFAULT_TIMEOUT_S = 300       # 单只股票分析超时（秒）
MIN_COVERAGE_PCT = 60.0       # 最低覆盖率（低于此降级）
DEFAULT_WEIGHT = 1.0          # 默认权重


@dataclass
class StockTask:
    """单只股票分析任务"""
    code: str
    weight: float = DEFAULT_WEIGHT
    cost_price: Optional[float] = None
    shares: Optional[float] = None
    name: Optional[str] = None
    extra: dict = field(default_factory=dict)  # 附加参数


@dataclass
class StockResult:
    """单只股票分析结果"""
    code: str
    weight: float
    status: str = "queued"     # queued | running | succeeded | failed | degraded
    result: Optional[dict] = None
    error: Optional[str] = None
    duration_ms: int = 0
    degraded_fields: list = field(default_factory=list)


@dataclass
class InspectionReport:
    """组合巡检报告"""
    stage: str = "queued"      # queued | analyzing | aggregating | completed | degraded
    total_stocks: int = 0
    completed_stocks: int = 0
    succeeded: int = 0
    failed: int = 0
    coverage_pct: float = 0.0
    results: list = field(default_factory=list)
    report: Optional[dict] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)


def _analyze_single_stock(
    task: StockTask,
    analyze_fn: Callable[[StockTask], dict],
    timeout_s: int = DEFAULT_TIMEOUT_S,
) -> StockResult:
    """分析单只股票（在线程中执行）"""
    start = time.monotonic()
    result = StockResult(code=task.code, weight=task.weight, status="running")
    try:
        data = analyze_fn(task)
        result.status = "succeeded"
        result.result = data
        result.duration_ms = int((time.monotonic() - start) * 1000)
        return result
    except TimeoutError:
        result.status = "failed"
        result.error = f"分析超时（{timeout_s}s）"
        result.duration_ms = int((time.monotonic() - start) * 1000)
        return result
    except Exception as e:
        result.status = "failed"
        result.error = f"{type(e).__name__}: {e}"
        result.duration_ms = int((time.monotonic() - start) * 1000)
        return result


def _degrade_result(result: StockResult, available_fields: list[str]) -> StockResult:
    """降级处理：保留可用字段，标记缺失字段"""
    if result.result is None:
        return result

    full_keys = set(result.result.keys())
    missing = full_keys - set(available_fields)
    if missing:
        result.degraded_fields = list(missing)
        result.status = "degraded"
    return result


def calculate_coverage(tasks: list[StockTask], results: list[StockResult]) -> float:
    """计算覆盖率（按权重加权）

    Returns:
        0~100 的覆盖率百分比
    """
    total_weight = sum(t.weight for t in tasks)
    if total_weight <= 0:
        return 0.0

    success_weight = 0.0
    result_map = {r.code: r for r in results}
    for task in tasks:
        r = result_map.get(task.code)
        if r and r.status in ("succeeded", "degraded"):
            success_weight += task.weight

    return round(success_weight / total_weight * 100, 1)


def run_portfolio_inspection(
    tasks: list[StockTask],
    analyze_fn: Callable[[StockTask], dict],
    concurrency: int = DEFAULT_CONCURRENCY,
    timeout_s: int = DEFAULT_TIMEOUT_S,
    min_coverage: float = MIN_COVERAGE_PCT,
    on_progress: Optional[Callable[[InspectionReport], None]] = None,
) -> InspectionReport:
    """执行组合巡检 — 并发分析 + 进度回调 + 降级

    Args:
        tasks: 股票分析任务列表
        analyze_fn: 分析函数，签名 (StockTask) -> dict
        concurrency: 并发数（限制 API 限流）
        timeout_s: 单只股票超时
        min_coverage: 最低覆盖率阈值
        on_progress: 进度回调（每完成一只股票触发一次）

    Returns:
        InspectionReport 完整报告
    """
    concurrency = min(concurrency, MAX_CONCURRENCY, len(tasks))
    report = InspectionReport(
        stage="analyzing",
        total_stocks=len(tasks),
        started_at=datetime.now(),
    )
    results: list[StockResult] = []

    # 并发执行
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = {
            executor.submit(_analyze_single_stock, task, analyze_fn, timeout_s): task
            for task in tasks
        }

        for future in as_completed(futures):
            task = futures[future]
            try:
                result = future.result(timeout=timeout_s + 5)
            except Exception as e:
                result = StockResult(
                    code=task.code, weight=task.weight,
                    status="failed", error=f"执行异常: {e}",
                )

            results.append(result)
            report.completed_stocks = len(results)
            report.succeeded = sum(1 for r in results if r.status in ("succeeded", "degraded"))
            report.failed = sum(1 for r in results if r.status == "failed")
            report.results = results
            report.coverage_pct = calculate_coverage(tasks, results)

            if on_progress:
                try:
                    on_progress(report)
                except Exception:
                    pass  # 进度回调不应阻塞主流程

    # 聚合阶段
    report.stage = "aggregating"
    report.completed_at = datetime.now()

    # 判断是否降级
    if report.coverage_pct < min_coverage:
        report.stage = "degraded"
        report.warnings.append(
            f"有效分析仅覆盖 {report.coverage_pct}% 持仓，"
            f"低于阈值 {min_coverage}%，报告可能不完整"
        )
        # 降级处理：标记缺失字段
        available_fields = _detect_available_fields(results)
        for r in results:
            if r.status == "succeeded":
                _degrade_result(r, available_fields)
    else:
        report.stage = "completed"

    return report


def _detect_available_fields(results: list[StockResult]) -> list[str]:
    """从成功结果中检测可用字段"""
    fields = set()
    for r in results:
        if r.status == "succeeded" and r.result:
            fields.update(r.result.keys())
    return sorted(fields)


def report_to_dict(report: InspectionReport) -> dict:
    """将 InspectionReport 转为可序列化的 dict"""
    return {
        "stage": report.stage,
        "total_stocks": report.total_stocks,
        "completed_stocks": report.completed_stocks,
        "succeeded": report.succeeded,
        "failed": report.failed,
        "coverage_pct": report.coverage_pct,
        "started_at": report.started_at.isoformat() if report.started_at else None,
        "completed_at": report.completed_at.isoformat() if report.completed_at else None,
        "duration_ms": (
            int((report.completed_at - report.started_at).total_seconds() * 1000)
            if report.completed_at and report.started_at else None
        ),
        "results": [
            {
                "code": r.code,
                "weight": r.weight,
                "status": r.status,
                "duration_ms": r.duration_ms,
                "error": r.error,
                "degraded_fields": r.degraded_fields,
                "result": r.result,
            }
            for r in report.results
        ],
        "warnings": report.warnings,
        "errors": report.errors,
    }
