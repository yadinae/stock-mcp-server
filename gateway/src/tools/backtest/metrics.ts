/**
 * Performance Metrics — ported from tools/backtest/metrics.py
 *
 * All pure math — calculates total return, annual return, max drawdown,
 * Sharpe ratio, win rate, profit factor, avg hold days.
 */

import { BacktestTrade, EquityPoint, BacktestMetrics } from "../../types";

export function calcTotalReturn(finalValue: number, initialCapital: number): { total_return_pct: number } {
  if (initialCapital <= 0) return { total_return_pct: 0 };
  return { total_return_pct: Math.round(((finalValue - initialCapital) / initialCapital) * 10000) / 100 };
}

export function calcAnnualReturn(totalReturnPct: number, days: number): { annual_return_pct: number; note?: string } {
  if (days <= 0 || totalReturnPct <= -100) return { annual_return_pct: 0, note: "数据不足" };
  const years = days / 250;
  if (years <= 0) return { annual_return_pct: 0 };
  const factor = 1 + totalReturnPct / 100;
  if (factor <= 0) return { annual_return_pct: -100 };
  const annual = (Math.pow(factor, 1 / years) - 1) * 100;
  return { annual_return_pct: Math.round(annual * 100) / 100 };
}

export function calcMaxDrawdown(equityCurve: EquityPoint[]): { max_drawdown_pct: number; max_drawdown_start?: string; max_drawdown_end?: string } {
  if (!equityCurve.length) return { max_drawdown_pct: 0 };

  let peak = equityCurve[0].value;
  let maxDd = 0;
  let maxDdStart = "";
  let maxDdEnd = "";
  let currentStart = "";

  for (const point of equityCurve) {
    if (point.value > peak) {
      peak = point.value;
      currentStart = point.date;
    }
    const dd = peak > 0 ? ((peak - point.value) / peak) * 100 : 0;
    if (dd > maxDd) {
      maxDd = dd;
      maxDdStart = currentStart;
      maxDdEnd = point.date;
    }
  }

  return {
    max_drawdown_pct: Math.round(maxDd * 100) / 100,
    max_drawdown_start: maxDdStart,
    max_drawdown_end: maxDdEnd,
  };
}

export function calcSharpeRatio(equityCurve: EquityPoint[], riskFreeRate = 0.02): { sharpe_ratio: number; note?: string; annual_volatility_pct?: number } {
  if (equityCurve.length < 30) return { sharpe_ratio: 0, note: "数据不足30个交易日，统计不显著" };

  const values = equityCurve.map(p => p.value);
  if (values[0] <= 0) return { sharpe_ratio: 0 };

  const dailyReturns: number[] = [];
  for (let i = 1; i < values.length; i++) {
    if (values[i - 1] > 0) {
      dailyReturns.push((values[i] - values[i - 1]) / values[i - 1]);
    }
  }

  if (dailyReturns.length < 20) return { sharpe_ratio: 0, note: "有效交易天数不足20" };

  const avgReturn = dailyReturns.reduce((a, b) => a + b, 0) / dailyReturns.length;
  const variance = dailyReturns.reduce((sum, r) => sum + (r - avgReturn) ** 2, 0) / dailyReturns.length;
  const dailyStd = Math.sqrt(variance);

  if (dailyStd === 0) return { sharpe_ratio: 0, note: "无波动" };

  const annualReturn = avgReturn * 250;
  const annualStd = dailyStd * Math.sqrt(250);
  const sharpe = (annualReturn - riskFreeRate) / annualStd;

  return {
    sharpe_ratio: Math.round(sharpe * 1000) / 1000,
    annual_volatility_pct: Math.round(annualStd * 10000) / 100,
  };
}

export function calcWinRate(trades: BacktestTrade[]): { win_rate_pct: number; win_count: number; loss_count: number; total_trades: number } {
  if (!trades.length) return { win_rate_pct: 0, win_count: 0, loss_count: 0, total_trades: 0 };
  const wins = trades.filter(t => t.profit > 0).length;
  return {
    win_rate_pct: Math.round((wins / trades.length) * 10000) / 100,
    win_count: wins,
    loss_count: trades.length - wins,
    total_trades: trades.length,
  };
}

export function calcProfitFactor(trades: BacktestTrade[]): { profit_factor: number } {
  if (!trades.length) return { profit_factor: 0 };
  const grossProfit = trades.filter(t => t.profit > 0).reduce((sum, t) => sum + t.profit, 0);
  const grossLoss = Math.abs(trades.filter(t => t.profit < 0).reduce((sum, t) => sum + t.profit, 0));
  if (grossLoss === 0) return { profit_factor: grossProfit > 0 ? Infinity : 0 };
  return { profit_factor: Math.round((grossProfit / grossLoss) * 1000) / 1000 };
}

export function calcAvgHoldDays(trades: BacktestTrade[]): { avg_hold_days: number; min_hold_days: number; max_hold_days: number } {
  if (!trades.length) return { avg_hold_days: 0, min_hold_days: 0, max_hold_days: 0 };
  const days = trades.map(t => t.hold_days);
  return {
    avg_hold_days: Math.round((days.reduce((a, b) => a + b, 0) / days.length) * 10) / 10,
    min_hold_days: Math.min(...days),
    max_hold_days: Math.max(...days),
  };
}

export function calcAllMetrics(
  trades: BacktestTrade[],
  equityCurve: EquityPoint[],
  finalValue: number,
  initialCapital: number,
  days: number,
): BacktestMetrics {
  const ret = calcTotalReturn(finalValue, initialCapital);
  const annual = calcAnnualReturn(ret.total_return_pct, days);
  const mdd = calcMaxDrawdown(equityCurve);
  const sharpe = calcSharpeRatio(equityCurve);
  const win = calcWinRate(trades);
  const pf = calcProfitFactor(trades);
  const hold = calcAvgHoldDays(trades);
  const metrics: BacktestMetrics = {
    ...ret,
    ...annual,
    ...mdd,
    ...sharpe,
    ...win,
    ...pf,
    ...hold,
    total_days: days,
  };
  return metrics;
}
