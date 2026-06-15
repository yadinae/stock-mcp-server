/**
 * Trap Detector — 杀猪盘识别引擎
 *
 * Detects pump-and-dump / scam patterns using:
 * - K-line anomaly signals (price pump, volume dump, limit-up streaks)
 * - News/promotion pattern search (老师推荐, 群推荐, etc.)
 *
 * Ported methodology from UZI-Skill trap-detector (v3.9.0)
 */

import { getCache, setCache, makeCacheKey, TTL_REALTIME } from "../cache";
import type { TrapReport, TrapSignal, KlineRecord } from "../types";

// ───── K-Line Signal Detection ─────

/**
 * Analyze kline records for trap signals.
 * Returns signals with severity levels.
 */
function detectKlineTraps(records: KlineRecord[]): TrapSignal[] {
  const signals: TrapSignal[] = [];
  if (!records || records.length < 5) return signals;

  // Ensure oldest-first ordering
  const sorted = [...records].sort(
    (a, b) => new Date(a.date).getTime() - new Date(b.date).getTime()
  );
  const closes = sorted.map(r => r.close);

  // ─── Signal 1: Price Pump (>15% in 5 days) ───
  if (closes.length >= 6) {
    const pct5d = (closes[closes.length - 1] - closes[closes.length - 6]) / closes[closes.length - 6] * 100;
    if (pct5d > 15) {
      signals.push({
        name: "短期暴涨",
        severity: "high",
        detail: `近5日涨幅 ${pct5d.toFixed(1)}%，超过15%警戒线`,
        evidence: `5日前收盘 ${closes[closes.length - 6].toFixed(2)} → 当前 ${closes[closes.length - 1].toFixed(2)}`,
      });
    } else if (pct5d > 10) {
      signals.push({
        name: "短期涨幅较大",
        severity: "medium",
        detail: `近5日涨幅 ${pct5d.toFixed(1)}%，接近10%关注线`,
      });
    }
  }

  // ─── Signal 2: 20-day Pump (>40%) ───
  if (closes.length >= 21) {
    const pct20d = (closes[closes.length - 1] - closes[closes.length - 21]) / closes[closes.length - 21] * 100;
    if (pct20d > 40) {
      signals.push({
        name: "中期暴涨",
        severity: "high",
        detail: `近20日涨幅 ${pct20d.toFixed(1)}%，疑似拉升出货阶段`,
        evidence: `20日前收盘 ${closes[closes.length - 21].toFixed(2)} → 当前 ${closes[closes.length - 1].toFixed(2)}`,
      });
    } else if (pct20d > 25) {
      signals.push({
        name: "中期涨幅较大",
        severity: "medium",
        detail: `近20日涨幅 ${pct20d.toFixed(1)}%，注意追高风险`,
      });
    }
  }

  // ─── Signal 3: Volume anomaly + price drop ───
  if (sorted.length >= 10) {
    const recent = sorted.slice(-10);
    const avgVol = recent.slice(0, 5).reduce((s, r) => s + r.volume, 0) / 5;
    const recent5 = recent.slice(-5);
    for (const r of recent5) {
      if (avgVol > 0 && r.volume > avgVol * 3) {
        const drop = (r.close - (recent5[0]?.close || r.close)) / (recent5[0]?.close || r.close) * 100;
        if (drop < -3) {
          signals.push({
            name: "放量下跌",
            severity: "high",
            detail: `${r.date} 成交量达均量 ${(r.volume / avgVol).toFixed(1)} 倍，股价下跌，疑似出货`,
            evidence: `量比 ${(r.volume / avgVol).toFixed(1)}x，跌幅 ${Math.abs(drop).toFixed(1)}%`,
          });
          break;
        }
      }
    }
  }

  // ─── Signal 4: Consecutive limit-up ───
  if (sorted.length >= 5) {
    const last5 = sorted.slice(-5);
    let streak = 0;
    for (const r of last5) {
      const d = (r.close - r.open) / r.open * 100;
      // A-share limit-up ≈ +10% (ST: +5%), detect > 8% as likely limit-up
      if (d > 7.5) {
        streak++;
      } else if (streak > 0) {
        break;
      }
    }
    if (streak >= 3) {
      signals.push({
        name: "连续涨停",
        severity: "high",
        detail: `最近5个交易日出现 ${streak} 次涨停，典型拉升模式`,
        evidence: `连续涨停 ${streak} 次`,
      });
    } else if (streak >= 2) {
      signals.push({
        name: "连板拉升",
        severity: "medium",
        detail: `最近5个交易日出现 ${streak} 次涨停，注意追高风险`,
      });
    }
  }

  // ─── Signal 5: Price-volume divergence ───
  if (sorted.length >= 15) {
    const recent = sorted.slice(-15);
    const first = recent[0];
    const last = recent[recent.length - 1];
    const priceUp = last.close > first.close;
    const volDown = recent.slice(-5).reduce((s, r) => s + r.volume, 0) / 5 <
      recent.slice(0, 5).reduce((s, r) => s + r.volume, 0) / 5 * 0.7;
    if (priceUp && volDown) {
      signals.push({
        name: "价量背离",
        severity: "medium",
        detail: "股价上涨但成交量持续萎缩，上涨动能减弱",
        evidence: "近期量能较前期下降超过30%",
      });
    }
  }

  // ─── Signal 6: High volatility (振幅过大) ───
  if (sorted.length >= 10) {
    const recent = sorted.slice(-10);
    let highVolDays = 0;
    for (const r of recent) {
      const amp = (r.high - r.low) / r.close * 100;
      if (amp > 8) highVolDays++;
    }
    if (highVolDays >= 5) {
      signals.push({
        name: "剧烈波动",
        severity: "medium",
        detail: `近10日中有 ${highVolDays} 天振幅超过8%，典型短线博弈特征`,
        evidence: `高振幅日 ${highVolDays}/10`,
      });
    }
  }

  return signals;
}

