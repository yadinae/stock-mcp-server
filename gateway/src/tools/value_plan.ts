/**
 * Value Creation Plan — 价值创造计划 (EBITDA Bridge)
 *
 * Ported from UZI-Skill deep_analysis_methods.py build_value_creation_plan()
 *
 * Generates a 5-year value creation roadmap with 5 levers:
 *   - Organic growth (market share)
 *   - Cross-sell (new products)
 *   - Pricing optimization
 *   - COGS / supply chain
 *   - Working capital efficiency
 *
 * Output: current → lever-by-lever impact → target EBITDA
 */

import type { FinancialSnapshot } from "../types";

// ───── Types ─────

export interface ValueLever {
  category: string;
  lever: string;
  current_state: string;
  target_state: string;
  ebitda_impact_yi: number;
  timeline: string;
  confidence: "High" | "Medium" | "Low";
}

export interface ValuePlanResult {
  method: string;
  code: string;
  name: string;
  current_ebitda_yi: number;
  current_margin_pct: number;
  levers: ValueLever[];
  total_uplift_yi: number;
  target_ebitda_yi: number;
  target_margin_pct: number;
  hundred_day_priorities: string[];
  methodology_log: string[];
}

// ───── Value Creation Plan ─────

export function buildValuePlan(
  code: string,
  name: string,
  fin: FinancialSnapshot,
): ValuePlanResult {
  const rev = Math.abs(fin.revenue || 0) / 1e8;
  const netMargin = fin.net_margin || 10;

  // Estimate EBITDA from net profit (rough: ebitda ≈ net_profit * 1.3 + depreciation 20%)
  const operatingProfit = Math.abs(fin.operating_profit || 0) / 1e8;
  const netProfit = Math.abs(fin.net_profit || 0) / 1e8;
  const ebitdaEst = Math.max(operatingProfit, netProfit * 1.3);
  const ebitdaMargin = rev > 0 ? (ebitdaEst / rev) * 100 : 0;

  // 5 value creation levers
  const levers: ValueLever[] = [
    {
      category: "Revenue · Organic Growth",
      lever: "现有市场渗透率提升",
      current_state: `营收 ${rev.toFixed(1)} 亿`,
      target_state: "5 年内提升 +3pp 市场份额",
      ebitda_impact_yi: +(rev * 0.03 * 0.25).toFixed(2),
      timeline: "Y1-Y5",
      confidence: "Medium",
    },
    {
      category: "Revenue · Cross-Sell",
      lever: "新产品/新渠道交叉销售",
      current_state: "核心产品驱动",
      target_state: "5 年新增 20% 营收占比",
      ebitda_impact_yi: +(rev * 0.20 * 0.20).toFixed(2),
      timeline: "Y2-Y5",
      confidence: "Medium",
    },
    {
      category: "Margin · Pricing Power",
      lever: "定价优化 / 产品升级",
      current_state: `净利率 ${netMargin.toFixed(1)}%`,
      target_state: "+300bps",
      ebitda_impact_yi: +(rev * 0.03).toFixed(2),
      timeline: "Y1-Y3",
      confidence: "High",
    },
    {
      category: "Margin · COGS",
      lever: "采购集中 + 供应链优化",
      current_state: "现有采购模式",
      target_state: "−200bps COGS",
      ebitda_impact_yi: +(rev * 0.02).toFixed(2),
      timeline: "Y1-Y2",
      confidence: "High",
    },
    {
      category: "Capital Efficiency",
      lever: "营运资本优化",
      current_state: "现有运转效率",
      target_state: "存货周转 +20%",
      ebitda_impact_yi: +(rev * 0.01).toFixed(2),
      timeline: "Y1-Y3",
      confidence: "Medium",
    },
  ];

  const totalUplift = levers.reduce((s, l) => s + l.ebitda_impact_yi, 0);
  const targetEbitda = ebitdaEst + totalUplift;
  const targetMargin = rev > 0 ? (targetEbitda / rev) * 100 : 0;

  return {
    method: "Value Creation Plan (EBITDA Bridge) — 价值创造计划",
    code,
    name,
    current_ebitda_yi: +ebitdaEst.toFixed(2),
    current_margin_pct: +ebitdaMargin.toFixed(1),
    levers,
    total_uplift_yi: +totalUplift.toFixed(2),
    target_ebitda_yi: +targetEbitda.toFixed(2),
    target_margin_pct: +targetMargin.toFixed(1),
    hundred_day_priorities: [
      "Day 30 · 财务 QoE 验证",
      "Day 60 · 关键绩效指标 Baseline 建立",
      "Day 90 · 季度业务复盘仪表盘上线",
    ],
    methodology_log: [
      `Step 1 · 现 EBITDA ${ebitdaEst.toFixed(1)} 亿 (${ebitdaMargin.toFixed(0)}% 利润率)`,
      `Step 2 · 5 大杠杆合计加厚 ${totalUplift.toFixed(1)} 亿`,
      `Step 3 · 目标 EBITDA ${targetEbitda.toFixed(1)} 亿 (${targetMargin.toFixed(0)}%)`,
      `Step 4 · ${ebitdaMargin > 0 ? `+${((targetMargin - ebitdaMargin) / ebitdaMargin * 100).toFixed(0)}% 利润率改善` : 'N/A (基期为负)'}`,
    ],
  };
}
