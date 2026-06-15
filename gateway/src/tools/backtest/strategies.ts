/**
 * Backtest Strategies — ported from tools/backtest/strategies.py
 *
 * 5 built-in strategies generating buy/sell signals from K-line data.
 * All pure math — no external dependencies.
 */

import { BacktestSignal } from "../../types";
import { calcMA, calcMACD, calcRSI, calcBollinger } from "./indicators";

type Signal = BacktestSignal;

function safeClose(records: any[], idx: number): number {
  try { return Number(records[idx]?.close) || 0; } catch { return 0; }
}

// ── Strategy 1: MA Crossover ──

export function maCrossover(records: any[], fast = 5, slow = 20): Signal[] {
  if (records.length < slow + 2) return [{ action: "hold", date: "", price: 0, reason: `数据不足（需要${slow+2}条）` }];

  const signals: Signal[] = [];
  for (let i = slow; i < records.length; i++) {
    const maFast = calcMA(records.slice(0, i + 1), fast);
    const maSlow = calcMA(records.slice(0, i + 1), slow);
    const maFastPrev = calcMA(records.slice(0, i), fast);
    const maSlowPrev = calcMA(records.slice(0, i), slow);

    if (maFast === 0 || maSlow === 0) continue;
    const price = safeClose(records, i);
    if (price === 0) continue;

    const prevCross = maFastPrev - maSlowPrev;
    const currCross = maFast - maSlow;

    if (prevCross <= 0 && currCross > 0) {
      signals.push({ date: records[i].date, action: "buy", price, reason: `MA金叉: MA${fast}=${maFast.toFixed(2)} 上穿 MA${slow}=${maSlow.toFixed(2)}` });
    } else if (prevCross >= 0 && currCross < 0) {
      signals.push({ date: records[i].date, action: "sell", price, reason: `MA死叉: MA${fast}=${maFast.toFixed(2)} 下穿 MA${slow}=${maSlow.toFixed(2)}` });
    }
  }
  return signals;
}

// ── Strategy 2: MACD ──

export function macdCrossover(records: any[]): Signal[] {
  const vals = records.filter(r => r.close).map(r => r.close);
  if (vals.length < 26) return [{ action: "hold", date: "", price: 0, reason: "数据不足（需要26条）" }];

  const signals: Signal[] = [];
  for (let i = 25; i < vals.length; i++) {
    const cur = calcMACD(vals.slice(0, i + 1));
    const prev = calcMACD(vals.slice(0, i));

    if (cur.signal === "金叉" && prev.signal !== "金叉") {
      signals.push({ date: records[i].date, action: "buy", price: vals[i], reason: `MACD金叉: DIF=${cur.dif} 上穿 DEA=${cur.dea}` });
    } else if (cur.signal === "死叉" && prev.signal !== "死叉") {
      signals.push({ date: records[i].date, action: "sell", price: vals[i], reason: `MACD死叉: DIF=${cur.dif} 下穿 DEA=${cur.dea}` });
    }
  }
  return signals;
}

// ── Strategy 3: RSI Mean Reversion ──

export function rsiMeanReversion(records: any[], oversold = 30, overbought = 70): Signal[] {
  const vals = records.filter(r => r.close).map(r => r.close);
  if (vals.length < 15) return [{ action: "hold", date: "", price: 0, reason: "数据不足（需要15条）" }];

  const signals: Signal[] = [];
  for (let i = 14; i < vals.length; i++) {
    const cur = calcRSI(vals.slice(0, i + 1), 14);
    const prev = calcRSI(vals.slice(0, i), 14);
    const curVal = cur.value;
    const prevVal = prev.value;

    if (prevVal < oversold && curVal >= oversold) {
      signals.push({ date: records[i].date, action: "buy", price: vals[i], reason: `RSI回升: ${prevVal}→${curVal} 突破超卖线${oversold}` });
    } else if (prevVal > overbought && curVal <= overbought) {
      signals.push({ date: records[i].date, action: "sell", price: vals[i], reason: `RSI回落: ${prevVal}→${curVal} 跌破超买线${overbought}` });
    }
  }
  return signals;
}

// ── Strategy 4: Bollinger Bounce ──

