/**
 * AI Stock Analyzer — ported from tools/analyzer.py
 *
 * Calls an OpenAI-compatible LLM to generate a decision dashboard.
 * Uses fetch() directly (no openai npm dependency).
 */

import type { Env } from "../types";

const SYSTEM_PROMPT = `你是一位专业的投资分析师，负责生成【决策仪表盘】分析报告。

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
            "trend_status": { "ma_alignment": "均线排列状态描述", "is_bullish": true, "trend_score": 0-100 },
            "price_position": { "current_price": 价格, "support_level": "支撑位", "resistance_level": "压力位" },
            "volume_analysis": { "volume_status": "放量/缩量/平量", "volume_meaning": "量能含义解读" }
        },
        "intelligence": {
            "latest_news": "近期重要新闻摘要",
            "risk_alerts": ["风险点1", "风险点2"],
            "positive_catalysts": ["利好1", "利好2"]
        },
        "battle_plan": {
            "sniper_points": { "ideal_buy": "理想入场位", "stop_loss": "止损位", "take_profit": "目标位" },
            "position_strategy": { "suggested_position": "建议仓位", "risk_control": "风控策略" }
        }
    },
    "analysis_summary": "100字综合分析摘要",
    "risk_warning": "风险提示"
}

## 原则
1. 核心结论先行，一句话说清
2. 分持仓建议（空仓者 vs 持仓者）
3. 给出具体价格点位
4. 风险点要醒目标出`;

function sanitize(text: string): string {
  return text.replace(/[{}`|]/g, "").replace(/\s+/g, " ").trim().slice(0, 200);
}

function loadLlmConfig(env: Env): { baseUrl: string; apiKey: string; model: string; error?: string } {
  const apiKey = env.STOCK_LLM_API_KEY || "";
  const model = env.STOCK_LLM_MODEL || "gpt-4o-mini";
  const baseUrl = env.STOCK_LLM_BASE_URL || "https://api.openai.com/v1";

  if (!apiKey) {
    return { baseUrl, apiKey: "", model, error: "AI 分析服务未配置：未设置 STOCK_LLM_API_KEY" };
  }
  return { baseUrl, apiKey, model };
}

async function callLlmWithRetry(
  baseUrl: string,
  apiKey: string,
  model: string,
  messages: { role: string; content: string }[],
  timeout = 120,
): Promise<string> {
  const maxRetries = 2;
  let lastError: Error | null = null;

  for (let attempt = 0; attempt <= maxRetries; attempt++) {
    try {
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), timeout * 1000);

      const resp = await fetch(`${baseUrl}/chat/completions`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${apiKey}`,
        },
        body: JSON.stringify({
          model,
          messages,
          temperature: 0.3,
          max_tokens: 4000,
          response_format: { type: "json_object" },
        }),
        signal: controller.signal,
      });

      clearTimeout(timer);

      if (!resp.ok) {
        throw new Error(`LLM API HTTP ${resp.status}: ${await resp.text().catch(() => "")}`);
      }

      const data: any = await resp.json();
      return data.choices?.[0]?.message?.content || "";
    } catch (err: any) {
      lastError = err;
      if (attempt < maxRetries) {
        const wait = Math.pow(2, attempt) * 1000;
        await new Promise(r => setTimeout(r, wait));
      }
    }
  }

  throw lastError || new Error("LLM 调用全部失败");
}

function parseLlmResponse(raw: string): Record<string, any> | null {
  try {
    const data = JSON.parse(raw);
    if (typeof data === "object" && !Array.isArray(data)) return data;
  } catch { /* ignore */ }

  // Try extracting from markdown code block
  const blockMatch = /```(?:json)?\s*(\{.*?\})\s*```/s.exec(raw);
  if (blockMatch) {
    try { return JSON.parse(blockMatch[1]); } catch { /* ignore */ }
  }

  // Try finding the first {...}
  const objMatch = /(\{.*\})/s.exec(raw);
  if (objMatch) {
    try { return JSON.parse(objMatch[1]); } catch { /* ignore */ }
  }

  return null;
}

