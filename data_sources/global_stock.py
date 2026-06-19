"""
美股港股全栈数据模块
===================
整合自 simonlin1212/global-stock-data 项目，覆盖 8 层数据源：
行情/K线/技术指标/基本面(中文三表+关键指标+Yahoo)/资金面/期权/SEC/工具搜索

全部零鉴权，仅依赖 requests。
"""

from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

import httpx

logger = logging.getLogger("stock-mcp.global_stock")

# ── 通用配置 ────────────────────────────────────────────────
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
HTTP_TIMEOUT = 15
DATACENTER_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"
SEC_HEADERS = {"User-Agent": "stock-mcp-server/1.0 (research; contact@stock-analysis.local)"}

# ═══════════════════════════════════════════════════════════
# 行情层
# ═══════════════════════════════════════════════════════════

def us_quote_sina(ticker: str) -> dict[str, Any]:
    """新浪美股实时行情 — 36 字段（含中文名/EPS/PE）
    
    注意：新浪财经接口可能受地域限制，建议优先用腾讯行情。
    """
    return {"error": "新浪美股行情受地域限制不可用，请使用 tencent 或 eastmoney 源"}


def us_quote_tencent(ticker: str) -> dict[str, Any]:
    """腾讯美股行情 — 71 字段（含 PE/PB/市值/52周高低）
    
    Args:
        ticker: 纯字母代码，如 "AAPL"
    
    Returns:
        {name, name_en, price, prev_close, open, high, low, volume,
         high_52w, low_52w, change_pct, market_cap, pe, pb, timestamp}
    """
    url = f"https://qt.gtimg.cn/q=us{ticker.upper()}"
    try:
        resp = httpx.get(url, timeout=HTTP_TIMEOUT)
        resp.encoding = "gbk"
        m = re.search(r'"(.+)"', resp.text)
        if not m:
            return {"error": f"腾讯美股行情未返回数据: {ticker}"}
        fields = m.group(1).split("~")
        if len(fields) < 50:
            return {"error": f"腾讯美股字段不足({len(fields)}): {ticker}"}
        # 腾讯美股字段索引(0-based):
        # 1=中文名, 3=现价, 4=昨收, 5=开盘, 6=成交量(股),
        # 30=时间, 31=涨跌额, 32=涨跌幅%, 33=最高, 34=最低,
        # 35=货币, 36=成交量, 37=成交额, 39=PE, 46=英文名,
        # 48=52周高, 49=52周低, 53=市值(亿), 55=PB
        def _sf(idx):
            v = fields[idx] if idx < len(fields) else ""
            try:
                return float(v)
            except (ValueError, TypeError):
                return 0
        return {
            "source": "tencent",
            "code": ticker.upper(),
            "name": fields[1],
            "name_en": fields[46] if len(fields) > 46 else "",
            "price": _sf(3),
            "prev_close": _sf(4),
            "open": _sf(5),
            "volume": int(fields[6]) if fields[6].isdigit() else 0,
            "high": _sf(33),
            "low": _sf(34),
            "high_52w": _sf(48) if len(fields) > 48 else 0,
            "low_52w": _sf(49) if len(fields) > 49 else 0,
            "change_pct": _sf(32),
            "market_cap": _sf(53) if len(fields) > 53 else 0,
            "pe": _sf(39),
            "pb": _sf(55) if len(fields) > 55 else 0,
            "timestamp": fields[30],
        }
    except Exception as e:
        logger.error("腾讯美股行情失败 %s: %s", ticker, e)
        return {"error": str(e)}


