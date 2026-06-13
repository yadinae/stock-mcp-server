"""A股数据源 — mootdx（通达信 TCP 协议直连）

mootdx 走通达信标准 TCP 协议，无需注册、无 API key、无 IP 限流。
作为腾讯 API 的 fallback 源，补充 ETF/指数等腾讯覆盖不全的数据。

依赖：pip install mootdx（已在 Hermes venv 中安装）
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Optional

from core.cache import get_cache, make_cache_key, TTL_REALTIME, TTL_KLINE

logger = logging.getLogger("stock-mcp.mootdx")

# ── 代码转换 ────────────────────────────────────────────────

# mootdx 需要 6 位纯数字代码
# 沪深 A 股（600/601/603/605/000/001/002/003/300/301）
# 科创板（688/689）
# 北交所（4/8 开头，mootdx 不支持）
# ETF/LOF（51/15/16/18 开头）


def _to_mootdx_code(code: str) -> Optional[str]:
    """转换为 mootdx 可识别的 6 位数字代码"""
    c = code.strip().upper().replace(".SH", "").replace(".SZ", "").replace(".BJ", "")
    if c.startswith(("SH", "SZ", "BJ")):
        c = c[2:]
    if c.isdigit() and len(c) == 6:
        return c
    # 带 HK 前缀或字母 -> 非 A 股
    return None


def _is_supported(code: str) -> bool:
    """判断 mootdx 是否支持该代码"""
    c = _to_mootdx_code(code)
    if c is None:
        return False
    # 北交所（4/8 开头）不支持
    if c[0] in ("4", "8"):
        return False
    return True


def _get_client():
    """获取单例 mootdx Quotes 客户端"""
    from mootdx.quotes import Quotes
    return Quotes.factory(market="std")


# ── 实时行情 ────────────────────────────────────────────────

def get_realtime_quote(code: str) -> Optional[dict[str, Any]]:
    """获取单只 A 股实时行情

    Returns:
        dict 或 None（当代码不支持或查询失败时）
    """
    if not _is_supported(code):
        return None

    cache = get_cache()
    key = make_cache_key("mootdx_realtime", code)
    cached = cache.get(key)
    if cached is not None:
        return cached

    try:
        mcode = _to_mootdx_code(code)
        client = _get_client()
        df = client.quotes(symbol=[mcode])
        if df is None or df.empty:
            return None

        row = df.iloc[0]
        price = float(row.get("price", 0))
        pre_close = float(row.get("last_close", 0))
        change_pct = ((price - pre_close) / pre_close * 100) if pre_close else 0

        result = {
            "code": code,
            "name": code,  # mootdx 不返回中文名
            "price": price,
            "pre_close": pre_close,
            "open": float(row.get("open", 0)),
            "high": float(row.get("high", 0)),
            "low": float(row.get("low", 0)),
            "change_pct": round(change_pct, 2),
            "change_amount": round(price - pre_close, 2),
            "volume": int(row.get("volume", 0)),
            "amount": round(float(row.get("amount", 0)) / 10000, 2),  # 元→万元
            "source": "mootdx",
        }
        cache.set(key, result, TTL_REALTIME)
        return result
    except Exception as e:
        logger.warning("mootdx realtime error for %s: %s", code, e)
        return None


def batch_realtime(codes: list[str]) -> list[dict[str, Any]]:
    """批量获取实时行情（单次 TCP 请求）"""
    supported = [c for c in codes if _is_supported(c)]
    if not supported:
        return [{"code": c, "error": "mootdx不支持的代码"} for c in codes]

    cache = get_cache()
    results = {}
    uncached = []

    for c in supported:
        key = make_cache_key("mootdx_realtime", c)
        cached = cache.get(key)
        if cached is not None:
            results[c] = cached
        else:
            uncached.append(c)

    if uncached:
        try:
            mcodes = [_to_mootdx_code(c) for c in uncached]
            client = _get_client()
            df = client.quotes(symbol=mcodes)
            if df is not None and not df.empty:
                for _, row in df.iterrows():
                    raw_code = str(row.get("code", ""))
                    price = float(row.get("price", 0))
                    pre_close = float(row.get("last_close", 0))
                    change_pct = ((price - pre_close) / pre_close * 100) if pre_close else 0
                    result = {
                        "code": raw_code,
                        "name": raw_code,
                        "price": price,
                        "pre_close": pre_close,
                        "open": float(row.get("open", 0)),
                        "high": float(row.get("high", 0)),
                        "low": float(row.get("low", 0)),
                        "change_pct": round(change_pct, 2),
                        "change_amount": round(price - pre_close, 2),
                        "volume": int(row.get("volume", 0)),
                        "amount": round(float(row.get("amount", 0)) / 10000, 2),
                        "source": "mootdx",
                    }
                    key = make_cache_key("mootdx_realtime", raw_code)
                    cache.set(key, result, TTL_REALTIME)
                    results[raw_code] = result
        except Exception as e:
            logger.warning("mootdx batch realtime error: %s", e)

    return [results.get(c, {"code": c, "error": "数据不可用"}) for c in codes]


# ── K 线数据 ────────────────────────────────────────────────

def get_kline(code: str, days: int = 60) -> Optional[dict[str, Any]]:
    """获取 A 股 K 线数据

    mootdx 翻页获取（每页 800 条），最多 25 页 = 20000 条。
    比腾讯 API 的 120 天限制更多，且支持 ETF。
    """
    if not _is_supported(code):
        return None

    cache = get_cache()
    key = make_cache_key("mootdx_kline", code, str(days))
    cached = cache.get(key)
    if cached is not None:
        return cached

    try:
        mcode = _to_mootdx_code(code)
        client = _get_client()

        # 根据 days 计算需要多少条数据（约 250 交易日/年）
        needed = max(days * 2, 60)  # 保险系数 2x
        pages = min((needed // 800) + 1, 25)

        records = []
        for page in range(pages):
            df = client.bars(symbol=mcode, frequency=4, start=page * 800, offset=800)
            if df is None or df.empty:
                break
            # 转成标准格式
            for idx, row in df.iterrows():
                records.append({
                    "date": str(idx.date()),
                    "open": round(float(row.get("open", 0)), 2),
                    "close": round(float(row.get("close", 0)), 2),
                    "high": round(float(row.get("high", 0)), 2),
                    "low": round(float(row.get("low", 0)), 2),
                    "volume": float(row.get("volume", 0)),
                })
            if len(df) < 800:
                break  # 最后一页

        # 按日期正序（mootdx 返回倒序）
        records.reverse()

        # 截取需要的天数
        if len(records) > days * 2:
            records = records[-(days * 2):]

        if records:
            result = {
                "code": code,
                "records": records,
                "count": len(records),
                "source": "mootdx",
            }
            cache.set(key, result, TTL_KLINE)
            return result

        logger.warning("mootdx kline empty for %s", code)
        return None

    except Exception as e:
        logger.warning("mootdx kline error for %s: %s", code, e)
        return None
