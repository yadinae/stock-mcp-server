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
    mode = os.environ.get("STOCK_MCP_MODE", "stdio")
    port = int(os.environ.get("STOCK_MCP_PORT", "8902"))
    if mode == "http":
        # streamable HTTP 模式（供 cron 脚本 / Hermes 远程调用）
        import uvicorn
        mcp.settings.host = "0.0.0.0"
        mcp.settings.port = port
        # 允许公网 IP 访问（QwenPaw 通过 8.208.28.70:8902 连接）
        mcp.settings.transport_security.allowed_hosts = ["127.0.0.1:*", "localhost:*", "[::1]:*", "8.208.28.70:*"]
        mcp.settings.transport_security.allowed_origins = ["http://127.0.0.1:*", "http://localhost:*", "http://[::1]:*", "http://8.208.28.70:*"]
        uvicorn.run(mcp.streamable_http_app(), host="0.0.0.0", port=port, log_level="warning")
    else:
        mcp.run()
