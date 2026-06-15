/**
 * Financial Data Fetcher — East Money Main Financial Indicators
 *
 * Fetches from RPT_F10_FINANCE_MAINFINADATA:
 * - Revenue, profit, EPS, BPS
 * - Free cash flow, operating cash flow
 * - Total liabilities, shares outstanding
 * - 5-period historical data for trend analysis
 */

import { getCache, setCache, makeCacheKey, TTL_HOURLY } from "../cache";
import type { FinancialSnapshot } from "../types";
import { getRealtimeQuote } from "./tencent";

const EM_BASE = "https://datacenter-web.eastmoney.com/api/data/v1/get";

const HTTP_HEADERS = {
  "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
  Accept: "application/json",
  Referer: "https://emweb.securities.eastmoney.com/",
};

/** Field mapping from East Money API to our model */
interface EmRecord {
  REPORT_DATE: string;
  NOTICE_DATE: string;
  OPERATE_INCOME_PK: number;       // 营业收入
  OPERATE_PROFIT_PK: number;       // 营业利润
  PARENTNETPROFIT: number;         // 归母净利润
  EPSJB: number;                   // 基本每股收益
  BPS: number;                     // 每股净资产
  NETCASH_OPERATE_PK: number;      // 经营活动现金流
  FCFF_BACK: number;               // 企业自由现金流(反向)
  FCFF_FORWARD: number;            // 企业自由现金流(正向)
  MGJYXJJE: number;                // 每股经营现金流
  LIABILITY: number;               // 总负债
  A_FREE_SHARE: number;            // 流通A股
  MGWFPLR: number;                 // 每股未分配利润
  MGZBGJ: number;                  // 每股资本公积
  INTSTCOVRATE: number;            // 利息覆盖倍数
  [key: string]: any;
}

export async function fetchFinancials(code: string): Promise<FinancialSnapshot> {
  const fKey = makeCacheKey("fin", code);
  const cached = await getCache(fKey);
  if (cached) return cached;

  // Fetch financial main data (last 5 reports)
  const url = `${EM_BASE}?` + new URLSearchParams({
    reportName: "RPT_F10_FINANCE_MAINFINADATA",
    columns: "ALL",
    filter: `(SECURITY_CODE="${code}")`,
    pageNumber: "1",
    pageSize: "5",
    sortTypes: "-1",
    sortColumns: "REPORT_DATE",
    source: "WEB",
    client: "WEB",
  }).toString();

  let records: EmRecord[] = [];
  try {
    const resp = await fetch(url, { headers: HTTP_HEADERS });
    const data: any = await resp.json();
    records = data?.result?.data || [];
  } catch { /* fall through */ }

  if (records.length === 0) {
    throw new Error(`未获取到 ${code} 的财务数据`);
  }

  // Use ANNUAL report (December) for base-year financials, quarterly for trend
  const annual = records.find(r => (r.REPORT_DATE || "").includes("-12-"));
  const latest = annual || records[0];
  const isAnnual = !!annual;

  // Get stock name from Tencent
  let name = code;
  try {
    const quote = await getRealtimeQuote(code);
    if (quote?.name) name = quote.name;
  } catch { /* ignore */ }

  const result: FinancialSnapshot = {
    code,
    name,
    report_date: (latest.REPORT_DATE || "").slice(0, 10),
    report_type: isAnnual ? "年报" : "季报",
    notice_date: (latest.NOTICE_DATE || "").slice(0, 10),
    revenue: latest.OPERATE_INCOME_PK,
    operating_profit: latest.OPERATE_PROFIT_PK,
    net_profit: latest.PARENTNETPROFIT,
    net_margin: latest.OPERATE_INCOME_PK ? +(latest.PARENTNETPROFIT / latest.OPERATE_INCOME_PK * 100).toFixed(2) : 0,
    eps: latest.EPSJB,
    bps: latest.BPS,
    operating_cashflow: latest.NETCASH_OPERATE_PK,
    fcff_back: latest.FCFF_BACK,
    fcff_forward: latest.FCFF_FORWARD,
    cashflow_per_share: latest.MGJYXJJE,
    total_liabilities: latest.LIABILITY,
    shares_outstanding: latest.A_FREE_SHARE,
    revenue_history: [],
    profit_history: [],
    eps_history: [],
    dates: [],
  };

  // Build history (oldest first for trend analysis)
  for (let i = records.length - 1; i >= 0; i--) {
    const r = records[i];
    result.revenue_history.push(r.OPERATE_INCOME_PK);
    result.profit_history.push(r.PARENTNETPROFIT);
    result.eps_history.push(r.EPSJB);
    result.dates.push((r.REPORT_DATE || "").slice(0, 7)); // YYYY-MM
  }

  await setCache(fKey, result, TTL_HOURLY);
  return result;
}
