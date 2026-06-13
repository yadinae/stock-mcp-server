"""AI 股票分析模块
================
调用 LLM 生成决策仪表盘分析报告。

P1 加固：
- 显式超时配置
- 指数退避重试
- 更清晰的错误信息
- 多 provider fallback
- LLM 响应格式校验
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from typing import Any, Optional

import yaml

logger = logging.getLogger("stock-mcp.analyzer")

# ── 配置常量 ──────────────────────────────────────────────
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
            "action_checklist": ["检查项1", "检查项2"]
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
2. 分持仓建议（空仓者 vs 持仓者）
3. 给出具体价格点位
4. 风险点要醒目标出
"""


def _load_llm_config() -> tuple[str, str, str, Optional[str]]:
    """从环境变量或 Hermes config 加载 LLM 配置

    Returns:
        (base_url, api_key, model, error)
    """
    base_url = os.environ.get("STOCK_LLM_BASE_URL", "")
    api_key = os.environ.get("STOCK_LLM_API_KEY", "")
    model = os.environ.get("STOCK_LLM_MODEL", "")

    # 环境变量优先
    if api_key:
        if not model:
            model = os.environ.get("LLM_MODEL", "gpt-4o-mini")
        return base_url or None, api_key, model, None

    # Fallback: 读 Hermes config
    try:
        hermes_home = os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes"))
        config_path = os.path.join(hermes_home, "config.yaml")
        if not os.path.exists(config_path):
            return None, "", "", "未找到 Hermes 配置文件"

        with open(config_path) as f:
            data = yaml.safe_load(f) or {}

        providers = data.get("providers", {}) or {}
        main_provider = data.get("model", {}).get("provider", "")
        if not model:
            model = data.get("model", {}).get("default", "gpt-4o-mini")

        # 优先：主 provider
        if main_provider and main_provider in providers:
            p = providers[main_provider]
            if p.get("api_key"):
                return p.get("base_url") or None, p["api_key"], model, None

        # 次优：扫描优选列表
        preferred = ["deepseek", "openai", "opencode-go", "openrouter"]
        for name in preferred:
            p = providers.get(name, {})
            if p and p.get("api_key"):
                logger.info("使用 LLM 提供商: %s", name)
                return p.get("base_url") or None, p["api_key"], model, None

        return None, "", model, "未找到可用的 LLM API Key"
    except Exception as e:
        return None, "", "", f"读取配置失败: {e}"


def _sanitize_prompt_text(text: str) -> str:
    """对外部数据做转义，防止 prompt injection"""
    text = text.replace("{", "(").replace("}", ")")
    text = text.replace("`", "'").replace("|", "/")
    text = re.sub(r'\s+', ' ', text).strip()
    return text[:200]


def _safe_get(records: list[dict], key: str, idx: int, default: Any = 0) -> Any:
    try:
        if idx < 0 and abs(idx) <= len(records):
            return records[idx].get(key, default)
        return default
    except (IndexError, TypeError):
        return default


def _call_llm_with_retry(client, model: str, messages: list, timeout: int,
                          max_retries: int = 2) -> Optional[str]:
    """调用 LLM 并指数退避重试"""
    last_error = None
    for attempt in range(max_retries + 1):
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=0.3,
                max_tokens=4000,
                response_format={"type": "json_object"},
                timeout=timeout,
            )
            return resp.choices[0].message.content or ""
        except Exception as e:
            last_error = e
            if attempt < max_retries:
                wait = 2 ** attempt  # 1s, 2s
                logger.warning("LLM 调用失败（第%d次重试）: %s", attempt + 1, e)
                time.sleep(wait)

    raise last_error or Exception("LLM 调用全部失败")


