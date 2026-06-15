/**
 * Backtest Engine Entry — ported from tools/backtest/__init__.py
 *
 * Provides runBacktest() which orchestrates strategy → simulation → metrics → report.
 */

import type { BacktestResult, EquityPoint } from "../../types";
import { listStrategies, runStrategy, STRATEGY_DEFAULT_PARAMS, STRATEGY_NAMES } from "./strategies";
import { runSimulation } from "./simulator";
import { calcAllMetrics } from "./metrics";

export {
  listStrategies,
  runStrategy,
  STRATEGY_DEFAULT_PARAMS,
  STRATEGY_NAMES,
  runSimulation,
};

export function runBacktest(
  code: string,
  records: any[],
  strategy = "ma_crossover",
  days = 365,
  capital = 100000,
  params?: Record<string, any>,
): BacktestResult {
  if (!records || records.length === 0) {
    return {
      code,
      strategy_id: strategy,
      strategy_name: STRATEGY_NAMES[strategy] || strategy,
      strategy_params: params || {},
      period: { start: "", end: "", trading_days: 0 },
      capital: { initial: capital, final: capital },
      metrics: { error: "无K线数据" } as any,
      trades: [],
      trade_count: 0,
      equity_curve: [],
      equity_curve_points: 0,
      success: false,
      note: "回测结果仅作研究参考，不代表未来收益",
    } as any;
  }

  const strategyParams = { ...(STRATEGY_DEFAULT_PARAMS[strategy] || {}), ...(params || {}) };
  let signals = runStrategy(strategy, records, strategyParams);

  // Filter out "hold" signals
  signals = signals.filter(s => s.action === "buy" || s.action === "sell");

  const simulation = runSimulation(records, signals, capital);

  // Period
  const startDate = records[0]?.date || "";
  const endDate = records[records.length - 1]?.date || "";
  const totalDays = records.length;

  const result: BacktestResult = {
    code,
    strategy_id: strategy,
    strategy_name: STRATEGY_NAMES[strategy] || strategy,
    strategy_params: strategyParams,
    period: { start: startDate, end: endDate, trading_days: totalDays },
    capital: { initial: capital, final: simulation.finalValue ?? capital },
    trades: simulation.trades || [],
    trade_count: (simulation.trades || []).length,
    equity_curve: simulation.equityCurve || [],
    equity_curve_points: (simulation.equityCurve || []).length,
    metrics: {} as any,
    success: !simulation.error,
    note: "⚠️ 回测结果仅作研究参考，不代表未来收益",
  };

  if (simulation.error) {
    result.metrics = { error: simulation.error } as any;
  } else {
    result.metrics = calcAllMetrics(
      simulation.trades || [],
      simulation.equityCurve || [],
      simulation.finalValue ?? capital,
      capital,
      totalDays,
    );
  }

  // Include additional fields
  (result as any).total_return = simulation.totalReturn;
  (result as any).initial_capital = capital;

  return result;
}
