"""美股/港股数据源 — Yahoo Finance

封装 _yf_realtime / _yf_kline 逻辑，
集成 TTL 缓存减少重复 API 调用。
"""

from __future__ import annotations

import logging
from typing import Any

import yfinance as yf

from core.cache import get_cache, make_cache_key
from core.cache import TTL_REALTIME, TTL_KLINE, TTL_STOCK_INFO
from core.health import get_health_tracker

logger = logging.getLogger("stock-mcp.yahoo")


def _detect_market(code: str) -> str:
    """判断市场类型"""
    c = code.strip().upper()
    if c.startswith("HK"):
        return "hk"
    if c.startswith(("SH", "SZ", "BJ")) or c.isdigit():
        return "a"
    return "us"  # 其他字母代码视为美股


def get_realtime_quote(code: str) -> dict[str, Any] | None:
    """获取美股/港股实时行情（带缓存）"""
    cache = get_cache()
    key = make_cache_key("yf_realtime", code)
    cached = cache.get(key)
    if cached is not None:
        return cached

    try:
        ticker = yf.Ticker(code)
        info = ticker.info or {}

        if info.get("currentPrice"):
            price = info["currentPrice"]
            prev = info.get("previousClose", 0) or 0
            result = {
                "code": code,
                "name": info.get("shortName") or info.get("longName") or code,
                "price": float(price),
                "change_pct": round((float(price) - float(prev)) / float(prev) * 100, 2) if prev else 0,
                "change_amount": float(price) - float(prev),
                "volume": info.get("volume") or info.get("regularMarketVolume") or 0,
                "market_cap": info.get("marketCap") or 0,
                "pe": info.get("trailingPE") or 0,
                "source": "yfinance",
            }
            cache.set(key, result, TTL_REALTIME)
            get_health_tracker().record_success("yahoo")
            return result

        # Fallback: use history
        hist = ticker.history(period="5d")
        if hist is not None and not hist.empty:
            price = float(hist["Close"].iloc[-1])
            prev = float(hist["Close"].iloc[-2]) if len(hist) > 1 else price
            result = {
                "code": code,
                "name": info.get("shortName") or info.get("longName") or code,
                "price": price,
                "change_pct": round((price - prev) / prev * 100, 2),
                "change_amount": round(price - prev, 2),
                "volume": int(hist["Volume"].iloc[-1]),
                "source": "yfinance",
            }
            cache.set(key, result, TTL_REALTIME)
            get_health_tracker().record_success("yahoo")
            return result

        get_health_tracker().record_failure("yahoo", "no data")
    except Exception as e:
        logger.warning("Yahoo Finance error for %s: %s", code, e)

    return None


def get_stock_info(code: str) -> dict[str, Any]:
    """获取美股/港股基本信息"""
    result = {"code": code, "type": _detect_market(code)}
    yf_result = get_realtime_quote(code)
    if yf_result:
        result.update(yf_result)
    return result


def get_kline(code: str, days: int = 60) -> dict[str, Any]:
    """获取美股/港股K线数据（带缓存）"""
    cache = get_cache()
    key = make_cache_key("yf_kline", code, str(days))
    cached = cache.get(key)
    if cached is not None:
        return cached

    try:
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
                    "change_pct": round(
                        (row["Close"] - row["Open"]) / row["Open"] * 100, 2
                    ),
                })
            result = {
                "code": code,
                "records": records,
                "count": len(records),
                "source": "yfinance",
            }
            cache.set(key, result, TTL_KLINE)
            get_health_tracker().record_success("yahoo")
            return result

        get_health_tracker().record_failure("yahoo", "kline empty")
    except Exception as e:
        logger.warning("Yahoo kline error for %s: %s", code, e)
        get_health_tracker().record_failure("yahoo", str(e))

    return {"code": code, "error": f"K线获取失败", "records": [], "count": 0}