export function bollingerBounce(records: any[]): Signal[] {
  if (records.length < 21) return [{ action: "hold", date: "", price: 0, reason: "数据不足（需要21条）" }];

  const signals: Signal[] = [];
  for (let i = 20; i < records.length; i++) {
    const curBB = calcBollinger(records.slice(0, i + 1), 20);
    const prevBB = calcBollinger(records.slice(0, i), 20);
    const price = safeClose(records, i);
    const prevPrice = safeClose(records, i - 1);

    const { upper, lower } = curBB;
    const { upper: prevUpper, lower: prevLower } = prevBB;

    if (lower === 0 || upper === 0) continue;

    if (prevPrice < prevLower && price >= lower) {
      signals.push({ date: records[i].date, action: "buy", price, reason: `布林带下轨反弹: 下轨=${lower.toFixed(2)}` });
    } else if (prevPrice > prevUpper && price <= upper) {
      signals.push({ date: records[i].date, action: "sell", price, reason: `布林带上轨回落: 上轨=${upper.toFixed(2)}` });
    }
  }
  return signals;
}

// ── Strategy 5: Combined Signals ──

export function combinedSignals(records: any[]): Signal[] {
  const vals = records.filter(r => r.close).map(r => r.close);
  if (vals.length < 26) return [{ action: "hold", date: "", price: 0, reason: "数据不足" }];

  const signals: Signal[] = [];
  let prevScore = 50;

  for (let i = 25; i < records.length; i++) {
    const window = records.slice(0, i + 1);
    const price = safeClose(records, i);

    // MA contribution (40%)
    const ma5 = calcMA(window, 5);
    const ma20 = calcMA(window, 20);
    let maScore = 0;
    if (ma5 > ma20 && ma20 > 0) {
      const ratio = Math.min((ma5 - ma20) / ma20 * 100, 10) / 10;
      maScore = 40 + ratio * 40;
    } else if (ma20 > 0) {
      const ratio = Math.min((ma20 - ma5) / ma20 * 100, 10) / 10;
      maScore = 40 - ratio * 40;
    } else {
      maScore = 40;
    }

    // MACD contribution (30%)
    const macd = calcMACD(vals.slice(0, i + 1));
    let macdScore = 15;
    if (macd.signal === "金叉") macdScore = 30;
    else if (macd.signal === "死叉") macdScore = 0;

    // RSI contribution (30%)
    const rsi = calcRSI(vals.slice(0, i + 1), 14);
    const rsiVal = rsi.value;
    let rsiScore = 10;
    if (rsiVal < 30) rsiScore = 30;
    else if (rsiVal < 50) rsiScore = 20;
    else if (rsiVal < 70) rsiScore = 10;
    else rsiScore = 0;

    const totalScore = maScore * 0.4 + macdScore * 0.3 + rsiScore * 0.3;

    if (prevScore <= 60 && totalScore > 60) {
      signals.push({ date: records[i].date, action: "buy", price, reason: `组合信号看多: 总分${Math.round(totalScore)} (MA=${Math.round(maScore)} MACD=${Math.round(macdScore)} RSI=${Math.round(rsiScore)})` });
    } else if (prevScore >= 40 && totalScore < 40) {
      signals.push({ date: records[i].date, action: "sell", price, reason: `组合信号看空: 总分${Math.round(totalScore)} (MA=${Math.round(maScore)} MACD=${Math.round(macdScore)} RSI=${Math.round(rsiScore)})` });
    }

    prevScore = totalScore;
  }
  return signals;
}

// ── Registry ──

export const STRATEGY_REGISTRY: Record<string, (records: any[], ...args: any[]) => Signal[]> = {
  ma_crossover: maCrossover as any,
  macd: macdCrossover as any,
  rsi: rsiMeanReversion as any,
  bollinger: bollingerBounce as any,
  combined: combinedSignals as any,
};

export const STRATEGY_NAMES: Record<string, string> = {
  ma_crossover: "MA金叉/死叉",
  macd: "MACD金叉/死叉",
  rsi: "RSI均值回归",
  bollinger: "布林带反弹",
  combined: "组合信号",
};

export const STRATEGY_DEFAULT_PARAMS: Record<string, Record<string, any>> = {
  ma_crossover: { fast: 5, slow: 20 },
  macd: {},
  rsi: { oversold: 30, overbought: 70 },
  bollinger: {},
  combined: {},
};

export function listStrategies(): { id: string; name: string; params: Record<string, any> }[] {
  return Object.keys(STRATEGY_REGISTRY).sort().map(sid => ({
    id: sid,
    name: STRATEGY_NAMES[sid] || sid,
    params: STRATEGY_DEFAULT_PARAMS[sid] || {},
  }));
}

export function runStrategy(sid: string, records: any[], kwargs?: Record<string, any>): Signal[] {
  const fn = STRATEGY_REGISTRY[sid];
  if (!fn) return [{ action: "hold" as const, date: "", price: 0, reason: `未知策略: ${sid}` }];
  return fn(records, ...Object.values(kwargs || {}));
}
