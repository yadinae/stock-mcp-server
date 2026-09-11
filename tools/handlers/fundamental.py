from __future__ import annotations

import json


def register(mcp):
    """Register fundamental analysis tools with the MCP server."""

    # ── 通达信 F10 数据 ─────────────────────────────────────

    @mcp.tool(name="get_tdx_company_info")
    def get_tdx_company_info(code: str) -> str:
        """通达信 F10 公司资料（东财 emweb 通道）— 公司简介、股本结构、注册地址、法人代表

        Args:
            code: 股票代码。A股示例：600519, 000001
        """
        from data_sources.em_f10 import get_company_profile
        return json.dumps(get_company_profile(code), ensure_ascii=False, default=str)

    @mcp.tool(name="get_tdx_finance_info")
    def get_tdx_finance_info(code: str) -> str:
        """通达信 F10 财务信息（东财 datacenter 通道）— EPS、营收、净利润、ROE、毛利率

        Args:
            code: 股票代码。A股示例：600519, 000001
        """
        from data_sources.em_f10 import get_company_financials
        return json.dumps(get_company_financials(code), ensure_ascii=False, default=str)

    @mcp.tool(name="get_tdx_xdxr_info")
    def get_tdx_xdxr_info(code: str) -> str:
        """通达信除权除息信息（东财通道）— 分红、送转股历史

        Args:
            code: 股票代码。A股示例：600519, 000001
        """
        from data_sources.em_f10 import get_xdxr_info
        return json.dumps(get_xdxr_info(code), ensure_ascii=False, default=str)

    # ── F10 增强版（🆕 标记） ────────────────────────────────

    @mcp.tool(name="get_company_profile")
    def get_company_profile(code: str) -> str:
        """🆕 获取公司详细资料（F10）— 名称、全称、成立日期、上市日期、注册地址、主营业务、行业分类、员工数、法人代表、总股本等。仅支持 A 股。

        Args:
            code: 股票代码，如 600519
        """
        from data_sources.em_f10 import get_company_profile as _get_company_profile
        return json.dumps(_get_company_profile(code), ensure_ascii=False, default=str)

    @mcp.tool(name="get_company_financials")
    def get_company_financials(code: str) -> str:
        """🆕 获取公司财务核心指标（F10）— 近8期EPS/营收/净利润/毛利率/ROE/资产负债率/BVPS/CFPS。仅支持 A 股。

        Args:
            code: 股票代码，如 600519
        """
        from data_sources.em_f10 import get_company_financials as _get_company_financials
        return json.dumps(_get_company_financials(code), ensure_ascii=False, default=str)

    @mcp.tool(name="get_top_shareholders")
    def get_top_shareholders(code: str) -> str:
        """🆕 获取十大股东 — 股东名称、持股数量、持股比例、变动情况。仅支持 A 股。

        Args:
            code: 股票代码，如 600519
        """
        from data_sources.em_f10 import get_top_shareholders as _get_top_shareholders
        return json.dumps(_get_top_shareholders(code), ensure_ascii=False, default=str)

    @mcp.tool(name="get_management_team")
    def get_management_team(code: str) -> str:
        """🆕 获取管理层信息 — 董事长/总经理/董秘/独董等核心岗位。仅支持 A 股。

        Args:
            code: 股票代码，如 600519
        """
        from data_sources.em_f10 import get_management_team as _get_management_team
        return json.dumps(_get_management_team(code), ensure_ascii=False, default=str)

    # ── 美股/港股财务 ──────────────────────────────────────

    @mcp.tool(name="get_us_financials")
    def get_us_financials(code: str, statement: str = "income", market: str = "us") -> str:
        """获取美股/港股财务报表（中文科目名）

        Args:
            code: AAPL(美股) / 00700(港股)
            statement: balance(资产负债表) / income(利润表) / cashflow(现金流量表)
            market: us(美股) / hk(港股)

        通过东财 datacenter 获取，中文字段名，按科目行展开。
        """
        from data_sources.global_stock import financial_statements, get_secucode
        try:
            secucode = get_secucode(code.strip().upper(), market)
            data = financial_statements(secucode, statement=statement)
            return json.dumps({
                "code": code.strip(),
                "secucode": secucode,
                "statement": statement,
                "records": data[:100],
                "count": len(data[:100]),
            }, ensure_ascii=False, default=str)
        except Exception as e:
            return json.dumps({"error": str(e), "code": code}, ensure_ascii=False)

    @mcp.tool(name="get_us_key_indicators")
    def get_us_key_indicators(code: str, market: str = "us") -> str:
        """获取美股/港股关键财务指标（中文版）

        Args:
            code: AAPL(美股) / 00700(港股)
            market: us(美股) / hk(港股)

        通过东财 GMAININDICATOR 获取，含 ROE/ROA/EPS/毛利率/资产负债率 等。
        """
        from data_sources.global_stock import key_indicators, get_secucode
        try:
            secucode = get_secucode(code.strip().upper(), market)
            data = key_indicators(secucode)
            return json.dumps({
                "code": code.strip(),
                "secucode": secucode,
                "records": data,
                "count": len(data),
            }, ensure_ascii=False, default=str)
        except Exception as e:
            return json.dumps({"error": str(e), "code": code}, ensure_ascii=False)

    # ── 东财财务数据 ──────────────────────────────────────

    @mcp.tool(name="fetch_financials")
    def fetch_financials(code: str) -> str:
        """获取股票财务报表核心数据 — 营收、利润、EPS、FCF、负债、流通股本等。
        Args:
            code: 股票代码。A股示例：600519, 000001
        """
        from data_sources.em_market import fetch_financials as _fetch_financials
        return json.dumps(_fetch_financials(code), ensure_ascii=False, default=str)

    # ── 新浪财报 ──────────────────────────────────────────

    @mcp.tool(name="get_financial_reports")
    def get_financial_reports(code: str, type: str = "lrb", periods: int = 8) -> str:
        """获取新浪财报三表数据（资产负债表/利润表/现金流量表）。
        Args:
            code: 股票代码
            type: 报表类型 zcfz(资产负债表) lrb(利润表) xjll(现金流量表)
            periods: 返回期数（默认8）
        """
        from data_sources.sina_financial import get_sina_financial_report
        return json.dumps(get_sina_financial_report(code, type, periods), ensure_ascii=False, default=str)

    @mcp.tool(name="get_yahoo_statistics")
    def get_yahoo_statistics(symbol: str) -> str:
        """获取美股/港股关键财务指标（英文版，Yahoo）
        Args: symbol=AAPL(美股)/0700.HK(港股)"""
        from data_sources.global_stock import yahoo_key_statistics
        try:
            return json.dumps(yahoo_key_statistics(symbol.strip().upper()), ensure_ascii=False, default=str)
        except Exception as e:
            return json.dumps({"error": str(e), "symbol": symbol}, ensure_ascii=False)

    @mcp.tool(name="get_institutional_holders")
    def get_institutional_holders(symbol: str) -> str:
        """获取美股/港股机构持仓（Yahoo）
        Args: symbol=AAPL(美股)/0700.HK(港股)"""
        from data_sources.global_stock import yahoo_institutional_holders
        try:
            return json.dumps(yahoo_institutional_holders(symbol.strip().upper()), ensure_ascii=False, default=str)
        except Exception as e:
            return json.dumps({"error": str(e), "symbol": symbol}, ensure_ascii=False)

    @mcp.tool(name="get_options_chain")
    def get_options_chain(symbol: str) -> str:
        """获取美股期权链（Yahoo，仅美股）
        Args: symbol=AAPL, TSLA 等美股 ticker"""
        from data_sources.global_stock import options_chain
        try:
            return json.dumps(options_chain(symbol.strip().upper()), ensure_ascii=False, default=str)
        except Exception as e:
            return json.dumps({"error": str(e), "symbol": symbol}, ensure_ascii=False)

    @mcp.tool(name="get_sec_filings")
    def get_sec_filings(ticker: str, form_type: str = "") -> str:
        """获取 SEC EDGAR 文件列表（仅美股）
        Args: ticker=AAPL/TSLA, form_type=10-K/10-Q/8-K(可选)"""
        from data_sources.global_stock import ticker_to_cik, sec_filings
        try:
            tk = ticker.strip().upper()
            cik_info = ticker_to_cik(tk)
            if "error" in cik_info: return json.dumps(cik_info, ensure_ascii=False)
            filings = sec_filings(cik_info["cik"], form_type=form_type)
            filings["ticker"] = tk
            return json.dumps(filings, ensure_ascii=False, default=str)
        except Exception as e:
            return json.dumps({"error": str(e), "ticker": ticker}, ensure_ascii=False)

    @mcp.tool(name="get_sec_xbrl")
    def get_sec_xbrl(ticker: str, metrics: str = "") -> str:
        """获取 SEC XBRL 结构化财务数据（仅美股，503个GAAP指标）
        Args: ticker=AAPL/TSLA, metrics=逗号分隔指标名(可选)"""
        from data_sources.global_stock import ticker_to_cik, sec_xbrl_facts
        try:
            tk = ticker.strip().upper()
            cik_info = ticker_to_cik(tk)
            if "error" in cik_info: return json.dumps(cik_info, ensure_ascii=False)
            metrics_list = [m.strip() for m in metrics.split(",") if m.strip()] if metrics else None
            return json.dumps(sec_xbrl_facts(cik_info["cik"], metrics=metrics_list), ensure_ascii=False, default=str)
        except Exception as e:
            return json.dumps({"error": str(e), "ticker": ticker}, ensure_ascii=False)

    @mcp.tool(name="search_global_stock")
    def search_global_stock(keyword: str) -> str:
        """搜索全球股票（东财，支持中英文）
        Args: keyword=AAPL/苹果/Tencent/00700"""
        from data_sources.global_stock import stock_search
        try:
            results = stock_search(keyword)
            return json.dumps({"keyword": keyword, "results": results, "count": len(results)}, ensure_ascii=False, default=str)
        except Exception as e:
            return json.dumps({"error": str(e), "keyword": keyword}, ensure_ascii=False)

    @mcp.tool(name="get_us_market_ranking")
    def get_us_market_ranking(market: str = "us_nasdaq", sort_by: str = "change_pct", ascending: bool = False, page: int = 1) -> str:
        """获取美股/港股全市场涨跌幅排名
        Args: market=us_nasdaq/us_nyse/us_etf/hk, sort_by=change_pct/volume/amount"""
        from data_sources.global_stock import market_stock_list
        try:
            sort_field_map = {"change_pct": "f3", "volume": "f5", "amount": "f6"}
            data = market_stock_list(market=market, sort_field=sort_field_map.get(sort_by, "f3"), sort_desc=not ascending, page=page)
            return json.dumps({"market": market, "sort_by": sort_by, "total": data["total"], "stocks": data["stocks"], "page": page}, ensure_ascii=False, default=str)
        except Exception as e:
            return json.dumps({"error": str(e)}, ensure_ascii=False)
