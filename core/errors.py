"""
Structured Error Classification — 借鉴 tradingview-mcp (https://github.com/atilaahmettaner/tradingview-mcp) errors.py

所有 MCP 工具的异常响应统一使用此模块。
错误响应格式:
{
    "error": {
        "code": "UPSTREAM_TIMEOUT",
        "message": "数据源暂时不可用",
        "source": "tradingview_ws",
        "retryable": true,
        "context": "tool_name"
    }
}
"""
from __future__ import annotations

import json
import logging
import re
from enum import Enum
from typing import Any, Optional

logger = logging.getLogger("stock-mcp.errors")


# ── Error Codes ────────────────────────────────────────────────────────────

class ErrorCode(str, Enum):
    """错误码分类"""
    # 参数校验
    INVALID_PARAM = "INVALID_PARAM"
    MISSING_PARAM = "MISSING_PARAM"
    # 数据源
    UPSTREAM_TIMEOUT = "UPSTREAM_TIMEOUT"
    UPSTREAM_NETWORK = "UPSTREAM_NETWORK"
    UPSTREAM_RATE_LIMIT = "UPSTREAM_RATE_LIMIT"
    UPSTREAM_UNAVAILABLE = "UPSTREAM_UNAVAILABLE"
    UPSTREAM_REJECTED = "UPSTREAM_REJECTED"
    UPSTREAM_CIRCUIT_OPEN = "UPSTREAM_CIRCUIT_OPEN"
    # 数据
    DATA_NOT_FOUND = "DATA_NOT_FOUND"
    DATA_PARSE_ERROR = "DATA_PARSE_ERROR"
    # LLM
    LLM_ERROR = "LLM_ERROR"
    # 配置
    CONFIG_MISSING = "CONFIG_MISSING"
    # 通用
    UNKNOWN = "UNKNOWN"


# ── Error Envelope ─────────────────────────────────────────────────────────

def make_error(
    code: ErrorCode,
    message: str,
    source: str = "",
    context: str = "",
    retryable: bool = False,
    detail: str = "",
) -> dict[str, Any]:
    """
    构造结构化错误响应。

    Args:
        code: 错误码
        message: 用户可读的错误消息
        source: 数据源名称 (e.g. "tradingview_ws", "eastmoney")
        context: 上下文信息 (e.g. tool name, symbol)
        retryable: 是否可重试
        detail: 内部调试信息 (不会返回给用户)
    """
    error = {
        "code": code.value if isinstance(code, ErrorCode) else code,
        "message": message,
        "retryable": retryable,
    }
    if source:
        error["source"] = source
    if context:
        error["context"] = context
    if detail:
        logger.warning("[stock-mcp] %s detail: %s", code, detail[:200])

    return {"error": error}


def exception_to_error(
    exc: Exception,
    source: str = "",
    context: str = "",
) -> dict[str, Any]:
    """
    将异常转换为结构化错误响应。
    自动分类异常类型 → ErrorCode。
    """
    error_type = type(exc).__name__
    error_msg = str(exc)

    # 分类
    if "timeout" in error_msg.lower() or "timed out" in error_msg.lower():
        code = ErrorCode.UPSTREAM_TIMEOUT
        retryable = True
        msg = "请求超时，请稍后重试"
    elif "connection" in error_msg.lower() or "connect" in error_msg.lower():
        code = ErrorCode.UPSTREAM_NETWORK
        retryable = True
        msg = "网络连接失败"
    elif "429" in error_msg or "rate limit" in error_msg.lower():
        code = ErrorCode.UPSTREAM_RATE_LIMIT
        retryable = True
        msg = "请求频率过高，请稍后重试"
    elif "403" in error_msg or "401" in error_msg:
        code = ErrorCode.UPSTREAM_REJECTED
        retryable = False
        msg = "访问被拒绝"
    elif "404" in error_msg:
        code = ErrorCode.DATA_NOT_FOUND
        retryable = False
        msg = "未找到数据"
    elif "json" in error_msg.lower() or "parse" in error_msg.lower():
        code = ErrorCode.DATA_PARSE_ERROR
        retryable = True
        msg = "数据格式解析失败"
    else:
        code = ErrorCode.UNKNOWN
        retryable = False
        msg = "服务暂时不可用"

    # 记录详细错误
    logger.warning(
        "[stock-mcp] %s (%s) [%s]: %s",
        error_type, code.value, source, error_msg[:200],
    )

    return make_error(code, msg, source=source, context=context, retryable=retryable)


# ── HTTP Status → ErrorCode ────────────────────────────────────────────────

def http_status_error(
    status_code: int,
    source: str = "",
    context: str = "",
    body: str = "",
) -> dict[str, Any]:
    """将 HTTP 状态码转换为结构化错误。"""
    if status_code == 429:
        return make_error(
            ErrorCode.UPSTREAM_RATE_LIMIT,
            "请求频率过高",
            source=source, context=context, retryable=True,
        )
    elif status_code in (502, 503, 504):
        return make_error(
            ErrorCode.UPSTREAM_UNAVAILABLE,
            f"上游服务暂时不可用 (HTTP {status_code})",
            source=source, context=context, retryable=True,
        )
    elif status_code in (401, 403):
        return make_error(
            ErrorCode.UPSTREAM_REJECTED,
            f"访问被拒绝 (HTTP {status_code})",
            source=source, context=context, retryable=False,
        )
    elif status_code == 404:
        return make_error(
            ErrorCode.DATA_NOT_FOUND,
            "未找到数据",
            source=source, context=context, retryable=False,
        )
    else:
        return make_error(
            ErrorCode.UNKNOWN,
            f"HTTP 错误 {status_code}",
            source=source, context=context,
            retryable=500 <= status_code < 600,
            detail=body[:200],
        )


# ── Legacy Compatibility ───────────────────────────────────────────────────

# 保持与旧代码兼容
_SAFE_MESSAGES = {
    "network": "数据源暂时不可用，请稍后重试",
    "parse": "数据格式解析失败",
    "timeout": "请求超时，请稍后重试",
    "default": "服务暂时不可用，请稍后重试",
}

_SENSITIVE_PATTERNS = [
    r'api[_-]?key\s*[:=]\s*\S+',
    r'secret\s*[:=]\s*\S+',
    r'token\s*[:=]\s*\S+',
    r'/etc/[\w/]+',
    r'~[/\w]+',
    r'password\s*[:=]\s*\S+',
]


def _sanitize_detail(detail: str) -> str:
    for pattern in _SENSITIVE_PATTERNS:
        detail = re.sub(pattern, '[REDACTED]', detail, flags=re.IGNORECASE)
    return detail


def safe_error(error: BaseException, msg_key: str = "default") -> str:
    detail = str(error) if error else "(no details)"
    logger.warning("stock-mcp error [%s]: %s", msg_key, _sanitize_detail(detail[:200]))
    return _SAFE_MESSAGES.get(msg_key, _SAFE_MESSAGES["default"])


def safe_response(error: BaseException, msg_key: str = "default", **extra: Any) -> dict[str, Any]:
    result = {"error": safe_error(error, msg_key)}
    result.update(extra)
    return result
