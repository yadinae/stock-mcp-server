/**
 * Technical Analysis Module — ported from tools/technical.py
 *
 * Pure math — all indicators calculated from K-line data directly.
 * No external dependencies (no TA-Lib, no numpy).
 */

import { getCache, setCache, makeCacheKey, TTL_TECHNICAL } from "../cache";
import type {
  KlineRecord, TrendResult, MacdResult, RsiResult,
  BollingerResult, IchimokuResult, CandlePattern, TechnicalResult,
} from "../types";

// ── Helpers ──

function closes(records: KlineRecord[]): number[] {
  return records.filter(r => r.close != null).map(r => r.close);
}

function safeClose(records: KlineRecord[], idx: number): number {
  try { return records[idx]?.close ?? 0; } catch { return 0; }
}

// ── MA ──

function calcMA(records: KlineRecord[], period: number): number {
  const vals = closes(records);
  if (vals.length < period) return 0;
  return Math.round((vals.slice(-period).reduce((a, b) => a + b, 0) / period) * 100) / 100;
}

// ── EMA ──

function calcEMA(closesArr: number[], period: number): number[] {
  if (closesArr.length === 0) return [];
  const multiplier = 2 / (period + 1);
  const ema = [closesArr[0]];
  for (let i = 1; i < closesArr.length; i++) {
    ema.push((closesArr[i] - ema[i - 1]) * multiplier + ema[i - 1]);
  }
  return ema;
}

// ── MACD ──

function calcMACD(closesArr: number[]): MacdResult {
  if (closesArr.length < 26) {
    return { dif: 0, dea: 0, bar: 0, status: "数据不足", signal: "" };
  }

  const ema12 = calcEMA(closesArr, 12);
  const ema26 = calcEMA(closesArr, 26);
  const dif: number[] = [];
  for (let i = 0; i < closesArr.length; i++) {
    dif.push(ema12[i] - ema26[i]);
  }
  const dea = calcEMA(dif, 9);
  const bar = dif.map((d, i) => d - (dea[i] ?? 0));

  const latestDif = Math.round(dif[dif.length - 1] * 1000) / 1000;
  const latestDea = dea.length === dif.length ? Math.round(dea[dea.length - 1] * 1000) / 1000 : 0;
  const latestBar = bar.length === dif.length ? Math.round(bar[bar.length - 1] * 1000) / 1000 : 0;

  let status = "中性";
  if (latestDif > 0 && latestBar > 0) {
    status = bar.length > 1 && latestBar > Math.abs(bar[bar.length - 2]) ? "多头加强" : "多头";
  } else if (latestDif > 0) {
    status = "多头减弱";
  } else if (latestDif < 0 && latestBar < 0) {
    status = bar.length > 1 && Math.abs(latestBar) > Math.abs(bar[bar.length - 2]) ? "空头加强" : "空头";
  } else if (latestDif < 0) {
    status = "空头减弱";
  }

  let signal = "";
  if (dif.length >= 2 && dea.length >= 2) {
    if (dif[dif.length - 2] < dea[dea.length - 2] && latestDif >= latestDea) signal = "金叉";
    else if (dif[dif.length - 2] > dea[dea.length - 2] && latestDif <= latestDea) signal = "死叉";
  }

  return { dif: latestDif, dea: latestDea, bar: latestBar, status, signal };
}

// ── RSI ──

function calcRSI(closesArr: number[], period = 14): RsiResult {
  if (closesArr.length < period + 1) {
    return { value: 50, status: "数据不足" };
  }

  let gains = 0, losses = 0;
  for (let i = closesArr.length - period; i < closesArr.length; i++) {
    const diff = closesArr[i] - closesArr[i - 1];
    if (diff > 0) gains += diff;
    else losses -= diff;
  }

  const avgGain = gains / period;
  const avgLoss = losses / period;

  let rsi: number;
  if (avgLoss === 0) rsi = 100;
  else {
    const rs = avgGain / avgLoss;
    rsi = Math.round((100 - 100 / (1 + rs)) * 100) / 100;
  }

  const status = rsi > 70 ? "超买" : rsi > 50 ? "强势" : rsi > 30 ? "弱势" : "超卖";
  return { value: rsi, status };
}

// ── Bollinger ──