def hk_quote_tencent(code: str) -> dict[str, Any]:
    """腾讯港股行情 — 78 字段（最全）
    
    Args:
        code: 五位数字代码，如 "00700", "09988"
    
    Returns:
        {name, name_en, price, prev_close, open, high, low, volume,
         amount, change_pct, pe, pb, high_52w, low_52w, market_cap, timestamp}
    """
    url = f"https://qt.gtimg.cn/q=r_hk{code}"
    try:
        resp = httpx.get(url, timeout=HTTP_TIMEOUT)
        resp.encoding = "gbk"
        m = re.search(r'"(.+)"', resp.text)
        if not m:
            return {"error": f"腾讯港股行情未返回数据: {code}"}
        fields = m.group(1).split("~")
        if len(fields) < 50:
            return {"error": f"腾讯港股字段不足({len(fields)}): {code}"}
        return {
            "source": "tencent_hk",
            "code": code,
            "name": fields[1],
            "name_en": fields[2],
            "price": float(fields[3]) if fields[3] else 0,
            "prev_close": float(fields[4]) if fields[4] else 0,
            "open": float(fields[5]) if fields[5] else 0,
            "high": float(fields[33]) if fields[33] else 0,
            "low": float(fields[34]) if fields[34] else 0,
            "volume": float(fields[6]) if fields[6] else 0,
            "amount": float(fields[37]) if fields[37] else 0,
            "change_pct": float(fields[32]) if fields[32] else 0,
            "pe": float(fields[39]) if fields[39] else 0,
            "pb": float(fields[56]) if fields[56] else 0,
            "high_52w": float(fields[35]) if fields[35] else 0,
            "low_52w": float(fields[36]) if fields[36] else 0,
            "market_cap": float(fields[44]) if fields[44] else 0,
            "timestamp": fields[30],
        }
    except Exception as e:
        logger.error("腾讯港股行情失败 %s: %s", code, e)
        return {"error": str(e)}


def hk_quote_sina(code: str) -> dict[str, Any]:
    """新浪港股行情 — 25 字段
    
    Args:
        code: 五位数字代码，如 "00700"
    """
    url = f"https://hq.sinajs.cn/list=rt_hk{code}"
    try:
        resp = httpx.get(url, headers={
            "Referer": "https://finance.sina.com.cn/",
            "User-Agent": UA,
        }, timeout=HTTP_TIMEOUT)
        resp.encoding = "gbk"
        m = re.search(r'"(.+)"', resp.text)
        if not m:
            return {"error": f"新浪港股行情未返回数据: {code}"}
        fields = m.group(1).split(",")
        if len(fields) < 15:
            return {"error": f"新浪港股字段不足({len(fields)}): {code}"}
        return {
            "source": "sina_hk",
            "code": code,
            "name_en": fields[0],
            "name": fields[1],
            "open": float(fields[2]) if fields[2] else 0,
            "prev_close": float(fields[3]) if fields[3] else 0,
            "high": float(fields[4]) if fields[4] else 0,
            "low": float(fields[5]) if fields[5] else 0,
            "price": float(fields[6]) if fields[6] else 0,
            "change": float(fields[7]) if fields[7] else 0,
            "change_pct": float(fields[8]) if fields[8] else 0,
            "volume": float(fields[12]) if fields[12] else 0,
            "amount": float(fields[11]) if fields[11] else 0,
        }
    except Exception as e:
        logger.error("新浪港股行情失败 %s: %s", code, e)
        return {"error": str(e)}


def quote_eastmoney(secid: str) -> dict[str, Any]:
    """东财 push2 实时行情 — 美股+港股统一接口
    
    Args:
        secid: "105.AAPL" (NASDAQ) / "106.BABA" (NYSE) / "116.00700" (港股)
    
    Returns:
        {code, name, price, high, low, open, volume, amount, 
         turnover_rate, prev_close, change_pct}
    """
    url = "https://push2.eastmoney.com/api/qt/stock/get"
    params = {
        "secid": secid,
        "fields": "f43,f44,f45,f46,f47,f48,f55,f57,f58,f59,f60,f170",
    }
    try:
        resp = httpx.get(url, params=params, timeout=HTTP_TIMEOUT)
        d = resp.json().get("data")
        if not d:
            return {"error": f"东财行情未返回数据: {secid}"}
        dec = d.get("f59", 3)
        divisor = 10 ** dec
        def _p(key):
            v = d.get(key)
            return round(v / divisor, 2) if v is not None else None
        return {
            "source": "eastmoney",
            "code": d.get("f57"),
            "name": d.get("f58"),
            "price": _p("f43"),
            "high": _p("f44"),
            "low": _p("f45"),
            "open": _p("f46"),
            "volume": d.get("f47"),
            "amount": d.get("f48"),
            "turnover_rate": d.get("f55"),
            "prev_close": _p("f60"),
            "change_pct": round(d["f170"] / 100, 2) if d.get("f170") is not None else None,
        }
    except Exception as e:
        logger.error("东财行情失败 %s: %s", secid, e)
        return {"error": str(e)}


