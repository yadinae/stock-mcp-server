"""Observability handler — data source health probe + tool call metrics."""
from __future__ import annotations

import json


def register(mcp):
    """Register observability tools."""

    @mcp.tool(name="probe_data_sources")
    def probe_data_sources() -> str:
        """实时探测所有数据源的可达性和延迟。
        主动 ping 腾讯/东财/Yahoo/TV REST/Binance 5 个数据源，
        返回每个源的状态(ok/error)、延迟(ms)、采样数据。
        用途：诊断数据源故障、对比延迟。"""
        from core.health import probe_all_sources
        results = probe_all_sources()
        ok_count = sum(1 for r in results if r["status"] == "ok")
        return json.dumps({
            "sources": results,
            "total": len(results),
            "ok": ok_count,
            "failed": len(results) - ok_count,
        }, ensure_ascii=False, default=str)

    @mcp.tool(name="get_tool_stats")
    def get_tool_stats(hours: int = 24) -> str:
        """获取工具调用统计（过去N小时）。
        返回总调用次数、成功率、平均延迟、Top 工具排行。
        数据持久化在 SQLite（~/.stock-mcp/metrics.db）。

        Args:
            hours: 统计时间范围（默认24小时）
        """
        from core.metrics import get_metrics
        return json.dumps(get_metrics().summary(hours), ensure_ascii=False, default=str)

    @mcp.tool(name="cleanup_metrics")
    def cleanup_metrics(days: int = 30) -> str:
        """清理过期的工具调用统计数据。
        Args:
            days: 保留天数（默认30天）"""
        from core.metrics import get_metrics
        return json.dumps(get_metrics().cleanup(days), ensure_ascii=False, default=str)
