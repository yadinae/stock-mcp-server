"""
Shared helper functions for MCP tool handlers.

Extracted from server.py to break circular imports between
server.py → tools/handlers/*.py → server.py.
"""
from __future__ import annotations

import json
import re
from typing import Any

from data_sources import tencent, yahoo

# ── Stock code validation ──────────────────────────────────

_STOCK_CODE_RE = re.compile(r"^[A-Za-z0-9]{2,10}$")


def _validate_code(code: str) -> str | None:
    """验证股票代码格式，返回错误信息或 None"""
    if not code or not code.strip():
        return "股票代码不能为空"
    c = code.strip()
    if not _STOCK_CODE_RE.match(c):
        return f"股票代码格式异常: {code}"
    return None


def _validate_days(days: int) -> str | None:
    """验证天数参数"""
    if not isinstance(days, int) or days < 1:
        return "天数必须 >= 1"
    if days > 730:
        return "天数不能超过 730（2年）"
    return None


def _error_response(code: str, message: str, error_type: str = "validation_error") -> str:
    """生成统一格式的错误响应"""
    return json.dumps({
        "code": code,
        "error": message,
        "error_type": error_type,
        "success": False,
    }, ensure_ascii=False)


# ── Code type detection ────────────────────────────────────

def _code_type(code: str) -> str:
    """Detect market: a=沪/深, us=美股, hk=港股"""
    return tencent.code_type(code)


# ── Realtime quote helpers ─────────────────────────────────

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


def _safe_quote(code: str) -> dict:
    """安全获取行情（供 watchlist_brief 使用），失败返回最小结构"""
    try:
        q = tencent.get_realtime_quote(code)
        return {
            "code": code,
            "name": q.get("name") or code,
            "price": q.get("price") or 0,
            "change_pct": q.get("change_pct") or 0,
            "source": q.get("source") or "",
        }
    except Exception:
        return {"code": code, "name": code, "price": 0, "change_pct": 0}


# ── secid helpers ──────────────────────────────────────────

def _code_to_secid(code: str) -> str:
    """将代码转为东财 secid 格式"""
    c = code.strip().upper()
    if c.isalpha() and len(c) <= 5:
        return f"105.{c}"  # 默认 NASDAQ
    if c.isdigit() and len(c) == 5:
        return f"116.{c}"  # 港股
    return ""


def _detect_secid_prefix(code: str) -> int:
    """自动检测 secid 前缀"""
    c = code.strip().upper()
    if c.isalpha() and len(c) <= 5:
        return 105  # NASDAQ
    if c.isdigit() and len(c) == 5:
        return 116  # 港股
    return 105
