#!/usr/bin/env python3
"""
Stock Analysis MCP Server
=========================
提供 A股（腾讯行情）+ 美股/港股（Yahoo Finance）实时数据。

工具列表：
- get_realtime_quote: 获取实时行情
- get_kline: 获取历史K线数据
- get_stock_info: 获取股票基本信息
- analyze_stocks: 批量股票分析报告
"""
from __future__ import annotations

import json
import logging
import re
import sys
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import quote

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("stock-mcp")

# ── MCP SDK ──────────────────────────────────────────────────
try:
    from mcp.server.fastmcp import FastMCP
    HAS_FASTMCP = True
except ImportError:
    HAS_FASTMCP = False
    print("ERROR: MCP SDK not installed. Run: pip install mcp", file=sys.stderr)
    sys.exit(1)

# ── Data source helpers ────────────────────────────────────────


def _code_type(code: str) -> str:
    """Detect market: a=沪/深, us=美股, hk=港股"""
    c = code.strip().upper()
    if c.startswith("HK"):
        return "hk"
    if c.startswith(("SH", "SZ", "BJ")):
        return "a"
    if c.isdigit():
        if c.startswith(("6", "5")):
            return "a"  # SH
        if c.startswith(("0", "3")):
            return "a"  # SZ/SZ创业板
        if c.startswith(("4", "8")):
            return "a"  # BJ
        return "a"
    if c.isalpha():
        return "us"
    return "unknown"


def _code_to_tx_symbol(code: str) -> str:
    """Convert stock code to Tencent Finance format."""
    c = code.strip().upper()
    # Already has exchange prefix
    if c.startswith("SH"):
        return f"sh{c[2:]}"
    if c.startswith("SZ"):
        return f"sz{c[2:]}"
    if c.startswith("BJ"):
        return f"bj{c[2:]}"
    if c.startswith("HK"):
        return f"hk{c[2:]}"
    # Pure digits - infer exchange
    if c.isdigit():
        if c.startswith(("6", "5")):
            return f"sh{c}"
        if c.startswith(("0", "3")):
            return f"sz{c}"
        if c.startswith(("4", "8")):
            return f"bj{c}"
        return f"sh{c}"
    return c


def _tx_realtime(codes: list[str]) -> list[dict[str, Any]]:
    """Fetch real-time quotes from Tencent Finance (qt.gtimg.cn)."""
    import httpx

    tx_codes = [_code_to_tx_symbol(c) for c in codes]
    url = f"https://qt.gtimg.cn/q={','.join(tx_codes)}"
    try:
        resp = httpx.get(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://qt.gtimg.cn",
        }, timeout=15)
        resp.encoding = "gbk"
        results = []
        for line in resp.text.strip().split("\n"):
            line = line.strip()
            if not line or not line.startswith("v_"):
                continue
            # Parse Tencent format
            # v_sh600519="1~贵州茅台~600519~1291.91~1279.00~1271.18~50495~24976~25519~..."
            # idx: 0=market,1=name,2=code,3=price,4=pre_close,5=open,...
            # For full format: https://github.com/niudai/stock-data/blob/master/tx.py
            try:
                m = re.search(r'"(.+)"', line)
                if not m:
                    continue
                parts = m.group(1).split("~")
                if len(parts) < 6:
                    continue
                name = parts[1]
                code = parts[2]
                price = float(parts[3]) if parts[3] else 0
                pre_close = float(parts[4]) if parts[4] else 0
                open_p = float(parts[5]) if parts[5] else 0
                volume = int(parts[6]) if len(parts) > 6 and parts[6] else 0
                bid = int(parts[7]) if len(parts) > 7 and parts[7] else 0
                ask = int(parts[8]) if len(parts) > 8 and parts[8] else 0
                high = float(parts[33]) if len(parts) > 33 and parts[33] else 0
                low = float(parts[34]) if len(parts) > 34 and parts[34] else 0
                change_pct = float(parts[32]) if len(parts) > 32 and parts[32] else 0
                amount = float(parts[37]) if len(parts) > 37 and parts[37] else 0

                change_pct = change_pct / 100 if abs(change_pct) > 10 else change_pct
                change_amount = round(price - pre_close, 2) if pre_close else 0

                results.append({
                    "code": code,
                    "name": name,
                    "price": price,
                    "pre_close": pre_close,
                    "open": open_p,
                    "high": high,
                    "low": low,
                    "change_pct": round(change_pct, 2),
                    "change_amount": change_amount,
                    "volume": volume,
                    "amount": round(amount, 2) if amount else 0,
                    "source": "tencent",
                })
            except (ValueError, IndexError) as e:
                logger.warning(f"Parse error for {line[:80]}: {e}")
                continue
        return results
    except Exception as e:
        logger.warning(f"Tencent API error: {e}")
        return []