def global_quote(code: str) -> dict[str, Any]:
    """统一美股/港股行情入口（自动选择最优数据源）
    
    Args:
        code: "AAPL" (美股) / "00700" (港股, 5位)
    """
    code = code.strip().upper()
    if code.isalpha() and len(code) <= 5:
        # 美股
        result = us_quote_sina(code)
        if "error" not in result:
            result["_fallback"] = "sina"
            return result
        result = us_quote_tencent(code)
        if "error" not in result:
            result["_fallback"] = "tencent"
            return result
        return {"error": f"行情获取失败: {code}", "code": code}
    elif code.isdigit() and len(code) == 5:
        # 港股
        result = hk_quote_tencent(code)
        if "error" not in result:
            return result
        result = hk_quote_sina(code)
        if "error" not in result:
            result["_fallback"] = "sina"
            return result
        return {"error": f"港股行情获取失败: {code}", "code": code}
    return {"error": f"无法识别的代码格式: {code}"}


# ═══════════════════════════════════════════════════════════
# K线层
# ═══════════════════════════════════════════════════════════

def us_kline_sina(ticker: str, num: int = 120) -> list[dict[str, Any]]:
    """新浪美股日K线 — 可回溯到1984年
    
    Args:
        ticker: 如 "AAPL"
        num: 天数，默认120
    
    Returns:
        [{date, open, high, low, close, volume}, ...]
    """
    url = "https://stock.finance.sina.com.cn/usstock/api/jsonp.php/var/US_MinKService.getDailyK"
    params = {"symbol": ticker.upper(), "num": num}
    try:
        resp = httpx.get(url, params=params, headers={
            "Referer": "https://finance.sina.com.cn/",
        }, timeout=HTTP_TIMEOUT)
        m = re.search(r'\((\[.+?\])\)', resp.text, re.DOTALL)
        if not m:
            return []
        items = json.loads(m.group(1))
        return [{
            "date": item.get("d", ""),
            "open": float(item.get("o", 0)),
            "high": float(item.get("h", 0)),
            "low": float(item.get("l", 0)),
            "close": float(item.get("c", 0)),
            "volume": int(item.get("v", 0)),
        } for item in items]
    except Exception as e:
        logger.error("新浪美股K线失败 %s: %s", ticker, e)
        return []


def kline_yahoo(symbol: str, interval: str = "1d",
                range_: str = "6mo") -> list[dict[str, Any]]:
    """Yahoo Finance chart API — 美股+港股通用，零crumb
    
    Args:
        symbol: "AAPL" (美股) / "0700.HK" (港股)
        interval: "1d", "1wk", "1mo", "5m", "15m", "1h"
        range_: "1d", "5d", "1mo", "3mo", "6mo", "1y", "5y", "max"
    
    Returns:
        [{date, open, high, low, close, volume}, ...]
    """
    url = f"https://query2.finance.yahoo.com/v8/finance/chart/{symbol}"
    params = {"interval": interval, "range": range_}
    try:
        resp = httpx.get(url, params=params, headers={
            "User-Agent": UA,
        }, timeout=HTTP_TIMEOUT)
        resp.raise_for_status()
        d = resp.json()
        chart = d.get("chart", {}).get("result", [{}])[0]
        timestamps = chart.get("timestamp", [])
        quote = chart.get("indicators", {}).get("quote", [{}])[0]

        result = []
        for i, ts in enumerate(timestamps):
            date_str = (
                datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
                if "m" in interval or "h" in interval
                else datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
            )
            result.append({
                "date": date_str,
                "open": round(quote["open"][i], 2) if quote.get("open") and quote["open"][i] else 0,
                "high": round(quote["high"][i], 2) if quote.get("high") and quote["high"][i] else 0,
                "low": round(quote["low"][i], 2) if quote.get("low") and quote["low"][i] else 0,
                "close": round(quote["close"][i], 2) if quote.get("close") and quote["close"][i] else 0,
                "volume": int(quote["volume"][i]) if quote.get("volume") and quote["volume"][i] else 0,
            })
        return result
    except Exception as e:
        logger.error("Yahoo K线失败 %s: %s", symbol, e)
        return []


# ═══════════════════════════════════════════════════════════
# 基本面层 — 东财 datacenter
# ═══════════════════════════════════════════════════════════

