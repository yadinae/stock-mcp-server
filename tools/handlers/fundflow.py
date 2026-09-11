from __future__ import annotations

import json


def register(mcp):
    """Register fund flow tools with the MCP server."""

    @mcp.tool(name="get_fund_flow_120d")
    def get_fund_flow_120d(code: str, days: int = 120) -> str:
        """获取个股120日资金流向（日级主力/大单/中单/小单净流入）。
        Args:
            code=股票代码
            days=返回天数(默认120)
        """
        from data_sources.em_fundflow import get_fund_flow_120d as _get_fund_flow_120d
        return json.dumps(_get_fund_flow_120d(code, days), ensure_ascii=False, default=str)

    @mcp.tool(name="get_fund_flow_minute")
    def get_fund_flow_minute(code: str) -> str:
        """获取个股当日盘中分钟级资金流向（主力/大单/中单/小单/超大单净流入）。
        Args:
            code=股票代码
        """
        from data_sources.em_fundflow import get_fund_flow_minute as _get_fund_flow_minute
        return json.dumps(_get_fund_flow_minute(code), ensure_ascii=False, default=str)

    @mcp.tool(name="get_concept_fund_flow")
    def get_concept_fund_flow(top_n: int = 20, sort_by: str = "net_inflow") -> str:
        """获取概念板块资金流向排名（主力净流入/流出）。
        Args:
            top_n=返回条数(默认20)
            sort_by=排序字段: net_inflow(净流入), net_outflow(净流出), total_amount(总成交额)
        """
        from data_sources.em_fundflow import get_concept_fund_flow as _get_concept_fund_flow
        return json.dumps(_get_concept_fund_flow(top_n, sort_by), ensure_ascii=False, default=str)

    @mcp.tool(name="get_industry_fund_flow")
    def get_industry_fund_flow(top_n: int = 20) -> str:
        """行业板块资金流向排名（主力净流入，东财 push2 502 时用腾讯板块接口替代）。
        Args:
            top_n=返回条数(默认20)
        """
        from data_sources.em_market import get_industry_fund_flow as _get_industry_fund_flow
        return json.dumps(_get_industry_fund_flow(top_n), ensure_ascii=False, default=str)

    @mcp.tool(name="get_us_fund_flow")
    def get_us_fund_flow(code: str, days: int = 30, secid_prefix: int = 0) -> str:
        """获取美股/港股日级资金流向

        Args:
            code: AAPL(美股) / 00700(港股)
            days: 返回天数（默认30）
            secid_prefix: 105=NASDAQ, 106=NYSE, 116=港股（0=自动检测）

        返回主力/大单/中单/小单净流入历史。
        """
        from data_sources.global_stock import fund_flow_daily
        from core.helpers import _detect_secid_prefix
        try:
            code_clean = code.strip().upper()
            if secid_prefix == 0:
                secid_prefix = _detect_secid_prefix(code_clean)
            secid = f"{secid_prefix}.{code_clean}"
            data = fund_flow_daily(secid, limit=days)
            return json.dumps({
                "code": code_clean,
                "secid": secid,
                "records": data,
                "count": len(data),
            }, ensure_ascii=False, default=str)
        except Exception as e:
            return json.dumps({"error": str(e), "code": code}, ensure_ascii=False)

    @mcp.tool(name="get_margin_trading")
    def get_margin_trading(code: str, days: int = 30) -> str:
        """获取个股融资融券明细（日级）。含融资余额、融资买入/偿还、融券余额等。
        Args:
            code=股票代码
            days=返回天数(默认30)
        """
        from data_sources.em_market import get_margin_trading as _get_margin_trading
        records = _get_margin_trading(code, days)
        return json.dumps({"code": code, "records": records}, ensure_ascii=False, default=str)
