"""News and intelligence tools (新闻/情报赛道)."""
from __future__ import annotations

import json

from core.helpers import _validate_code, _error_response, _get_stock_info
from data_sources import intel as intel_tools
from data_sources.em_market import get_convertible_bonds
from core.compression import compress_dict_result


def register(mcp):
    """Register news and intelligence tools."""

    @mcp.tool(name="search_stock_news")
    def search_stock_news(code: str, name: str = "") -> str:
        """搜索股票相关新闻
        Args:
            code: 股票代码
            name: 股票名称（可选，提供后可提高搜索准确度）
        """
        from tools.news import search_news
        err = _validate_code(code)
        if err:
            return _error_response(code, err)
        stock_name = name or _get_stock_info(code).get("name", "")
        result = search_news(code, stock_name)
        return json.dumps(result, ensure_ascii=False, default=str)

    @mcp.tool(name="list_sectors")
    def list_sectors() -> str:
        """列出所有投资情报赛道。
        返回 12 大赛道（AI/半导体/机器人/汽车/新能源/医药/航天/网安/科技/消费/宏观/科学），
        含 A 股板块代码(BK)与标签。用途：了解可订阅的情报范围。"""
        return json.dumps(intel_tools.list_sectors(), ensure_ascii=False, default=str)

    @mcp.tool(name="get_sector_briefing")
    def get_sector_briefing(sector_id: str = "ai") -> str:
        """获取指定赛道的 AI 摘要简报。
        Args: sector_id=赛道ID（ai/semi/robot/auto/energy/bio/space/security/tech/consumer/macro/science）
        返回该赛道今日要点 + 最新新闻。用途：快速了解某赛道最新动态。"""
        return json.dumps(intel_tools.get_sector_briefing(sector_id), ensure_ascii=False, default=str)

    @mcp.tool(name="get_sector_news")
    def get_sector_news(sector_id: str = "ai", limit: int = 10) -> str:
        """获取指定赛道的最新原始新闻。
        Args: sector_id=赛道ID, limit=返回条数(默认10)
        用途：查看赛道原始新闻标题/来源/摘要。"""
        return json.dumps(intel_tools.get_sector_news(sector_id, limit), ensure_ascii=False, default=str)

    @mcp.tool(name="get_all_sectors_briefing")
    def get_all_sectors_briefing() -> str:
        """全赛道综合摘要 — 一次获取 12 大赛道的 AI 摘要 + 跨赛道综述 + 当前热门赛道。
        用途：开盘前快速了解全市场情报。"""
        return compress_dict_result(intel_tools.get_all_sectors_briefing())

    @mcp.tool(name="search_industry_news")
    def search_industry_news(keyword: str) -> str:
        """跨赛道搜索新闻。
        Args: keyword=搜索关键词
        用途：在所有赛道的缓存新闻中搜索特定主题。"""
        return json.dumps(intel_tools.search_industry_news(keyword), ensure_ascii=False, default=str)

    @mcp.tool(name="refresh_intel_cache")
    def refresh_intel_cache() -> str:
        """刷新所有赛道情报缓存（重新抓取 RSS）。
        用途：缓存过期后手动刷新。"""
        return json.dumps(intel_tools.refresh_intel_cache(), ensure_ascii=False, default=str)

    @mcp.tool(name="get_convertible_bonds")
    def _get_convertible_bonds(page_size: int = 20) -> str:
        """可转债列表 — 代码/名称/价格/溢价率。

        Args:
            page_size: 返回条数
        """
        return json.dumps(get_convertible_bonds(page_size), ensure_ascii=False, default=str)
