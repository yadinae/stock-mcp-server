"""
AI 审计员 — 只做 veto，不做升级

设计原则（借鉴 WyckoffTradingAgent）：
1. 只能将代码规则准入的候选标记为 VETO
2. 不能将规则未准入的股票加入候选（禁止升级）
3. LLM 不可用时自动 PASS（代码规则已做安全网）
4. VETO 结果必须给出结构化原因

用法:
    auditor = AIAuditor()           # 无 LLM，全 PASS
    auditor = AIAuditor(llm_fn=fn)  # 有 LLM，执行 veto 审计
    decisions = auditor.audit(candidates)
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("stock-mcp.ai_auditor")


@dataclass
class AuditDecision:
    """单个候选的审计结果"""
    code: str
    action: str           # "PASS" | "VETO"
    reason: str
    confidence: float     # 0-1

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "action": self.action,
            "reason": self.reason,
            "confidence": self.confidence,
        }


@dataclass
class AuditResult:
    """审计整体结果"""
    decisions: List[AuditDecision]
    vetoed_count: int = 0
    passed_count: int = 0
    llm_available: bool = False

    def vetoed_codes(self) -> List[str]:
        return [d.code for d in self.decisions if d.action == "VETO"]

    def passed_codes(self) -> List[str]:
        return [d.code for d in self.decisions if d.action == "PASS"]

    def summary(self) -> str:
        return (
            f"Audit: {self.passed_count} PASS, {self.vetoed_count} VETO "
            f"(LLM: {'available' if self.llm_available else 'unavailable'})"
        )


# ── Prompt 模板 ──────────────────────────────────────────

DEFAULT_PROMPT_TEMPLATE = """你是威科夫量价分析审计员。对以下候选执行否决审计。

股票: {code} ({name})
技术面通道: {channels}
成交额: {amount}
价格: {price}

规则：
1. 你只能输出 PASS 或 VETO + 原因
2. 不能将规则未准入的股票加入候选
3. VETO 必须基于：结构已坏、基本面恶化、重大风险、流动性不足
4. 如果信息不足以判断，输出 PASS

输出 JSON: {{"action": "PASS 或 VETO", "reason": "原因", "confidence": 0.0-1.0}}"""


class AIAuditor:
    """
    AI 审计员

    Args:
        llm_fn: LLM 调用函数 (prompt: str) -> str
                 为 None 时所有候选自动 PASS
        prompt_template: 自定义 Prompt 模板
        veto_threshold: VETO 最低置信度（低于此值的 VETO 降级为 PASS）
    """

    def __init__(
        self,
        llm_fn: Optional[Callable[[str], str]] = None,
        prompt_template: Optional[str] = None,
        veto_threshold: float = 0.6,
    ):
        self.llm = llm_fn
        self.template = prompt_template or DEFAULT_PROMPT_TEMPLATE
        self.veto_threshold = veto_threshold

    def audit(
        self,
        candidates: List[dict],
        context: Optional[dict] = None,
    ) -> AuditResult:
        """
        审计候选列表

        Returns:
            AuditResult: 每个候选的审计结果
        """
        if not candidates:
            return AuditResult(decisions=[], llm_available=self.llm is not None)

        # LLM 不可用时自动 PASS
        if self.llm is None:
            logger.info("LLM unavailable, auto-PASS all %d candidates", len(candidates))
            return AuditResult(
                decisions=[
                    AuditDecision(code=c["code"], action="PASS",
                                  reason="LLM unavailable, code rules applied",
                                  confidence=1.0)
                    for c in candidates
                ],
                passed_count=len(candidates),
                llm_available=False,
            )

        decisions = []
        for candidate in candidates:
            try:
                decision = self._audit_one(candidate)
                decisions.append(decision)
            except Exception as e:
                logger.error("Audit failed for %s: %s", candidate.get("code"), e)
                decisions.append(AuditDecision(
                    code=candidate.get("code", "?"),
                    action="PASS",
                    reason=f"Audit error: {e}",
                    confidence=0.5,
                ))

        vetoed = [d for d in decisions if d.action == "VETO"]
        passed = [d for d in decisions if d.action == "PASS"]

        return AuditResult(
            decisions=decisions,
            vetoed_count=len(vetoed),
            passed_count=len(passed),
            llm_available=True,
        )

    def _audit_one(self, candidate: dict) -> AuditDecision:
        """审计单个候选"""
        prompt = self.template.format(
            code=candidate.get("code", ""),
            name=candidate.get("name", ""),
            channels=candidate.get("channels", []),
            amount=candidate.get("amount", "N/A"),
            price=candidate.get("price", "N/A"),
        )

        assert self.llm is not None, "llm_fn must be set before calling _audit_one"
        response = self.llm(prompt)
        return self._parse_response(candidate.get("code", ""), response)

    def _parse_response(self, code: str, response: str) -> AuditDecision:
        """解析 LLM 响应"""
        try:
            text = response.strip()

            # 兼容 markdown code block
            if "```" in text:
                parts = text.split("```")
                if len(parts) >= 2:
                    text = parts[1]
                    if text.startswith("json"):
                        text = text[4:]
                    text = text.strip()

            data = json.loads(text)
            action = data.get("action", "PASS").upper()
            confidence = float(data.get("confidence", 0.8))

            # 置信度低于阈值的 VETO 降级为 PASS
            if action == "VETO" and confidence < self.veto_threshold:
                logger.info(
                    "VETO for %s downgraded to PASS (confidence %.2f < threshold %.2f)",
                    code, confidence, self.veto_threshold,
                )
                action = "PASS"

            return AuditDecision(
                code=code,
                action=action,
                reason=data.get("reason", ""),
                confidence=confidence,
            )
        except (json.JSONDecodeError, ValueError, KeyError) as e:
            logger.warning("Failed to parse audit response for %s: %s", code, e)
            return AuditDecision(
                code=code, action="PASS",
                reason=f"Parse error: {e}", confidence=0.5,
            )
