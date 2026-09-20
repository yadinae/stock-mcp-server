#!/usr/bin/env python3
"""
Stock Analysis MCP Server
=========================
基于 FastMCP 的股票分析 MCP 服务端。

架构：
  - server.py      本文件，初始化 + 自动注册（<200行）
  - core/helpers.py 共享 helper（校验/行情/代码转换）
  - core/cache.py   TTL 缓存
  - core/parallel.py 并行执行
  - core/store.py   本地 SQLite（交易日志/观察清单）
  - core/health.py  数据源健康追踪
  - tools/registry.py 自动发现注册
  - tools/handlers/*.py  110 个工具 handler（按功能分组）
  - data_sources/*.py  数据源模块
  - webhook/*.py  告警推送
"""
from __future__ import annotations

import logging
import sys
from datetime import datetime

# ── MCP SDK ──────────────────────────────────────────────────
try:
    from mcp.server.fastmcp import FastMCP
except ImportError:
    print("ERROR: MCP SDK not installed. Run: pip install mcp", file=sys.stderr)
    sys.exit(1)

# ── 日志 ──────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("stock-mcp")

# ── FastMCP 实例 ─────────────────────────────────────────────
mcp = FastMCP("stock-mcp")

# ── 自动注册所有工具 handler ──────────────────────────────────
from tools.registry import auto_register
auto_register(mcp)

# ── 启动 ──────────────────────────────────────────────────────
if __name__ == "__main__":
    import os
    from core.mcp_auth import build_token_verifier

    mode = os.environ.get("STOCK_MCP_MODE", "stdio")
    port = int(os.environ.get("STOCK_MCP_PORT", "8902"))
    if mode == "http":
        # streamable HTTP 模式（供 cron 脚本 / Hermes 远程调用）
        import uvicorn
        # P0 修复：http 模式必须携带 Bearer token 认证（STOCK_MCP_API_KEY）。
        # 未配置 key 时直接拒绝启动，避免退回"零认证"状态。
        verifier = build_token_verifier()
        if verifier is None:
            logger.error("STOCK_MCP_API_KEY 未设置，http 模式拒绝启动（避免零认证暴露）")
            sys.exit(2)
        # 默认仅监听回环；确需远程（如 QwenPaw）时通过 STOCK_MCP_HOST 显式放开，
        # 且必须配合 token 认证（verifier 已强制）。
        host = os.environ.get("STOCK_MCP_HOST", "127.0.0.1")
        mcp.settings.host = host
        mcp.settings.port = port
        mcp.settings.transport_security.allowed_hosts = [
            "127.0.0.1:*", "localhost:*", "[::1]:*",
        ]
        mcp.settings.transport_security.allowed_origins = [
            "http://127.0.0.1:*", "http://localhost:*", "http://[::1]:*",
        ]
        # 注入 FastMCP auth 中间件所需的 token verifier。
        # streamable_http_app() 仅当 self.settings.auth 非 None 时挂载 auth 中间件，
        # 因此必须给 settings.auth 赋 AuthSettings 实例（issuer_url 等保持 None，
        # 仅启用 token_verifier 路径）。
        from mcp.server.auth.settings import AuthSettings
        mcp._token_verifier = verifier
        # AuthSettings.issuer_url/resource_server_url 是必填 URL 字段，
        # 纯 token-verifier 场景用占位 URL 满足 pydantic，实际不走 OAuth 发现流程。
        _placeholder = f"http://{host if host != '0.0.0.0' else '127.0.0.1'}:{port}"
        mcp.settings.auth = AuthSettings(
            issuer_url=_placeholder, resource_server_url=_placeholder,
            required_scopes=[],
        )
        app = mcp.streamable_http_app()
        uvicorn.run(app, host=host, port=port, log_level="warning")
    else:
        mcp.run()
