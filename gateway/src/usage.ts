/**
 * usage.ts — 用量追踪与计费（P1 生产加固）
 *
 * 在 rate_limit（频率限制）和 audit_log（请求日志）基础上，
 * 提供每日用量聚合、按工具统计、费用计算、历史查询等功能。
 *
 * 数据结构（KV）：
 *   usagedaily:{key}:{YYYYMMDD}        → JSON: { count, tools: { name: count }, cost }
 *   usagemonthly:{key}:{YYYYMM}        → JSON: { count, cost }
 *
 * TTL：daily 90 天，monthly 24 个月
 */

// ───── Types ─────

export interface DailyUsage {
  count: number;
  tools: Record<string, number>;
  cost: number;
}

export interface MonthlyUsage {
  count: number;
  cost: number;
}

export interface ToolPriceEntry {
  tool: string;
  name: string;
  credits: number;
}

export interface BillingPeriod {
  month: string;       // YYYYMM
  totalCalls: number;
  totalCost: number;
  perTool: Record<string, { calls: number; cost: number }>;
}

export interface UsageHistoryResult {
  daily: (DailyUsage & { date: string })[];
  totals: { calls: number; cost: number };
  toolPrices: ToolPriceEntry[];
}

// ───── Tool Pricing Model ─────

/** Tool price catalogue for reporting */
export const TOOL_PRICES: ToolPriceEntry[] = [
  // Free
  { tool: 'get_realtime_quote', name: '实时行情', credits: 0 },
  { tool: 'get_stock_info', name: '股票信息', credits: 0 },
  { tool: 'get_cache_stats', name: '缓存统计', credits: 0 },
  { tool: 'get_data_source_health', name: '数据源健康', credits: 0 },
  // Standard (1)
  { tool: 'get_kline', name: 'K线数据', credits: 1 },
  { tool: 'search_stock_news', name: '股票新闻', credits: 1 },
  { tool: 'analyze_lhb', name: '龙虎榜', credits: 1 },
  { tool: 'fetch_financials', name: '财务报表', credits: 1 },
  // Analysis (2)
  { tool: 'get_technical_analysis', name: '技术分析', credits: 2 },
  { tool: 'check_st_risk', name: 'ST风险检测', credits: 2 },
  { tool: 'check_trap_risk', name: '杀猪盘检测', credits: 2 },
  // Bundle (3)
  { tool: 'get_stock_context', name: '综合数据', credits: 3 },
  { tool: 'analyze_stocks', name: '批量分析', credits: 3 },
  { tool: 'dcf_valuation', name: 'DCF估值', credits: 3 },
  { tool: 'ic_memo', name: 'IC备忘录', credits: 3 },
  { tool: 'unit_economics', name: '单元经济', credits: 3 },
  { tool: 'value_creation_plan', name: '价值创造计划', credits: 3 },
  { tool: 'dd_checklist', name: '尽调清单', credits: 3 },
  // Premium (5)
  { tool: 'analyze_stock_ai', name: 'AI智能分析', credits: 5 },
  { tool: 'check_backtest', name: '策略回测', credits: 5 },
];

const toolCostMap = new Map<string, number>();
for (const t of TOOL_PRICES) {
  toolCostMap.set(t.tool, t.credits);
}

/** Get the credit cost for a tool call */
export function getToolCost(toolName: string): number {
  return toolCostMap.get(toolName) ?? 1; // default: 1 credit
}

// ───── KV Operations ─────

/**
 * Record a usage event for an API key.
 * Updates daily and monthly counters in KV.
 *
 * Called on each tools/call after the tool executes.
 * Writes are blocking (for reliability), but fast (single KV put).
 */