def _eastmoney_datacenter(
    report_name: str,
    filter_str: str = "",
    page_size: int = 50,
    sort_columns: str = "",
    sort_types: str = "-1",
) -> list[dict]:
    """东财数据中心统一查询"""
    params = {
        "reportName": report_name, "columns": "ALL",
        "filter": filter_str, "pageNumber": "1", "pageSize": str(page_size),
        "sortColumns": sort_columns, "sortTypes": sort_types,
        "source": "WEB", "client": "WEB",
    }
    try:
        resp = httpx.get(DATACENTER_URL, params=params, headers={
            "User-Agent": UA,
        }, timeout=HTTP_TIMEOUT)
        d = resp.json()
        if d.get("result") and d["result"].get("data"):
            return d["result"]["data"]
        return []
    except Exception as e:
        logger.error("东财数据中心查询失败: %s", e)
        return []


def get_secucode(ticker: str, market: str = "us") -> str:
    """将 ticker 转为东财 datacenter SECUCODE 格式
    
    Args:
        ticker: "AAPL" / "00700"
        market: "us" / "hk"
    
    Returns:
        "AAPL.O" (NASDAQ) / "BABA.N" (NYSE) / "00700.HK" (港股)
    """
    if market == "hk":
        return f"{ticker}.HK"
    # 美股 — 默认 NASDAQ (.O)
    return f"{ticker}.O"


def financial_statements(
    secucode: str, statement: str = "balance",
    page_size: int = 200,
) -> list[dict]:
    """东财 datacenter 财报三表 — 中文科目名，按行展开
    
    Args:
        secucode: "AAPL.O" / "00700.HK"
        statement: "balance" / "income" / "cashflow"
        page_size: 返回行数
    
    Returns:
        [{ITEM_NAME, AMOUNT, YOY_RATIO, REPORT, REPORT_DATE, ...}, ...]
    """
    report_map = {
        "balance": {"us": "RPT_USF10_FN_BALANCE", "hk": "RPT_HKF10_FN_BALANCE"},
        "income":  {"us": "RPT_USF10_FN_INCOME",  "hk": "RPT_HKF10_FN_INCOME"},
        "cashflow": {"us": "RPT_USSK_FN_CASHFLOW", "hk": "RPT_HKSK_FN_CASHFLOW"},
    }
    market = "hk" if secucode.upper().endswith(".HK") else "us"
    report_name = report_map[statement][market]
    return _eastmoney_datacenter(
        report_name=report_name,
        filter_str=f'(SECUCODE="{secucode}")',
        page_size=page_size,
        sort_columns="REPORT_DATE",
        sort_types="-1",
    )


def key_indicators(
    secucode: str, page_size: int = 4,
) -> list[dict]:
    """东财 GMAININDICATOR 关键财务指标（中文）
    
    Args:
        secucode: "AAPL.O" / "00700.HK"
        page_size: 最近几期（默认4期=一年）
    
    美股核心字段: OPERATE_INCOME(营收), GROSS_PROFIT(毛利), 
      GROSS_PROFIT_RATIO(毛利率%), PARENT_HOLDER_NETPROFIT(归母净利),
      BASIC_EPS, ROE_AVG(平均ROE%), ROA(%), CURRENT_RATIO(流动比率),
      DEBT_ASSET_RATIO(资产负债率%)
    """
    market = "hk" if secucode.upper().endswith(".HK") else "us"
    report_name = f"RPT_{'HK' if market == 'hk' else 'US'}F10_FN_GMAININDICATOR"
    return _eastmoney_datacenter(
        report_name=report_name,
        filter_str=f'(SECUCODE="{secucode}")',
        page_size=page_size,
        sort_columns="REPORT_DATE",
        sort_types="-1",
    )


# ═══════════════════════════════════════════════════════════
# Yahoo quoteSummary 模块
# ═══════════════════════════════════════════════════════════

_yahoo_session: Optional[httpx.Client] = None


def _get_yahoo_session() -> httpx.Client:
    """获取带 crumb 的 Yahoo Finance session"""
    global _yahoo_session
    if _yahoo_session is not None:
        return _yahoo_session

    client = httpx.Client(headers={"User-Agent": UA}, timeout=HTTP_TIMEOUT)
    client.get("https://fc.yahoo.com")
    r = client.get("https://query2.finance.yahoo.com/v1/test/getcrumb")
    r.raise_for_status()
    client._crumb = r.text.strip()
    _yahoo_session = client
    return client


def _yahoo_val(d: dict, key: str):
    """提取 Yahoo 嵌套字段的 raw 值"""
    v = d.get(key, {})
    return v.get("raw") if isinstance(v, dict) else v


