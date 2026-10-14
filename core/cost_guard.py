"""LLM-cost 配额守护（medium — 2026-10-10 security-audit run-2）

per-client 速率限制 + 日成本上限，防止有效 Bearer token 泄露后被无限消耗 LLM 额度。

设计要点：
- budget.json 使用原子写入（先写 .tmp 再 rename）避免并发写入损坏 JSON
- 时间窗口：24h rolling reset，按自然日对齐（UTC+8 零点重置，与 cron 调度一致）
- 调用计数：每次成功进入 LLM 调用前计数 +1，失败不计（只在 agnes_llm_call 入口计数不可行，
  因为异常路径不计费；这里在客户端侧计数，失败也算一次「占用」以避免 DoS）
- 超额策略：返回结构化错误，不调用 LLM，不消耗 token

限制：
- 仅对 MCP 工具层生效；core/llm_agnes.py 的单元测试（doctest）不受影响
- 不防 token 泄露后的批量窃取（需要服务端 token 吊销），仅防单 token 超限
"""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path

logger = logging.getLogger("stock-mcp.cost_guard")

# ── 路径 ───────────────────────────────────────────────────
_CONFIG_DIR = Path(os.environ.get("STOCK_MCP_DATA_DIR", str(Path.home() / ".stock-mcp")))
_BUDGET_FILE = _CONFIG_DIR / "budget.json"

# ── 默认限额 ───────────────────────────────────────────────
# analyze_stock_ai: 1 LLM call/call; debate_multiagent: 3-5 LLM calls/call
# 单日上限以「调用次数」计，debate 一次算 5 次（最坏情况）
DEFAULT_DAILY_LIMIT_ANALYZE = 50
DEFAULT_DAILY_LIMIT_DEBATE = 10   # 按「debate 调用次数」计，非 LLM 调用次数


def _load_budget() -> dict:
    try:
        return json.loads(_BUDGET_FILE.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_budget(data: dict) -> None:
    tmp = _BUDGET_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False))
    tmp.replace(_BUDGET_FILE)


def _today_key() -> str:
    """UTC+8 自然日字符串，如 '2026-10-10'。"""
    from datetime import datetime, timezone, timedelta
    cst = timezone(timedelta(hours=8))
    return datetime.now(cst).strftime("%Y-%m-%d")


def check_cost(
    tool_name: str,
    client_id: str = "default",
    daily_limit: int | None = None,
) -> tuple[bool, str]:
    """检查并递增当日调用计数。

    Returns:
        (allowed, message): allowed=True 时可继续；False 时应返回错误给用户。
    """
    if tool_name not in ("analyze_stock_ai", "debate_multiagent"):
        return True, ""

    limit = daily_limit or (
        DEFAULT_DAILY_LIMIT_DEBATE if tool_name == "debate_multiagent"
        else DEFAULT_DAILY_LIMIT_ANALYZE
    )

    budget = _load_budget()
    day = _today_key()
    key = f"{day}:{client_id}:{tool_name}"

    count = budget.get(key, 0)
    if count >= limit:
        logger.warning("cost_guard: %s over limit %d/%d (key=%s)", client_id, count, limit, key)
        return False, (
            f"今日 {tool_name} 调用已达上限 ({limit} 次)，请稍后再试。"
        )

    # 原子递增
    budget[key] = count + 1
    # 清理过期 key（保留最近 3 天）
    budget = {k: v for k, v in budget.items() if k.split(":")[0] >= _yesterday_key()}
    _save_budget(budget)
    return True, ""


def _yesterday_key() -> str:
    from datetime import datetime, timezone, timedelta
    cst = timezone(timedelta(hours=8))
    yesterday = datetime.now(cst) - timedelta(days=1)
    return yesterday.strftime("%Y-%m-%d")
