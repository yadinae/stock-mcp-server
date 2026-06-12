"""
AI 股票分析模块
================
从 daily_stock_analysis 抄逻辑：调用 LLM 生成决策仪表盘分析报告
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Optional

import yaml

logger = logging.getLogger("stock-mcp.analyzer")

# ── 从原仓库抄的 SYSTEM_PROMPT（精简版，保留核心框架）──
SYSTEM_PROMPT = """你是一位专业的投资分析师，负责生成【决策仪表盘】分析报告。

## 输出格式：决策仪表盘 JSON

请严格按照以下 JSON 格式输出：

{
    "stock_name": "股票中文名称",
    "sentiment_score": 0-100整数,
    "trend_prediction": "强烈看多/看多/震荡/看空/强烈看空",
    "operation_advice": "买入/加仓/持有/减仓/卖出/观望",
    "confidence_level": "高/中/低",

    "dashboard": {
        "core_conclusion": {
            "one_sentence": "一句话核心结论（30字以内）",
            "signal_type": "买入信号/持有观望/卖出信号/风险警告",
            "position_advice": {
                "no_position": "空仓者建议",
                "has_position": "持仓者建议"
            }
        },
        "data_perspective": {
            "trend_status": {
                "ma_alignment": "均线排列状态描述",
                "is_bullish": true/false,
                "trend_score": 0-100
            },
            "price_position": {
                "current_price": 当前价格,
                "ma5": MA5数值,
                "ma10": MA10数值,
                "ma20": MA20数值,
                "bias_ma5": 乖离率,
                "bias_status": "安全/警戒/危险",
                "support_level": "支撑位",
                "resistance_level": "压力位"
            },
            "volume_analysis": {
                "volume_ratio": 量比,
                "volume_status": "放量/缩量/平量",
                "turnover_rate": 换手率,
                "volume_meaning": "量能含义解读"
            }
        },
        "intelligence": {
            "latest_news": "近期重要新闻摘要",
            "risk_alerts": ["风险点1", "风险点2"],
            "positive_catalysts": ["利好1", "利好2"],
            "sentiment_summary": "舆情情绪总结"
        },
        "battle_plan": {
            "sniper_points": {
                "ideal_buy": "理想入场位",
                "secondary_buy": "次优入场位",
                "stop_loss": "止损位",
                "take_profit": "目标位"
            },
            "position_strategy": {
                "suggested_position": "建议仓位",
                "entry_plan": "分批建仓策略",
                "risk_control": "风控策略"
            },
            "action_checklist": [
                "检查项1",
                "检查项2"
            ]
        }
    },

    "analysis_summary": "100字综合分析摘要",
    "key_points": "3-5个核心看点",
    "risk_warning": "风险提示",
    "buy_reason": "操作理由",

    "technical_analysis": "技术面综合分析",
    "ma_analysis": "均线系统分析",
    "volume_analysis": "量能分析",
    "news_summary": "新闻摘要"
}

## 评分参考

- 强烈买入/看多 (80-100): 多头排列 MA5>MA10>MA20 + 低乖离率 + 量能配合 + 利好催化
- 买入/看多 (60-79): 多头排列或弱势多头 + 乖离率 <5% + 量能正常
- 观望/震荡 (40-59): 乖离率 >5% + 均线缠绕 + 有风险事件
- 卖出/看空 (0-39): 空头排列 + 跌破MA20 + 放量下跌 + 重大利空

