#!/usr/bin/env python3
"""Portfolio tool handlers — risk diagnosis, correlation, full report, rebalance, signal."""
from __future__ import annotations

import json

from tools.portfolio import (
    portfolio_risk_diagnosis,
    portfolio_correlation,
    portfolio_full_report,
    portfolio_rebalance,
    portfolio_signal,
)
from core.compression import compress_dict_result


def register(mcp) -> None:
    @mcp.tool(name="portfolio_risk_diagnosis")
    def tool_portfolio_risk_diagnosis(holdings=None) -> str:
        """组合风险诊断 — 持仓集中度、行业暴露、跨市场分布、浮动盈亏。

        Args:
            holdings: 持仓 JSON 字符串或数组，如 [{"code":"600519","shares":100,"cost_price":1500}]
        """
        try:
            h = json.loads(holdings) if isinstance(holdings, str) else holdings
        except Exception:
            return json.dumps({"error": "holdings 必须是合法 JSON"}, ensure_ascii=False)
        return compress_dict_result(portfolio_risk_diagnosis(h))

    @mcp.tool(name="portfolio_correlation")
    def tool_portfolio_correlation(codes: str, days: int = 60) -> str:
        """持仓相关性矩阵 — 计算组合内各持仓两两 Pearson 相关系数。

        Args:
            codes: JSON数组或逗号分隔字符串，如 ["600519","000001"] 或 "600519,000001"
            days: 分析天数
        """
        try:
            c = json.loads(codes) if isinstance(codes, str) and codes.strip().startswith("[") else [x.strip() for x in codes.replace("，", ",").split(",") if x.strip()]
        except Exception:
            c = [x.strip() for x in codes.replace("，", ",").split(",") if x.strip()]
        return json.dumps(portfolio_correlation(c, days), ensure_ascii=False, default=str)

    @mcp.tool(name="portfolio_full_report")
    def tool_portfolio_full_report(holdings=None, days: int = 60) -> str:
        """综合组合报告 — 行情摘要 + 集中度 + 行业暴露 + 相关性矩阵。

        Args:
            holdings: 持仓 JSON 字符串或数组
            days: 分析天数
        """
        try:
            h = json.loads(holdings) if isinstance(holdings, str) else holdings
        except Exception:
            return json.dumps({"error": "holdings 必须是合法 JSON"}, ensure_ascii=False)
        return compress_dict_result(portfolio_full_report(h, days))

    @mcp.tool(name="portfolio_rebalance")
    def tool_portfolio_rebalance(holdings=None, max_single_weight: float = 40) -> str:
        """组合调仓建议 — 仓位调整 + 行业分散优化。

        Args:
            holdings: 持仓 JSON 字符串或数组
            max_single_weight: 单标的权重上限(%)
        """
        try:
            h = json.loads(holdings) if isinstance(holdings, str) else holdings
        except Exception:
            return json.dumps({"error": "holdings 必须是合法 JSON"}, ensure_ascii=False)
        return json.dumps(portfolio_rebalance(h, max_single_weight), ensure_ascii=False, default=str)

    @mcp.tool(name="portfolio_signal")
    def tool_portfolio_signal(holdings=None) -> str:
        """组合调仓信号 — urgency(high/medium/low) + 建议。

        Args:
            holdings: 持仓 JSON 字符串或数组
        """
        try:
            h = json.loads(holdings) if isinstance(holdings, str) else holdings
        except Exception:
            return json.dumps({"error": "holdings 必须是合法 JSON"}, ensure_ascii=False)
        return json.dumps(portfolio_signal(h), ensure_ascii=False, default=str)