def _yf_realtime(code: str) -> dict[str, Any] | None:
    """Fetch real-time quote from Yahoo Finance."""
    try:
        import yfinance as yf
        ticker = yf.Ticker(code if code.startswith(("^",)) else code)
        info = ticker.info or {}
        if not info or not info.get("currentPrice"):
            # Try ticker.info alternate
            hist = ticker.history(period="2d")
            if hist is not None and not hist.empty:
                price = float(hist["Close"].iloc[-1])
                prev = float(hist["Close"].iloc[-2]) if len(hist) > 1 else price
                return {
                    "code": code,
                    "name": info.get("shortName") or info.get("longName") or code,
                    "price": price,
                    "change_pct": round((price - prev) / prev * 100, 2),
                    "change_amount": round(price - prev, 2),
                    "volume": int(hist["Volume"].iloc[-1]),
                    "source": "yfinance",
                }
            return None
        price = info.get("currentPrice") or info.get("regularMarketPrice") or 0
        prev = info.get("previousClose") or 0
        change_pct = ((price - prev) / prev * 100) if prev else 0
        return {
            "code": code,
            "name": info.get("shortName") or info.get("longName") or code,
            "price": float(price),
            "change_pct": round(change_pct, 2),
            "change_amount": float(price - prev),
            "volume": info.get("volume") or info.get("regularMarketVolume") or 0,
            "market_cap": info.get("marketCap") or 0,
            "pe": info.get("trailingPE") or 0,
            "source": "yfinance",
        }
    except Exception as e:
        logger.warning(f"Yahoo Finance error for {code}: {e}")
        return None


def _get_realtime_quote(code: str) -> dict[str, Any]:
    """Get real-time quote for any stock code."""
    ctype = _code_type(code)

    if ctype == "a":
        results = _tx_realtime([code])
        if results:
            return results[0]
        return {"code": code, "error": "无法获取A股行情"}

    if ctype in ("us", "hk"):
        result = _yf_realtime(code)
        if result:
            return result
        return {"code": code, "error": f"无法获取{'美股' if ctype == 'us' else '港股'}行情"}

    return {"code": code, "error": f"无法识别股票代码: {code}"}


def _get_kline(code: str, days: int = 60) -> dict[str, Any]:
    """Get historical K-line data."""
    ctype = _code_type(code)

    if ctype == "a":
        # Use Tencent Finance K-line API
        tx_code = _code_to_tx_symbol(code)
        # Mapping: qfq=前复权, hfq=后复权
        import httpx
        try:
            url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={tx_code},day,,,{days},qfq"
            resp = httpx.get(url, headers={
                "User-Agent": "Mozilla/5.0",
                "Referer": "https://stock.finance.sina.com.cn",
            }, timeout=15)
            data = resp.json()
            records = []
            for row in (data.get("data", {}).get(tx_code, {}).get("day", []) or
                        data.get("data", {}).get(tx_code, {}).get("qfqday", []) or []):
                if len(row) < 6:
                    continue
                date_str = row[0]
                open_p = row[1]
                close_p = row[2]
                high_p = row[3]
                low_p = row[4]
                volume = row[5]
                records.append({
                    "date": date_str[:10],
                    "open": float(open_p),
                    "close": float(close_p),
                    "high": float(high_p),
                    "low": float(low_p),
                    "volume": float(volume) if volume else 0,
                })
            if records:
                return {"code": code, "records": records, "count": len(records), "source": "tencent"}
            # Fallback: try to get daily data from single stock endpoint
            url2 = f"https://qt.gtimg.cn/q={tx_code}"
            resp2 = httpx.get(url2, headers={
                "User-Agent": "Mozilla/5.0",
                "Referer": "https://qt.gtimg.cn",
            }, timeout=15)
            resp2.encoding = "gbk"
            # Parse basic data
            return {"code": code, "records": [], "count": 0,
                    "note": "K线数据获取失败，可使用实时行情替代"}
        except Exception as e:
            logger.warning(f"Tencent kline error: {e}")
            return {"code": code, "error": f"A股K线获取失败: {e}"}

    if ctype in ("us", "hk"):
        try:
            import yfinance as yf
            ticker = yf.Ticker(code)
            hist = ticker.history(period=f"{days}d")
            if hist is not None and not hist.empty:
                records = []
                for idx, row in hist.iterrows():
                    records.append({
                        "date": str(idx.date()),
                        "open": round(float(row["Open"]), 2),
                        "close": round(float(row["Close"]), 2),
                        "high": round(float(row["High"]), 2),
                        "low": round(float(row["Low"]), 2),
                        "volume": int(row["Volume"]),
                        "change_pct": round((row["Close"] - row["Open"]) / row["Open"] * 100, 2),
                    })
                return {"code": code, "records": records, "count": len(records), "source": "yfinance"}
        except Exception as e:
            logger.warning(f"Yahoo kline error: {e}")
            return {"code": code, "error": f"K线获取失败: {e}"}

    return {"code": code, "error": f"不支持的市场类型: {ctype}"}


