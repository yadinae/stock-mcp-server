"""A股数据源 — 腾讯行情 API

封装 _code_type / _code_to_tx_symbol / _tx_realtime / _get_kline 逻辑，
集成 TTL 缓存减少重复 API 调用。
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta
from typing import Any

import httpx

from core.cache import TTLCache, get_cache, make_cache_key
from core.cache import TTL_REALTIME, TTL_KLINE, TTL_STOCK_INFO

logger = logging.getLogger("stock-mcp.tencent")

# ── 常量 ────────────────────────────────────────────────
TX_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://qt.gtimg.cn",
}
KLINE_HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Referer": "https://stock.finance.sina.com.cn",
}
HTTP_TIMEOUT = 15


# ── 代码类型判断 ────────────────────────────────────────

def code_type(code: str) -> str:
    """检测市场类型: a=沪/深, us=美股, hk=港股"""
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


def code_to_tx_symbol(code: str) -> str:
    """转换股票代码为腾讯行情格式"""
    c = code.strip().upper()
    if c.startswith("SH"):
        return f"sh{c[2:]}"
    if c.startswith("SZ"):
        return f"sz{c[2:]}"
    if c.startswith("BJ"):
        return f"bj{c[2:]}"
    if c.startswith("HK"):
        return f"hk{c[2:]}"
    if c.isdigit():
        if c.startswith(("6", "5")):
            return f"sh{c}"
        if c.startswith(("0", "3")):
            return f"sz{c}"
        if c.startswith(("4", "8")):
            return f"bj{c}"
        return f"sh{c}"
    return c


# ── 数据获取（带缓存） ────────────────────────────────

def _fetch_tx_realtime(codes: list[str]) -> list[dict[str, Any]]:
    """从腾讯获取实时行情（内部实现，不缓存）"""
    tx_codes = [code_to_tx_symbol(c) for c in codes]
    url = f"https://qt.gtimg.cn/q={','.join(tx_codes)}"
    try:
        resp = httpx.get(url, headers=TX_HEADERS, timeout=HTTP_TIMEOUT)
        resp.encoding = "gbk"
        return _parse_tx_response(resp.text)
    except Exception as e:
        logger.warning("Tencent API error: %s", e)
        return []


def _parse_tx_response(text: str) -> list[dict[str, Any]]:
    """解析腾讯行情返回文本"""
    results = []
    for line in text.strip().split("\n"):
        line = line.strip()
        if not line or not line.startswith("v_"):
            continue
        try:
            m = re.search(r'\"(.+)\"', line)
            if not m:
                continue
            parts = m.group(1).split("~")
            if len(parts) < 6:
                continue
            price = float(parts[3]) if parts[3] else 0
            pre_close = float(parts[4]) if parts[4] else 0
            open_p = float(parts[5]) if parts[5] else 0
            volume = int(parts[6]) if len(parts) > 6 and parts[6] else 0
            high = float(parts[33]) if len(parts) > 33 and parts[33] else 0
            low = float(parts[34]) if len(parts) > 34 and parts[34] else 0
            change_pct = float(parts[32]) if len(parts) > 32 and parts[32] else 0
            amount = float(parts[37]) if len(parts) > 37 and parts[37] else 0

            change_pct = change_pct / 100 if abs(change_pct) > 10 else change_pct
            change_amount = round(price - pre_close, 2) if pre_close else 0

            results.append({
                "code": parts[2],
                "name": parts[1],
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
            logger.warning("Parse error for %.80s: %s", line, e)
            continue
    return results


def get_realtime_quote(code: str) -> dict[str, Any]:
    """获取单只A股实时行情（带缓存）"""
    cache = get_cache()
    key = make_cache_key("tx_realtime", code)
    cached = cache.get(key)
    if cached is not None:
        return cached

    results = _fetch_tx_realtime([code])
    result = results[0] if results else {"code": code, "error": "无法获取A股行情"}
    cache.set(key, result, TTL_REALTIME)
    return result


def batch_realtime(codes: list[str]) -> list[dict[str, Any]]:
    """批量获取A股实时行情（单次API调用获取全部）"""
    cache = get_cache()

    # 检查缓存，只请求未缓存的部分
    uncached = []
    result_map = {}
    for c in codes:
        key = make_cache_key("tx_realtime", c)
        cached = cache.get(key)
        if cached is not None:
            result_map[c] = cached
        else:
            uncached.append(c)

    if uncached:
        results = _fetch_tx_realtime(uncached)
        for r in results:
            code = r.get("code", "")
            key = make_cache_key("tx_realtime", code)
            cache.set(key, r, TTL_REALTIME)
            result_map[code] = r

    return [result_map.get(c, {"code": c, "error": "未获取到行情"}) for c in codes]


def get_stock_info(code: str) -> dict[str, Any]:
    """获取A股基本信息（带缓存）"""
    cache = get_cache()
    key = make_cache_key("tx_info", code)
    cached = cache.get(key)
    if cached is not None:
        return cached

    quotes = _fetch_tx_realtime([code])
    if quotes:
        q = quotes[0]
        result = {
            "code": code,
            "type": "a",
            "name": q.get("name", ""),
            "price": q.get("price", 0),
            "high": q.get("high", 0),
            "low": q.get("low", 0),
            "volume": q.get("volume", 0),
            "amount": q.get("amount", 0),
            "change_pct": q.get("change_pct", 0),
            "source": "tencent",
        }
    else:
        result = {"code": code, "type": "a", "error": "无法获取信息"}

    cache.set(key, result, TTL_STOCK_INFO)
    return result


def get_kline(code: str, days: int = 60) -> dict[str, Any]:
    """获取A股K线数据（带缓存）"""
    cache = get_cache()
    key = make_cache_key("tx_kline", code, str(days))
    cached = cache.get(key)
    if cached is not None:
        return cached

    tx_code = code_to_tx_symbol(code)
    try:
        url = (
            f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/"
            f"get?param={tx_code},day,,,{days},qfq"
        )
        resp = httpx.get(url, headers=KLINE_HEADERS, timeout=HTTP_TIMEOUT)
        data = resp.json()
        records = _parse_kline_response(data, tx_code)

        if records:
            result = {
                "code": code,
                "records": records,
                "count": len(records),
                "source": "tencent",
            }
            cache.set(key, result, TTL_KLINE)
            return result

        # Fallback
        result = {
            "code": code, "records": [], "count": 0,
            "note": "K线数据获取失败，可使用实时行情替代",
        }
        cache.set(key, result, 60)  # 失败时短缓存
        return result

    except Exception as e:
        logger.warning("Tencent kline error: %s", e)
        return {"code": code, "error": f"A股K线获取失败: {e}"}


def _parse_kline_response(data: dict, tx_code: str) -> list[dict[str, Any]]:
    """解析腾讯 K 线 JSON 响应"""
    records = []
    for row in (
        data.get("data", {}).get(tx_code, {}).get("day", [])
        or data.get("data", {}).get(tx_code, {}).get("qfqday", [])
        or []
    ):
        if len(row) < 6:
            continue
        records.append({
            "date": str(row[0])[:10],
            "open": float(row[1]),
            "close": float(row[2]),
            "high": float(row[3]),
            "low": float(row[4]),
            "volume": float(row[5]) if row[5] else 0,
        })
    return records