def yahoo_key_statistics(symbol: str) -> dict[str, Any]:
    """Yahoo 关键财务指标
    
    Args:
        symbol: "AAPL" / "0700.HK"
    
    Returns:
        {current_price, target_mean, trailing_pe, forward_pe, peg_ratio,
         price_to_book, enterprise_value, profit_margin, return_on_equity,
         earnings_growth, revenue_growth, beta, dividend_yield, market_cap, ...}
    """
    try:
        s = _get_yahoo_session()
        r = s.get(
            f"https://query2.finance.yahoo.com/v10/finance/quoteSummary/{symbol}",
            params={
                "modules": "financialData,defaultKeyStatistics,summaryDetail",
                "crumb": s._crumb,
            },
        )
        r.raise_for_status()
        data = r.json().get("quoteSummary", {}).get("result", [{}])[0]
    except Exception as e:
        logger.error("Yahoo key_statistics 失败 %s: %s", symbol, e)
        return {"error": str(e)}

    fd = data.get("financialData", {})
    ks = data.get("defaultKeyStatistics", {})
    sd = data.get("summaryDetail", {})

    return {
        "current_price": _yahoo_val(fd, "currentPrice"),
        "target_high": _yahoo_val(fd, "targetHighPrice"),
        "target_low": _yahoo_val(fd, "targetLowPrice"),
        "target_mean": _yahoo_val(fd, "targetMeanPrice"),
        "recommendation": fd.get("recommendationKey"),
        "trailing_pe": _yahoo_val(sd, "trailingPE"),
        "forward_pe": _yahoo_val(ks, "forwardPE"),
        "peg_ratio": _yahoo_val(ks, "pegRatio"),
        "price_to_book": _yahoo_val(ks, "priceToBook"),
        "enterprise_value": _yahoo_val(ks, "enterpriseValue"),
        "ev_to_ebitda": _yahoo_val(ks, "enterpriseToEbitda"),
        "profit_margin": _yahoo_val(ks, "profitMargins"),
        "operating_margin": _yahoo_val(fd, "operatingMargins"),
        "gross_margin": _yahoo_val(fd, "grossMargins"),
        "return_on_equity": _yahoo_val(fd, "returnOnEquity"),
        "return_on_assets": _yahoo_val(fd, "returnOnAssets"),
        "earnings_growth": _yahoo_val(fd, "earningsGrowth"),
        "revenue_growth": _yahoo_val(fd, "revenueGrowth"),
        "beta": _yahoo_val(ks, "beta"),
        "short_ratio": _yahoo_val(ks, "shortRatio"),
        "dividend_yield": _yahoo_val(sd, "dividendYield"),
        "payout_ratio": _yahoo_val(ks, "payoutRatio"),
        "market_cap": _yahoo_val(sd, "marketCap"),
        "total_revenue": _yahoo_val(fd, "totalRevenue"),
        "total_cash": _yahoo_val(fd, "totalCash"),
        "total_debt": _yahoo_val(fd, "totalDebt"),
    }


def yahoo_institutional_holders(symbol: str) -> dict[str, Any]:
    """Yahoo 机构持仓
    
    Args:
        symbol: "AAPL" / "0700.HK"
    
    Returns:
        {overview: {insiders_pct, institutions_pct, institutions_count},
         top_holders: [{name, shares, value, pct_held}, ...]}
    """
    try:
        s = _get_yahoo_session()
        r = s.get(
            f"https://query2.finance.yahoo.com/v10/finance/quoteSummary/{symbol}",
            params={
                "modules": "institutionOwnership,majorHoldersBreakdown",
                "crumb": s._crumb,
            },
        )
        r.raise_for_status()
        data = r.json().get("quoteSummary", {}).get("result", [{}])[0]
    except Exception as e:
        logger.error("Yahoo 机构持仓失败 %s: %s", symbol, e)
        return {"error": str(e)}

    mhb = data.get("majorHoldersBreakdown", {})
    overview = {
        "insiders_pct": _yahoo_val(mhb, "insidersPercentHeld"),
        "institutions_pct": _yahoo_val(mhb, "institutionsPercentHeld"),
        "institutions_float_pct": _yahoo_val(mhb, "institutionsFloatPercentHeld"),
        "institutions_count": _yahoo_val(mhb, "institutionsCount"),
    }

    io = data.get("institutionOwnership", {}).get("ownershipList", [])
    top_holders = [{
        "name": h.get("organization"),
        "shares": _yahoo_val(h, "position"),
        "value": _yahoo_val(h, "value"),
        "pct_held": _yahoo_val(h, "pctHeld"),
    } for h in io[:10]]

    return {"overview": overview, "top_holders": top_holders}


