/**
 * Unit Economics — 单元经济分析
 *
 * Ported from UZI-Skill deep_analysis_methods.py
 *
 * For SaaS/recurring business:
 *   ARPU / LTV / CAC / Payback period
 *
 * For non-recurring (manufacturing, trading, etc.):
 *   Gross margin waterfall decomposition
 */

import type { FinancialSnapshot } from "../types";

// ───── Types ─────

export interface UnitEconResult {
  method: string;
  code: string;
  name: string;
  business_type: "recurring" | "non-recurring";
  metrics: Record<string, number | string | boolean>;
  verdict: string;
  waterfall?: MarginStage[];
  healthy?: boolean;
  methodology_log: string[];
}

interface MarginStage {
  stage: string;
  value: number;
  label: string;
}

// ───── Industry Classification ─────

// Keywords that suggest recurring/SaaS business model
const RECURRING_KEYWORDS = ["软件", "服务", "云", "互联网", "SaaS", "科技", "传媒", "通信"];

function isRecurringBusiness(name: string): boolean {
  return RECURRING_KEYWORDS.some((kw) => name.includes(kw));
}

// ───── Unit Economics ─────

export function buildUnitEconomics(
  code: string,
  name: string,
  fin: FinancialSnapshot,
): UnitEconResult {
  const recurring = isRecurringBusiness(name);

  if (recurring) {
    return buildSaaSUnitEconomics(code, name, fin);
  }
  return buildNonRecurringUnitEconomics(code, name, fin);
}

/**
 * SaaS / recurring business model
 * Computes ARPU, LTV, CAC, payback period
 */
function buildSaaSUnitEconomics(
  code: string,
  name: string,
  fin: FinancialSnapshot,
): UnitEconResult {
  const revenueYi = Math.abs(fin.revenue || 0) / 1e8;
  const grossMargin = fin.net_margin > 0
    ? Math.min(fin.net_margin + 20, 85) // estimate gross margin from net margin
    : 50;
  const netMargin = fin.net_margin;

  // SaaS proxy metrics
  const customerCount = 1000; // fallback — we don't have real customer data
  const arpu = revenueYi / customerCount;
  const churnRate = 0.15; // annual churn default
  const ltv = churnRate > 0 ? (arpu * grossMargin / 100) / churnRate : 0;
  const cac = arpu * 0.5; // rough proxy
  const ltvCac = cac > 0 ? ltv / cac : 0;
  const paybackMonths = arpu > 0 ? cac / (arpu * grossMargin / 100 / 12) : 0;
  const healthy = ltvCac >= 3 && paybackMonths <= 24;

  return {
    method: "Unit Economics (SaaS/recurring)",
    code,
    name,
    business_type: "recurring",
    metrics: {
      revenue_yi: +revenueYi.toFixed(2),
      gross_margin_pct: +grossMargin.toFixed(1),
      net_margin_pct: +netMargin.toFixed(1),
      arpu_yi: +arpu.toFixed(4),
      churn_rate_pct: +(churnRate * 100).toFixed(1),
      ltv_yi: +ltv.toFixed(4),
      cac_yi: +cac.toFixed(4),
      ltv_cac_ratio: +ltvCac.toFixed(2),
      payback_months: +paybackMonths.toFixed(1),
      customer_count_est: customerCount,
    },
    verdict: healthy ? "🟢 健康 — LTV/CAC ≥ 3x，回本周期 ≤ 24个月" : "🔴 不健康 — LTV/CAC 或回本周期不达标",
    healthy,
    methodology_log: [
      `Step 1 · 估计营收 ${revenueYi.toFixed(2)} 亿 · 毛利率 ${grossMargin.toFixed(0)}% · 净利率 ${netMargin.toFixed(0)}%`,
      `Step 2 · ARPU ${arpu.toFixed(4)} 亿 · 年流失率 ${(churnRate * 100).toFixed(0)}%`,
      `Step 3 · LTV ${ltv.toFixed(2)} / CAC ${cac.toFixed(2)} = ${ltvCac.toFixed(1)}x`,
      `Step 4 · 回本周期 ${paybackMonths.toFixed(0)} 个月`,
      `Step 5 · 结论: ${healthy ? "健康" : "需改善"}`,
    ],
  };
}

/**
 * Non-recurring business
 * Gross margin waterfall decomposition
 */
function buildNonRecurringUnitEconomics(
  code: string,
  name: string,
  fin: FinancialSnapshot,
): UnitEconResult {
  const revenueYi = Math.abs(fin.revenue || 0) / 1e8;
  const netMargin = fin.net_margin || 10;
  const grossMargin = Math.min(netMargin * 2 + 10, 80); // estimate: net_margin * 2 + 10%, capped at 80%
  const opexPct = Math.max(0, grossMargin - netMargin);

  const waterfall: MarginStage[] = [
    { stage: "收入", value: 100, label: "100%" },
    { stage: "毛利", value: netMargin + opexPct, label: `${(netMargin + opexPct).toFixed(0)}%` },
    { stage: "运营费用", value: opexPct, label: `${opexPct.toFixed(0)}%` },
    { stage: "净利", value: netMargin, label: `${netMargin.toFixed(0)}%` },
  ];

  return {
    method: "Margin Decomposition (毛利瀑布分解)",
    code,
    name,
    business_type: "non-recurring",
    metrics: {
      revenue_yi: +revenueYi.toFixed(2),
      net_margin_pct: +netMargin.toFixed(1),
      opex_pct_of_revenue: +opexPct.toFixed(1),
      gross_margin_pct: +(netMargin + opexPct).toFixed(1),
    },
    verdict: netMargin > 15
      ? "🟢 盈利能力良好 — 净利率 > 15%"
      : netMargin > 5
        ? "🟡 盈利能力一般 — 净利率 5%-15%"
        : "🔴 盈利能力偏弱 — 净利率 < 5%",
    waterfall,
    methodology_log: [
      `Step 1 · 营收 ${revenueYi.toFixed(2)} 亿`,
      `Step 2 · 毛利约 ${(netMargin + opexPct).toFixed(0)}% · 运营费率 ${opexPct.toFixed(0)}% · 净利率 ${netMargin.toFixed(0)}%`,
      `Step 3 · 结论: ${netMargin > 15 ? "盈利健康" : netMargin > 5 ? "盈利一般" : "盈利偏弱"}`,
    ],
  };
}