function calcBollinger(records: KlineRecord[], period = 20): BollingerResult {
  const vals = closes(records);
  if (vals.length < period) {
    return { upper: 0, middle: 0, lower: 0, bandwidth: 0, position: "数据不足" };
  }

  const ma = vals.slice(-period).reduce((a, b) => a + b, 0) / period;
  const variance = vals.slice(-period).reduce((sum, c) => sum + (c - ma) ** 2, 0) / period;
  const std = Math.sqrt(variance);

  const upper = Math.round((ma + 2 * std) * 100) / 100;
  const middle = Math.round(ma * 100) / 100;
  const lower = Math.round((ma - 2 * std) * 100) / 100;
  const bandwidth = middle > 0 ? Math.round(((upper - lower) / middle) * 10000) / 100 : 0;

  const current = vals[vals.length - 1];
  let position = "下轨之下（超卖）";
  if (current > upper) position = "上轨之上（超买）";
  else if (current > middle) position = "中轨至上轨";
  else if (current > lower) position = "下轨至中轨";

  return { upper, middle, lower, bandwidth, position };
}

// ── Volume Ratio ──

function calcVolumeRatio(records: KlineRecord[]): number {
  const volumes = records.filter(r => (r.volume ?? 0) > 0).map(r => r.volume!);
  if (volumes.length < 6) return 0;
  const current = volumes[volumes.length - 1];
  const avg5 = volumes.slice(-6, -1).reduce((a, b) => a + b, 0) / 5;
  return avg5 > 0 ? Math.round((current / avg5) * 100) / 100 : 0;
}

// ── Bias ──

function calcBias(closesArr: number[], ma: number): number {
  if (closesArr.length === 0 || ma === 0) return 0;
  return Math.round(((closesArr[closesArr.length - 1] - ma) / ma) * 10000) / 100;
}

// ── Trend Status ──

function calcTrendStatus(records: KlineRecord[]): TrendResult {
  const vals = closes(records);
  if (vals.length < 20) {
    return { status: "数据不足", score: 50, ma5: 0, ma10: 0, ma20: 0, ma60: 0 };
  }

  const ma5 = calcMA(records, 5);
  const ma10 = calcMA(records, 10);
  const ma20 = calcMA(records, 20);
  const ma60 = calcMA(records, 60);

  const spread5_10 = Math.abs(ma5 - ma10);
  const spread10_20 = Math.abs(ma10 - ma20);

  let status: string, score: number;
  if (ma5 > ma10 && ma10 > ma20) {
    if (spread5_10 > 1 && spread10_20 > 1) { status = "强势多头"; score = 85; }
    else { status = "多头排列"; score = 70; }
  } else if (ma5 > ma10 && ma10 < ma20) { status = "弱势多头"; score = 55; }
  else if (ma5 < ma10 && ma10 > ma20) { status = "弱势空头"; score = 45; }
  else if (ma5 < ma10 && ma10 < ma20) {
    if (spread5_10 > 1 && spread10_20 > 1) { status = "强势空头"; score = 15; }
    else { status = "空头排列"; score = 30; }
  } else { status = "震荡整理"; score = 50; }

  return { status, score, ma5, ma10, ma20, ma60 };
}

// ── Ichimoku ──

function calcIchimoku(records: KlineRecord[]): IchimokuResult {
  const highs = records.map(r => r.high).filter(h => h != null);
  const lows = records.map(r => r.low).filter(l => l != null);
  const vals = closes(records);

  if (vals.length < 52) return { status: "数据不足（需52个交易日）" };

  const tenkan = (Math.max(...highs.slice(-9)) + Math.min(...lows.slice(-9))) / 2;
  const kijun = (Math.max(...highs.slice(-26)) + Math.min(...lows.slice(-26))) / 2;
  const spanA = (tenkan + kijun) / 2;
  const spanB = (Math.max(...highs.slice(-52)) + Math.min(...lows.slice(-52))) / 2;
  const chiko = vals.length >= 26 ? vals[vals.length - 26] : vals[0];

  const price = vals[vals.length - 1];
  const aboveCloud = price > Math.max(spanA, spanB);
  const belowCloud = price < Math.min(spanA, spanB);

  let trend: string;
  if (aboveCloud && tenkan > kijun) trend = "多头（云上+金叉）";
  else if (aboveCloud) trend = "偏多（云上）";
  else if (belowCloud && tenkan < kijun) trend = "空头（云下+死叉）";
  else if (belowCloud) trend = "偏空（云下）";
  else trend = "震荡（云中）";

  return {
    tenkan: Math.round(tenkan * 100) / 100,
    kijun: Math.round(kijun * 100) / 100,
    span_a: Math.round(spanA * 100) / 100,
    span_b: Math.round(spanB * 100) / 100,
    chiko: Math.round(chiko * 100) / 100,
    trend,
  };
}

