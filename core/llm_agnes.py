"""
Agnes LLM 适配器 — 为 AI 审计员提供 LLM 调用能力

用法:
    from core.llm_agnes import create_auditor_with_llm
    auditor = create_auditor_with_llm()
    result = auditor.audit(candidates)
"""
from __future__ import annotations

import json
import logging
import os
from typing import Optional

import httpx

logger = logging.getLogger("stock-mcp.llm_agnes")

AGNES_API_URL = "https://apihub.agnes-ai.com/v1/chat/completions"
AGNES_API_KEY = os.environ.get(
    "AGNES_API_KEY",
    "sk-184qqj2TeGnoy7DBjfGSkbJ71nxBDklOXh2HvCzgfDUFyAWO",
)
AGNES_MODEL = "agnes-2.0-flash"


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
        "model": AGNES_MODEL,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }

    try:
        resp = httpx.post(
            AGNES_API_URL,
            json=payload,
            headers={
                "Authorization": f"Bearer {AGNES_API_KEY}",
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
        logger.error("Agnes API HTTP error: %s", e)
        raise
    except Exception as e:
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
