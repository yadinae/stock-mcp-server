#!/usr/bin/env python3
"""Watchlist tool handlers — create, add, remove, list, brief."""
from __future__ import annotations

import json

from core import store as local_store
from core.helpers import _safe_quote


def register(mcp) -> None:
    @mcp.tool(name="watchlist_create")
    def tool_watchlist_create(name: str, description: str = "") -> str:
        """创建观察清单。

        Args:
            name: 清单名称
            description: 描述
        """
        return json.dumps(local_store.watchlist_create(name, description), ensure_ascii=False, default=str)

    @mcp.tool(name="watchlist_add")
    def tool_watchlist_add(watchlist_id: int, symbols: str) -> str:
        """添加标的到观察清单。

        Args:
            watchlist_id: 清单ID
            symbols: 代码，逗号分隔或JSON数组
        """
        try:
            s = json.loads(symbols) if isinstance(symbols, str) and symbols.strip().startswith("[") else symbols
        except Exception:
            s = symbols
        return json.dumps(local_store.watchlist_add(watchlist_id, s), ensure_ascii=False, default=str)

    @mcp.tool(name="watchlist_remove")
    def tool_watchlist_remove(watchlist_id: int, symbol: str) -> str:
        """从观察清单移除标的。

        Args:
            watchlist_id: 清单ID
            symbol: 代码
        """
        return json.dumps(local_store.watchlist_remove(watchlist_id, symbol), ensure_ascii=False, default=str)

    @mcp.tool(name="watchlist_list")
    def tool_watchlist_list() -> str:
        """查看所有观察清单。"""
        return json.dumps(local_store.watchlist_list(), ensure_ascii=False, default=str)

    @mcp.tool(name="watchlist_brief")
    def tool_watchlist_brief(watchlist_id: int) -> str:
        """生成观察清单实时简报。

        Args:
            watchlist_id: 清单ID
        """
        symbols = local_store.watchlist_get_items(watchlist_id)
        if not symbols:
            return json.dumps({"error": f"观察清单 {watchlist_id} 无标的"}, ensure_ascii=False)
        quotes = []
        up = down = 0
        for s in symbols:
            q = _safe_quote(s)
            quotes.append(q)
            if q.get("change_pct", 0) > 0:
                up += 1
            elif q.get("change_pct", 0) < 0:
                down += 1
        quotes.sort(key=lambda x: x.get("change_pct", 0), reverse=True)
        result = {
            "watchlist_id": watchlist_id,
            "total": len(quotes),
            "up_count": up, "down_count": down,
            "top_gainer": quotes[0] if quotes else None,
            "top_loser": quotes[-1] if quotes else None,
            "quotes": quotes,
        }
        return json.dumps(result, ensure_ascii=False, default=str)
