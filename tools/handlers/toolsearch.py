"""ToolSearch handler — search_tools + list_tool_groups MCP tools."""
from __future__ import annotations

import json


def register(mcp):
    """Register ToolSearch tools."""

    @mcp.tool(name="list_tool_groups")
    def list_tool_groups() -> str:
        """列出所有工具分组及工具数量。
        用于客户端按需加载特定分组的工具，避免一次加载全部110个工具浪费token。"""
        from tools.groups import TOOL_GROUPS
        result = {}
        for name, group in TOOL_GROUPS.items():
            result[name] = {
                "description": group["description"],
                "tool_count": len(group["tools"]),
                "tools": group["tools"],
            }
        return json.dumps({
            "groups": result,
            "total_groups": len(result),
            "total_tools": sum(g["tool_count"] for g in result.values()),
        }, ensure_ascii=False, default=str)

    @mcp.tool(name="search_tools")
    def search_tools(query: str) -> str:
        """按关键词搜索匹配的工具（ToolSearch）。
        返回匹配的工具名、描述摘要、所属分组。
        用于客户端动态发现需要的工具，而非加载全部110个。

        Args:
            query: 搜索关键词，如 '资金流向'、'美股行情'、'DCF估值'
        """
        from tools.metadata import TOOL_META
        from tools.groups import TOOL_GROUPS

        query_lower = query.lower()
        matches = []

        for tool_name, meta in TOOL_META.items():
            # Keyword match (exact substring in any keyword)
            keyword_hit = any(query_lower in kw.lower() for kw in meta.get("keywords", []))
            # Group name match
            group_hit = query_lower in meta.get("group", "").lower()
            # Tool name match
            name_hit = query_lower in tool_name.lower()

            if keyword_hit or group_hit or name_hit:
                matches.append({
                    "name": tool_name,
                    "group": meta.get("group", ""),
                    "complexity": meta.get("complexity", "medium"),
                    "market": meta.get("market", []),
                    "latency": meta.get("latency", "medium"),
                    "data_source": meta.get("data_source", ""),
                })

        # Sort by relevance: keyword hits first, then by complexity (low > medium > high)
        complexity_order = {"low": 0, "medium": 1, "high": 2}
        matches.sort(key=lambda m: complexity_order.get(m["complexity"], 1))

        return json.dumps({
            "query": query,
            "matches": matches,
            "count": len(matches),
            "hint": f"共 {len(matches)} 个工具匹配 '{query}'",
        }, ensure_ascii=False, default=str)
