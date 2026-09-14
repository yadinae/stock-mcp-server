#!/usr/bin/env python3
"""Chip distribution + macro data tool handlers."""
from __future__ import annotations

import json


def register(mcp) -> None:
    @mcp.tool(name="get_chip_distribution")
    def tool_get_chip_distribution(code: str, days: int = 120) -> str:
        """计算个股筹码分布（CYQ）

        基于换手率驱动的筹码迁移模型，输出：
        - 平均成本、获利盘比例、套牢盘比例
        - 90%/70%筹码集中度区间
        - 筹码分布图（价格→占比）

        Args:
            code: 股票代码（如 600519, 000001）
            days: 计算天数（默认120，最大250）
        """
        from data_sources.chip_distribution import calculate_chip_distribution
        days = max(20, min(250, days))
        result = calculate_chip_distribution(code, days=days)
        return json.dumps(result, ensure_ascii=False, default=str)

    @mcp.tool(name="get_macro_pmi")
    def tool_get_macro_pmi(months: int = 12) -> str:
        """获取制造业PMI + 非制造业PMI

        输出：月度数据序列、最新值、趋势判断。
        PMI > 50 = 扩张，< 50 = 收缩。

        Args:
            months: 返回月数（默认12）
        """
        from data_sources.macro_data import get_pmi
        months = max(3, min(24, months))
        return json.dumps(get_pmi(months), ensure_ascii=False, default=str)

    @mcp.tool(name="get_macro_cpi")
    def tool_get_macro_cpi(months: int = 12) -> str:
        """获取全国CPI（同比/环比/累计）

        输出：月度数据序列、最新值、通胀趋势判断。

        Args:
            months: 返回月数（默认12）
        """
        from data_sources.macro_data import get_cpi
        months = max(3, min(24, months))
        return json.dumps(get_cpi(months), ensure_ascii=False, default=str)

    @mcp.tool(name="get_macro_m2")
    def tool_get_macro_m2(months: int = 12) -> str:
        """获取M2货币供应量（同比/环比/M2-M1剪刀差）

        输出：月度数据、M2-M1剪刀差及解读。
        剪刀差 > 2 = 资金淤积（偏空），< 0 = 资金活化（偏多）。

        Args:
            months: 返回月数（默认12）
        """
        from data_sources.macro_data import get_m2
        months = max(3, min(24, months))
        return json.dumps(get_m2(months), ensure_ascii=False, default=str)

    @mcp.tool(name="get_macro_summary")
    def tool_get_macro_summary() -> str:
        """宏观数据全景（PMI + CPI + M2 一次获取）

        输出三大指标最新值 + 综合信号判断（扩张/收缩、通胀/通缩、资金活化/淤积）。
        适用于快速了解当前宏观环境。
        """
        from data_sources.macro_data import get_macro_summary
        return json.dumps(get_macro_summary(), ensure_ascii=False, default=str)