def _get_stock_info(code: str) -> dict[str, Any]:
    """Get stock basic info by combining available data sources."""
    ctype = _code_type(code)
    result = {"code": code, "type": ctype}

    if ctype == "a":
        quotes = _tx_realtime([code])
        if quotes:
            q = quotes[0]
            result.update({
                "name": q.get("name", ""),
                "price": q.get("price", 0),
                "high": q.get("high", 0),
                "low": q.get("low", 0),
                "volume": q.get("volume", 0),
                "amount": q.get("amount", 0),
                "change_pct": q.get("change_pct", 0),
                "source": "tencent",
            })

    if ctype in ("us", "hk"):
        yf_result = _yf_realtime(code)
        if yf_result:
            result.update(yf_result)

    return result


from tools.technical import analyze as _technical_analyze
from tools.news import search_news as _search_news
from tools.analyzer import analyze_stock as _ai_analyze

mcp = FastMCP("stock-mcp")

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

    # Separate A-shares from US/HK
    a_codes = [c for c in codes if _code_type(c) == "a"]
    us_codes = [c for c in codes if _code_type(c) in ("us", "hk")]

    results = []
    if a_codes:
        quotes = _tx_realtime(a_codes)
        results.extend(quotes)
    if us_codes:
        for c in us_codes:
            r = _yf_realtime(c)
            if r:
                results.append(r)

    return json.dumps({"stocks": results, "count": len(results), "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")},
                      ensure_ascii=False, default=str)


@mcp.tool(name="get_technical_analysis")
def get_technical_analysis(code: str) -> str:
    """获取股票技术分析（MA/MACD/RSI/布林带/趋势判断/量价分析）
    Args:
        code: 股票代码。A股示例：600519, 000001  美股示例：AAPL, MSFT  港股示例：HK00700
    """
    # 取足够长的K线用于计算
    kline = _get_kline(code, days=120)
    records = kline.get("records", [])
    if not records:
        return json.dumps({"code": code, "error": kline.get("error", "无K线数据")}, ensure_ascii=False)

    result = _technical_analyze(records)
    result["code"] = code
    return json.dumps(result, ensure_ascii=False, default=str)


@mcp.tool(name="search_stock_news")
def search_stock_news(code: str, name: str = "") -> str:
    """搜索股票相关新闻
    Args:
        code: 股票代码
        name: 股票名称（可选，提供后可提高搜索准确度）
    """
    # 如果没有提供名称，尝试获取
    stock_name = name
    if not stock_name:
        info = _get_stock_info(code)
        stock_name = info.get("name", "")
    result = _search_news(code, stock_name)
    return json.dumps(result, ensure_ascii=False, default=str)


@mcp.tool(name="get_stock_context")
def get_stock_context(code: str) -> str:
    """获取股票综合数据（一次调用返回所有可用数据）
    Args:
        code: 股票代码。A股示例：600519, 000001  美股示例：AAPL, MSFT  港股示例：HK00700
    """
    result = {
        "code": code,
        "realtime": _get_realtime_quote(code),
        "info": _get_stock_info(code),
        "kline": _get_kline(code, days=120),
        "technical": None,
        "news": None,
    }
    # 技术分析
    kline = result["kline"]
    records = kline.get("records", []) if isinstance(kline, dict) else []
    if records:
        try:
            result["technical"] = _technical_analyze(records)
        except Exception as e:
            result["technical"] = {"error": str(e)}
    # 新闻
    try:
        info = result["info"]
        stock_name = info.get("name", "") if isinstance(info, dict) else ""
        result["news"] = _search_news(code, stock_name)
    except Exception as e:
        result["news"] = {"error": str(e)}
    result["time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return json.dumps(result, ensure_ascii=False, default=str)


@mcp.tool(name="analyze_stock_ai")
def analyze_stock_ai(code: str, name: str = "") -> str:
    """AI 智能分析股票，生成决策仪表盘（含评分、买卖建议、技术面、消息面）
    Args:
        code: 股票代码。A股示例：600519, 000001  美股示例：AAPL, MSFT  港股示例：HK00700
        name: 股票名称（可选）
    """
    # 收集所有数据
    stock_name = name
    if not stock_name:
        info = _get_stock_info(code)
        stock_name = info.get("name", "") if isinstance(info, dict) else ""

    realtime = _get_realtime_quote(code)
    kline = _get_kline(code, days=120)

    # 技术分析
    technical = {}
    records = kline.get("records", []) if isinstance(kline, dict) else []
    if records:
        try:
            technical = _technical_analyze(records)
        except Exception as e:
            technical = {"error": str(e)}

    # 新闻
    news = {}
    try:
        news = _search_news(code, stock_name or code)
    except Exception as e:
        news = {"error": str(e)}

    result = _ai_analyze(
        stock_code=code,
        stock_name=stock_name or code,
        realtime_data=realtime,
        kline_data=kline,
        technical_data=technical,
        news_data=news,
    )
    return json.dumps(result, ensure_ascii=False, default=str)


if __name__ == "__main__":
    mcp.run()