# ═══════════════════════════════════════════════════════════
# 资金面层 — 东财 push2his
# ═══════════════════════════════════════════════════════════

def fund_flow_daily(secid: str, limit: int = 100) -> list[dict[str, Any]]:
    """东财 push2his 日级资金流 — 主力/大单/中单/小单净流入
    
    Args:
        secid: "105.AAPL" (NASDAQ) / "116.00700" (港股)
        limit: 返回天数
    
    Returns:
        [{date, main_net, small_net, mid_net, big_net, super_big_net, main_pct}, ...]
    """
    url = "https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get"
    params = {
        "secid": secid,
        "klt": 101,
        "fields1": "f1,f2,f3,f7",
        "fields2": "f51,f52,f53,f54,f55,f56,f57",
        "lmt": limit,
    }
    try:
        resp = httpx.get(url, params=params, timeout=HTTP_TIMEOUT)
        d = resp.json()
        data = d.get("data")
        if not data or not data.get("klines"):
            return []
        result = []
        for line in data["klines"]:
            parts = line.split(",")
            result.append({
                "date": parts[0],
                "main_net": float(parts[1]),
                "small_net": float(parts[2]),
                "mid_net": float(parts[3]),
                "big_net": float(parts[4]),
                "super_big_net": float(parts[5]),
                "main_pct": float(parts[6]) if len(parts) > 6 and parts[6] else 0,
            })
        return result
    except Exception as e:
        logger.error("东财资金流失败 %s: %s", secid, e)
        return []


# ═══════════════════════════════════════════════════════════
# 期权层 — Yahoo Finance
# ═══════════════════════════════════════════════════════════

def options_chain(symbol: str, expiration: int = 0) -> dict[str, Any]:
    """Yahoo 期权链 — calls + puts（仅美股）
    
    Args:
        symbol: "AAPL", "TSLA" （港股期权不在Yahoo覆盖范围）
        expiration: Unix timestamp（不传则返回最近到期日）
    
    Returns:
        {expiration_dates, calls: [{strike, last_price, bid, ask, volume, 
         open_interest, implied_volatility, in_the_money}, ...],
         puts: [...], underlying_price}
    """
    try:
        s = _get_yahoo_session()
        params = {"crumb": s._crumb}
        if expiration:
            params["date"] = expiration
        r = s.get(
            f"https://query2.finance.yahoo.com/v7/finance/options/{symbol}",
            params=params,
        )
        r.raise_for_status()
        oc = r.json().get("optionChain", {}).get("result", [{}])[0]
    except Exception as e:
        logger.error("Yahoo 期权链失败 %s: %s", symbol, e)
        return {"error": str(e)}

    exp_dates = oc.get("expirationDates", [])
    options = oc.get("options", [{}])[0] if oc.get("options") else {}

    def _parse(opts):
        ret = []
        for o in opts:
            ret.append({
                "strike": _yahoo_val(o, "strike"),
                "last_price": _yahoo_val(o, "lastPrice"),
                "bid": _yahoo_val(o, "bid"),
                "ask": _yahoo_val(o, "ask"),
                "volume": _yahoo_val(o, "volume"),
                "open_interest": _yahoo_val(o, "openInterest"),
                "implied_volatility": _yahoo_val(o, "impliedVolatility"),
                "in_the_money": o.get("inTheMoney"),
            })
        return ret

    return {
        "expiration_dates": exp_dates,
        "calls": _parse(options.get("calls", [])),
        "puts": _parse(options.get("puts", [])),
        "underlying_price": oc.get("quote", {}).get("regularMarketPrice"),
    }


# ═══════════════════════════════════════════════════════════
# SEC Filing 层（仅美股）
# ═══════════════════════════════════════════════════════════

_cik_cache: Optional[dict] = None


