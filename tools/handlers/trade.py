#!/usr/bin/env python3
"""Trade journal tool handlers — open, close, list, stats, update."""
from __future__ import annotations

import json

from core import store as local_store


def register(mcp) -> None:
    @mcp.tool(name="trade_journal_open")
    def tool_trade_journal_open(symbol: str, shares: float, entry_price: float, strategy: str = "",
                                rationale: str = "", side: str = "long", name: str = "") -> str:
        """开仓 — 记录一笔交易。

        Args:
            symbol: 代码
            shares: 股数
            entry_price: 成交价
            strategy: 策略标签
            rationale: 理由
            side: long/short
            name: 名称
        """
        return json.dumps(local_store.trade_open(symbol, shares, entry_price, strategy, rationale, side, name), ensure_ascii=False, default=str)

    @mcp.tool(name="trade_journal_close")
    def tool_trade_journal_close(id: int, exit_price: float, notes: str = "") -> str:
        """平仓 — 关闭一笔持仓并计算盈亏。

        Args:
            id: 交易ID
            exit_price: 卖出价
            notes: 备注
        """
        return json.dumps(local_store.trade_close(id, exit_price, notes), ensure_ascii=False, default=str)

    @mcp.tool(name="trade_journal_list")
    def tool_trade_journal_list(status: str = "", strategy: str = "", symbol: str = "") -> str:
        """交易查询 — 按状态/策略/标的筛选。

        Args:
            status: open/closed
            strategy: 策略
            symbol: 代码
        """
        return json.dumps(local_store.trade_list(status, strategy, symbol), ensure_ascii=False, default=str)

    @mcp.tool(name="trade_journal_stats")
    def tool_trade_journal_stats() -> str:
        """交易统计 — 胜率、总盈亏、按策略聚合。"""
        return json.dumps(local_store.trade_stats(), ensure_ascii=False, default=str)

    @mcp.tool(name="trade_journal_update")
    def tool_trade_journal_update(id: int, notes: str = "", strategy: str = "", rationale: str = "", entry_price: float = 0) -> str:
        """交易更新 — 修改备注/策略/理由。

        Args:
            id: 交易ID
            notes/strategy/rationale/entry_price: 可更新字段
        """
        return json.dumps(local_store.trade_update(id, notes, strategy, rationale, entry_price), ensure_ascii=False, default=str)