// ── Candle Patterns ──

function identifyCandlePatterns(records: KlineRecord[]): CandlePattern[] {
  if (records.length < 3) return [];

  const patterns: CandlePattern[] = [];
  for (let i = Math.max(0, records.length - 10); i < records.length; i++) {
    const r = records[i];
    const body = Math.abs(r.close - r.open);
    const upperWick = r.high - Math.max(r.open, r.close);
    const lowerWick = Math.min(r.open, r.close) - r.low;
    const totalRange = r.high - r.low;

    if (totalRange === 0) continue;

    const found: string[] = [];
    const bullish = r.close > r.open;

    // Doji
    if (body / totalRange < 0.05) found.push("doji");

    // Hammer
    if (!bullish && lowerWick > body * 2 && upperWick < body * 0.5) found.push("hammer");

    // Shooting Star
    if (bullish && upperWick > body * 2 && lowerWick < body * 0.5) found.push("shooting_star");

    // Engulfing
    if (i > 0) {
      const prev = records[i - 1];
      const prevBullish = prev.close > prev.open;
      if (bullish && !prevBullish && r.close > prev.open && r.open < prev.close) {
        found.push("bullish_engulfing");
      }
      if (!bullish && prevBullish && r.open > prev.close && r.close < prev.open) {
        found.push("bearish_engulfing");
      }
    }

    patterns.push({ date: r.date, patterns: found });
  }

  return patterns;
}

// ── Main analyze() ──

export async function analyze(records: KlineRecord[], code = ""): Promise<TechnicalResult> {
  const vals = closes(records);
  if (vals.length === 0) {
    return { error: "无数据" } as any;
  }

  const lastDate = records.length > 0 ? records[records.length - 1].date : "";
  const firstDate = records.length > 0 ? records[0].date : "";
  const techKey = makeCacheKey("technical", code, lastDate, firstDate, String(records.length));
  const cached = await getCache(techKey);
  if (cached) return cached;

  const trend = calcTrendStatus(records);
  const macd = calcMACD(vals);
  const rsi = calcRSI(vals);
  const bollinger = calcBollinger(records);
  const volumeRatio = calcVolumeRatio(records);

  const biasMA5 = calcBias(vals, trend.ma5);
  const biasMA20 = calcBias(vals, trend.ma20);

  const price = vals[vals.length - 1];
  const supportMA5 = trend.ma5 > 0 && Math.abs(price - trend.ma5) / trend.ma5 < 0.01;
  const supportMA10 = trend.ma10 > 0 && Math.abs(price - trend.ma10) / trend.ma10 < 0.01;

  let score = trend.score;
  if (macd.signal === "金叉") score += 10;
  else if (macd.signal === "死叉") score -= 10;

  const rsiVal = rsi.value;
  if (rsiVal >= 40 && rsiVal <= 60) score += 5;
  else if (rsiVal > 80 || rsiVal < 20) score -= 10;

  if (volumeRatio >= 0.8 && volumeRatio <= 1.5) score += 5;
  else if (volumeRatio > 3) score -= 5;

  score = Math.max(0, Math.min(100, score));

  let advice: string;
  if (score >= 75) advice = "买入";
  else if (score >= 60) advice = "观望（偏多）";
  else if (score >= 40) advice = "观望";
  else if (score >= 25) advice = "观望（偏空）";
  else advice = "卖出";

  const ichimoku = calcIchimoku(records);
  const candlePatterns = identifyCandlePatterns(records);

  const result: TechnicalResult = {
    trend,
    macd,
    rsi,
    bollinger,
    volume_ratio: volumeRatio,
    bias: { ma5: biasMA5, ma20: biasMA20 },
    support: { ma5: supportMA5, ma10: supportMA10 },
    ichimoku,
    candle_patterns: candlePatterns,
    price,
    score,
    advice,
    analysis_count: records.length,
  };

  await setCache(techKey, result, TTL_TECHNICAL);
  return result;
}