export async function analyzeStock(
  stockCode: string,
  stockName: string,
  realtimeData: Record<string, any>,
  klineData: Record<string, any>,
  technicalData: Record<string, any>,
  newsData: Record<string, any>,
  env: Env,
): Promise<Record<string, any>> {
  const config = loadLlmConfig(env);
  if (config.error) {
    return { code: stockCode, success: false, error: config.error };
  }

  // Build context
  const contextParts: string[] = [];
  contextParts.push(`股票：${sanitize(stockName)}(${stockCode})`);

  if (realtimeData && !realtimeData.error) {
    contextParts.push(`【实时行情】
当前价格：${realtimeData.price ?? "N/A"}
涨跌幅：${realtimeData.change_pct ?? "N/A"}%
最高：${realtimeData.high ?? "N/A"}
最低：${realtimeData.low ?? "N/A"}
成交量：${realtimeData.volume ?? "N/A"}
成交额：${realtimeData.amount ?? "N/A"}
昨收：${realtimeData.pre_close ?? "N/A"}
今开：${realtimeData.open ?? "N/A"}`);
  }

  if (klineData && !klineData.error) {
    const records: any[] = klineData.records || [];
    if (records.length > 0) {
      const closes = records.filter(r => r.close).map(r => r.close);
      let pct5d = 0, pct20d = 0, high20 = 0, low20 = 0;
      if (closes.length >= 6) {
        pct5d = Math.round(((closes[closes.length - 1] - closes[closes.length - 6]) / closes[closes.length - 6]) * 10000) / 100;
      }
      if (closes.length >= 21) {
        pct20d = Math.round(((closes[closes.length - 1] - closes[closes.length - 21]) / closes[closes.length - 21]) * 10000) / 100;
      }
      const last20 = records.slice(-20);
      high20 = Math.max(...last20.map(r => r.high).filter((h: number) => h));
      low20 = Math.min(...last20.map(r => r.low).filter((l: number) => l));

      contextParts.push(`【K线概要】
近5日涨幅：${pct5d}%
近20日涨幅：${pct20d}%
20日最高：${high20}
20日最低：${low20}
数据天数：${records.length}`);
    }
  }

  if (technicalData && !technicalData.error) {
    const lines: string[] = [];
    const trend = technicalData.trend || {};
    if (trend.ma5) lines.push(`MA5：${trend.ma5} MA10：${trend.ma10} MA20：${trend.ma20} MA60：${trend.ma60}`);
    if (trend.status) lines.push(`趋势判断：${trend.status} 评分=${trend.score}`);
    if (technicalData.volume_ratio) lines.push(`量比：${technicalData.volume_ratio}`);

    const macd = technicalData.macd || {};
    if (macd.dif != null) {
      lines.push(`MACD：DIF=${macd.dif} DEA=${macd.dea} BAR=${macd.bar} 状态=${macd.status}`);
    }
    const rsi = technicalData.rsi || {};
    if (rsi.value != null) lines.push(`RSI(14)：${rsi.value} 状态=${rsi.status}`);
    const boll = technicalData.bollinger || {};
    if (boll.middle) {
      lines.push(`布林带：中轨=${boll.middle} 上轨=${boll.upper} 下轨=${boll.lower}`);
    }

    if (lines.length > 0) {
      contextParts.push(`【技术分析】\n${lines.join("\n")}`);
    }
  }

  if (newsData && !newsData.error) {
    const newsItems: any[] = newsData.news || [];
    if (newsItems.length > 0) {
      const newsLines = newsItems.slice(0, 5).map((n: any) => {
        const title = sanitize(n.title || "");
        const source = sanitize(n.source || "");
        return title ? `- [${source}] ${title}` : "";
      }).filter(Boolean);
      if (newsLines.length > 0) {
        contextParts.push(`【近期新闻】\n${newsLines.join("\n")}`);
      }
    }
  }

  const context = contextParts.join("\n\n");

  // Call LLM
  try {
    const raw = await callLlmWithRetry(
      config.baseUrl,
      config.apiKey,
      config.model,
      [
        { role: "system", content: SYSTEM_PROMPT },
        { role: "user", content: `请分析以下股票数据，生成决策仪表盘：\n\n${context}` },
      ],
      parseInt(env.STOCK_LLM_TIMEOUT || "120"),
    );

    const data = parseLlmResponse(raw);
    if (!data) {
      return { code: stockCode, success: false, error: "AI 分析输出格式错误（非 JSON）" };
    }

    data.code = stockCode;
    data.success = true;
    data.model_used = config.model;
    return data;
  } catch (err: any) {
    return { code: stockCode, success: false, error: `AI 分析调用失败（已重试2次）: ${err.message}` };
  }
}
