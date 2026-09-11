#!/usr/bin/env python3
"""System / meta tool handlers — cache stats, data source health, block trade, holder change, dividend history."""
from __future__ import annotations

import json
from datetime import datetime

from core.cache import get_cache
from core.health import get_health_tracker
from data_sources.em_market import get_block_trade, get_holder_change, get_dividend_history


def register(mcp) -> None:
    @mcp.tool(name="get_cache_stats")
    def tool_get_cache_stats() -> str:
        """获取缓存统计（命中率、条目数、各TTL分布）

        用于监控缓存效率和诊断性能问题。
        """
        cache = get_cache()
        stats = cache.stats
        stats["tool_name"] = "get_cache_stats"
        stats["note"] = "缓存命中率 > 60% 为健康，< 40% 需调整 TTL"
        return json.dumps(stats, ensure_ascii=False, default=str)

    @mcp.tool(name="get_data_source_health")
    def tool_get_data_source_health() -> str:
        """获取数据源健康状态（腾讯、mootdx、Yahoo 的可用性和成功率）

        用于监控各数据源运行状态，及时发现腾讯 API 失效等故障。
        """
        report = get_health_tracker().get_report()
        result = {
            "sources": report,
            "count": len(report),
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "tool_name": "get_data_source_health",
        }
        return json.dumps(result, ensure_ascii=False, default=str)

    @mcp.tool(name="get_block_trade")
    def tool_get_block_trade(code: str) -> str:
        """获取个股大宗交易记录。含成交价、溢价率、买卖方营业部。

        Args:
            code=股票代码
        """
        records = get_block_trade(code)
        return json.dumps({"code": code, "records": records}, ensure_ascii=False, default=str)

    @mcp.tool(name="get_holder_change")
    def tool_get_holder_change(code: str) -> str:
        """获取股东户数变化（季度级）。含股东户数、环比变化、户均持股。

        Args:
            code=股票代码
        """
        records = get_holder_change(code)
        return json.dumps({"code": code, "records": records}, ensure_ascii=False, default=str)

    @mcp.tool(name="get_dividend_history")
    def tool_get_dividend_history(code: str) -> str:
        """获取分红送转历史。含每股派息、每10股转增/送股比例。

        Args:
            code=股票代码
            用途：分红能力评估
        """
        records = get_dividend_history(code)
        return json.dumps({"code": code, "records": records}, ensure_ascii=False, default=str)