def ticker_to_cik(ticker: str) -> dict[str, str]:
    """SEC ticker → CIK 映射
    
    Args:
        ticker: "AAPL", "TSLA"
    
    Returns:
        {"ticker": "AAPL", "cik": "0000320193", "company": "Apple Inc."}
    """
    global _cik_cache
    if _cik_cache is None:
        try:
            r = httpx.get(
                "https://www.sec.gov/files/company_tickers.json",
                headers=SEC_HEADERS, timeout=HTTP_TIMEOUT,
            )
            r.raise_for_status()
            _cik_cache = r.json()
        except Exception as e:
            logger.error("SEC CIK 映射下载失败: %s", e)
            return {"error": str(e)}

    ticker_upper = ticker.upper()
    for _, v in _cik_cache.items():
        if v.get("ticker") == ticker_upper:
            return {
                "ticker": ticker_upper,
                "cik": str(v["cik_str"]).zfill(10),
                "company": v.get("title"),
            }
    return {"error": f"未找到 ticker: {ticker}"}


def sec_filings(cik: str, form_type: str = "") -> dict[str, Any]:
    """SEC EDGAR Filing 列表
    
    Args:
        cik: CIK号（10位补零），如 "0000320193"
        form_type: "10-K" / "10-Q" / "8-K"（不传返回全部）
    
    Returns:
        {company_name, cik, ticker, filings: [{form, date, url}, ...]}
    """
    url = f"https://data.sec.gov/submissions/CIK{cik}.json"
    try:
        r = httpx.get(url, headers=SEC_HEADERS, timeout=HTTP_TIMEOUT)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        logger.error("SEC Filing 失败 %s: %s", cik, e)
        return {"error": str(e)}

    recent = data.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    dates = recent.get("filingDate", [])
    accessions = recent.get("accessionNumber", [])
    primary_docs = recent.get("primaryDocument", [])

    filings = []
    for i in range(len(forms)):
        if form_type and forms[i] != form_type:
            continue
        doc_url = (
            f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/"
            f"{accessions[i].replace('-', '')}/{primary_docs[i]}"
            if i < len(primary_docs) and primary_docs[i] else ""
        )
        filings.append({
            "form": forms[i],
            "date": dates[i],
            "accession_number": accessions[i],
            "primary_document": primary_docs[i] if i < len(primary_docs) else "",
            "url": doc_url,
        })

    return {
        "company_name": data.get("name"),
        "cik": cik,
        "ticker": data.get("tickers", [""])[0] if data.get("tickers") else "",
        "filings": filings[:50],
        "total": len(filings),
    }


def sec_xbrl_facts(cik: str, metrics: Optional[list[str]] = None) -> dict[str, Any]:
    """SEC EDGAR XBRL 结构化财务数据
    
    Args:
        cik: CIK号（10位补零）
        metrics: 指标名列表。不传则返回可用指标名。
    
    Returns:
        {company, metrics: {name: [{end, val, form, fy}, ...]}}
    """
    url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
    try:
        r = httpx.get(url, headers=SEC_HEADERS, timeout=HTTP_TIMEOUT)
        r.raise_for_status()
        facts = r.json()
    except Exception as e:
        logger.error("SEC XBRL 失败 %s: %s", cik, e)
        return {"error": str(e)}

    us_gaap = facts.get("facts", {}).get("us-gaap", {})

    if not metrics:
        available = [{
            "name": k,
            "label": v.get("label", k),
            "units": list(v.get("units", {}).keys()),
        } for k, v in us_gaap.items()]
        return {
            "company": facts.get("entityName"),
            "total_metrics": len(available),
            "available_metrics": available[:100],
        }

    result = {}
    for metric_name in metrics:
        metric = us_gaap.get(metric_name, {})
        if not metric:
            result[metric_name] = []
            continue
        units = metric.get("units", {})
        unit_key = "USD" if "USD" in units else next(iter(units.keys()), None)
        if not unit_key:
            result[metric_name] = []
            continue
        entries = units[unit_key]
        filtered = [e for e in entries if e.get("form") in ("10-K", "10-Q")]
        result[metric_name] = [{
            "end": e.get("end"),
            "val": e.get("val"),
            "form": e.get("form"),
            "filed": e.get("filed"),
            "fy": e.get("fy"),
            "fp": e.get("fp"),
        } for e in filtered[-20:]]

    return {"company": facts.get("entityName"), "metrics": result}


# ═══════════════════════════════════════════════════════════
# 工具层 — 搜索 / 新闻 / 市场列表
# ═══════════════════════════════════════════════════════════

