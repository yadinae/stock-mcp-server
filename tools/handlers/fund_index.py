"""Fund and index tools (蛋卷基金 + 中证指数)."""
from __future__ import annotations

import json

from data_sources import danjuan_csindex


def register(mcp):
    """Register fund and index tools."""

    @mcp.tool(name="get_fund_info")
    def get_fund_info(code: str) -> str:
        """基金基础信息 — 名称/类型/规模/经理/风险等级/状态。

        Args:
            code: 基金代码（6位数字）
        """
        return json.dumps(danjuan_csindex.fund_info(code), ensure_ascii=False, default=str)

    @mcp.tool(name="get_fund_detail")
    def get_fund_detail(code: str) -> str:
        """基金详情 — 公司介绍+持仓(前10)+费率+经理列表。

        Args:
            code: 基金代码（6位数字）
        """
        return json.dumps(danjuan_csindex.fund_detail(code), ensure_ascii=False, default=str)

    @mcp.tool(name="get_fund_nav_history")
    def get_fund_nav_history(code: str, page: int = 1, size: int = 30) -> str:
        """基金净值历史 — 每日净值+涨跌幅。

        Args:
            code: 基金代码（6位数字）
            page: 页码
            size: 每页条数
        """
        return json.dumps(danjuan_csindex.fund_nav_history(code, page, size), ensure_ascii=False, default=str)

    @mcp.tool(name="get_fund_growth")
    def get_fund_growth(code: str, day: str = "ty") -> str:
        """基金阶段涨幅 — day: ty(今年)/1y/3y/5y。

        Args:
            code: 基金代码（6位数字）
            day: 区间（默认ty=今年以来）
        """
        return json.dumps(danjuan_csindex.fund_growth(code, day), ensure_ascii=False, default=str)

    @mcp.tool(name="get_fund_asset")
    def get_fund_asset(code: str) -> str:
        """基金资产配置 — 股票/债券/现金比例+重仓股(前10)。

        Args:
            code: 基金代码（6位数字）
        """
        return json.dumps(danjuan_csindex.fund_asset(code), ensure_ascii=False, default=str)

    @mcp.tool(name="get_fund_manager")
    def get_fund_manager(code: str) -> str:
        """基金经理 — 任期/年限/业绩。

        Args:
            code: 基金代码（6位数字）
        """
        return json.dumps(danjuan_csindex.fund_manager(code), ensure_ascii=False, default=str)

    @mcp.tool(name="get_index_info")
    def get_index_info(code: str) -> str:
        """指数基本信息 — 全名/简称/基日/基点/发布日期/编制说明。

        Args:
            code: 指数代码（6位数字，如 000300）
        """
        return json.dumps(danjuan_csindex.index_basic_info(code), ensure_ascii=False, default=str)

    @mcp.tool(name="get_index_details")
    def get_index_details(code: str) -> str:
        """指数详情文件清单 — 编制方案PDF/样本权重xls等直链。

        Args:
            code: 指数代码（6位数字）
        """
        return json.dumps(danjuan_csindex.index_details(code), ensure_ascii=False, default=str)

    @mcp.tool(name="get_index_perf")
    def get_index_perf(code: str, days: int = 30) -> str:
        """指数区间表现 — 每日开高低收/涨跌幅。

        Args:
            code: 指数代码（6位数字）
            days: 返回天数
        """
        return json.dumps(danjuan_csindex.index_perf(code, days), ensure_ascii=False, default=str)