## 原则
1. 核心结论先行，一句话说清
2. 分持仓建议
3. 给出具体价格点位
4. 风险点要醒目标出
"""


def _get_llm_client() -> tuple[Any, Optional[str]]:
    """从环境变量创建 LLM 客户端，返回 (client, error)"""
    base_url = os.environ.get("STOCK_LLM_BASE_URL", "")
    api_key = os.environ.get("STOCK_LLM_API_KEY", "")

    if not api_key:
        # Fallback to Hermes config's main provider
        try:
            hermes_home = os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes"))
            config_path = os.path.join(hermes_home, "config.yaml")
            if os.path.exists(config_path):
                with open(config_path) as f:
                    data = yaml.safe_load(f) or {}
                # 直接用主模型的 provider 配置
                provider_name = data.get("model", {}).get("provider", "")
                providers = data.get("providers", {}) or {}
                if provider_name and provider_name in providers:
                    p = providers[provider_name]
                    if p.get("api_key"):
                        base_url = p.get("base_url", base_url)
                        api_key = p.get("api_key", api_key)
                # 如果主 provider 没 key，遍历所有 provider 找第一个有 key 的
                if not api_key:
                    preferred = ["deepseek", "openai", "openrouter", "anthropic", "gemini",
                                 "siliconflow", "aihubmix", "opencode-go"]
                    for name in preferred:
                        p = providers.get(name, {})
                        if p and p.get("api_key"):
                            api_key = p["api_key"]
                            base_url = p.get("base_url", base_url) or base_url
                            logger.info(f"使用 LLM 提供商: {name}")
                            break
        except Exception as e:
            logger.warning("读取 Hermes config 失败: %s", e)

    if not api_key:
        return None, "未配置 LLM API Key（设置 STOCK_LLM_API_KEY 环境变量）"

    try:
        from openai import OpenAI
        client = OpenAI(base_url=base_url or None, api_key=api_key, timeout=60)
        return client, None
    except Exception as e:
        return None, f"LLM 客户端初始化失败: {e}"


def get_llm_model() -> str:
    """获取 LLM 模型名"""
    model = os.environ.get("STOCK_LLM_MODEL", os.environ.get("LLM_MODEL", ""))
    if model:
        return model
    # Fallback to Hermes config
    try:
        hermes_home = os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes"))
        config_path = os.path.join(hermes_home, "config.yaml")
        if os.path.exists(config_path):
            with open(config_path) as f:
                data = yaml.safe_load(f) or {}
            # Try deepseek first
            providers = data.get("providers", {}) or {}
            if "deepseek" in providers and providers["deepseek"].get("model"):
                return providers["deepseek"]["model"]
            # Fallback to default model
            return data.get("model", {}).get("default", "gpt-4o-mini")
    except Exception:
        pass
    return "gpt-4o-mini"


def _sanitize_prompt_text(text: str) -> str:
    """对外部数据做转义，防止 prompt injection"""
    # 去除花括号、反引号、换行等可能破坏 prompt 边界的字符
    text = text.replace("{", "(").replace("}", ")")
    text = text.replace("`", "'").replace("|", "/")
    text = re.sub(r'\s+', ' ', text).strip()
    return text[:200]  # 限制长度


def _safe_get(records: list[dict], key: str, idx: int, default: Any = 0) -> Any:
    """安全从 K 线记录列表取值，防止 KeyError"""
    try:
        if idx < 0 and abs(idx) <= len(records):
            return records[idx].get(key, default)
        return default
    except (IndexError, TypeError):
        return default


def analyze_stock(
    stock_code: str,
    stock_name: str,
    realtime_data: dict[str, Any],
    kline_data: dict[str, Any],
    technical_data: dict[str, Any],
    news_data: dict[str, Any],
) -> dict[str, Any]:
    """执行 AI 股票分析

    Args:
        stock_code: 股票代码
        stock_name: 股票名称
        realtime_data: 实时行情数据
        kline_data: K线数据
        technical_data: 技术分析数据
        news_data: 新闻数据

    Returns:
        分析结果字典
    """
    client, error = _get_llm_client()
    if error:
        if logger.isEnabledFor(logging.DEBUG):
            logger.error("_[get_llm_client.failed] %s", error)
        return {"code": stock_code, "success": False, "error": "AI 分析服务未配置"}

    model = get_llm_model()

    # 构建上下文（给 LLM 的数据摘要）
    context_parts = [f"股票：{_sanitize_prompt_text(stock_name)}({stock_code})"]

    # 实时行情
    if realtime_data and "error" not in realtime_data:
        ctx = (
            f"当前价格：{realtime_data.get('price', 'N/A')}\n"
            f"涨跌幅：{realtime_data.get('change_pct', 'N/A')}%\n"
            f"涨跌额：{realtime_data.get('change_amount', 'N/A')}\n"
            f"最高：{realtime_data.get('high', 'N/A')}\n"
            f"最低：{realtime_data.get('low', 'N/A')}\n"
            f"成交量：{realtime_data.get('volume', 'N/A')}\n"
            f"成交额：{realtime_data.get('amount', 'N/A')}\n"
            f"昨收：{realtime_data.get('pre_close', 'N/A')}\n"
            f"今开：{realtime_data.get('open', 'N/A')}"
        )
        context_parts.append(f"【实时行情】\n{ctx}")

    # K线概要
    if kline_data and "error" not in kline_data:
        records = kline_data.get("records", [])
        if records:
            closes = [r.get("close", 0) for r in records if isinstance(r.get("close"), (int, float))]
            if len(closes) >= 2:
                current = closes[-1] if closes[-1] else 0
                pct_5d = round((current - closes[-6]) / closes[-6] * 100, 2) if len(closes) >= 6 and closes[-6] else 0
                pct_20d = round((current - closes[-21]) / closes[-21] * 100, 2) if len(closes) >= 21 and closes[-21] else 0
                highs = [r.get("high", 0) for r in records[-20:] if r.get("high")]
                lows = [r.get("low", 0) for r in records[-20:] if r.get("low")]
                high_20 = max(highs) if highs else current
                low_20 = min(lows) if lows else current
            else:
                pct_5d = pct_20d = high_20 = low_20 = 0
            ctx = (
                f"近5日涨幅：{pct_5d}%\n"
                f"近20日涨幅：{pct_20d}%\n"
                f"20日最高：{high_20}\n"
                f"20日最低：{low_20}\n"
                f"数据天数：{len(records)}"
            )
            context_parts.append(f"【K线概要】\n{ctx}")

    # 技术分析 — 从 trend dict 内读取 MA 值
    if technical_data and "error" not in technical_data:
        ctx_lines = []
        trend = technical_data.get("trend", {})
        if isinstance(trend, dict):
            for key, label in [("ma5", "MA5"), ("ma10", "MA10"), ("ma20", "MA20"), ("ma60", "MA60")]:
                val = trend.get(key, "")
                if val:
                    ctx_lines.append(f"{label}：{val}")
            vol_ratio = technical_data.get("volume_ratio", "")
            if vol_ratio:
                ctx_lines.append(f"量比：{vol_ratio}")
            bias = technical_data.get("bias", "")
            if bias:
                ctx_lines.append(f"乖离率：{bias}")
            if trend.get("status"):
                ctx_lines.append(f"趋势判断：{trend.get('status', '')} 评分={trend.get('score', '')}")

        macd = technical_data.get("macd", {})
        if isinstance(macd, dict):
            ctx_lines.append(f"MACD：DIF={macd.get('dif', '')} DEA={macd.get('dea', '')} BAR={macd.get('bar', '')} "
                             f"状态={macd.get('status', '')} 信号={macd.get('signal', '')}")

        rsi = technical_data.get("rsi", {})
        if isinstance(rsi, dict):
            ctx_lines.append(f"RSI(14)：{rsi.get('value', '')} 状态={rsi.get('status', '')}")

        boll = technical_data.get("bollinger", {})
        if isinstance(boll, dict):
            ctx_lines.append(f"布林带：中轨={boll.get('mid', '')} 上轨={boll.get('upper', '')} 下轨={boll.get('lower', '')}")

        if ctx_lines:
            context_parts.append(f"【技术分析】\n{chr(10).join(ctx_lines)}")

    # 新闻
    if news_data and "error" not in news_data:
        news_items = news_data.get("news", [])
        if news_items:
            news_lines = []
            for n in news_items[:5]:
                title = _sanitize_prompt_text(n.get("title", ""))
                source = _sanitize_prompt_text(n.get("source", ""))
                if title:
                    news_lines.append(f"- [{source}] {title}")
            if news_lines:
                context_parts.append(f"【近期新闻】\n{chr(10).join(news_lines)}")

    context = "\n\n".join(context_parts)

    # 调用 LLM（带超时保护）
    timeout_seconds = int(os.environ.get("STOCK_LLM_TIMEOUT", "120"))
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"请分析以下股票数据，生成决策仪表盘：\n\n{context}"},
            ],
            temperature=0.3,
            max_tokens=4000,
            response_format={"type": "json_object"},
            timeout=timeout_seconds,
        )
        raw = resp.choices[0].message.content or ""
    except Exception as e:
        logger.warning("LLM 主调用失败，尝试 fallback: %s", e)
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": f"请分析以下股票数据，生成决策仪表盘：\n\n{context}"},
                ],
                temperature=0.3,
                max_tokens=4000,
                timeout=timeout_seconds,
            )
            raw = resp.choices[0].message.content or ""
        except Exception as e2:
            logger.error("LLM fallback 也失败: %s", e2)
            return {"code": stock_code, "success": False, "error": "AI 分析调用失败"}

    # 解析 JSON
    data = None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        # Try extracting from markdown code block
        m = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', raw, re.DOTALL)
        if m:
            try:
                data = json.loads(m.group(1))
            except json.JSONDecodeError:
                pass
        if data is None:
            m = re.search(r'(\{.*\})', raw, re.DOTALL)
            if m:
                try:
                    data = json.loads(m.group(1))
                except json.JSONDecodeError:
                    pass
    if data is None:
        logger.warning("LLM 输出 JSON 解析失败: %.200s", raw)
        return {"code": stock_code, "success": False, "error": "AI 分析输出格式错误"}

    # 注入元数据
    data["code"] = stock_code
    data["success"] = True
    data["model_used"] = model
    return data
