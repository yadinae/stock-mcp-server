from __future__ import annotations
import json

from tools.aggregate import market_overview, market_regime, sector_rotation, stock_finder, cache_warmup
from tools.advanced import search_tradingview_market
from data_sources import em_market
from core.compression import compress_dict_result, truncate_table


def register(mcp):
    @mcp.tool(name="market_overview")
    def market_overview_tool() -> str:
        """全市场总览 — A股主要指数 + 行业板块强弱 + 美股三大指数"""
        result = market_overview()
        return compress_dict_result(result)

    @mcp.tool(name="market_regime")
    def market_regime_tool() -> str:
        """市场状态判断 — 指数趋势(MA20/MA60) + 成交量 + 行业宽度 → bull/bear/oscillate"""
        result = market_regime()
        return json.dumps(result, ensure_ascii=False, default=str)

    @mcp.tool(name="sector_rotation")
    def sector_rotation_tool() -> str:
        """板块轮动追踪 — 全行业 N 日涨跌排名及动量变化"""
        result = sector_rotation()
        return json.dumps(result, ensure_ascii=False, default=str)

    @mcp.tool(name="stock_finder")
    def stock_finder_tool(strategy: str = "etf", max_results: int = 5,
                          risk_tolerance: str = "medium", holdings: str = "") -> str:
        """股票/ETF 推荐 — 策略选股 + 本地行情评分
        Args:
            strategy: 策略 (etf/value/momentum/reversal)
            max_results: 最大返回数(1-10)
            risk_tolerance: 风险偏好 (low/medium/high)
            holdings: 已持仓代码(JSON数组或逗号分隔)
        """
        # Parse holdings from JSON array or comma-separated string
        parsed_holdings = []
        if holdings:
            s = holdings.strip()
            if s.startswith("["):
                try:
                    parsed = json.loads(s)
                    if isinstance(parsed, list):
                        parsed_holdings = parsed
                except json.JSONDecodeError:
                    parsed_holdings = [x.strip() for x in s.split(",") if x.strip()]
            else:
                parsed_holdings = [x.strip() for x in s.split(",") if x.strip()]
        result = stock_finder(strategy=strategy, max_results=max_results,
                              risk_tolerance=risk_tolerance, holdings=parsed_holdings)
        return json.dumps(result, ensure_ascii=False, default=str)

    @mcp.tool(name="cache_warmup")
    def cache_warmup_tool(codes: str = "") -> str:
        """缓存预热 — 预取热门股票数据到内存缓存
        Args:
            codes: 逗号分隔的股票代码(可选，不传则预热热门股票)
        """
        # Parse codes from comma-separated string
        parsed_codes = None
        if codes:
            parsed_codes = [x.strip() for x in codes.split(",") if x.strip()]
        result = cache_warmup(codes=parsed_codes)
        return json.dumps(result, ensure_ascii=False, default=str)

    @mcp.tool(name="get_industry_rank")
    def get_industry_rank_tool(top_n: int = 20) -> str:
        """全行业涨跌幅排名（TV REST 数据源，东财 push2 对数据中心IP限流时的替代）
        Args:
            top_n: 返回前N名
        """
        r = em_market.get_industry_rank_tv(top_n)
        if isinstance(r, dict) and r.get("top") and r.get("total"):
            rows = [{"name": x.get("industry", ""), "change_pct": x.get("avg_change_pct", 0),
                     "count": x.get("count", 0), "up_count": x.get("up_count", 0),
                     "down_count": x.get("down_count", 0)} for x in r["top"]]
            # 2026-09-18 修复: 原 rows[-n:] 当 len(rows) < 2n 时与 rows[:n] 完全相同
            # （行业数 8、n=12 → 两榜都是全部 8 行，top==bottom，下游 clean_industry_rank
            #   过滤不出差异 → 快照里 top/bottom 板块名+涨跌幅完全相同 → 文章引用的
            #   "领跌板块"实际是领涨板块（09-18 Jev 门禁实测发现该内部矛盾）。
            #   规则: top = 涨幅最高 n 个; bottom = 涨幅最低的 n 个（即跌幅榜）；
            #   两榜重叠（行业数 < 2n）时各取不重叠的一半，避免"领跌榜"里全是涨的。
            n = min(max(int(top_n or 20), 1), len(rows))
            # 两榜重叠（行业数 < 2n）时各取不重叠的一半，避免"领跌榜"里全是涨的
            half = n if 2 * n <= len(rows) else (len(rows) + 1) // 2
            top_rows = rows[:half]
            bottom_rows = rows[-half:]
            return compress_dict_result({"source": r.get("source"), "total": len(rows),
                               "top": top_rows, "bottom": bottom_rows})
        return json.dumps(r, ensure_ascii=False, default=str)

    @mcp.tool(name="get_tv_industry_rank")
    def get_tv_industry_rank_tool(top_n: int = 20) -> str:
        """TV REST 行业涨跌排名（英文GICS分类）。
        Args:
            top_n: 返回前N名
        """
        result = em_market.get_industry_rank_tv(top_n)
        return json.dumps(result, ensure_ascii=False, default=str)

    @mcp.tool(name="get_market_hot_stocks")
    def get_market_hot_stocks_tool(date: str = "") -> str:
        """当日强势股清单及题材归因（同花顺热点）
        Args:
            date: 日期 YYYYMMDD（默认今天）
        """
        result = em_market.get_market_hot_stocks(date)
        return json.dumps(result, ensure_ascii=False, default=str)

    @mcp.tool(name="get_wallstreetcn_news")
    def get_wallstreetcn_news_tool(limit: int = 10, mode: str = "all") -> str:
        """华尔街见闻快讯 — 7x24 快讯 + 热门文章 + 最新文章摘要。
        Args:
            limit: 返回条数
            mode: all/headline/latest
        """
        result = em_market.get_wallstreetcn_news(limit=limit, mode=mode)
        return json.dumps(result, ensure_ascii=False, default=str)

    @mcp.tool(name="search_tradingview_market")
    def search_tradingview_market_tool(query: str, filter: str = "") -> str:
        """搜索 TV 行情代码。TV REST scanner + 东财 suggest 兜底。
        Args:
            query: 搜索关键词
            filter: 类型筛选(可选)
        """
        result = search_tradingview_market(query=query, filter_type=filter)
        return json.dumps(result, ensure_ascii=False, default=str)

    @mcp.tool(name="analyze_limitup_tiers")
    def analyze_limitup_tiers() -> str:
        """涨停梯队分析 — 首板/二连板/三连板及以上/炸板分类 + 市场统计。
        数据源: 东财 datacenter + 腾讯K线连板判断"""
        from data_sources.em_market import get_limitup_tiers
        return json.dumps(get_limitup_tiers(), ensure_ascii=False, default=str)
