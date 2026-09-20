"""MCP Bearer-token 认证（P0 修复 — security-audit run-1）。

FastMCP 的 transport_security.allowed_hosts/allowed_origins 只是
Host/Origin 头白名单（防 DNS-rebinding / 浏览器 CSRF），不是凭证校验。
http 模式下若不带 token 认证，任何能到达 8902 的主体（含公网 8.208.28.70）
都能调用全部 151 个工具。

本模块提供 :class:`EnvBearerVerifier`：实现 mcp SDK 的 ``TokenVerifier``
protocol（async ``verify_token(token) -> AccessToken | None``），从
环境变量 / .env 文件读取 ``STOCK_MCP_API_KEY``，做恒定时间比对。
仅当 env 中确实设置了非空 key 时才启用认证，避免破坏 stdio / 未配置场景。
"""
from __future__ import annotations

import hmac
import os
import time
from pathlib import Path

from mcp.server.auth.provider import AccessToken, TokenVerifier

_KEY_ENV = "STOCK_MCP_API_KEY"
_CLIENT_ID = "stock-mcp-client"
# token 有效期：MCP 长连接场景，给 24h；过期后客户端需重连换新。
_TTL_SECONDS = 24 * 3600


def _load_api_key() -> str | None:
    """解析 STOCK_MCP_API_KEY：优先进程 env，其次项目根 .env。

    返回 None 表示未配置（认证关闭）；返回空串同样视为未配置。
    """
    key = os.environ.get(_KEY_ENV, "").strip()
    if key:
        return key
    # 兜底：项目根 .env（systemd 未注入 EnvironmentFile 时）
    env_file = Path(__file__).resolve().parent.parent / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line.startswith(_KEY_ENV + "="):
                key = line.split("=", 1)[1].strip().strip('"').strip("'")
                if key:
                    return key
    return None


class EnvBearerVerifier(TokenVerifier):
    """恒定时间比对 Bearer token 与 STOCK_MCP_API_KEY。

    未配置 key 时 ``verify_token`` 一律返回 None（拒绝），
    由调用方在 server.py 中根据是否配置了 key 决定是否传入 verifier。
    """

    def __init__(self, key: str) -> None:
        self._key = key.encode("utf-8")

    async def verify_token(self, token: str) -> AccessToken | None:
        if not token:
            return None
        if not hmac.compare_digest(token.encode("utf-8"), self._key):
            return None
        return AccessToken(
            token=token,
            client_id=_CLIENT_ID,
            scopes=[],
            expires_at=int(time.time()) + _TTL_SECONDS,
            subject="stock-mcp",
        )


def build_token_verifier() -> EnvBearerVerifier | None:
    """若配置了 STOCK_MCP_API_KEY 则返回 verifier，否则 None。"""
    key = _load_api_key()
    if not key:
        return None
    return EnvBearerVerifier(key)
