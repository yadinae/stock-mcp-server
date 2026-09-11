#!/usr/bin/env python3
"""Narrative tool handlers — 概念归一化、跨股票叙事分析。"""
from __future__ import annotations

import json

from tools.narrative import (
    normalize_concepts,
    rank_narratives,
    enhance_stock_boards,
    cross_stock_narratives,
    boards_with_narratives,
)


def register(mcp) -> None:
    @mcp.tool(name="narrative_normalize")
    def tool_narrative_normalize(concepts: str) -> str:
        """Narrative 概念归一化 — 将东财原始概念标签映射为核心叙事

        纯代码确定性逻辑，零 LLM 成本。适合批量处理。

        Args:
            concepts: 概念标签 JSON 数组，如 ["AI智能体", "大模型", "算力概念"]
        """
        try:
            c = json.loads(concepts) if isinstance(concepts, str) else concepts
        except Exception:
            c = [x.strip() for x in concepts.replace("，", ",").split(",") if x.strip()]
        result = rank_narratives(c)
        return json.dumps({"narratives": result, "total": len(result)}, ensure_ascii=False)

    @mcp.tool(name="narrative_rank")
    def tool_narrative_rank(concepts: str, min_score: float = 20) -> str:
        """Narrative 叙事排名 — 归一化后按广度折扣得分排序

        Args:
            concepts: 概念标签 JSON 数组
            min_score: 最低得分过滤（默认20）
        """
        try:
            c = json.loads(concepts) if isinstance(concepts, str) else concepts
        except Exception:
            c = [x.strip() for x in concepts.replace("，", ",").split(",") if x.strip()]
        result = rank_narratives(c, min_score=min_score)
        return json.dumps({"narratives": result, "total": len(result)}, ensure_ascii=False)

    @mcp.tool(name="boards_with_narratives")
    def tool_boards_with_narratives(code: str) -> str:
        """个股板块 + 叙事归一化 — 获取板块数据并自动归一化为核心叙事

        Args:
            code: 股票代码，如 600519
        """
        result = boards_with_narratives(code)
        return json.dumps(result, ensure_ascii=False, default=str)

    @mcp.tool(name="cross_stock_narratives")
    def tool_cross_stock_narratives(stocks: str) -> str:
        """跨股票叙事分析 — 找出多只股票的共同叙事和独有叙事

        Args:
            stocks: JSON数组，如 [{"code":"600519","concepts":["白酒","消费"]}, ...]
        """
        try:
            s = json.loads(stocks) if isinstance(stocks, str) else stocks
        except Exception:
            return json.dumps({"error": "stocks 必须是合法 JSON"}, ensure_ascii=False)
        result = cross_stock_narratives(s)
        return json.dumps(result, ensure_ascii=False, default=str)
