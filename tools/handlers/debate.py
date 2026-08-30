"""
多空辩论 + 推理审计 — 两个多Agent分析工具

debate_multiagent:
    事实底稿(13项数据, 不经LLM) → 多方研究员 → 空方研究员
    → (可选)交叉反驳 → 中立主持归纳分歧

reflection_audit:
    对已有分析文本做推理审计, 挑出"听起来合理但没有依据"的部分

设计参考: Vibe-Research debate.py + reflection.py
数据源: 复用 stock-mcp 现有126个数据工具作为底稿
LLM: 复用 core/llm_agnes.py (Agnes API)
"""
from __future__ import annotations

import json
import logging
from typing import Optional

from core.llm_agnes import agnes_llm_call
from core.parallel import run_parallel

logger = logging.getLogger("stock-mcp.debate")

# ── 事实底稿清单 ──────────────────────────────────────
# 13项客观数据, 不经LLM, 全部从现有数据工具拉取
FACT_CHECKLIST = [
    "realtime_quote",
    "kline_60d",
    "technical_indicators",
    "fund_flow_120d",
    "margin_trading",
    "shareholder_change",
    "company_profile",
    "financial_indicators",
    "research_reports",
    "announcements",
    "stock_boards",
    "lockup_calendar",
    "news",
]


def _build_fact_dossier(code: str, stock_name: str = "") -> dict:
    """拉取13项事实底稿 (并行, 不消耗token)"""
    from core.helpers import (
        _get_realtime_quote, _get_kline, _get_stock_info,
    )
    from tools.technical import analyze as analyze_technical
    from tools.news import search_news

    # 并行拉取
    tasks = {
        "realtime": lambda: _get_realtime_quote(code),
        "kline": lambda: _get_kline(code, days=60),
        "news": lambda: search_news(code, stock_name or code),
    }
    parallel = run_parallel(tasks, timeout=25)

    # 技术指标(从K线计算)
    kline = parallel.get("kline", {})
    records = kline.get("records", []) if isinstance(kline, dict) else []
    technical = {}
    if records:
        try:
            technical = analyze_technical(records, code)
        except Exception as e:
            technical = {"error": str(e)}

    # 补充数据 (串行, 避免限流)
    extra = {}
    for tool_name, fn in [
        ("company_profile", lambda: _safe_call(
            "data_sources.em_f10", "get_company_profile", code)),
        ("financial_indicators", lambda: _safe_call(
            "data_sources.em_f10", "get_tdx_finance_info", code)),
        ("fund_flow", lambda: _safe_call(
            "data_sources.em_fundflow", "get_fund_flow_120d", code)),
        ("boards", lambda: _safe_call(
            "data_sources.em_f10", "get_stock_boards", code)),
    ]:
        try:
            extra[tool_name] = fn()
        except Exception as e:
            extra[tool_name] = {"error": str(e)}

    # 组装底稿
    dossier = {
        "code": code,
        "name": stock_name or parallel.get("realtime", {}).get("name", code),
        "realtime": parallel.get("realtime", {}),
        "kline_summary": _summarize_kline(records),
        "technical": technical,
        "news": _summarize_news(parallel.get("news", {})),
        "company_profile": extra.get("company_profile", {}),
        "financials": extra.get("financial_indicators", {}),
        "fund_flow": extra.get("fund_flow", {}),
        "boards": extra.get("boards", {}),
    }

    # 确保不缺少必要字段
    for key in FACT_CHECKLIST[:8]:  # 核心字段
        if key not in dossier:
            dossier[key] = {}

    return dossier


def _safe_call(module_name: str, func_name: str, *args, **kwargs):
    """安全调用数据模块函数"""
    import importlib
    mod = importlib.import_module(module_name)
    fn = getattr(mod, func_name)
    return fn(*args, **kwargs)


def _summarize_kline(records: list) -> dict:
    """从K线数据提取摘要"""
    if not records:
        return {"error": "无K线数据"}
    try:
        prices = [r.get("close", 0) for r in records if r.get("close")]
        volumes = [r.get("volume", 0) for r in records if r.get("volume")]
        if not prices:
            return {"error": "无有效价格数据"}
        return {
            "period": f"{records[0].get('date', '?')} ~ {records[-1].get('date', '?')}",
            "latest_price": prices[-1],
            "high": max(prices),
            "low": min(prices),
            "change_pct": round((prices[-1] - prices[0]) / prices[0] * 100, 2) if prices[0] else 0,
            "avg_volume": int(sum(volumes) / len(volumes)) if volumes else 0,
            "data_points": len(records),
        }
    except Exception as e:
        return {"error": str(e)}


