/**
 * Trade Simulator — ported from tools/backtest/simulator.py
 *
 * Converts strategy signals into simulated trades with:
 * - T+1 settlement (A-share rule)
 * - Commission (buy 0.025%, sell 0.025% + stamp tax 0.1%)
 * - 0.1% slippage
 * - Full position mode
 */

import { BacktestSignal, BacktestTrade, EquityPoint } from "../../types";

const COMMISSION_RATE_BUY = 0.00025;
const COMMISSION_RATE_SELL = 0.00025;
const STAMP_TAX_RATE = 0.001;
const SLIPPAGE_RATE = 0.001;

function getOpenPrice(records: any[], idx: number, slippageUp = true): number {
  try {
    let price = Number(records[idx]?.open) || 0;
    if (price === 0) price = Number(records[idx]?.close) || 0;
    return price * (1 + (slippageUp ? SLIPPAGE_RATE : -SLIPPAGE_RATE));
  } catch { return 0; }
}

export function runSimulation(
  records: any[],
  signals: BacktestSignal[],
  initialCapital = 100000,
): {
  trades: BacktestTrade[];
  equityCurve: EquityPoint[];
  finalValue: number;
  initialCapital: number;
  totalReturn: number;
  tradeCount: number;
  finalCash: number;
  finalShares: number;
  error?: string;
} {
  if (!records || records.length === 0) {
    return { error: "无K线数据", trades: [], equityCurve: [], finalValue: 0, initialCapital, totalReturn: 0, tradeCount: 0, finalCash: 0, finalShares: 0 };
  }

  if (!signals || signals.length === 0) {
    return {
      trades: [],
      equityCurve: records.map(r => ({ date: r.date || "", value: initialCapital })),
      finalValue: initialCapital,
      initialCapital,
      totalReturn: 0,
      tradeCount: 0,
      finalCash: initialCapital,
      finalShares: 0,
    };
  }

  // Build date-to-index mapping
  const dateToIdx: Record<string, number> = {};
  for (let i = 0; i < records.length; i++) {
    dateToIdx[records[i].date] = i;
  }

  let cash = initialCapital;
  let shares = 0;
  let buyDate = "";
  let buyPrice = 0;
  const trades: BacktestTrade[] = [];
  let lastTradeIdx = -2;

  for (const sig of signals) {
    if (sig.action !== "buy" && sig.action !== "sell") continue;

    const sigIdx = dateToIdx[sig.date];
    if (sigIdx == null) continue;

    // Execute next day (signal confirmed at close)
    const execIdx = sigIdx + 1;
    if (execIdx >= records.length) continue;

    const execDate = records[execIdx].date;

    if (sig.action === "buy" && cash > 0 && shares === 0) {
      const price = getOpenPrice(records, execIdx, true);
      const sharesBuyable = Math.floor(cash / (price * (1 + COMMISSION_RATE_BUY)));
      if (sharesBuyable <= 0) continue;

      shares = sharesBuyable;
      const commission = Math.round(shares * price * COMMISSION_RATE_BUY * 100) / 100;
      cash -= shares * price + commission;
      buyDate = execDate;
      buyPrice = price;
      lastTradeIdx = execIdx;

    } else if (sig.action === "sell" && shares > 0) {
      if (execIdx <= lastTradeIdx) continue; // T+1

      const price = getOpenPrice(records, execIdx, false);
      const proceeds = shares * price;
      const commission = Math.round(proceeds * COMMISSION_RATE_SELL * 100) / 100;
      const stampTax = Math.round(proceeds * STAMP_TAX_RATE * 100) / 100;
      const netProceeds = proceeds - commission - stampTax;
      const totalBuyCost = shares * buyPrice + shares * buyPrice * COMMISSION_RATE_BUY;
      const profit = netProceeds - totalBuyCost;
      const holdDays = execIdx - lastTradeIdx;
      const profitPct = (profit / totalBuyCost) * 100;

      trades.push({
        buy_date: buyDate,
        sell_date: execDate,
        buy_price: Math.round(buyPrice * 100) / 100,
        sell_price: Math.round(price * 100) / 100,
        shares,
        commission: Math.round((commission + shares * buyPrice * COMMISSION_RATE_BUY) * 100) / 100,
        stamp_tax: Math.round(stampTax * 100) / 100,
        profit: Math.round(profit * 100) / 100,
        profit_pct: Math.round(profitPct * 100) / 100,
        hold_days: holdDays,
      });

      cash = netProceeds;
      shares = 0;
    }
  }

  // Final equity
  const lastClose = records.length > 0 ? Number(records[records.length - 1].close) || 0 : 0;
  const finalValue = cash + shares * lastClose;
  const totalReturn = initialCapital > 0 ? Math.round(((finalValue - initialCapital) / initialCapital) * 10000) / 100 : 0;

  // Build equity curve
  const equityCurve = rebuildEquityCurve(records, trades, initialCapital);

  return {
    trades,
    equityCurve,
    finalValue: Math.round(finalValue * 100) / 100,
    initialCapital,
    totalReturn,
    tradeCount: trades.length,
    finalCash: Math.round(cash * 100) / 100,
    finalShares: shares,
  };
}

export function rebuildEquityCurve(records: any[], trades: BacktestTrade[], initialCapital: number): EquityPoint[] {
  const curve: EquityPoint[] = [];
  let cash = initialCapital;
  let shares = 0;
  let tradePtr = 0;

  for (const r of records) {
    const date = r.date || "";
    const close = Number(r.close) || 0;

    // Process trades on their dates
    while (tradePtr < trades.length) {
      const t = trades[tradePtr];
      if (t.buy_date === date) {
        const cost = t.shares * t.buy_price + t.shares * t.buy_price * COMMISSION_RATE_BUY;
        cash -= cost;
        shares = t.shares;
        tradePtr++;
      } else if (t.sell_date === date) {
        const proceeds = t.shares * t.sell_price - t.commission - t.stamp_tax;
        cash += proceeds;
        shares = 0;
        tradePtr++;
      } else {
        break;
      }
    }

    const marketValue = shares * close;
    curve.push({ date, value: Math.round((cash + marketValue) * 100) / 100 });
  }

  return curve;
}
