/**
 * LHB 龙虎榜 Analyzer — ported from UZI-Skill fetch_lhb.py + data_sources.py
 *
 * Fetches 龙虎榜 (Dragon & Tiger Board) data from East Money datacenter API.
 * Matches 营业部 names against known 游资 seats, splits institutional vs hot money.
 */

import { getCache, setCache, makeCacheKey, TTL_HOURLY } from "../cache";
import type {
  LhbReport, LhbRecord, YouziActivity, LhbSplit,
} from "../types";
import { matchSeat, isInstitutional } from "./seat_db";
import type { SeatEntry } from "./seat_db";
import { getRealtimeQuote } from "./tencent";

const HTTP_HEADERS = {
  "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
  Accept: "application/json",
  Referer: "https://data.eastmoney.com/",
};

// ══════════════════════════════════════════════════════════════
// East Money Datacenter API
// ══════════════════════════════════════════════════════════════

const EM_BASE = "https://datacenter-web.eastmoney.com/api/data/v1/get";

/** All columns we need for LHB detail */
const COLUMNS_DETAIL = "ALL";

/**
 * Fetch LHB on-board dates for a given stock.
 */
async function fetchLhbDates(code: string): Promise<string[]> {
  const url = `${EM_BASE}?` + new URLSearchParams({
    reportName: "RPT_LHB_BOARDDATE",
    columns: "SECURITY_CODE,TRADE_DATE,TR_DATE",
    filter: `(SECURITY_CODE="${code}")`,
    pageNumber: "1",
    pageSize: "1000",
    sortTypes: "-1",
    sortColumns: "TRADE_DATE",
    source: "WEB",
    client: "WEB",
  }).toString();

  try {
    const resp = await fetch(url, { headers: HTTP_HEADERS });
    const data: any = await resp.json();
    if (data?.result?.data) {
      return data.result.data.map((r: any) => {
        const d = r.TRADE_DATE || r.TR_DATE || "";
        return d.slice(0, 10).replace(/-/g, "");
      });
    }
  } catch { /* ignore */ }
  return [];
}

/**
 * Fetch LHB detail for a specific stock + date.
 * East Money returns top buy/sell seats with OPERATEDEPT_NAME, BUY, SELL, NET fields.
 */
async function fetchLhbDetail(
  code: string,
  date: string,
  flag: "BUY" | "SELL",
): Promise<any[]> {
  const reportMap: Record<string, string> = {
    BUY: "RPT_BILLBOARD_DAILYDETAILSBUY",
    SELL: "RPT_BILLBOARD_DAILYDETAILSSELL",
  };

  const formattedDate = `${date.slice(0, 4)}-${date.slice(4, 6)}-${date.slice(6, 8)}`;
  const url = `${EM_BASE}?` + new URLSearchParams({
    reportName: reportMap[flag],
    columns: "ALL",
    filter: `(TRADE_DATE='${formattedDate}')(SECURITY_CODE="${code}")`,
    pageNumber: "1",
    pageSize: "500",
    source: "WEB",
    client: "WEB",
  }).toString();

  try {
    const resp = await fetch(url, { headers: HTTP_HEADERS });
    const data: any = await resp.json();
    return data?.result?.data || [];
  } catch { /* ignore */ }
  return [];
}

/**
 * Fetch LHB statistics (appearance count in last month).
 * Uses RPT_BILLBOARD_TRADEALL (个股上榜统计).
 */
async function fetchLhbStatistic(code: string): Promise<{ count30d: number; stockName: string }> {
  const url = `${EM_BASE}?` + new URLSearchParams({
    reportName: "RPT_BILLBOARD_TRADEALL",
    columns: "SECURITY_CODE,SECURITY_NAME_ABBR,BILLBOARD_TIMES,LATEST_TDATE,CLOSE_PRICE,CHANGE_RATE,BILLBOARD_NET_AMT",
    filter: `(STATISTICS_CYCLE="01")(SECURITY_CODE="${code}")`,
    pageNumber: "1",
    pageSize: "1",
    sortTypes: "-1",
    sortColumns: "BILLBOARD_TIMES",
    source: "WEB",
    client: "WEB",
  }).toString();

  try {
    const resp = await fetch(url, { headers: HTTP_HEADERS });
    const data: any = await resp.json();
    if (data?.result?.data?.[0]) {
      const row = data.result.data[0];
      return {
        count30d: parseInt(row.BILLBOARD_TIMES) || 0,
        stockName: row.SECURITY_NAME_ABBR || code,
      };
    }
  } catch { /* ignore */ }
  return { count30d: 0, stockName: code };
}

// ══════════════════════════════════════════════════════════════
// Analysis Logic
// ══════════════════════════════════════════════════════════════

function makeVerdict(youzi: SeatEntry, netBuy: number): string {
  if (youzi.premium === "negative") {
    return netBuy > 0 ? "反向预警（该游资为反向指标）" : "不在射程";
  }
  if (youzi.premium === "positive") {
    return netBuy > 0 ? "✅ 在射程（正向信号）" : "不在射程";
  }
  if (youzi.premium === "neutral_positive") {
    return netBuy > 0 ? "✅ 在射程" : "不在射程";
  }
  // neutral
  return netBuy > 0 ? "在射程（中性信号）" : "不在射程";
}

function splitInstVsYouzi(records: LhbRecord[]): LhbSplit {
  let instBuy = 0, instSell = 0, youziBuy = 0, youziSell = 0;
  for (const r of records) {
    if (isInstitutional(r.seat_name)) {
      instBuy += r.buy_amount;
      instSell += r.sell_amount;
    } else {
      youziBuy += r.buy_amount;
      youziSell += r.sell_amount;
    }
  }
  return {
    institutional_buy: instBuy,
    institutional_sell: instSell,
    institutional_net: instBuy - instSell,
    youzi_buy: youziBuy,
    youzi_sell: youziSell,
    youzi_net: youziBuy - youziSell,
  };
}