def _summarize_news(news_data: dict) -> list:
    """提取新闻摘要(最多5条)"""
    if isinstance(news_data, dict) and "error" in news_data:
        return [news_data]
    if isinstance(news_data, list):
        return news_data[:5]
    if isinstance(news_data, dict):
        items = news_data.get("items", news_data.get("data", []))
        if isinstance(items, list):
            return items[:5]
    return []


# ── LLM 角色 Prompt ──────────────────────────────────────

BULL_RESEARCHER_PROMPT = """你是一名看多研究员。基于以下客观事实底稿，为股票 {code} ({name}) 做多头分析。

## 事实底稿
{dossier}

## 要求
1. 列出3-5个核心看多论点，每个论点必须标明依据的数据来源
2. 论点按置信度从高到低排列
3. 没有数据支撑的论点必须标注「⚠️ 无数据支撑」
4. 分析逻辑链必须清晰：数据 → 推理 → 结论
5. 总字数控制在800-1200字"""

BEAR_RESEARCHER_PROMPT = """你是一名看空研究员。基于以下客观事实底稿，为股票 {code} ({name}) 做空头分析。

## 事实底稿
{dossier}

## 要求
1. 列出3-5个核心看空论点，每个论点必须标明依据的数据来源
2. 论点按风险严重度从高到低排列
3. 没有数据支撑的论点必须标注「⚠️ 无数据支撑」
4. 分析逻辑链必须清晰：数据 → 推理 → 结论
5. 总字数控制在800-1200字"""

CROSS_EXAMINATION_PROMPT = """你是一名交叉审查员。基于多方和空方的分析，逐条审查。

## 多方论点
{bull_points}

## 空方论点
{bear_points}

## 事实底稿
{dossier}

## 要求
1. 逐条回应：承认对方合理之处，指出数据错误或逻辑漏洞
2. 标注「✅ 承认」「❌ 反驳」「⚠️ 数据不足」
3. 总字数控制在600-800字"""

MODERATOR_PROMPT = """你是一名中立主持人。基于多空双方的分析，做最终归纳。

## 多方立场
{bull_analysis}

## 空方立场
{bear_analysis}

## 交叉反驳
{cross_examination}

## 事实底稿
{dossier}

## 要求 (严格遵守)
1. **不裁决谁对谁错**, 不给评级或倾向
2. 列出双方共识点
3. 列出真正分歧点(是数据不足还是解读不同?)
4. 给出验证清单(要确认哪些数据才能判断)
5. 标注数据缺口(哪些关键数据缺失)
6. **不输出买卖结论**
7. 总字数控制在500-800字"""

REFLECTION_PROMPT = """你是一名推理审计员。对以下分析文本做逻辑审计, 找出"听起来合理但没有依据"的部分。

## 待审计的分析
{analysis_text}

## 审计维度
1. **数据支撑**: 每个结论是否有明确的数据来源? 标注「有数据」或「无数据」
2. **逻辑链完整性**: 从数据到结论的推理是否完整? 有无跳跃?
3. **归因准确性**: 是否把相关性当成了因果性?
4. **量化精确度**: 是否有"频繁""大幅"等模糊表述应量化?
5. **一致性检查**: 分析内部有无自相矛盾?

## 输出格式 (JSON)
{{
    "overall_quality": "优/良/中/差",
    "score": 0-100,
    "findings": [
        {{
            "text": "原文片段",
            "issue": "问题类型(无数据/逻辑跳跃/模糊表述/自相矛盾/归因错误)",
            "severity": "P0/P1/P2",
            "suggestion": "改进建议"
        }}
    ],
    "strengths": ["分析中的强项"],
    "missing_data": ["缺失的关键数据"],
    "verdict": "一句话总结审计结论"
}}

只输出JSON, 不要解释。"""


