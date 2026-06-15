import { RealtimeQuote } from '../types';

/**
 * Yahoo Finance API for US/HK stocks
 * https://query1.finance.yahoo.com/v8/finance/chart/AAPL
 */

const YAHOO_BASE = 'https://query1.finance.yahoo.com';

export async function getRealtimeQuote(code: string): Promise<RealtimeQuote> {
  const yCode = yahooCode(code);
  const url = `${YAHOO_BASE}/v8/finance/chart/${yCode}?interval=1d&range=1mo`;

  const res = await fetch(url, {
    headers: { 'User-Agent': 'Mozilla/5.0' },
    cf: { cacheTtl: 30, cacheEverything: true },
  });

  if (!res.ok) {
    return { code, error: `Yahoo API HTTP ${res.status}` };
  }

  const data: any = await res.json();
  const result = data?.chart?.result?.[0];
  if (!result) {
    const err = data?.chart?.error?.description || 'no data';
    return { code, error: `Yahoo: ${err}` };
  }

  const meta = result.meta || {};
  const quotes = result.indicators?.quote?.[0] || {};
  const closes = result.indicators?.adjclose?.[0]?.adjclose || [];
  const timestamps = result.timestamp || [];

  const lastIdx = timestamps.length - 1;
  const prevIdx = Math.max(0, lastIdx - 1);

  const price = closes[lastIdx] || meta.regularMarketPrice || 0;
  const prevClose = meta.chartPreviousClose || closes[prevIdx] || price;
  const change = price - prevClose;
  const changePct = prevClose > 0 ? (change / prevClose) * 100 : 0;

  return {
    code,
    name: meta.symbol || code,
    price,
    change,
    change_pct: changePct,
    open: meta.regularMarketOpen || quotes.open?.[lastIdx] || 0,
    high: meta.regularMarketDayHigh || quotes.high?.[lastIdx] || 0,
    low: meta.regularMarketDayLow || quotes.low?.[lastIdx] || 0,
    volume: meta.regularMarketVolume || quotes.volume?.[lastIdx] || 0,
    pre_close: prevClose,
  };
}

export async function getKline(code: string, days = 60): Promise<{ code: string; records: any[] }> {
  const yCode = yahooCode(code);
  const range = days <= 30 ? '1mo' : days <= 90 ? '3mo' : '6mo';
  const url = `${YAHOO_BASE}/v8/finance/chart/${yCode}?interval=1d&range=${range}`;

  const res = await fetch(url, {
    headers: { 'User-Agent': 'Mozilla/5.0' },
    cf: { cacheTtl: 120, cacheEverything: true },
  });

  if (!res.ok) {
    return { code, records: [] };
  }

  const data: any = await res.json();
  const result = data?.chart?.result?.[0];
  if (!result) return { code, records: [] };

  const timestamps = result.timestamp || [];
  const quotes = result.indicators?.quote?.[0] || {};

  const records = timestamps.map((t: number, i: number) => ({
    date: new Date(t * 1000).toISOString().slice(0, 10),
    open: quotes.open?.[i] || 0,
    high: quotes.high?.[i] || 0,
    low: quotes.low?.[i] || 0,
    close: quotes.close?.[i] || 0,
    volume: quotes.volume?.[i] || 0,
  }));

  return { code, records };
}

function yahooCode(code: string): string {
  code = code.toUpperCase();
  if (code.startsWith('HK')) return `${code.slice(2)}.HK`;
  return code;
}