def _parse_llm_response(raw: str) -> Optional[dict]:
    """解析 LLM 返回的 JSON，支持 Markdown 代码块包裹格式"""
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass

    # 尝试从代码块提取
    m = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', raw, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass

    # 最粗暴：找第一个 {...}
    m = re.search(r'(\{.*\})', raw, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass

    return None


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
    base_url, api_key, model, error = _load_llm_config()
    if error:
        logger.error("LLM 配置加载失败: %s", error)
        return {
            "code": stock_code, "success": False,
            "error": f"AI 分析服务未配置: {error}",
        }

    if not api_key:
        return {
            "code": stock_code, "success": False,
            "error": "AI 分析服务未配置：未找到 LLM API Key。"
                     "请设置 STOCK_LLM_API_KEY 环境变量或确保 Hermes config 中有可用的 provider",
        }

    try:
        from openai import OpenAI
        timeout_seconds = int(os.environ.get("STOCK_LLM_TIMEOUT", "120"))
        client = OpenAI(base_url=base_url or None, api_key=api_key, timeout=timeout_seconds)
    except Exception as e:
        return {
            "code": stock_code, "success": False,
            "error": f"LLM 客户端初始化失败: {e}",
        }

    # 构建上下文
    context_parts = [f"股票：{_sanitize_prompt_text(stock_name)}({stock_code})"]

    if realtime_data and "error" not in realtime_data:
        ctx = (
            f"当前价格：{realtime_data.get('price', 'N/A')}\n"
            f"涨跌幅：{realtime_data.get('change_pct', 'N/A')}%\n"
            f"最高：{realtime_data.get('high', 'N/A')}\n"
            f"最低：{realtime_data.get('low', 'N/A')}\n"
            f"成交量：{realtime_data.get('volume', 'N/A')}\n"
            f"成交额：{realtime_data.get('amount', 'N/A')}\n"
            f"昨收：{realtime_data.get('pre_close', 'N/A')}\n"
            f"今开：{realtime_data.get('open', 'N/A')}"
        )
        context_parts.append(f"【实时行情】\n{ctx}")

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
            if trend.get("status"):
                ctx_lines.append(f"趋势判断：{trend.get('status', '')} 评分={trend.get('score', '')}")

        macd = technical_data.get("macd", {})
        if isinstance(macd, dict):
            ctx_lines.append(
                f"MACD：DIF={macd.get('dif', '')} DEA={macd.get('dea', '')} "
                f"BAR={macd.get('bar', '')} 状态={macd.get('status', '')}"
            )

        rsi = technical_data.get("rsi", {})
        if isinstance(rsi, dict):
            ctx_lines.append(f"RSI(14)：{rsi.get('value', '')} 状态={rsi.get('status', '')}")

        boll = technical_data.get("bollinger", {})
        if isinstance(boll, dict):
            ctx_lines.append(
                f"布林带：中轨={boll.get('middle', '')} 上轨={boll.get('upper', '')} "
                f"下轨={boll.get('lower', '')}"
            )

        if ctx_lines:
            context_parts.append("【技术分析】\n" + "\n".join(ctx_lines))

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
                context_parts.append("【近期新闻】\n" + "\n".join(news_lines))

    context = "\n\n".join(context_parts)

    # 调用 LLM（带重试）
    try:
        raw = _call_llm_with_retry(
            client=client,
            model=model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"请分析以下股票数据，生成决策仪表盘：\n\n{context}"},
            ],
            timeout=timeout_seconds,
            max_retries=2,
        )
    except Exception as e:
        logger.error("LLM 调用全部失败: %s", e)
        return {
            "code": stock_code, "success": False,
            "error": f"AI 分析调用失败（已重试2次）: {e}",
        }

    data = _parse_llm_response(raw)
    if data is None:
        logger.warning("LLM 输出 JSON 解析失败: %.200s", raw)
        return {
            "code": stock_code, "success": False,
            "error": "AI 分析输出格式错误（非 JSON）",
        }

    data["code"] = stock_code
    data["success"] = True
    data["model_used"] = model
    return data
