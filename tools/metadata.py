"""
Tool metadata registry — structured descriptions for semantic search.

Inspired by go-stock (https://github.com/ArvinLovegood/go-stock) tool_desc_trim.go + tool_groups.go pattern.
Each tool gets keywords, complexity, data sources, market coverage, and latency hints.
"""
from __future__ import annotations

TOOL_META: dict[str, dict] = {
    # ── 行情基础 (quote) ──
    "get_realtime_quote": {
        "group": "行情基础", "complexity": "low", "latency": "fast",
        "keywords": ["行情", "实时", "价格", "涨跌", "成交量", "报价"],
        "data_source": "tencent/yahoo", "market": ["A", "US", "HK"],
    },
    "get_kline": {
        "group": "行情基础", "complexity": "low", "latency": "fast",
        "keywords": ["K线", "历史", "日线", "走势", "蜡烛图"],
        "data_source": "tencent/yahoo", "market": ["A", "US", "HK"],
    },
    "get_stock_info": {
        "group": "行情基础", "complexity": "low", "latency": "fast",
        "keywords": ["基本信息", "名称", "代码", "市值"],
        "data_source": "tencent/yahoo", "market": ["A", "US", "HK"],
    },
    "analyze_stocks": {
        "group": "行情基础", "complexity": "medium", "latency": "medium",
        "keywords": ["批量", "多股", "对比", "行情摘要"],
        "data_source": "tencent/yahoo", "market": ["A", "US", "HK"],
    },
    "get_stock_context": {
        "group": "行情基础", "complexity": "medium", "latency": "medium",
        "keywords": ["综合", "一次", "全部数据", "行情+K线+新闻"],
        "data_source": "tencent/yahoo", "market": ["A", "US", "HK"],
    },
    "get_global_quote": {
        "group": "行情基础", "complexity": "low", "latency": "fast",
        "keywords": ["美股", "港股", "行情", "多数据源"],
        "data_source": "sina/tencent/eastmoney", "market": ["US", "HK"],
    },
    "get_global_kline": {
        "group": "行情基础", "complexity": "low", "latency": "fast",
        "keywords": ["美股", "港股", "K线", "历史"],
        "data_source": "sina/yahoo", "market": ["US", "HK"],
    },
    "get_tv_quote": {
        "group": "行情基础", "complexity": "low", "latency": "fast",
        "keywords": ["TV", "行情", "A股"],
        "data_source": "tradingview", "market": ["A"],
    },
    "get_tv_market_list": {
        "group": "行情基础", "complexity": "low", "latency": "fast",
        "keywords": ["大盘股", "市值排序", "TV"],
        "data_source": "tradingview", "market": ["A"],
    },

    # ── 技术分析 (technical) ──
    "get_technical_analysis": {
        "group": "技术分析", "complexity": "medium", "latency": "fast",
        "keywords": ["技术", "MACD", "RSI", "布林", "均线", "趋势", "指标"],
        "data_source": "tencent/yahoo", "market": ["A", "US", "HK"],
    },
    "technical_batch_scan": {
        "group": "技术分析", "complexity": "high", "latency": "slow",
        "keywords": ["批量", "技术扫描", "筛选", "金叉", "死叉", "超买", "超卖"],
        "data_source": "tencent/yahoo", "market": ["A"],
    },
    "tdx_test": {
        "group": "技术分析", "complexity": "low", "latency": "fast",
        "keywords": ["通达信", "测试", "连通性", "行情链路"],
        "data_source": "mootdx/tencent", "market": ["A"],
    },

    # ── 资金流向 (fundflow) ──
    "get_fund_flow_120d": {
        "group": "资金流向", "complexity": "low", "latency": "fast",
        "keywords": ["资金", "主力", "净流入", "中长期", "日级"],
        "data_source": "eastmoney", "market": ["A"],
    },
    "get_fund_flow_minute": {
        "group": "资金流向", "complexity": "low", "latency": "fast",
        "keywords": ["资金", "盘中", "分钟", "实时", "主力"],
        "data_source": "eastmoney", "market": ["A"],
    },
    "get_concept_fund_flow": {
        "group": "资金流向", "complexity": "low", "latency": "fast",
        "keywords": ["概念", "板块", "资金流向", "热点题材"],
        "data_source": "tencent/eastmoney", "market": ["A"],
    },
    "get_industry_fund_flow": {
        "group": "资金流向", "complexity": "low", "latency": "fast",
        "keywords": ["行业", "资金流向", "主力净流入"],
        "data_source": "tencent", "market": ["A"],
    },
    "get_us_fund_flow": {
        "group": "资金流向", "complexity": "low", "latency": "fast",
        "keywords": ["美股", "港股", "资金流向", "主力"],
        "data_source": "eastmoney", "market": ["US", "HK"],
    },
    "get_margin_trading": {
        "group": "资金流向", "complexity": "low", "latency": "fast",
        "keywords": ["融资融券", "两融", "杠杆", "融资余额"],
        "data_source": "eastmoney", "market": ["A"],
    },

    # ── F10/财务 (fundamental) ──
    "get_tdx_company_info": {
        "group": "F10财务", "complexity": "low", "latency": "fast",
        "keywords": ["公司", "资料", "简介", "股本", "法人"],
        "data_source": "eastmoney_emweb", "market": ["A"],
    },
    "get_tdx_finance_info": {
        "group": "F10财务", "complexity": "low", "latency": "fast",
        "keywords": ["财务", "EPS", "营收", "ROE", "毛利率"],
        "data_source": "eastmoney_datacenter", "market": ["A"],
    },
    "get_tdx_xdxr_info": {
        "group": "F10财务", "complexity": "low", "latency": "fast",
        "keywords": ["除权除息", "分红", "送转", "股利"],
        "data_source": "eastmoney", "market": ["A"],
    },
    "get_company_profile": {
        "group": "F10财务", "complexity": "low", "latency": "fast",
        "keywords": ["公司", "详细", "资料", "F10", "全称", "成立日期"],
        "data_source": "eastmoney_emweb", "market": ["A"],
    },
    "get_company_financials": {
        "group": "F10财务", "complexity": "low", "latency": "fast",
        "keywords": ["财务", "核心指标", "EPS", "ROE", "F10"],
        "data_source": "eastmoney_datacenter", "market": ["A"],
    },
    "get_top_shareholders": {
        "group": "F10财务", "complexity": "low", "latency": "fast",
        "keywords": ["股东", "十大股东", "持股比例"],
        "data_source": "eastmoney", "market": ["A"],
    },
    "get_management_team": {
        "group": "F10财务", "complexity": "low", "latency": "fast",
        "keywords": ["管理层", "董事长", "总经理", "董秘"],
        "data_source": "eastmoney_emweb", "market": ["A"],
    },
    "get_us_financials": {
        "group": "F10财务", "complexity": "low", "latency": "fast",
        "keywords": ["美股", "港股", "财务报表", "三表"],
        "data_source": "eastmoney", "market": ["US", "HK"],
    },
    "get_us_key_indicators": {
        "group": "F10财务", "complexity": "low", "latency": "fast",
        "keywords": ["美股", "港股", "关键指标", "ROE", "EPS"],
        "data_source": "eastmoney", "market": ["US", "HK"],
    },
    "fetch_financials": {
        "group": "F10财务", "complexity": "low", "latency": "fast",
        "keywords": ["财务", "核心数据", "营收", "利润", "FCF"],
        "data_source": "eastmoney", "market": ["A"],
    },
    "get_financial_reports": {
        "group": "F10财务", "complexity": "low", "latency": "fast",
        "keywords": ["三表", "利润表", "资产负债表", "现金流量表", "新浪"],
        "data_source": "sina", "market": ["A"],
    },
    "get_yahoo_statistics": {
        "group": "F10财务", "complexity": "low", "latency": "fast",
        "keywords": ["美股", "港股", "Yahoo", "PE", "PB", "Beta"],
        "data_source": "yahoo", "market": ["US", "HK"],
    },
    "get_institutional_holders": {
        "group": "F10财务", "complexity": "low", "latency": "fast",
        "keywords": ["机构", "持仓", "基金", "持股比例"],
        "data_source": "yahoo", "market": ["US", "HK"],
    },
    "get_options_chain": {
        "group": "F10财务", "complexity": "low", "latency": "fast",
        "keywords": ["期权", "期权链", "Greeks", "隐含波动率"],
        "data_source": "yahoo", "market": ["US"],
    },
    "get_sec_filings": {
        "group": "F10财务", "complexity": "low", "latency": "medium",
        "keywords": ["SEC", "EDGAR", "年报", "季报", "10-K", "10-Q"],
        "data_source": "sec_edgar", "market": ["US"],
    },
    "get_sec_xbrl": {
        "group": "F10财务", "complexity": "low", "latency": "medium",
        "keywords": ["SEC", "XBRL", "GAAP", "结构化财务"],
        "data_source": "sec_edgar", "market": ["US"],
    },
    "search_global_stock": {
        "group": "F10财务", "complexity": "low", "latency": "fast",
        "keywords": ["搜索", "全球", "代码", "中英文"],
        "data_source": "eastmoney", "market": ["A", "US", "HK"],
    },
    "get_us_market_ranking": {
        "group": "F10财务", "complexity": "low", "latency": "fast",
        "keywords": ["美股", "港股", "涨跌排名", "排行榜"],
        "data_source": "eastmoney", "market": ["US", "HK"],
    },

    # ── 龙虎榜/游资 (lhb) ──
    "get_market_lhb": {
        "group": "龙虎榜", "complexity": "low", "latency": "fast",
        "keywords": ["龙虎榜", "上榜", "净买入"],
        "data_source": "eastmoney_datacenter", "market": ["A"],
    },
    "get_lockup_calendar": {
        "group": "龙虎榜", "complexity": "low", "latency": "fast",
        "keywords": ["限售", "解禁", "限售股"],
        "data_source": "eastmoney", "market": ["A"],
    },
    "get_research_reports": {
        "group": "龙虎榜", "complexity": "low", "latency": "fast",
        "keywords": ["研报", "机构", "评级"],
        "data_source": "eastmoney", "market": ["A"],
    },
    "get_announcements": {
        "group": "龙虎榜", "complexity": "low", "latency": "fast",
        "keywords": ["公告", "巨潮", "公司公告"],
        "data_source": "cninfo", "market": ["A"],
    },
    "analyze_lhb": {
        "group": "龙虎榜", "complexity": "high", "latency": "medium",
        "keywords": ["龙虎榜", "深度", "游资", "席位", "博弈"],
        "data_source": "eastmoney_datacenter", "market": ["A"],
    },
    "analyze_hot_money": {
        "group": "龙虎榜", "complexity": "high", "latency": "medium",
        "keywords": ["游资", "资金博弈", "龙虎榜", "板块", "概念"],
        "data_source": "eastmoney", "market": ["A"],
    },

    # ── 组合/持仓 (portfolio) ──
    "portfolio_risk_diagnosis": {
        "group": "组合持仓", "complexity": "high", "latency": "medium",
        "keywords": ["组合", "风险", "集中度", "行业暴露", "盈亏"],
        "data_source": "tencent", "market": ["A", "US", "HK"],
    },
    "portfolio_correlation": {
        "group": "组合持仓", "complexity": "high", "latency": "medium",
        "keywords": ["相关性", "Pearson", "矩阵", "分散化"],
        "data_source": "tencent", "market": ["A", "US", "HK"],
    },
    "portfolio_full_report": {
        "group": "组合持仓", "complexity": "high", "latency": "slow",
        "keywords": ["组合", "综合报告", "行情+集中度+相关性"],
        "data_source": "tencent", "market": ["A", "US", "HK"],
    },
    "portfolio_rebalance": {
        "group": "组合持仓", "complexity": "high", "latency": "medium",
        "keywords": ["调仓", "仓位调整", "分散优化"],
        "data_source": "tencent", "market": ["A", "US", "HK"],
    },
    "portfolio_signal": {
        "group": "组合持仓", "complexity": "high", "latency": "medium",
        "keywords": ["信号", "urgency", "加仓", "减仓"],
        "data_source": "tencent", "market": ["A", "US", "HK"],
    },

    # ── 交易日志 (trade) ──
    "trade_journal_open": {
        "group": "交易日志", "complexity": "low", "latency": "fast",
        "keywords": ["开仓", "记录", "交易"],
        "data_source": "local_sqlite", "market": [],
    },
    "trade_journal_close": {
        "group": "交易日志", "complexity": "low", "latency": "fast",
        "keywords": ["平仓", "盈亏", "结算"],
        "data_source": "local_sqlite", "market": [],
    },
    "trade_journal_list": {
        "group": "交易日志", "complexity": "low", "latency": "fast",
        "keywords": ["查询", "交易列表", "筛选"],
        "data_source": "local_sqlite", "market": [],
    },
    "trade_journal_stats": {
        "group": "交易日志", "complexity": "low", "latency": "fast",
        "keywords": ["统计", "胜率", "盈亏"],
        "data_source": "local_sqlite", "market": [],
    },
    "trade_journal_update": {
        "group": "交易日志", "complexity": "low", "latency": "fast",
        "keywords": ["更新", "备注", "策略"],
        "data_source": "local_sqlite", "market": [],
    },

    # ── 观察清单 (watchlist) ──
    "watchlist_create": {
        "group": "观察清单", "complexity": "low", "latency": "fast",
        "keywords": ["创建", "清单", "自选股"],
        "data_source": "local_sqlite", "market": [],
    },
    "watchlist_add": {
        "group": "观察清单", "complexity": "low", "latency": "fast",
        "keywords": ["添加", "标的"],
        "data_source": "local_sqlite", "market": [],
    },
    "watchlist_remove": {
        "group": "观察清单", "complexity": "low", "latency": "fast",
        "keywords": ["移除", "删除"],
        "data_source": "local_sqlite", "market": [],
    },
    "watchlist_list": {
        "group": "观察清单", "complexity": "low", "latency": "fast",
        "keywords": ["查看", "所有清单"],
        "data_source": "local_sqlite", "market": [],
    },
    "watchlist_brief": {
        "group": "观察清单", "complexity": "medium", "latency": "medium",
        "keywords": ["简报", "实时", "涨跌汇总"],
        "data_source": "tencent", "market": ["A", "US", "HK"],
    },

    # ── 市场全景 (market) ──
    "market_overview": {
        "group": "市场全景", "complexity": "medium", "latency": "medium",
        "keywords": ["全市场", "指数", "总览", "行情"],
        "data_source": "tencent/eastmoney", "market": ["A", "US"],
    },
    "market_regime": {
        "group": "市场全景", "complexity": "medium", "latency": "medium",
        "keywords": ["市场状态", "牛市", "熊市", "震荡", "趋势"],
        "data_source": "tencent/eastmoney", "market": ["A"],
    },
    "sector_rotation": {
        "group": "市场全景", "complexity": "medium", "latency": "medium",
        "keywords": ["板块轮动", "行业", "动量"],
        "data_source": "tencent/eastmoney", "market": ["A"],
    },
    "stock_finder": {
        "group": "市场全景", "complexity": "high", "latency": "slow",
        "keywords": ["选股", "推荐", "价值", "动量", "ETF", "反转"],
        "data_source": "tencent", "market": ["A"],
    },
    "cache_warmup": {
        "group": "市场全景", "complexity": "low", "latency": "fast",
        "keywords": ["缓存", "预热", "预取"],
        "data_source": "tencent/yahoo", "market": ["A", "US", "HK"],
    },
    "get_industry_rank": {
        "group": "市场全景", "complexity": "low", "latency": "fast",
        "keywords": ["行业", "排名", "涨跌幅", "TV"],
        "data_source": "tradingview", "market": ["A"],
    },
    "get_tv_industry_rank": {
        "group": "市场全景", "complexity": "low", "latency": "fast",
        "keywords": ["行业", "排名", "英文", "GICS"],
        "data_source": "tradingview", "market": ["A"],
    },
    "get_market_hot_stocks": {
        "group": "市场全景", "complexity": "low", "latency": "fast",
        "keywords": ["强势股", "热点", "题材", "同花顺"],
        "data_source": "eastmoney", "market": ["A"],
    },
    "get_wallstreetcn_news": {
        "group": "市场全景", "complexity": "low", "latency": "fast",
        "keywords": ["华尔街见闻", "快讯", "新闻", "财经"],
        "data_source": "wallstreetcn", "market": [],
    },
    "search_tradingview_market": {
        "group": "市场全景", "complexity": "low", "latency": "fast",
        "keywords": ["搜索", "TV代码", "行情代码"],
        "data_source": "tradingview/eastmoney", "market": ["A"],
    },
    "analyze_limitup_tiers": {
        "group": "市场全景", "complexity": "medium", "latency": "medium",
        "keywords": ["涨停", "连板", "梯队", "封板", "炸板"],
        "data_source": "eastmoney/tencent", "market": ["A"],
    },

    # ── 新闻/情报 (intel) ──
    "search_stock_news": {
        "group": "新闻情报", "complexity": "low", "latency": "fast",
        "keywords": ["新闻", "搜索", "资讯"],
        "data_source": "eastmoney", "market": ["A", "US", "HK"],
    },
    "list_sectors": {
        "group": "新闻情报", "complexity": "low", "latency": "fast",
        "keywords": ["赛道", "情报", "列表", "AI", "半导体"],
        "data_source": "intel_rss", "market": [],
    },
    "get_sector_briefing": {
        "group": "新闻情报", "complexity": "low", "latency": "fast",
        "keywords": ["赛道", "摘要", "简报"],
        "data_source": "intel_rss", "market": [],
    },
    "get_sector_news": {
        "group": "新闻情报", "complexity": "low", "latency": "fast",
        "keywords": ["赛道", "新闻", "原始"],
        "data_source": "intel_rss", "market": [],
    },
    "get_all_sectors_briefing": {
        "group": "新闻情报", "complexity": "medium", "latency": "slow",
        "keywords": ["全赛道", "综合", "摘要", "热门"],
        "data_source": "intel_rss", "market": [],
    },
    "search_industry_news": {
        "group": "新闻情报", "complexity": "low", "latency": "fast",
        "keywords": ["搜索", "跨赛道", "关键词"],
        "data_source": "intel_rss", "market": [],
    },
    "refresh_intel_cache": {
        "group": "新闻情报", "complexity": "low", "latency": "slow",
        "keywords": ["刷新", "缓存", "RSS"],
        "data_source": "intel_rss", "market": [],
    },
    "get_convertible_bonds": {
        "group": "新闻情报", "complexity": "low", "latency": "fast",
        "keywords": ["可转债", "转股", "溢价率"],
        "data_source": "eastmoney", "market": ["A"],
    },

    # ── AI分析/回测 (analysis) ──
    "analyze_stock_ai": {
        "group": "AI分析", "complexity": "high", "latency": "slow",
        "keywords": ["AI", "智能分析", "评分", "建议", "仪表盘"],
        "data_source": "tencent/yahoo", "market": ["A", "US", "HK"],
    },
    "check_backtest": {
        "group": "AI分析", "complexity": "high", "latency": "slow",
        "keywords": ["回测", "策略", "模拟交易", "绩效", "夏普"],
        "data_source": "tencent/yahoo", "market": ["A", "US", "HK"],
    },
    "run_alert_check": {
        "group": "AI分析", "complexity": "medium", "latency": "medium",
        "keywords": ["告警", "预警", "推送", "钉钉", "飞书"],
        "data_source": "webhook", "market": ["A"],
    },
    "check_st_risk": {
        "group": "AI分析", "complexity": "medium", "latency": "fast",
        "keywords": ["ST", "退市", "风险", "面值", "异常"],
        "data_source": "tencent", "market": ["A"],
    },
    "dcf_valuation": {
        "group": "AI分析", "complexity": "high", "latency": "medium",
        "keywords": ["DCF", "估值", "内在价值", "安全边际", "WACC"],
        "data_source": "eastmoney", "market": ["A"],
    },
    "ic_memo": {
        "group": "AI分析", "complexity": "high", "latency": "medium",
        "keywords": ["投委会", "备忘录", "质量", "P0-P4", "买入"],
        "data_source": "eastmoney", "market": ["A"],
    },
    "unit_economics": {
        "group": "AI分析", "complexity": "high", "latency": "medium",
        "keywords": ["单元经济", "SaaS", "ARPU", "LTV", "CAC", "毛利"],
        "data_source": "eastmoney", "market": ["A"],
    },
    "value_creation_plan": {
        "group": "AI分析", "complexity": "high", "latency": "medium",
        "keywords": ["价值创造", "EBITDA", "增长", "杠杆"],
        "data_source": "eastmoney", "market": ["A"],
    },
    "stock_score": {
        "group": "AI分析", "complexity": "medium", "latency": "medium",
        "keywords": ["评分", "综合", "技术+资金", "0-100"],
        "data_source": "tencent/eastmoney", "market": ["A"],
    },
    "stock_signals": {
        "group": "AI分析", "complexity": "medium", "latency": "medium",
        "keywords": ["信号", "多因子", "多头", "空头"],
        "data_source": "tencent/eastmoney", "market": ["A"],
    },
    "strategy_scan": {
        "group": "AI分析", "complexity": "high", "latency": "slow",
        "keywords": ["策略扫描", "连板", "动量", "超跌", "均线多头"],
        "data_source": "eastmoney/tencent", "market": ["A"],
    },
    "check_trap_risk": {
        "group": "AI分析", "complexity": "high", "latency": "medium",
        "keywords": ["杀猪盘", "骗局", "推广", "拉盘", "出货"],
        "data_source": "eastmoney", "market": ["A"],
    },
    "dd_checklist": {
        "group": "AI分析", "complexity": "high", "latency": "medium",
        "keywords": ["尽调", "尽职调查", "清单", "财务+商业+法律"],
        "data_source": "eastmoney", "market": ["A"],
    },
    "analyze_policy": {
        "group": "AI分析", "complexity": "medium", "latency": "fast",
        "keywords": ["政策", "宏观", "行业", "宽松", "收紧"],
        "data_source": "wallstreetcn", "market": [],
    },
    "analyze_stock_agent": {
        "group": "AI分析", "complexity": "high", "latency": "slow",
        "keywords": ["综合分析", "Agent", "一站式", "行情+财务+估值+风险"],
        "data_source": "multi", "market": ["A"],
    },

    # ── 基金/指数 (fund_index) ──
    "get_fund_info": {
        "group": "基金指数", "complexity": "low", "latency": "fast",
        "keywords": ["基金", "基础信息", "类型", "规模"],
        "data_source": "danjuan", "market": ["A"],
    },
    "get_fund_detail": {
        "group": "基金指数", "complexity": "low", "latency": "fast",
        "keywords": ["基金", "详情", "持仓", "费率"],
        "data_source": "danjuan", "market": ["A"],
    },
    "get_fund_nav_history": {
        "group": "基金指数", "complexity": "low", "latency": "fast",
        "keywords": ["基金", "净值", "历史"],
        "data_source": "danjuan", "market": ["A"],
    },
    "get_fund_growth": {
        "group": "基金指数", "complexity": "low", "latency": "fast",
        "keywords": ["基金", "涨幅", "阶段", "今年"],
        "data_source": "danjuan", "market": ["A"],
    },
    "get_fund_asset": {
        "group": "基金指数", "complexity": "low", "latency": "fast",
        "keywords": ["基金", "资产配置", "重仓股", "债券"],
        "data_source": "danjuan", "market": ["A"],
    },
    "get_fund_manager": {
        "group": "基金指数", "complexity": "low", "latency": "fast",
        "keywords": ["基金经理", "任期", "业绩"],
        "data_source": "danjuan", "market": ["A"],
    },
    "get_index_info": {
        "group": "基金指数", "complexity": "low", "latency": "fast",
        "keywords": ["指数", "基本信息", "编制方案"],
        "data_source": "csindex", "market": ["A"],
    },
    "get_index_details": {
        "group": "基金指数", "complexity": "low", "latency": "fast",
        "keywords": ["指数", "详情", "文件", "PDF"],
        "data_source": "csindex", "market": ["A"],
    },
    "get_index_perf": {
        "group": "基金指数", "complexity": "low", "latency": "fast",
        "keywords": ["指数", "表现", "每日", "涨跌幅"],
        "data_source": "csindex", "market": ["A"],
    },

    # ── 加密货币 (crypto) ──
    "get_crypto_quote": {
        "group": "加密货币", "complexity": "low", "latency": "fast",
        "keywords": ["加密", "货币", "行情", "BTC", "ETH"],
        "data_source": "binance/kraken", "market": ["CRYPTO"],
    },
    "get_crypto_quotes": {
        "group": "加密货币", "complexity": "low", "latency": "fast",
        "keywords": ["批量", "加密", "行情"],
        "data_source": "binance/kraken", "market": ["CRYPTO"],
    },
    "get_crypto_kline": {
        "group": "加密货币", "complexity": "low", "latency": "fast",
        "keywords": ["加密", "K线", "历史"],
        "data_source": "binance/kraken", "market": ["CRYPTO"],
    },
    "get_top_crypto": {
        "group": "加密货币", "complexity": "low", "latency": "fast",
        "keywords": ["热门", "排行", "成交量", "涨跌幅"],
        "data_source": "binance/kraken", "market": ["CRYPTO"],
    },

    # ── 市场数据补充 (market_data) ──
    "get_block_trade": {
        "group": "市场数据", "complexity": "low", "latency": "fast",
        "keywords": ["大宗交易", "溢价率", "营业部"],
        "data_source": "eastmoney_datacenter", "market": ["A"],
    },
    "get_holder_change": {
        "group": "市场数据", "complexity": "low", "latency": "fast",
        "keywords": ["股东户数", "筹码", "集中度"],
        "data_source": "eastmoney_datacenter", "market": ["A"],
    },
    "get_dividend_history": {
        "group": "市场数据", "complexity": "low", "latency": "fast",
        "keywords": ["分红", "送转", "股利", "历史"],
        "data_source": "eastmoney_datacenter", "market": ["A"],
    },
    "get_stock_boards": {
        "group": "市场数据", "complexity": "low", "latency": "fast",
        "keywords": ["板块", "行业", "概念", "地域", "归属"],
        "data_source": "eastmoney_emweb", "market": ["A"],
    },

    # ── 系统 (system) ──
    "get_cache_stats": {
        "group": "系统", "complexity": "low", "latency": "fast",
        "keywords": ["缓存", "统计", "命中率"],
        "data_source": "local", "market": [],
    },
    "get_data_source_health": {
        "group": "系统", "complexity": "low", "latency": "fast",
        "keywords": ["数据源", "健康", "监控", "延迟"],
        "data_source": "local", "market": [],
    },

    # ── 复合决策 (decisions) ──
    "portfolio_rebalance_signal": {
        "group": "复合决策", "complexity": "high", "latency": "slow",
        "keywords": ["调仓", "信号", "技术评分", "集中度", "止损", "urgency"],
        "data_source": "tencent/eastmoney", "market": ["A", "US", "HK"],
    },
    "intraday_alert": {
        "group": "复合决策", "complexity": "high", "latency": "medium",
        "keywords": ["盘中", "异动", "预警", "涨停", "主力", "放量", "跌停"],
        "data_source": "tencent/eastmoney", "market": ["A"],
    },

    # ── 可观测性 (observability) ──
    "probe_data_sources": {
        "group": "可观测性", "complexity": "low", "latency": "slow",
        "keywords": ["探测", "数据源", "可达性", "延迟", "ping"],
        "data_source": "multi", "market": [],
    },
    "get_tool_stats": {
        "group": "可观测性", "complexity": "low", "latency": "fast",
        "keywords": ["统计", "调用", "延迟", "成功率", "排行"],
        "data_source": "local_sqlite", "market": [],
    },
    "cleanup_metrics": {
        "group": "可观测性", "complexity": "low", "latency": "fast",
        "keywords": ["清理", "过期", "数据"],
        "data_source": "local_sqlite", "market": [],
    },

    # ── 筹码分布 (chip_distribution) ──
    "get_chip_distribution": {
        "group": "筹码分布", "complexity": "medium", "latency": "slow",
        "keywords": ["筹码", "CYQ", "获利盘", "套牢盘", "成本", "集中度", "换手率"],
        "data_source": "push2his", "market": ["A"],
    },

    # ── 宏观经济 (macro) ──
    "get_macro_pmi": {
        "group": "宏观经济", "complexity": "low", "latency": "fast",
        "keywords": ["PMI", "制造业", "非制造业", "采购经理", "经济景气"],
        "data_source": "eastmoney_datacenter", "market": ["macro"],
    },
    "get_macro_cpi": {
        "group": "宏观经济", "complexity": "low", "latency": "fast",
        "keywords": ["CPI", "通胀", "通缩", "物价", "消费价格"],
        "data_source": "eastmoney_datacenter", "market": ["macro"],
    },
    "get_macro_m2": {
        "group": "宏观经济", "complexity": "low", "latency": "fast",
        "keywords": ["M2", "M1", "货币供应", "剪刀差", "流动性", "社融"],
        "data_source": "eastmoney_datacenter", "market": ["macro"],
    },
    "get_macro_summary": {
        "group": "宏观经济", "complexity": "low", "latency": "medium",
        "keywords": ["宏观", "全景", "PMI", "CPI", "M2", "经济环境", "综合判断"],
        "data_source": "eastmoney_datacenter", "market": ["macro"],
    },
}
