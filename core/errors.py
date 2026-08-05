"""统一安全错误处理模块

所有 MCP 工具的异常响应必须使用此模块，禁止直接将 str(e) 放入响应体。
"""

from __future__ import annotations

import functools
import logging
import re
from typing import Any, Callable
from inspect import signature

logger = logging.getLogger("stock-mcp.errors")

# 安全的错误消息模板（对调用方可见）
_SAFE_MESSAGES = {
    "network": "数据源暂时不可用，请稍后重试",
    "parse": "数据格式解析失败",
    "timeout": "请求超时，请稍后重试",
    "default": "服务暂时不可用，请稍后重试",
}

# 敏感信息模式（用于过滤日志中的敏感内容）
_SENSITIVE_PATTERNS = [
    r'api[_-]?key\s*[:=]\s*\S+',
    r'secret\s*[:=]\s*\S+',
    r'token\s*[:=]\s*\S+',
    r'/etc/[\w/]+',
    r'~[/\w]+',
    r'password\s*[:=]\s*\S+',
]


def _sanitize_detail(detail: str) -> str:
    """移除敏感信息后的错误详情"""
    for pattern in _SENSITIVE_PATTERNS:
        detail = re.sub(pattern, '[REDACTED]', detail, flags=re.IGNORECASE)
    return detail


def safe_error(error: BaseException, msg_key: str = "default") -> str:
    """返回安全的错误消息给用户，详细错误记录到日志。

    Args:
        error: 捕获的异常对象
        msg_key: 对应 _SAFE_MESSAGES 的键名

    Returns:
        对调用方安全的通用错误消息
    """
    detail = str(error) if error else "(no details)"
    # 只记录前 200 字符，防止超长日志
    logger.warning("stock-mcp error [%s]: %s", msg_key, _sanitize_detail(detail[:200]))
    return _SAFE_MESSAGES.get(msg_key, _SAFE_MESSAGES["default"])


def safe_response(error: BaseException, msg_key: str = "default", **extra: Any) -> dict[str, Any]:
    """构造安全的 JSON 响应字典。

    Usage:
        return safe_response(e, "network", code=code)
    """
    result = {"error": safe_error(error, msg_key)}
    result.update(extra)
    return result


def secure_tool(func: Callable) -> Callable:
    """装饰器：自动捕获工具函数的异常并返回安全响应。
    
    使用方式：
        @secure_tool
        def my_tool(code: str) -> str:
            ...
    """
    sig = signature(func)
    
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            # 记录详细错误到日志
            logger.error("工具 %s 执行失败: %s", func.__name__, _sanitize_detail(str(e)[:200]))
            # 返回安全错误
            return {"error": safe_error(e, "default")}
    
    # 保留原始签名信息（用于 MCP 工具注册）
    wrapper.__signature__ = sig
    return wrapper


def with_safe_except(msg_key: str = "default"):
    """装饰器工厂：为函数添加安全的异常处理。
    
    可带参数使用：
        @with_safe_except("network")
        def fetch_quote(): ...
    """
    def decorator(func: Callable) -> Callable:
        sig = signature(func)
        
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                logger.error("工具 %s 执行失败 [%s]: %s", 
                           func.__name__, msg_key, _sanitize_detail(str(e)[:200]))
                return {"error": safe_error(e, msg_key)}
        
        wrapper.__signature__ = sig
        return wrapper
    return decorator
