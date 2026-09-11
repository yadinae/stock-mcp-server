"""缠论分析工具 handler"""
from __future__ import annotations

import json

from core.helpers import _validate_code, _error_response, _get_kline


def register(mcp):
    """Register chanlun analysis tools."""

    @mcp.tool(name="analyze_chanlun")
    def analyze_chanlun_tool(code: str, days: int = 200) -> str:
        """缠论技术分析 — K线合并→分型→笔→中枢→买卖点→背驰

        基于缠论理论的完整分析流水线，输出：
        - 笔序列（方向/高低点/确认状态）
        - 中枢（上沿/下沿/最高最低/笔数）
        - 买卖点信号（一二三类买卖点）
        - 背驰信号（笔背驰/盘整背驰/趋势背驰）

        Args:
            code: 股票代码。A股示例：600519, 000001  美股示例：AAPL, MSFT
            days: 分析天数（默认200，建议>=120以获得完整中枢结构）

        输出：结构化的缠论分析结果（JSON），含 summary/bis/zhongshus/signals/divergences
        注意：缠论分析仅作技术研究参考，不代表投资建议
        """
        from tools.backtest.chanlun import ChanlunAnalyser

        err = _validate_code(code)
        if err:
            return _error_response(code, err)

        analysis_days = min(max(days, 60), 730)
        kline = _get_kline(code, days=analysis_days)
        records = kline.get("records", [])
        if not records:
            return _error_response(code, kline.get("error", "无K线数据"), "data_error")

        analyser = ChanlunAnalyser(code=code, frequency="DAILY")
        result = analyser.analyse(records)

        output = result.to_dict()
        output["days"] = analysis_days
        return json.dumps(output, ensure_ascii=False, default=str)