function generateRecommendation(split: LhbSplit, youziCount: number): string {
  const parts: string[] = [];
  if (split.institutional_net > 0 && split.youzi_net > 0) {
    parts.push("机构与游资均净买入，市场合力向上");
  } else if (split.institutional_net > 0) {
    parts.push("机构主导买入，基本面驱动型行情");
  } else if (split.youzi_net > 0) {
    parts.push("游资主导炒作，注意短线波动风险");
  }
  if (split.institutional_net < 0 && split.youzi_net < 0) {
    parts.push("机构与游资均净卖出，建议谨慎");
  }
  if (youziCount > 3) {
    parts.push("多路游资齐聚，辨识度较高");
  }
  return parts.join("。") || "龙虎榜数据正常，未出现异常集中交易。";
}

// ══════════════════════════════════════════════════════════════
// Public Entry Point
// ══════════════════════════════════════════════════════════════

export async function analyzeLhb(code: string): Promise<LhbReport> {
  // Cache check
  const lKey = makeCacheKey("lhb", code);
  const cached = await getCache(lKey);
  if (cached) return cached;

  // 1. Get LHB statistics (appearance count + stock name)
  const { count30d, stockName } = await fetchLhbStatistic(code);

  // 1b. Fallback name lookup via existing Tencent module
  let resolvedName = stockName || code;
  if (resolvedName === code) {
    try {
      const quote = await getRealtimeQuote(code);
      if (quote?.name) resolvedName = quote.name;
    } catch { /* ignore */ }
  }

  // 2. Get on-board dates
  const dates = await fetchLhbDates(code);
  const recentDates = dates.slice(0, 10); // last 10 dates

  // 3. Fetch details for each recent date (buy + sell)
  const allRecords: LhbRecord[] = [];
  const youziMap = new Map<string, { seat: SeatEntry; buy: number; sell: number }>();

  for (const dt of recentDates) {
    const [buySide, sellSide] = await Promise.all([
      fetchLhbDetail(code, dt, "BUY"),
      fetchLhbDetail(code, dt, "SELL"),
    ]);

    // Merge buy side
    for (const row of buySide) {
      const seatName = row.OPERATEDEPT_NAME || "";
      if (!seatName) continue;

      const buyAmt = (parseFloat(row.BUY) || 0) / 10000; // 元 → 万
      const sellAmt = (parseFloat(row.SELL) || 0) / 10000;
      const netAmt = (parseFloat(row.NET) || 0) / 10000;

      allRecords.push({
        date: dt,
        code,
        name: row.SECURITY_CODE || code,
        seat_name: seatName,
        buy_amount: Math.round(buyAmt * 100) / 100,
        sell_amount: Math.round(sellAmt * 100) / 100,
        net_amount: Math.round(netAmt * 100) / 100,
      });

      // Match against known seats
      const matched = matchSeat(seatName);
      if (matched) {
        const key = matched.entry.id;
        if (!youziMap.has(key)) {
          youziMap.set(key, { seat: matched.entry, buy: 0, sell: 0 });
        }
        const entry = youziMap.get(key)!;
        entry.buy += buyAmt;
        entry.sell += sellAmt;
      }
    }

    // Merge sell side
    for (const row of sellSide) {
      const seatName = row.OPERATEDEPT_NAME || "";
      if (!seatName) continue;

      const buyAmt = (parseFloat(row.BUY) || 0) / 10000;
      const sellAmt = (parseFloat(row.SELL) || 0) / 10000;
      const netAmt = (parseFloat(row.NET) || 0) / 10000;

      allRecords.push({
        date: dt,
        code,
        name: row.SECURITY_CODE || code,
        seat_name: seatName,
        buy_amount: Math.round(buyAmt * 100) / 100,
        sell_amount: Math.round(sellAmt * 100) / 100,
        net_amount: Math.round(netAmt * 100) / 100,
      });

      const matched = matchSeat(seatName);
      if (matched) {
        const key = matched.entry.id;
        if (!youziMap.has(key)) {
          youziMap.set(key, { seat: matched.entry, buy: 0, sell: 0 });
        }
        const entry = youziMap.get(key)!;
        entry.buy += buyAmt;
        entry.sell += sellAmt;
      }
    }
  }

  // 4. Build youzi activity list
  const matchedYouzi: YouziActivity[] = [];
  for (const [id, info] of youziMap) {
    matchedYouzi.push({
      youzi: info.seat,
      total_buy: Math.round(info.buy * 100) / 100,
      total_sell: Math.round(info.sell * 100) / 100,
      net: Math.round((info.buy - info.sell) * 100) / 100,
      confidence: "high",
      verdict: makeVerdict(info.seat, info.buy - info.sell),
    });
  }

  // Sort by net buy descending
  matchedYouzi.sort((a, b) => b.net - a.net);

  // 5. Split institutional vs hot money
  const split = splitInstVsYouzi(allRecords);

  // 6. Generate recommendation
  const recommendation = generateRecommendation(split, matchedYouzi.length);

  const report: LhbReport = {
    code,
    name: resolvedName,
    lhb_count_30d: count30d,
    lhb_records: allRecords.slice(0, 50), // cap at 50 records
    matched_youzi: matchedYouzi,
    inst_vs_youzi: split,
    recommendation,
  };

  await setCache(lKey, report, TTL_HOURLY);
  return report;
}
