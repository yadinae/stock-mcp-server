from __future__ import annotations

import json

from core.helpers import _validate_code, _error_response, _get_kline
from core.compression import compress_dict_result


def register(mcp):
    """Register technical analysis tools with the MCP server."""

    @mcp.tool(name="get_technical_analysis")
    def get_technical_analysis(code: str) -> str:
        """获取股票技术分析（MA/MACD/RSI/布林带/趋势判断/量价分析）
        Args:
            code: 股票代码。A股示例：600519, 000001  美股示例：AAPL, MSFT  港股示例：HK00700
        """
        from tools.technical import analyze as analyze_technical

        err = _validate_code(code)
        if err:
            return _error_response(code, err)
        kline = _get_kline(code, days=120)
        records = kline.get("records", [])
        if not records:
            return _error_response(code, kline.get("error", "无K线数据"), "data_error")

        result = analyze_technical(records, code)
        result["code"] = code
        return json.dumps(result, ensure_ascii=False, default=str)

    @mcp.tool(name="technical_batch_scan")
    def technical_batch_scan(codes: str, days: int = 90, filter: str = "") -> str:
        """批量技术指标扫描 — 一次计算多只股票的技术指标并可按条件筛选。
        Args:
            codes: 逗号分隔的股票代码列表，如 "600519,000001,AAPL"
            days: 最近多少天（默认90）
            filter: 筛选条件，如 "macd_golden_cross", "rsi_oversold"
        """
        from tools.advanced import technical_batch_scan as _batch_scan
        return compress_dict_result(_batch_scan(codes=codes, days=days, filter_str=filter))

    @mcp.tool(name="tdx_test")
    def tdx_test() -> str:
        """TDX 协议连通性测试 — mootdx TCP 直连 + 腾讯行情兜底。
        用途：验证行情链路可用性
        """
        from tools.advanced import tdx_test as _tdx_test
        return json.dumps(_tdx_test(), ensure_ascii=False, default=str)
