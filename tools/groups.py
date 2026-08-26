"""
Tool groups — structured group index for ToolSearch.

Groups organize tools by domain, each with a description and tool list.
"""
from __future__ import annotations

TOOL_GROUPS: dict[str, dict] = {
    "行情基础": {
        "description": "股票/基金/指数实时行情查询（价格/涨跌幅/成交量/K线）",
        "tools": [
            "get_realtime_quote", "get_kline", "get_stock_info", "analyze_stocks",
            "get_stock_context", "get_global_quote", "get_global_kline",
            "get_tv_quote", "get_tv_market_list",
        ],
    },
    "技术分析": {
        "description": "K线数据、技术指标计算、形态识别、批量扫描",
        "tools": ["get_technical_analysis", "technical_batch_scan", "tdx_test"],
    },
    "技术面选股": {
        "description": "经典技术面策略全市场扫描（海龟突破/均线金叉/旗形整理/RPS突破）",
        "tools": [
            "strategy_scan_turtle", "strategy_scan_ma_vol",
            "strategy_scan_flag", "strategy_scan_rps",
            "strategy_scan_all", "baostock_backfill",
        ],
    },
    "资金流向": {
        "description": "个股/行业/概念资金流向、融资融券、主力动向",
        "tools": [
            "get_fund_flow_120d", "get_fund_flow_minute", "get_concept_fund_flow",
            "get_industry_fund_flow", "get_us_fund_flow", "get_margin_trading",
        ],
    },
    "F10财务": {
        "description": "公司资料、财务报表、股东、管理层、SEC文件",
        "tools": [
            "get_tdx_company_info", "get_tdx_finance_info", "get_tdx_xdxr_info",
            "get_company_profile", "get_company_financials", "get_top_shareholders",
            "get_management_team", "get_us_financials", "get_us_key_indicators",
            "fetch_financials", "get_financial_reports", "get_yahoo_statistics",
            "get_institutional_holders", "get_options_chain",
            "get_sec_filings", "get_sec_xbrl", "search_global_stock",
            "get_us_market_ranking",
        ],
    },
    "龙虎榜": {
        "description": "龙虎榜数据、游资席位、研报、公告、大宗交易",
        "tools": [
            "get_market_lhb", "get_lockup_calendar", "get_research_reports",
            "get_announcements", "analyze_lhb", "analyze_hot_money",
        ],
    },
    "组合持仓": {
        "description": "组合风险诊断、相关性矩阵、调仓建议、信号",
        "tools": [
            "portfolio_risk_diagnosis", "portfolio_correlation",
            "portfolio_full_report", "portfolio_rebalance", "portfolio_signal",
        ],
    },
    "交易日志": {
        "description": "开仓/平仓记录、交易查询、统计",
        "tools": [
            "trade_journal_open", "trade_journal_close", "trade_journal_list",
            "trade_journal_stats", "trade_journal_update",
        ],
    },
    "观察清单": {
        "description": "自选股清单管理、实时简报",
        "tools": [
            "watchlist_create", "watchlist_add", "watchlist_remove",
            "watchlist_list", "watchlist_brief",
        ],
    },
    "市场全景": {
        "description": "全市场总览、行业排名、热点股票、新闻快讯、涨停梯队",
        "tools": [
            "market_overview", "market_regime", "sector_rotation",
            "stock_finder", "cache_warmup", "get_industry_rank",
            "get_tv_industry_rank", "get_market_hot_stocks",
            "get_wallstreetcn_news", "search_tradingview_market",
            "analyze_limitup_tiers",
        ],
    },
    "新闻情报": {
        "description": "投资情报赛道、RSS新闻、跨赛道搜索、可转债",
        "tools": [
            "search_stock_news", "list_sectors", "get_sector_briefing",
            "get_sector_news", "get_all_sectors_briefing",
            "search_industry_news", "refresh_intel_cache",
            "get_convertible_bonds",
        ],
    },
    "AI分析": {
        "description": "AI综合分析、回测、估值、风险检测、策略扫描、告警",
        "tools": [
            "analyze_stock_ai", "check_backtest", "run_alert_check",
            "check_st_risk", "dcf_valuation", "ic_memo",
            "unit_economics", "value_creation_plan", "stock_score",
            "stock_signals", "strategy_scan", "check_trap_risk",
            "dd_checklist", "analyze_policy", "analyze_stock_agent",
        ],
    },
    "基金指数": {
        "description": "基金信息/净值/持仓/经理、指数表现/详情",
        "tools": [
            "get_fund_info", "get_fund_detail", "get_fund_nav_history",
            "get_fund_growth", "get_fund_asset", "get_fund_manager",
            "get_index_info", "get_index_details", "get_index_perf",
        ],
    },
    "加密货币": {
        "description": "加密货币行情/K线/排行（Binance/Kraken）",
        "tools": [
            "get_crypto_quote", "get_crypto_quotes",
            "get_crypto_kline", "get_top_crypto",
        ],
    },
    "市场数据": {
        "description": "大宗交易、股东户数、分红送转、板块归属",
        "tools": [
            "get_block_trade", "get_holder_change",
            "get_dividend_history", "get_stock_boards",
        ],
    },
    "系统": {
        "description": "缓存统计、数据源健康监控",
        "tools": ["get_cache_stats", "get_data_source_health"],
    },
    "复合决策": {
        "description": "组合调仓信号、盘中异动预警（组合多工具输出做决策判断）",
        "tools": ["portfolio_rebalance_signal", "intraday_alert"],
    },
    "可观测性": {
        "description": "数据源实时探测、工具调用统计、数据清理",
        "tools": ["probe_data_sources", "get_tool_stats", "cleanup_metrics"],
    },
}