// ─── Rock-bottom price trap (杀猪盘常见微盘股) ───

function detectMicroCapTrap(price: number, volume: number, marketCap?: number): TrapSignal | null {
  if (marketCap != null && marketCap < 20 && price < 10) {
    return {
      name: "微盘低价股",
      severity: "medium",
      detail: `流通市值约 ${marketCap.toFixed(1)} 亿，价格 ${price} 元，微盘低价股易被操纵`,
      evidence: `市值 ${marketCap.toFixed(1)}亿，价格 ${price}元`,
    };
  }
  return null;
}

// ───── Web Search Signals (News-based) ─────

/**
 * Search news for promotion patterns.
 * Checks: 老师推荐, 群推荐, 翻倍, 稳赚, 内幕等关键词
 */
async function detectPromotionSignals(
  code: string,
  name: string,
): Promise<TrapSignal[]> {
  const signals: TrapSignal[] = [];

  // Search for "老师推荐" pattern
  const promotionTerms = [
    { term: `${name} 老师`, label: "老师推荐", severity: "high" as const },
    { term: `${name} 推荐`, label: "推荐推广", severity: "medium" as const },
    { term: `${name} 翻倍`, label: "翻倍承诺", severity: "high" as const },
    { term: `${name} 内幕`, label: "内幕消息", severity: "high" as const },
    { term: `${name} VIP`, label: "付费社群引流", severity: "high" as const },
    { term: `${name} 群`, label: "群组推荐", severity: "medium" as const },
    { term: `${name} 涨停`, label: "涨停预测", severity: "medium" as const },
    { term: `${name} 骗局`, label: "投资者投诉", severity: "high" as const },
    { term: `${name} 杀猪盘`, label: "杀猪盘举报", severity: "high" as const },
  ];

  // For each term, search via Baidu News
  for (const pt of promotionTerms) {
    try {
      const url = `https://news.baidu.com/s?tn=news&word=${encodeURIComponent(pt.term)}&pn=0&rn=3`;
      const resp = await fetch(url, {
        headers: {
          "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        },
      });
      const text = await resp.text();
      // Count search results
      const resultCount = (text.match(/class="result"/g) || []).length +
                         (text.match(/<h3/g) || []).length;

      if (resultCount >= 3) {
        signals.push({
          name: pt.label,
          severity: pt.severity,
          detail: `搜索"${pt.term}"发现 ${resultCount} 条相关内容`,
          evidence: `命中 ${resultCount} 条结果`,
        });
      }
    } catch {
      // Silently skip on fetch errors
    }
  }

  return signals;
}

// ───── Aggregation ─────

interface TrapInput {
  code: string;
  name: string;
  price?: number | null;
  volume?: number | null;
  marketCap?: number | null;
  klineRecords?: KlineRecord[];
}

export async function analyzeTrapRisk(input: TrapInput): Promise<TrapReport> {
  const { code, name, price, volume, marketCap, klineRecords } = input;

  // Cache check
  const cKey = makeCacheKey("trap", code);
  const cached = await getCache(cKey);
  if (cached) return cached;

  const allSignals: TrapSignal[] = [];

  // 1. K-line based signals
  if (klineRecords && klineRecords.length >= 5) {
    allSignals.push(...detectKlineTraps(klineRecords));
  }

  // 2. Micro-cap trap
  if (price != null && volume != null) {
    const microSignal = detectMicroCapTrap(price, volume, marketCap ?? undefined);
    if (microSignal) allSignals.push(microSignal);
  }

  // 3. News-based promotion signals (async)
  const promoSigs = await detectPromotionSignals(code, name);
  allSignals.push(...promoSigs);

  // ───── Scoring ─────

  let score = 0;
  let maxSev: string = "low";
  const sevMap: Record<string, number> = { low: 1, medium: 2, high: 3 };

  for (const sig of allSignals) {
    const sev = sevMap[sig.severity] || 1;
    score += sev * 10;
    if (sev > sevMap[maxSev]) maxSev = sig.severity;
  }

  // Cap at 100
  score = Math.min(score, 100);

  // ───── Rating ─────

  let level: string, recommendation: string;
  if (allSignals.length <= 1) {
    level = "🟢 安全";
    recommendation = "未发现杀猪盘特征信号，可正常分析。任何投资请自行判断。";
  } else if (allSignals.length <= 3) {
    level = "🟡 注意";
    recommendation = "检测到少量推广或异常信号，建议核实信息来源，谨慎决策。";
  } else if (allSignals.length <= 5) {
    level = "🟠 警惕";
    recommendation = "⚠️ 多个异常信号！强烈建议谨慎，核实所有信息源后再做决策。";
  } else {
    level = "🔴 高度可疑";
    recommendation = "⛔️ 大量杀猪盘特征信号！强烈建议回避该标的，谨防资金损失。";
  }

  // ───── Report ─────

  const report: TrapReport = {
    code,
    name,
    trap_score: score,
    trap_level: level,
    max_severity: maxSev,
    signals: allSignals,
    user_keyword_boost: 0,
    recommendation,
  };

  await setCache(cKey, report, TTL_REALTIME);
  return report;
}