def stock_search(keyword: str, count: int = 10) -> list[dict[str, Any]]:
    """东财股票搜索 — 支持中英文
    
    Args:
        keyword: "AAPL" / "苹果" / "Tencent" / "00700"
        count: 返回条数
    
    Returns:
        [{code, name, mkt_num, market_name}, ...]
    
    mkt_num 即 secid 前缀: 105=NASDAQ, 106=NYSE, 107=US_OTHER, 116=港股
    """
    url = "https://searchapi.eastmoney.com/api/suggest/get"
    params = {
        "input": keyword,
        "type": 14,
        "token": "D43BF722C8E33BDC906FB84D85E326E8",
        "count": count,
    }
    try:
        r = httpx.get(url, params=params, timeout=HTTP_TIMEOUT)
        suggestions = r.json().get("QuotationCodeTable", {}).get("Data", [])
    except Exception as e:
        logger.error("东财搜索失败: %s", e)
        return []

    market_map = {"105": "NASDAQ", "106": "NYSE", "107": "US_OTHER", "116": "HK"}
    result = []
    for s in suggestions:
        mkt = str(s.get("MktNum", ""))
        if mkt not in market_map:
            continue
        result.append({
            "code": s.get("Code"),
            "name": s.get("Name"),
            "mkt_num": int(mkt),
            "market_name": market_map[mkt],
        })
    return result


def stock_news_yahoo(keyword: str, count: int = 10) -> list[dict[str, Any]]:
    """Yahoo Finance 新闻搜索
    
    Args:
        keyword: 股票代码或关键词，如 "AAPL", "Tesla"
        count: 返回条数
    
    Returns:
        [{title, publisher, link, publish_time}, ...]
    """
    import httpx
    try:
        # 需先获取 cookie
        client = httpx.Client(headers={"User-Agent": UA}, timeout=HTTP_TIMEOUT)
        client.get("https://fc.yahoo.com")
        r = client.get("https://query2.finance.yahoo.com/v1/finance/search", params={
            "q": keyword, "quotesCount": 0, "newsCount": count,
        })
        r.raise_for_status()
        news = r.json().get("news", [])
    except Exception as e:
        logger.error("Yahoo 新闻失败: %s", e)
        return []

    return [{
        "title": n.get("title"),
        "publisher": n.get("publisher"),
        "link": n.get("link"),
        "publish_time": n.get("providerPublishTime"),
    } for n in news]


def market_stock_list(market: str = "us_nasdaq",
                      sort_field: str = "f3",
                      sort_desc: bool = True,
                      page: int = 1,
                      page_size: int = 20) -> dict[str, Any]:
    """东财全市场股票列表 — 涨跌幅/成交量/成交额排名
    
    Args:
        market: "us_nasdaq" / "us_nyse" / "us_etf" / "hk"
        sort_field: f3=涨跌幅, f5=成交量, f6=成交额
        sort_desc: True=降序, False=升序
        page/page_size: 分页
    
    Returns:
        {total, stocks: [{code, name, price, change_pct, volume, amount, ...}, ...]}
    """
    market_map = {
        "us_nasdaq": "m:105", "us_nyse": "m:106",
        "us_etf": "m:107", "hk": "m:116",
    }
    fs = market_map.get(market, market)
    url = "https://push2.eastmoney.com/api/qt/clist/get"
    params = {
        "fs": fs,
        "fields": "f2,f3,f4,f5,f6,f7,f12,f14,f15,f16,f17,f18",
        "pn": page,
        "pz": page_size,
        "fid": sort_field,
        "po": 1 if sort_desc else 0,
    }
    try:
        r = httpx.get(url, params=params, timeout=HTTP_TIMEOUT)
        data = r.json().get("data", {})
    except Exception as e:
        logger.error("东财市场列表失败: %s", e)
        return {"total": 0, "stocks": []}

    total = data.get("total", 0)
    diff = data.get("diff", [])
    stocks = [{
        "code": item.get("f12"),
        "name": item.get("f14"),
        "price": item.get("f2"),
        "change_pct": round(item["f3"] / 100, 2) if item.get("f3") is not None else None,
        "volume": item.get("f5"),
        "amount": item.get("f6"),
        "amplitude": round(item["f7"] / 100, 2) if item.get("f7") is not None else None,
        "high": item.get("f15"),
        "low": item.get("f16"),
        "open": item.get("f17"),
        "prev_close": item.get("f18"),
    } for item in diff]

    return {"total": total, "stocks": stocks}
