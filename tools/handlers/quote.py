from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from core.helpers import (
    _validate_code,
    _validate_days,
    _error_response,
    _code_type,
    _get_realtime_quote,
    _get_kline,
    _get_stock_info,
    _code_to_secid,
)


def register(mcp):
    """Register quote tools with the MCP server."""

    @mcp.tool(name="get_realtime_quote")
    def get_realtime_quote(code: str) -> str:
        """获取股票实时行情（价格、涨跌幅、成交量等）
        Args:
            code: 股票代码。A股示例：600519, 000001, sh600519
                  美股示例：AAPL, MSFT, TSLA
                  港股示例：HK00700, hk00700
        """
        err = _validate_code(code)
        if err:
            return _error_response(code, err)
        result = _get_realtime_quote(code)
        return json.dumps(result, ensure_ascii=False, default=str)

    @mcp.tool(name="get_kline")
    def get_kline(code: str, days: int = 60) -> str:
        """获取股票历史K线数据
        Args:
            code: 股票代码
            days: 最近多少天（默认60）
        """
        err = _validate_code(code)
        if err:
            return _error_response(code, err)
        err = _validate_days(days)
        if err:
            return _error_response(code, err)
        result = _get_kline(code, min(days, 365))
        return json.dumps(result, ensure_ascii=False, default=str)

    @mcp.tool(name="get_stock_info")
    def get_stock_info(code: str) -> str:
        """获取股票基本信息（名称、现价、涨跌幅、成交量）
        Args:
            code: 股票代码
        """
        err = _validate_code(code)
        if err:
            return _error_response(code, err)
        result = _get_stock_info(code)
        return json.dumps(result, ensure_ascii=False, default=str)

    @mcp.tool(name="analyze_stocks")
    def analyze_stocks(stock_list: str) -> str:
        """批量分析多只股票的行情摘要
        Args:
            stock_list: 逗号分隔的股票代码，如 "600519,000001,AAPL,HK00700"
        """
        from data_sources import tencent, yahoo
        from core.parallel import parallel_map

        codes = [c.strip() for c in stock_list.split(",") if c.strip()]
        if not codes:
            return _error_response("", "请提供至少一个股票代码")
        # 验证每个代码
        for c in codes:
            err = _validate_code(c)
            if err:
                return _error_response(c, err)
        # 按市场分组
        a_codes = [c for c in codes if _code_type(c) == "a"]
        us_codes = [c for c in codes if _code_type(c) in ("us", "hk")]

        # A 股批量查询（单次 API 调用）
        a_results = tencent.batch_realtime(a_codes) if a_codes else []

        # 美股/港股并行查询
        us_results = []
        if us_codes:
            us_results = parallel_map(yahoo.get_realtime_quote, us_codes, max_workers=4)

        results = a_results + [r for r in us_results if r is not None]

        return json.dumps({
            "stocks": results,
            "count": len(results),
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }, ensure_ascii=False, default=str)

    @mcp.tool(name="get_global_quote")
    def get_global_quote(code: str, source: str = "auto") -> str:
        """获取美股/港股实时行情（增强版，多数据源）

        Args:
            code: 美股字母代码如 AAPL, TSLA / 港股5位数字如 00700, 09988
            source: auto(自动选最优) / sina / tencent / eastmoney

        字段含中文名、PE、PB、市值、52周高低等，比Yahoo基础版更丰富。
        """
        from data_sources.global_stock import (
            global_quote, us_quote_sina, us_quote_tencent,
            hk_quote_tencent, hk_quote_sina, quote_eastmoney,
        )
        try:
            code = code.strip().upper()
            if source == "sina":
                if code.isalpha():
                    result = us_quote_sina(code)
                else:
                    result = hk_quote_sina(code)
            elif source == "tencent":
                if code.isalpha():
                    result = us_quote_tencent(code)
                else:
                    result = hk_quote_tencent(code)
            elif source == "eastmoney":
                secid = _code_to_secid(code)
                result = quote_eastmoney(secid) if secid else {"error": f"无法映射secid: {code}"}
            else:
                result = global_quote(code)
            result["code"] = code
            return json.dumps(result, ensure_ascii=False, default=str)
        except Exception as e:
            return json.dumps({"error": str(e), "code": code}, ensure_ascii=False)

    @mcp.tool(name="get_global_kline")
    def get_global_kline(code: str, days: int = 120, interval: str = "1d") -> str:
        """获取美股/港股历史K线数据

        Args:
            code: AAPL(美股) / 0700.HK(港股)
            days: 天数（默认120，新浪美股可回溯至1984年）
            interval: 周期 1d(日) / 1wk(周) / 1mo(月)

        美股优先用新浪（回溯更久），港股用 Yahoo。Yahoo 支持多周期。
        """
        from data_sources.global_stock import us_kline_sina, kline_yahoo
        try:
            code_clean = code.strip().upper()
            records = []

            if code_clean.isalpha() and len(code_clean) <= 5:
                # 美股 → 新浪
                records = us_kline_sina(code_clean, num=days)
                if not records:
                    # Fallback 到 Yahoo
                    range_map = {60: "3mo", 120: "6mo", 250: "1y", 750: "5y"}
                    range_ = "6mo"
                    for d, r in sorted(range_map.items()):
                        if days <= d:
                            range_ = r
                            break
                    records = kline_yahoo(code_clean, interval=interval, range_=range_)
            else:
                # 港股 → Yahoo
                if not code_clean.endswith(".HK"):
                    code_clean = f"{code_clean}.HK"
                range_map = {60: "3mo", 120: "6mo", 250: "1y", 750: "5y"}
                range_ = "6mo"
                for d, r in sorted(range_map.items()):
                    if days <= d:
                        range_ = r
                        break
                records = kline_yahoo(code_clean, interval=interval, range_=range_)

            return json.dumps({
                "code": code.strip(),
                "records": records,
                "count": len(records),
            }, ensure_ascii=False, default=str)
        except Exception as e:
            return json.dumps({"error": str(e), "code": code}, ensure_ascii=False)

    @mcp.tool(name="get_tv_quote")
    def get_tv_quote(code: str) -> str:
        """TV REST 个股行情（A股）。
        Args:
            code: 6位A股代码
        """
        from data_sources.em_market import get_tv_quote as _get_tv_quote
        return json.dumps(_get_tv_quote(code), ensure_ascii=False, default=str)

    @mcp.tool(name="get_tv_market_list")
    def get_tv_market_list(top_n: int = 100) -> str:
        """TV REST 大盘股列表（按市值排序）。
        Args:
            top_n: 返回前N名
        """
        from data_sources.em_market import get_tv_market_list as _get_tv_market_list
        return json.dumps(_get_tv_market_list(top_n), ensure_ascii=False, default=str)

    @mcp.tool(name="get_stock_context")
    def get_stock_context(code: str) -> str:
        """获取股票综合数据（一次调用返回所有可用数据）
        Args:
            code: 股票代码
        使用并行执行同时获取实时行情 + K 线数据。"""
        from core.helpers import _validate_code, _error_response, _get_realtime_quote, _get_kline, _get_stock_info
        from core.parallel import run_parallel
        from tools.technical import analyze as analyze_technical
        from tools.news import search_news
        from datetime import datetime

        err = _validate_code(code)
        if err:
            return _error_response(code, err)
        tasks = {"realtime": lambda: _get_realtime_quote(code), "kline": lambda: _get_kline(code, days=120)}
        pr = run_parallel(tasks, timeout=20)
        result = {"code": code, "realtime": pr.get("realtime", {"error": "获取失败"}), "kline": pr.get("kline", {"error": "获取失败"}), "technical": None, "news": None}
        kline_data = result["kline"]
        records = kline_data.get("records", []) if isinstance(kline_data, dict) else []
        if records:
            try: result["technical"] = analyze_technical(records, code)
            except Exception as e: result["technical"] = {"error": str(e)}
        try:
            stock_name = _get_stock_info(code).get("name", "")
            result["news"] = search_news(code, stock_name)
        except Exception as e: result["news"] = {"error": str(e)}
        result["time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return json.dumps(result, ensure_ascii=False, default=str)