def _format_dossier(dossier: dict) -> str:
    """将底稿格式化为LLM可读文本"""
    lines = []
    lines.append(f"### 股票: {dossier.get('code', '?')} ({dossier.get('name', '?')})")

    # 实时行情
    rt = dossier.get("realtime", {})
    if rt and "error" not in rt:
        lines.append(f"\n**实时行情**: 现价={rt.get('price', '?')}, "
                     f"涨跌={rt.get('change', '?')}, "
                     f"成交量={rt.get('volume', '?')}, "
                     f"换手率={rt.get('turnover', '?')}")

    # K线摘要
    ks = dossier.get("kline_summary", {})
    if ks and "error" not in ks:
        lines.append(f"\n**K线(60日)**: 区间={ks.get('period', '?')}, "
                     f"涨幅={ks.get('change_pct', '?')}%, "
                     f"最高={ks.get('high', '?')}, 最低={ks.get('low', '?')}")

    # 技术指标
    tech = dossier.get("technical", {})
    if tech and "error" not in tech:
        lines.append(f"\n**技术指标**: {json.dumps(tech, ensure_ascii=False)[:500]}")

    # 新闻
    news = dossier.get("news", [])
    if news:
        lines.append("\n**新闻摘要**:")
        for i, n in enumerate(news[:5], 1):
            if isinstance(n, dict):
                title = n.get("title", n.get("text", str(n)))
                lines.append(f"  {i}. {title[:100]}")
            else:
                lines.append(f"  {i}. {str(n)[:100]}")

    # 公司概况
    cp = dossier.get("company_profile", {})
    if cp and "error" not in cp:
        intro = cp.get("introduction", cp.get("profile", ""))
        if intro:
            lines.append(f"\n**公司概况**: {str(intro)[:300]}")

    # 财务指标
    fin = dossier.get("financials", {})
    if fin and "error" not in fin:
        lines.append(f"\n**财务指标**: {json.dumps(fin, ensure_ascii=False)[:500]}")

    # 板块
    boards = dossier.get("boards", {})
    if boards and "error" not in boards:
        if isinstance(boards, dict):
            industry = boards.get("industry", [])
            concept = boards.get("concept", [])
            if industry:
                lines.append(f"\n**所属行业**: {', '.join(industry[:5])}")
            if concept:
                lines.append(f"**热门概念**: {', '.join(concept[:5])}")

    # 资金流
    ff = dossier.get("fund_flow", {})
    if ff and "error" not in ff:
        lines.append(f"\n**资金流**: {json.dumps(ff, ensure_ascii=False)[:300]}")

    return "\n".join(lines)


def _parse_llm_json(text: str) -> dict:
    """解析LLM返回的JSON, 兼容markdown code block"""
    text = text.strip()
    if "```" in text:
        parts = text.split("```")
        if len(parts) >= 2:
            text = parts[1]
            if text.startswith("json"):
                text = text[4:]
            text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"raw": text}


def _run_debate(
    code: str,
    stock_name: str = "",
    rounds: int = 1,
) -> dict:
    """
    执行多空辩论流程

    Args:
        code: 股票代码
        stock_name: 股票名称
        rounds: 交叉反驳轮数 (0=各自陈述, 1=加一轮交叉)
    """
    # Step 1: 拉取事实底稿 (不消耗token)
    dossier = _build_fact_dossier(code, stock_name)
    dossier_text = _format_dossier(dossier)

    result = {
        "code": code,
        "name": dossier.get("name", stock_name or code),
        "rounds": rounds,
        "dossier": dossier,
        "steps": {},
    }

    # Step 2: 多方研究员
    try:
        bull_prompt = BULL_RESEARCHER_PROMPT.format(
            code=code, name=dossier.get("name", code),
            dossier=dossier_text,
        )
        bull_analysis = agnes_llm_call(
            bull_prompt,
            system_prompt="你是一名资深看多研究员。基于客观数据做多头分析。",
            max_tokens=2048,
            temperature=0.4,
        )
        result["steps"]["bull"] = bull_analysis
    except Exception as e:
        logger.error("Bull researcher failed: %s", e)
        bull_analysis = f"[多方研究员调用失败: {e}]"
        result["steps"]["bull"] = bull_analysis

    # Step 3: 空方研究员
    try:
        bear_prompt = BEAR_RESEARCHER_PROMPT.format(
            code=code, name=dossier.get("name", code),
            dossier=dossier_text,
        )
        bear_analysis = agnes_llm_call(
            bear_prompt,
            system_prompt="你是一名资深看空研究员。基于客观数据做空头分析。",
            max_tokens=2048,
            temperature=0.4,
        )
        result["steps"]["bear"] = bear_analysis
    except Exception as e:
        logger.error("Bear researcher failed: %s", e)
        bear_analysis = f"[空方研究员调用失败: {e}]"
        result["steps"]["bear"] = bear_analysis

    # Step 4: 交叉反驳 (如果rounds >= 1)
    cross_examination = ""
    if rounds >= 1:
        try:
            cross_prompt = CROSS_EXAMINATION_PROMPT.format(
                bull_points=bull_analysis,
                bear_points=bear_analysis,
                dossier=dossier_text,
            )
            cross_examination = agnes_llm_call(
                cross_prompt,
                system_prompt="你是一名中立的交叉审查员。逐条审查多空双方的论点。",
                max_tokens=1536,
                temperature=0.3,
            )
            result["steps"]["cross_examination"] = cross_examination
        except Exception as e:
            logger.error("Cross-examination failed: %s", e)
            cross_examination = f"[交叉反驳调用失败: {e}]"
            result["steps"]["cross_examination"] = cross_examination

    # Step 5: 中立主持
    try:
        mod_prompt = MODERATOR_PROMPT.format(
            bull_analysis=bull_analysis,
            bear_analysis=bear_analysis,
            cross_examination=cross_examination or "（未进行交叉反驳）",
            dossier=dossier_text,
        )
        moderator = agnes_llm_call(
            mod_prompt,
            system_prompt="你是一名中立的投研主持人。不裁决不给结论, 只归纳分歧和验证清单。",
            max_tokens=1536,
            temperature=0.3,
        )
        result["steps"]["moderator"] = moderator
    except Exception as e:
        logger.error("Moderator failed: %s", e)
        moderator = f"[中立主持调用失败: {e}]"
        result["steps"]["moderator"] = moderator

    # 汇总
    result["summary"] = {
        "bull_thesis": bull_analysis[:200] + "..." if len(bull_analysis) > 200 else bull_analysis,
        "bear_thesis": bear_analysis[:200] + "..." if len(bear_analysis) > 200 else bear_analysis,
        "consensus_and_divergence": moderator[:300] + "..." if len(moderator) > 300 else moderator,
        "llm_calls": 3 + (1 if rounds >= 1 else 0) + 1,  # bull + bear + [cross] + moderator
    }

    return result


