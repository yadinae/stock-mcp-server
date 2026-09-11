#!/usr/bin/env python3
"""Portfolio Inspect tool handler — 并发工作池 + 降级逻辑

新增 portfolio_inspect 工具：并发分析多只股票，支持进度追踪和 coverage 降级。
"""
from __future__ import annotations

import json
import time
import traceback

from core.portfolio_pool import (
    StockTask,
    InspectionReport,
    run_portfolio_inspection,
    report_to_dict,
    calculate_coverage,
)
from core.compression import compress_dict_result


def _analyze_stock(task: StockTask) -> dict:
    """单只股票的完整分析（行情 + 行业 + 叙事）

    在 worker 线程中执行，只读操作。
    """
    code = task.code
    result = {}

    # 1. 实时行情
    try:
        from data_sources import tencent
        q = tencent.get_realtime_quote(code)
        result["quote"] = {
            "code": code,
            "name": q.get("name") or code,
            "price": q.get("price"),
            "change_pct": q.get("change_pct"),
            "volume": q.get("volume"),
        }
    except Exception as e:
        result["quote"] = {"code": code, "error": str(e)}

    # 2. 板块 + 叙事归一化
    try:
        from tools.narrative import boards_with_narratives
        boards = boards_with_narratives(code)
        result["narratives"] = boards.get("narratives", [])
        result["industry"] = boards.get("industry", "未知")
        result["concept_count"] = boards.get("total", 0)
    except Exception as e:
        result["narratives"] = []
        result["industry"] = "未知"
        result["error_narratives"] = str(e)

    # 3. 技术分析摘要（轻量）
    try:
        from data_sources import tencent as tc
        kline = tc.get_kline(code, 30)
        records = kline.get("records") or []
        if len(records) >= 5:
            closes = [r.get("close", 0) for r in records if r.get("close")]
            if closes:
                ma5 = sum(closes[-5:]) / 5
                ma20 = sum(closes[-20:]) / min(20, len(closes)) if len(closes) >= 20 else sum(closes) / len(closes)
                latest = closes[-1]
                result["technical"] = {
                    "ma5": round(ma5, 2),
                    "ma20": round(ma20, 2),
                    "latest_close": latest,
                    "above_ma5": latest > ma5,
                    "above_ma20": latest > ma20,
                    "trend": "多头" if ma5 > ma20 else ("空头" if ma5 < ma20 else "震荡"),
                }
    except Exception:
        pass  # 技术分析非必须

    # 4. 浮动盈亏
    if task.cost_price and task.shares:
        try:
            price = result.get("quote", {}).get("price") or 0
            value = price * task.shares
            cost_total = task.cost_price * task.shares
            pl = value - cost_total
            pl_pct = round(pl / cost_total * 100, 2) if cost_total else 0
            result["pnl"] = {
                "cost_price": task.cost_price,
                "shares": task.shares,
                "value": round(value, 2),
                "cost_total": round(cost_total, 2),
                "pl": round(pl, 2),
                "pl_pct": pl_pct,
            }
        except Exception:
            pass

    return result


def register(mcp) -> None:
    @mcp.tool(name="portfolio_inspect")
    def tool_portfolio_inspect(
        holdings: str,
        concurrency: int = 5,
        include_technical: bool = False,
    ) -> str:
        """组合 AI 巡检 — 并发分析持仓个股（行情+叙事+技术+盈亏）

        并发工作池执行，每只股票独立分析。部分失败不阻塞整体报告。
        Coverage 低于 60% 时自动降级。

        Args:
            holdings: 持仓 JSON 字符串或数组，如 [{"code":"600519","shares":100,"cost_price":1500}]
            concurrency: 并发数（1-10，默认5）
            include_technical: 是否包含技术分析（增加 API 调用）
        """
        try:
            h = json.loads(holdings) if isinstance(holdings, str) else holdings
        except Exception:
            return json.dumps({"error": "holdings 必须是合法 JSON"}, ensure_ascii=False)

        if not h or not isinstance(h, list):
            return json.dumps({"error": "holdings 不能为空"}, ensure_ascii=False)

        # 构造任务列表
        tasks = []
        for item in h:
            code = str(item.get("code") or "").strip()
            if not code:
                continue
            tasks.append(StockTask(
                code=code,
                weight=float(item.get("weight") or item.get("shares") or 1),
                cost_price=float(item["cost_price"]) if item.get("cost_price") else None,
                shares=float(item["shares"]) if item.get("shares") else None,
                name=item.get("name"),
            ))

        if not tasks:
            return json.dumps({"error": "没有有效的持仓数据"}, ensure_ascii=False)

        # 执行巡检
        start = time.monotonic()
        report = run_portfolio_inspection(
            tasks=tasks,
            analyze_fn=_analyze_stock,
            concurrency=min(max(concurrency, 1), 10),
            min_coverage=60.0,
        )

        # 构建聚合摘要
        summary = _build_summary(report, tasks)
        report_dict = report_to_dict(report)
        report_dict["summary"] = summary

        return compress_dict_result(report_dict)

    @mcp.tool(name="portfolio_inspect_progress")
    def tool_portfolio_inspect_progress() -> str:
        """查看最近一次组合巡检的状态（占位 — 用于长时间分析的进度查询）

        注：MCP 无状态架构下每次调用独立。此工具返回提示信息。
        """
        return json.dumps({
            "info": "当前为无状态模式，portfolio_inspect 为同步执行。",
            "tip": "对于大持仓组合，可降低 concurrency 或分批调用。",
        }, ensure_ascii=False)


def _build_summary(report: InspectionReport, tasks: list[StockTask]) -> dict:
    """构建巡检摘要"""
    total_value = 0.0
    total_cost = 0.0
    industry_exposure = {}
    narrative_exposure = {}
    failed_codes = []

    task_map = {t.code: t for t in tasks}
    for r in report.results:
        task = task_map.get(r.code)
        if r.status in ("succeeded", "degraded") and r.result:
            # 行业暴露
            industry = r.result.get("industry", "未知")
            industry_exposure[industry] = industry_exposure.get(industry, 0) + (task.weight if task else 1)

            # 叙事暴露
            for nar in r.result.get("narratives", []):
                name = nar.get("name", "")
                if name:
                    narrative_exposure[name] = narrative_exposure.get(name, 0) + 1

            # 盈亏
            pnl = r.result.get("pnl", {})
            if pnl:
                total_value += pnl.get("value", 0)
                total_cost += pnl.get("cost_total", 0)
        elif r.status == "failed":
            failed_codes.append(r.code)

    total_pl = total_value - total_cost
    total_pl_pct = round(total_pl / total_cost * 100, 2) if total_cost else 0

    # 叙事排名
    ranked_narratives = sorted(
        narrative_exposure.items(), key=lambda x: x[1], reverse=True
    )[:10]

    return {
        "coverage_pct": report.coverage_pct,
        "stage": report.stage,
        "duration_ms": (
            int((report.completed_at - report.started_at).total_seconds() * 1000)
            if report.completed_at and report.started_at else None
        ),
        "total_value": round(total_value, 2),
        "total_cost": round(total_cost, 2),
        "total_pl": round(total_pl, 2),
        "total_pl_pct": total_pl_pct,
        "industry_exposure": industry_exposure,
        "top_narratives": [{"name": n, "stock_count": c} for n, c in ranked_narratives],
        "failed_codes": failed_codes,
        "warnings": report.warnings,
    }
