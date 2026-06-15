/**
 * Pure-math indicator functions — shared by technical.ts and backtest modules
 *
 * These duplicate the logic from tools/technical.ts but are isolated
 * here to avoid circular dependencies when backtest strategies need them.
 */

export function calcMA(records: any[], period: number): number {
  const vals = records.filter((r: any) => r.close != null).map((r: any) => r.close);
  if (vals.length < period) return 0;
  return Math.round((vals.slice(-period).reduce((a: number, b: number) => a + b, 0) / period) * 100) / 100;
}

export function calcEMA(closesArr: number[], period: number): number[] {
  if (closesArr.length === 0) return [];
  const multiplier = 2 / (period + 1);
  const ema = [closesArr[0]];
  for (let i = 1; i < closesArr.length; i++) {
    ema.push((closesArr[i] - ema[i - 1]) * multiplier + ema[i - 1]);
  }
  return ema;
}

export function calcMACD(closesArr: number[]): { dif: number; dea: number; bar: number; status: string; signal: string } {
  if (closesArr.length < 26) {
    return { dif: 0, dea: 0, bar: 0, status: "数据不足", signal: "" };
  }
  const ema12 = calcEMA(closesArr, 12);
  const ema26 = calcEMA(closesArr, 26);
  const dif: number[] = [];
  for (let i = 0; i < closesArr.length; i++) dif.push(ema12[i] - ema26[i]);
  const dea = calcEMA(dif, 9);
  const bar = dif.map((d, i) => d - (dea[i] ?? 0));

  const latestDif = Math.round(dif[dif.length - 1] * 1000) / 1000;
  const latestDea = dea.length === dif.length ? Math.round(dea[dea.length - 1] * 1000) / 1000 : 0;

  let status = "中性";
  if (latestDif > 0 && bar[bar.length - 1] > 0) {
    status = bar.length > 1 && bar[bar.length - 1] > Math.abs(bar[bar.length - 2]) ? "多头加强" : "多头";
  } else if (latestDif > 0) status = "多头减弱";
  else if (latestDif < 0 && bar[bar.length - 1] < 0) {
    status = bar.length > 1 && Math.abs(bar[bar.length - 1]) > Math.abs(bar[bar.length - 2]) ? "空头加强" : "空头";
  } else if (latestDif < 0) status = "空头减弱";

  let signal = "";
  if (dif.length >= 2 && dea.length >= 2) {
    if (dif[dif.length - 2] < dea[dea.length - 2] && latestDif >= latestDea) signal = "金叉";
    else if (dif[dif.length - 2] > dea[dea.length - 2] && latestDif <= latestDea) signal = "死叉";
  }

  return { dif: latestDif, dea: latestDea, bar: Math.round(bar[bar.length - 1] * 1000) / 1000, status, signal };
}

export function calcRSI(closesArr: number[], period = 14): { value: number; status: string } {
  if (closesArr.length < period + 1) return { value: 50, status: "数据不足" };
  let gains = 0, losses = 0;
  for (let i = closesArr.length - period; i < closesArr.length; i++) {
    const diff = closesArr[i] - closesArr[i - 1];
    if (diff > 0) gains += diff; else losses -= diff;
  }
  const avgGain = gains / period, avgLoss = losses / period;
  let rsi: number;
  if (avgLoss === 0) rsi = 100;
  else rsi = Math.round((100 - 100 / (1 + avgGain / avgLoss)) * 100) / 100;
  return { value: rsi, status: rsi > 70 ? "超买" : rsi > 50 ? "强势" : rsi > 30 ? "弱势" : "超卖" };
}

export function calcBollinger(records: any[], period = 20): { upper: number; middle: number; lower: number; bandwidth: number; position: string } {
  const vals = records.filter((r: any) => r.close != null).map((r: any) => r.close);
  if (vals.length < period) return { upper: 0, middle: 0, lower: 0, bandwidth: 0, position: "数据不足" };
  const ma = vals.slice(-period).reduce((a: number, b: number) => a + b, 0) / period;
  const variance = vals.slice(-period).reduce((sum: number, c: number) => sum + (c - ma) ** 2, 0) / period;
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
