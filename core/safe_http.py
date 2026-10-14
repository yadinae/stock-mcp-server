"""
Safe HTTP — urllib 安全包装

提供安全的 HTTP 请求函数，强制校验 URL scheme 白名单（仅 http/https），
防止 SSRF（file:/、gopher:、ftp: 等危险协议）。

与标准库 urllib.request.urlopen 兼容，可直接替换。

用法:
    from core.safe_http import safe_urlopen, safe_request
    
    # 直接替换
    resp = safe_urlopen(url, timeout=15)
    
    # 或分步
    req = safe_request(url, headers={...})
    with safe_urlopen(req, timeout=15) as resp:
        data = resp.read()
"""
from __future__ import annotations

import logging
import os
import ssl
import urllib.error
import urllib.request
from typing import Any, Optional

logger = logging.getLogger("stock-mcp.safe_http")

# 允许的网络协议
ALLOWED_SCHEMES = frozenset({"http", "https"})

# 私有 IP 地址前缀（可选：拦截内网探测）
BLOCKED_HOST_PREFIXES = (
    "127.", "10.", "172.16.", "172.17.", "172.18.", "172.19.",
    "172.20.", "172.21.", "172.22.", "172.23.", "172.24.", "172.25.",
    "172.26.", "172.27.", "172.28.", "172.29.", "172.30.", "172.31.",
    "192.168.", "0.", "::1", "[::1]",
)

# 是否启用内网 IP 拦截（默认关闭，可通过环境变量开启）
_BLOCKS_INTERNAL_IPS = os.environ.get("STOCK_MCP_BLOCK_INTERNAL_IPS", "false").lower() in ("1", "true", "yes")


def _parse_scheme(url: str) -> Optional[str]:
    """从 URL 提取 scheme，失败返回 None"""
    try:
        return url.split("://")[0].lower().strip()
    except (KeyError, ValueError, TypeError, AttributeError):
        return None


def _extract_host(url: str) -> str:
    """从 URL 提取 host 部分"""
    try:
        # Remove scheme
        without_scheme = url.split("://", 1)[-1]
        # Remove auth
        without_auth = without_scheme.split("@", 1)[-1]
        # Remove path/query
        host = without_auth.split("/", 1)[0].split(":", 1)[0].strip()
        # Remove port brackets
        return host.strip("[]")
    except (KeyError, ValueError, TypeError, AttributeError):
        return ""


def _is_safe_url(url: str, check_internal_ip: bool = True) -> tuple[bool, str]:
    """
    校验 URL 安全性。
    Returns: (is_safe, reason)
    """
    scheme = _parse_scheme(url)

    # 1. Scheme 白名单检查
    if scheme not in ALLOWED_SCHEMES:
        return False, f"Blocked scheme: '{scheme}' (allowed: {ALLOWED_SCHEMES})"

    # 2. 空 URL 检查
    if not url or not url.strip():
        return False, "Empty URL"

    # 3. 内网 IP 检查（可选）
    if check_internal_ip and _BLOCKS_INTERNAL_IPS:
        host = _extract_host(url)
        if host:
            for prefix in BLOCKED_HOST_PREFIXES:
                if host.startswith(prefix):
                    return False, f"Blocked internal IP: '{host}'"
            # Handle localhost aliases
            if host in ("localhost", "0.0.0.0", "127.0.0.1"):
                return False, f"Blocked localhost: '{host}'"

    return True, "OK"


def safe_request(
    url: str,
    data: Optional[bytes] = None,
    headers: Optional[dict[str, str]] = None,
    method: Optional[str] = None,
) -> urllib.request.Request:
    """
    安全地构建并返回一个 Request 对象（不发起请求）。
    校验 URL scheme，不符合白名单则抛出 ValueError。
    """
    is_safe, reason = _is_safe_url(url)
    if not is_safe:
        logger.warning(f"[safe_http] Blocked request to {url}: {reason}")
        raise ValueError(f"Unsafe URL: {reason}")

    req = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    return req


def safe_urlopen(
    url: str,
    data: Optional[bytes] = None,
    timeout: float = 15.0,
    headers: Optional[dict[str, str]] = None,
    check_internal_ip: bool = True,
) -> urllib.request.HTTPResponse:
    """
    安全地打开 URL。等价于 urllib.request.urlopen，但强制校验 scheme 白名单。
    
    Args:
        url: 目标 URL
        data: POST 数据
        timeout: 超时秒数
        headers: 请求头
        check_internal_ip: 是否检查内网 IP（可关闭用于测试）
    
    Returns:
        HTTPResponse
    """
    is_safe, reason = _is_safe_url(url, check_internal_ip)
    if not is_safe:
        logger.warning(f"[safe_http] Blocked urlopen to {url}: {reason}")
        raise ValueError(f"Unsafe URL: {reason}")

    req = urllib.request.Request(url, data=data, headers=headers or {})
    
    # SSL 安全配置
    ctx = ssl.create_default_context()
    ctx.check_hostname = True
    ctx.verify_mode = ssl.CERT_REQUIRED
    
    try:
        resp = urllib.request.urlopen(req, timeout=timeout, context=ctx)  # nosec B310 (scheme already validated)
        return resp
    except urllib.error.HTTPError as e:
        logger.warning(f"[safe_http] HTTP error for {url}: {e.code} {e.reason}")
        raise
    except urllib.error.URLError as e:
        logger.warning(f"[safe_http] URL error for {url}: {e.reason}")
        raise
    except (KeyError, ValueError, TypeError, AttributeError) as e:
        logger.warning(f"[safe_http] Request error for {url}: {e}")
        raise


def safe_get(url: str, timeout: float = 15.0, **kwargs) -> dict:
    """
    便捷函数：安全 GET 请求，自动解析 JSON。
    等价于 safe_urlopen 的 JSON 专用版。
    """
    import json as _json
    resp = safe_urlopen(url, timeout=timeout, **kwargs)
    body = resp.read()
    resp.close()
    encoding = kwargs.get("encoding", "utf-8")
    text = body.decode(encoding, errors="replace")
    return _json.loads(text)


# ── 替换现有代码的入口函数 ──────────────────────────────────────────────────

def safe_urlopen_legacy(url: str, timeout: float = 15.0, **kwargs) -> urllib.request.HTTPResponse:
    """
    向后兼容的 safe_urlopen：接受 Request 对象或 URL 字符串。
    用于逐步替换现有代码。
    """
    import urllib.request as _urllib
    if isinstance(url, _urllib.Request):
        # Request 对象，检查其 url 属性
        req = url
        if not _is_safe_url(req.full_url or "")[0]:
            raise ValueError("Unsafe URL in Request")
        ctx = ssl.create_default_context()
        ctx.check_hostname = True
        ctx.verify_mode = ssl.CERT_REQUIRED
        try:
            return _urllib.urlopen(req, timeout=timeout, context=ctx)  # nosec B310 (scheme already validated)
        except (KeyError, ValueError, TypeError, AttributeError) as e:
            logger.warning(f"[safe_http] Legacy urlopen error: {e}")
            raise
    else:
        return safe_urlopen(url, timeout=timeout, **kwargs)
