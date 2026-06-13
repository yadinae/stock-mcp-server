#!/usr/bin/env python3
"""
Stock Analysis MCP Server
=========================
提供 A股（腾讯行情）+ 美股/港股（Yahoo Finance）实时数据。
8 个工具，集成 TTL 缓存 + 并行执行。

P0:  缓存 + 并行化
P1:  模块拆分 + LLM 配置加固
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timedelta
from typing import Any

# ── MCP SDK ──────────────────────────────────────────────────
try:
    from mcp.server.fastmcp import FastMCP
except ImportError:
    print("ERROR: MCP SDK not installed. Run: pip install mcp", file=sys.stderr)
    sys.exit(1)

# ── 内部模块 ──────────────────────────────────────────────────
from core.cache import get_cache
from core.parallel import run_parallel, parallel_map
from data_sources import tencent, yahoo
from tools.technical import analyze as analyze_technical
from tools.news import search_news
from tools.analyzer import analyze_stock as ai_analyze

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("stock-mcp")

mcp = FastMCP("stock-mcp")

# ── 代码分类辅助函数 ──────────────────────────────────────────


def _code_type(code: str) -> str:
    """Detect market: a=沪/深, us=美股, hk=港股"""
    return tencent.code_type(code)


def _get_realtime_quote(code: str) -> dict[str, Any]:
    """通用实时行情（自动判断市场）"""
    ctype = _code_type(code)
    if ctype == "a":
        return tencent.get_realtime_quote(code)
    if ctype in ("us", "hk"):
        result = yahoo.get_realtime_quote(code)
        return result or {"code": code, "error": f"无法获取{'美股' if ctype == 'us' else '港股'}行情"}
    return {"code": code, "error": f"无法识别股票代码: {code}"}


def _get_kline(code: str, days: int = 60) -> dict[str, Any]:
    """通用 K 线数据（自动判断市场）"""
    ctype = _code_type(code)
    if ctype == "a":
        return tencent.get_kline(code, days)
    if ctype in ("us", "hk"):
        return yahoo.get_kline(code, days)
    return {"code": code, "error": f"不支持的市场类型: {ctype}"}


def _get_stock_info(code: str) -> dict[str, Any]:
    """通用股票信息（自动判断市场）"""
    ctype = _code_type(code)
    result = {"code": code, "type": ctype}
    if ctype == "a":
        result.update(tencent.get_stock_info(code))
    elif ctype in ("us", "hk"):
        result.update(yahoo.get_stock_info(code))
    return result


# ── MCP 工具定义 ─────────────────────────────────────────────


@mcp.tool(name="get_realtime_quote")
def get_realtime_quote(code: str) -> str:
    """获取股票实时行情（价格、涨跌幅、成交量等）
    Args:
        code: 股票代码。A股示例：600519, 000001, sh600519
              美股示例：AAPL, MSFT, TSLA
              港股示例：HK00700, hk00700
    """
    result = _get_realtime_quote(code)
    return json.dumps(result, ensure_ascii=False, default=str)


@mcp.tool(name="get_kline")
def get_kline(code: str, days: int = 60) -> str:
    """获取股票历史K线数据
    Args:
        code: 股票代码
        days: 最近多少天（默认60）
    """
    result = _get_kline(code, min(days, 365))
    return json.dumps(result, ensure_ascii=False, default=str)


@mcp.tool(name="get_stock_info")
def get_stock_info(code: str) -> str:
    """获取股票基本信息（名称、现价、涨跌幅、成交量）
    Args:
        code: 股票代码
    """
    result = _get_stock_info(code)
    return json.dumps(result, ensure_ascii=False, default=str)


@mcp.tool(name="analyze_stocks")
def analyze_stocks(stock_list: str) -> str:
    """批量分析多只股票的行情摘要
    Args:
        stock_list: 逗号分隔的股票代码，如 "600519,000001,AAPL,HK00700"
    """
    codes = [c.strip() for c in stock_list.split(",") if c.strip()]
    if not codes:
        return json.dumps({"error": "请提供至少一个股票代码"}, ensure_ascii=False)

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


@mcp.tool(name="get_technical_analysis")
def get_technical_analysis(code: str) -> str:
    """获取股票技术分析（MA/MACD/RSI/布林带/趋势判断/量价分析）
    Args:
        code: 股票代码。A股示例：600519, 000001  美股示例：AAPL, MSFT  港股示例：HK00700
    """
    kline = _get_kline(code, days=120)
    records = kline.get("records", [])
    if not records:
        return json.dumps({"code": code, "error": kline.get("error", "无K线数据")},
                          ensure_ascii=False)

    result = analyze_technical(records, code)
    result["code"] = code
    return json.dumps(result, ensure_ascii=False, default=str)


@mcp.tool(name="search_stock_news")
def search_stock_news(code: str, name: str = "") -> str:
    """搜索股票相关新闻
    Args:
        code: 股票代码
        name: 股票名称（可选，提供后可提高搜索准确度）
    """
    stock_name = name or _get_stock_info(code).get("name", "")
    result = search_news(code, stock_name)
    return json.dumps(result, ensure_ascii=False, default=str)


@mcp.tool(name="get_stock_context")
def get_stock_context(code: str) -> str:
    """获取股票综合数据（一次调用返回所有可用数据）
    Args:
        code: 股票代码。A股示例：600519, 000001  美股示例：AAPL, MSFT  港股示例：HK00700

    使用并行执行同时获取实时行情 + K 线数据，显著减少响应时间。
    """
    tasks = {
        "realtime": lambda: _get_realtime_quote(code),
        "kline": lambda: _get_kline(code, days=120),
    }
    parallel_results = run_parallel(tasks, timeout=20)

    result = {
        "code": code,
        "realtime": parallel_results.get("realtime", {"error": "获取失败"}),
        "kline": parallel_results.get("kline", {"error": "获取失败"}),
        "technical": None,
        "news": None,
    }

    # 技术分析（基于并行获取的 K 线）
    kline_data = result["kline"]
    records = kline_data.get("records", []) if isinstance(kline_data, dict) else []
    if records:
        try:
            result["technical"] = analyze_technical(records, code)
        except Exception as e:
            result["technical"] = {"error": str(e)}

    # 新闻（并行获取）
    news_tasks = {
        "news": lambda: search_news(code, _get_stock_info(code).get("name", "")),
    }
    news_results = run_parallel(news_tasks, timeout=15)
    result["news"] = news_results.get("news", {"error": "获取失败"})

    result["time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return json.dumps(result, ensure_ascii=False, default=str)


@mcp.tool(name="analyze_stock_ai")
def analyze_stock_ai(code: str, name: str = "") -> str:
    """AI 智能分析股票，生成决策仪表盘（含评分、买卖建议、技术面、消息面）
    Args:
        code: 股票代码。A股示例：600519, 000001  美股示例：AAPL, MSFT  港股示例：HK00700
        name: 股票名称（可选）

    并行获取实时行情 + K 线 + 新闻数据，然后调用 LLM 分析。
    """
    import copy

    stock_name = name or _get_stock_info(code).get("name", "")

    # 并行获取独立数据
    tasks = {
        "realtime": lambda: _get_realtime_quote(code),
        "kline": lambda: _get_kline(code, days=120),
        "news": lambda: search_news(code, stock_name or code),
    }
    parallel_results = run_parallel(tasks, timeout=25)

    realtime = parallel_results.get("realtime", {"error": "获取失败"})
    kline = parallel_results.get("kline", {"error": "获取失败"})
    news_data = parallel_results.get("news", {"error": "获取失败"})

    # 技术分析（基于 K 线，非并行可省略—K 线已经并行获取）
    technical = {}
    records = kline.get("records", []) if isinstance(kline, dict) else []
    if records:
        try:
            technical = analyze_technical(records, code)
        except Exception as e:
            technical = {"error": str(e)}

    # 调用 AI 分析
    result = ai_analyze(
        stock_code=code,
        stock_name=stock_name or code,
        realtime_data=realtime,
        kline_data=kline,
        technical_data=technical,
        news_data=news_data,
    )
    return json.dumps(result, ensure_ascii=False, default=str)


if __name__ == "__main__":
    mcp.run()