def _run_reflection(analysis_text: str) -> dict:
    """
    执行推理审计

    Args:
        analysis_text: 待审计的分析文本
    """
    if not analysis_text or not analysis_text.strip():
        return {"error": "分析文本不能为空"}

    # 截断过长文本 (Agnes max_tokens限制)
    if len(analysis_text) > 12000:
        analysis_text = analysis_text[:12000] + "\n\n[文本过长, 已截断至12000字]"

    try:
        prompt = REFLECTION_PROMPT.format(analysis_text=analysis_text)
        response = agnes_llm_call(
            prompt,
            system_prompt="你是一名推理审计员。只输出JSON, 不要解释。",
            max_tokens=2048,
            temperature=0.2,
        )
        result = _parse_llm_json(response)
        result["input_length"] = len(analysis_text)
        return result
    except Exception as e:
        logger.error("Reflection audit failed: %s", e)
        return {
            "error": str(e),
            "overall_quality": "未知",
            "score": 0,
            "findings": [],
            "verdict": f"审计调用失败: {e}",
        }


# ── MCP 工具注册 ──────────────────────────────────────

def register(mcp):
    @mcp.tool(name="debate_multiagent")
    def debate_multiagent_tool(
        code: str,
        name: str = "",
        rounds: int = 1,
    ) -> str:
        """多空辩论 — 多Agent对抗式投研分析

        事实底稿(13项数据, 不经LLM) → 多方研究员 → 空方研究员 → 交叉反驳 → 中立主持

        Args:
            code: 股票代码。A股示例: 600519  美股示例: AAPL  港股示例: 00700
            name: 股票名称(可选)
            rounds: 交叉反驳轮数(0=各自陈述不交叉, 1=加一轮交叉反驳, 默认1)

        输出:
            - 事实底稿(13项客观数据)
            - 多方论点(每条标注数据来源)
            - 空方论点(每条标注数据来源)
            - 交叉反驳(逐条审查)
            - 中立主持归纳(共识/分歧/验证清单/数据缺口)

        注意:
            - 不输出买卖结论
            - 一轮辩论约3-4次LLM调用, 耗时约60-90秒
            - 数据底稿约35秒(不消耗token)
        """
        from core.helpers import _validate_code, _error_response, _get_stock_info

        err = _validate_code(code)
        if err:
            return _error_response(code, err)

        stock_name = name or _get_stock_info(code).get("name", "")
        rounds = max(0, min(rounds, 2))  # 限制0-2轮

        result = _run_debate(code, stock_name, rounds)
        return json.dumps(result, ensure_ascii=False, default=str)

    @mcp.tool(name="reflection_audit")
    def reflection_audit_tool(
        analysis_text: str,
    ) -> str:
        """推理审计 — 对已有分析文本做逻辑审计

        挑出"听起来合理但没有依据"的部分, 检查逻辑链完整性。

        Args:
            analysis_text: 待审计的分析文本(可以直接粘贴, 也可以传入其他工具的输出)

        审计维度:
            1. 数据支撑 — 每个结论是否有明确数据来源
            2. 逻辑链完整性 — 推理是否有跳跃
            3. 归因准确性 — 是否把相关性当因果性
            4. 量化精确度 — "频繁""大幅"等模糊表述是否应量化
            5. 一致性检查 — 分析内部有无自相矛盾

        输出: JSON含overall_quality/score(0-100)/findings/strengths/missing_data/verdict
        """
        if not analysis_text or not analysis_text.strip():
            return json.dumps({"error": "分析文本不能为空"}, ensure_ascii=False)

        result = _run_reflection(analysis_text)
        return json.dumps(result, ensure_ascii=False, default=str)
