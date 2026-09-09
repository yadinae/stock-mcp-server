"""
LLM 适配器 — 为 AI 审计员/辩论模块提供 LLM 调用能力

配置来源: ~/.hermes/scripts/llm_provider.json（与雪球定时任务共享）
"""
from __future__ import annotations

import json
import logging
import os
from typing import Optional

import httpx

logger = logging.getLogger("stock-mcp.llm_agnes")

_PROVIDER_CONFIG = "/home/admin/.hermes/scripts/llm_provider.json"
_PROVIDER_CONFIG_FALLBACK = "/home/admin/.hermes/scripts/xueqiu_articles/llm_config.json"


def _load_provider() -> dict:
    """加载统一 LLM provider 配置"""
    for path in (_PROVIDER_CONFIG, _PROVIDER_CONFIG_FALLBACK):
        if os.path.exists(path):
            with open(path) as f:
                return json.load(f)
    return {
        "base_url": os.environ.get("LLM_BASE_URL", "https://apihub.agnes-ai.com/v1"),
        "api_key": os.environ.get("AGNES_API_KEY", ""),
        "model": os.environ.get("LLM_MODEL", "agnes-2.0-flash"),
    }


_PROVIDER = _load_provider()
LLM_API_URL = _PROVIDER["base_url"].rstrip("/") + "/chat/completions"
LLM_API_KEY = _PROVIDER.get("api_key", "")
LLM_MODEL = _PROVIDER.get("model", "agnes-2.0-flash")


def agnes_llm_call(
    prompt: str,
    system_prompt: str = "你是威科夫量价分析审计员。只输出 JSON，不要解释。",
    max_tokens: int = 1024,
    temperature: float = 0.3,
) -> str:
    """
    调用 Agnes LLM

    Args:
        prompt: 用户提示
        system_prompt: 系统提示
        max_tokens: 最大输出 token
        temperature: 温度

    Returns:
        LLM 输出文本
    """
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": prompt},
    ]

    payload = {
        "model": LLM_MODEL,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }

    import time as _time
    last_err = None
    for attempt in range(3):
        try:
            resp = httpx.post(
                LLM_API_URL,
                json=payload,
                headers={
                    "Authorization": f"Bearer {LLM_API_KEY}",
                    "Content-Type": "application/json",
                },
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()

            content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            reasoning = data.get("choices", [{}])[0].get("message", {}).get("reasoning_content", "")

            # Agnes 可能把思考过程放在 reasoning_content，实际输出在 content
            # 如果 content 为空，尝试从 reasoning 提取 JSON
            if not content.strip() and reasoning:
                # 尝试从 reasoning 中提取 JSON
                if "{" in reasoning:
                    start = reasoning.index("{")
                    end = reasoning.rindex("}") + 1
                    content = reasoning[start:end]

            return content.strip()

        except httpx.HTTPStatusError as e:
            last_err = e
            if e.response.status_code == 429 and attempt < 2:
                wait = 15 * (attempt + 1)
                logger.warning("Agnes API 429 限流 (第%d次)，等待 %ds 重试...", attempt + 1, wait)
                _time.sleep(wait)
                continue
            logger.error("Agnes API HTTP error: %s", e)
            raise
        except Exception as e:
            last_err = e
            if attempt < 2:
                logger.warning("Agnes API 异常 (%s)，重试...", str(e)[:50])
                _time.sleep(3)
                continue
            logger.error("Agnes API error: %s", e)
            raise


def create_auditor_with_llm(
    veto_threshold: float = 0.6,
    prompt_template: Optional[str] = None,
):
    """
    创建带 LLM 的 AI 审计员

    Args:
        veto_threshold: VETO 最低置信度
        prompt_template: 自定义 Prompt 模板

    Returns:
        AIAuditor 实例
    """
    from core.ai_auditor import AIAuditor

    def llm_fn(prompt: str) -> str:
        return agnes_llm_call(prompt)

    return AIAuditor(
        llm_fn=llm_fn,
        prompt_template=prompt_template,
        veto_threshold=veto_threshold,
    )


def test_agnes_connection() -> dict:
    """测试 Agnes API 连通性"""
    try:
        result = agnes_llm_call("回复 OK 两个字", max_tokens=50)
        return {"status": "ok", "response": result}
    except Exception as e:
        return {"status": "error", "error": str(e)}
