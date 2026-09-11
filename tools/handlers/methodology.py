#!/usr/bin/env python3
"""Methodology tool handlers — 策略知识缓存管理。"""
from __future__ import annotations

import json

from core.methodology_cache import (
    add_strategy,
    search_strategies,
    get_strategy_content,
    build_context,
    list_strategies,
    remove_strategy,
)


def register(mcp) -> None:
    @mcp.tool(name="methodology_add")
    def tool_methodology_add(
        title: str,
        content: str,
        tags: str = "",
        source: str = "",
        doc_type: str = "strategy",
    ) -> str:
        """添加策略文档到本地知识库

        Args:
            title: 策略名称
            content: 策略正文
            tags: 标签（逗号分隔）
            source: 来源
            doc_type: 文档类型 (strategy/methodology/research/memo)
        """
        tag_list = [t.strip() for t in tags.replace("，", ",").split(",") if t.strip()] if tags else []
        result = add_strategy(title, content, tags=tag_list, source=source, doc_type=doc_type)
        return json.dumps(result, ensure_ascii=False)

    @mcp.tool(name="methodology_search")
    def tool_methodology_search(query: str, limit: int = 5, doc_type: str = "") -> str:
        """搜索策略知识库

        Args:
            query: 搜索关键词
            limit: 最大返回数
            doc_type: 限定类型
        """
        result = search_strategies(query, limit=limit, doc_type=doc_type or None)
        return json.dumps(result, ensure_ascii=False)

    @mcp.tool(name="methodology_get")
    def tool_methodology_get(doc_id: str) -> str:
        """获取策略文档完整内容

        Args:
            doc_id: 文档 ID
        """
        result = get_strategy_content(doc_id)
        return json.dumps(result, ensure_ascii=False)

    @mcp.tool(name="methodology_context")
    def tool_methodology_context(query: str, max_chars: int = 8000) -> str:
        """构建策略上下文（供 LLM 分析注入）

        Args:
            query: 当前分析查询
            max_chars: 最大字符数
        """
        result = build_context(query, max_chars=max_chars)
        return result if result else "（本地策略知识库无相关内容）"

    @mcp.tool(name="methodology_list")
    def tool_methodology_list(doc_type: str = "") -> str:
        """列出所有策略文档

        Args:
            doc_type: 限定类型
        """
        result = list_strategies(doc_type=doc_type or None)
        return json.dumps(result, ensure_ascii=False)

    @mcp.tool(name="methodology_remove")
    def tool_methodology_remove(doc_id: str) -> str:
        """删除策略文档

        Args:
            doc_id: 文档 ID
        """
        result = remove_strategy(doc_id)
        return json.dumps(result, ensure_ascii=False)