export async function recordUsage(
  kv: KVNamespace,
  apiKey: string,
  toolName: string,
): Promise<void> {
  const now = new Date();
  const year = now.getFullYear();
  const month = pad2(now.getMonth() + 1);
  const day = pad2(now.getDate());
  const dateKey = `${year}${month}${day}`;
  const monthKey = `${year}${month}`;
  const cost = getToolCost(toolName);

  // ─── Daily counter ───
  const dailyKvKey = `usagedaily:${apiKey}:${dateKey}`;
  try {
    const raw = await kv.get(dailyKvKey);
    const daily: DailyUsage = raw
      ? JSON.parse(raw)
      : { count: 0, tools: {}, cost: 0 };
    daily.count++;
    daily.tools[toolName] = (daily.tools[toolName] || 0) + 1;
    daily.cost += cost;
    await kv.put(dailyKvKey, JSON.stringify(daily), {
      expirationTtl: 7_776_000, // 90 days
    });
  } catch (e) {
    console.error(`[Usage] Failed to record daily for ${apiKey}:`, e);
  }

  // ─── Monthly counter ───
  const monthlyKvKey = `usagemonthly:${apiKey}:${monthKey}`;
  try {
    const raw = await kv.get(monthlyKvKey);
    const monthly: MonthlyUsage = raw
      ? JSON.parse(raw)
      : { count: 0, cost: 0 };
    monthly.count++;
    monthly.cost += cost;
    await kv.put(monthlyKvKey, JSON.stringify(monthly), {
      expirationTtl: 63_072_000, // 2 years
    });
  } catch (e) {
    console.error(`[Usage] Failed to record monthly for ${apiKey}:`, e);
  }
}

/**
 * Get daily usage for a specific date.
 */
export async function getDailyUsage(
  kv: KVNamespace,
  apiKey: string,
  date?: string, // YYYYMMDD, defaults to today
): Promise<(DailyUsage & { date: string }) | null> {
  if (!date) {
    const now = new Date();
    date = `${now.getFullYear()}${pad2(now.getMonth() + 1)}${pad2(now.getDate())}`;
  }
  try {
    const raw = await kv.get(`usagedaily:${apiKey}:${date}`);
    if (!raw) return null;
    return { ...JSON.parse(raw), date };
  } catch {
    return null;
  }
}

/**
 * Get monthly usage summary.
 */
export async function getMonthlyUsage(
  kv: KVNamespace,
  apiKey: string,
  month: string, // YYYYMM
): Promise<(MonthlyUsage & { month: string }) | null> {
  try {
    const raw = await kv.get(`usagemonthly:${apiKey}:${month}`);
    if (!raw) return null;
    return { ...JSON.parse(raw), month };
  } catch {
    return null;
  }
}

/**
 * Get usage history for last N days.
 */
export async function getUsageHistory(
  kv: KVNamespace,
  apiKey: string,
  days: number = 7,
): Promise<UsageHistoryResult> {
  const daily: (DailyUsage & { date: string })[] = [];
  let totalCalls = 0;
  let totalCost = 0;

  const now = new Date();
  for (let i = days - 1; i >= 0; i--) {
    const d = new Date(now);
    d.setDate(d.getDate() - i);
    const dateKey = `${d.getFullYear()}${pad2(d.getMonth() + 1)}${pad2(d.getDate())}`;
    const usage = await getDailyUsage(kv, apiKey, dateKey);
    if (usage) {
      daily.push(usage);
      totalCalls += usage.count;
      totalCost += usage.cost;
    }
  }

  return {
    daily,
    totals: { calls: totalCalls, cost: totalCost },
    toolPrices: TOOL_PRICES,
  };
}

/**
 * Get monthly billing report — per-tool breakdown for a given month.
 * Scans daily entries within the month to reconstruct per-tool details.
 */
export async function getBillingReport(
  kv: KVNamespace,
  apiKey: string,
  month: string, // YYYYMM
): Promise<BillingPeriod | null> {
  const year = parseInt(month.slice(0, 4), 10);
  const mon = parseInt(month.slice(4, 6), 10);

  // Get overall monthly total
  const monthly = await getMonthlyUsage(kv, apiKey, month);
  if (!monthly) return null;

  // Calculate days in this month
  const daysInMonth = new Date(year, mon, 0).getDate();

  // Aggregate per-tool from daily entries
  const perTool: Record<string, { calls: number; cost: number }> = {};
  let totalCalls = 0;
  let totalCost = 0;

  for (let d = 1; d <= daysInMonth; d++) {
    const dateKey = `${month}${pad2(d)}`;
    const daily = await getDailyUsage(kv, apiKey, dateKey);
    if (!daily) continue;

    totalCalls += daily.count;
    totalCost += daily.cost;

    for (const [tool, count] of Object.entries(daily.tools)) {
      if (!perTool[tool]) perTool[tool] = { calls: 0, cost: 0 };
      perTool[tool].calls += count;
      perTool[tool].cost += getToolCost(tool) * count;
    }
  }

  return {
    month,
    totalCalls,
    totalCost,
    perTool,
  };
}

// ───── Helpers ─────

export function pad2(n: number): string {
  return n < 10 ? '0' + n : '' + n;
}
