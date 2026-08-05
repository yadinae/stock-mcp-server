#!/usr/bin/env python3
"""
Stock Analysis MCP Server — Phase 3 精简版
==========================================
仅保留通达信(TDX)工具，其他功能已迁移至 Gateway。

剩余工具 (3个):
- get_tdx_company_info: 公司资料
- get_tdx_finance_info: 财务信息  
- get_tdx_xdxr_info: 除权除息
"""

from __future__ import annotations

import json
import logging
import re
import sys
from typing import Any

# ── MCP SDK ──────────────────────────────────────────────────
try:
    from mcp.server.fastmcp import FastMCP
except ImportError:
    print("ERROR: MCP SDK not installed. Run: pip install mcp", file=sys.stderr)
    sys.exit(1)

# ── 内部模块 ──────────────────────────────────────────────────
from core.errors import safe_error
from data_sources import tencent
from data_sources import mootdx

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("stock-mcp")

mcp = FastMCP("stock-mcp")


def _to_mootdx_code(code: str) -> str:
    """转换为 mootdx 格式代码"""
    return mootdx.to_mcode(code)


def _is_supported(code: str) -> bool:
    """检查是否支持 TDX"""
    return mootdx.is_a_share(code)


# ═══════════════════════════════════════════════════════════════
# 通达信 F10 数据工具（仅保留 TDX 相关）
# ═══════════════════════════════════════════════════════════════


@mcp.tool(name="get_tdx_company_info")
def get_tdx_company_info(code: str) -> str:
    """🆕 通达信 F10 公司资料 — 公司简介、股本结构、财务摘要、除权除息

    Args:
        code: 股票代码。A股示例：600519, 000001
    """
    if not _is_supported(code):
        return json.dumps({"error": f"通达信不支持该代码: {code}"}, ensure_ascii=False)

    mcode = _to_mootdx_code(code)
    try:
        from mootdx.quotes import Quotes
        client = Quotes.factory(market="std")
        company_info = client.company_info(mcode)

        if not company_info:
            return json.dumps({"error": "无公司资料数据", "code": code}, ensure_ascii=False)

        result = {
            "code": code,
            "source": "mootdx_tcp",
            "company_info": company_info.to_dict() if hasattr(company_info, 'to_dict') else str(company_info),
        }
        return json.dumps(result, ensure_ascii=False, default=str)
    except Exception as e:
        return json.dumps({"error": safe_error(e, "tdx"), "code": code}, ensure_ascii=False)


@mcp.tool(name="get_tdx_finance_info")
def get_tdx_finance_info(code: str) -> str:
    """🆕 通达信 F10 财务信息 — 盈利能力、成长能力、偿债能力等指标

    Args:
        code: 股票代码。A股示例：600519
    """
    if not _is_supported(code):
        return json.dumps({"error": f"通达信不支持该代码: {code}"}, ensure_ascii=False)

    mcode = _to_mootdx_code(code)
    try:
        from mootdx.finance import Finance
        client = Finance.factory(market="std")
        finance_data = client.finance_analysis(mcode)

        if not finance_data:
            return json.dumps({"error": "无财务数据", "code": code}, ensure_ascii=False)

        result = {
            "code": code,
            "source": "mootdx_tcp",
            "finance": finance_data.to_dict() if hasattr(finance_data, 'to_dict') else str(finance_data),
        }
        return json.dumps(result, ensure_ascii=False, default=str)
    except Exception as e:
        return json.dumps({"error": safe_error(e, "tdx"), "code": code}, ensure_ascii=False)


@mcp.tool(name="get_tdx_xdxr_info")
def get_tdx_xdxr_info(code: str) -> str:
    """🆕 通达信除权除息信息 — 送股、派息、配股历史

    Args:
        code: 股票代码。A股示例：600519
    """
    if not _is_supported(code):
        return json.dumps({"error": f"通达信不支持该代码: {code}"}, ensure_ascii=False)

    mcode = _to_mootdx_code(code)
    try:
        from mootdx.xdxr import Xdxr
        client = Xdxr.factory(market="std")
        xdxr_data = client.xdxr_daily(mcode)

        if not xdxr_data:
            return json.dumps({"error": "无除权除息数据", "code": code}, ensure_ascii=False)

        result = {
            "code": code,
            "source": "mootdx_tcp",
            "records": xdxr_data.to_dict() if hasattr(xdxr_data, 'to_dict') else str(xdxr_data),
            "count": len(xdxr_data) if hasattr(xdxr_data, '__len__') else 0,
        }
        return json.dumps(result, ensure_ascii=False, default=str)
    except Exception as e:
        return json.dumps({"error": safe_error(e, "tdx"), "code": code}, ensure_ascii=False)


# ═══════════════════════════════════════════════════════════════
# 启动入口
# ═══════════════════════════════════════════════════════════════
if __name__ == "__main__":
    import asyncio
    # Use stdio transport by default, or serve via HTTP if bridge enabled
    mcp.run()
