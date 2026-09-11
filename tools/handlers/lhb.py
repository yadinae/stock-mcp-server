from __future__ import annotations
import json

from data_sources import em_market


def register(mcp):
    @mcp.tool(name="get_market_lhb")
    def get_market_lhb_tool(date: str = "", min_net_buy: float = 0) -> str:
        """全市场龙虎榜 — 当日所有上榜股票，含上榜原因、净买入、换手率。
        Args:
            date: 日期 YYYYMMDD（默认今天）
            min_net_buy: 最小净买入(万)过滤
        """
        result = em_market.get_market_lhb(date, min_net_buy)
        return json.dumps(result, ensure_ascii=False, default=str)

    @mcp.tool(name="get_lockup_calendar")
    def get_lockup_calendar_tool(code: str) -> str:
        """个股限售解禁日历 — 历史解禁 + 未来90天待解禁。
        Args:
            code: 股票代码
        """
        result = em_market.get_lockup_calendar(code)
        return json.dumps(result, ensure_ascii=False, default=str)

    @mcp.tool(name="get_research_reports")
    def get_research_reports_tool(code: str, pages: int = 1) -> str:
        """个股研报列表 — 研报标题、机构、评级。
        Args:
            code: 股票代码
            pages: 页数（每页20条）
        """
        result = em_market.get_research_reports(code, pages)
        return json.dumps(result, ensure_ascii=False, default=str)

    @mcp.tool(name="get_announcements")
    def get_announcements_tool(code: str, page_size: int = 30) -> str:
        """个股公告全文检索（巨潮）。
        Args:
            code: 股票代码
            page_size: 返回条数
        """
        result = em_market.get_announcements(code, page_size)
        return json.dumps(result, ensure_ascii=False, default=str)

    @mcp.tool(name="analyze_lhb")
    def analyze_lhb(code: str) -> str:
        """龙虎榜深度分析 — 个股近30日龙虎榜数据、游资席位识别、机构vs游资博弈。
        Args: code=股票代码（仅A股）"""
        from tools.advanced2_lhb import analyze_lhb as _analyze_lhb
        return json.dumps(_analyze_lhb(code), ensure_ascii=False, default=str)

    @mcp.tool(name="analyze_hot_money")
    def analyze_hot_money(code: str) -> str:
        """游资深度分析 — 综合龙虎榜+资金流向+板块资金+概念热度。
        Args: code=股票代码"""
        from tools.advanced2_hot import analyze_hot_money as _analyze_hot_money
        return json.dumps(_analyze_hot_money(code), ensure_ascii=False, default=str)
