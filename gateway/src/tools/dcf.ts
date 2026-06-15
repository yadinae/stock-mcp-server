/**
 * DCF Valuation Model — Two-stage Discounted Cash Flow
 *
 * Ported from UZI-Skill fin_models.py with A-share defaults:
 * - Risk-free rate: 2.5% (10Y Chinese gov bond)
 * - Equity risk premium: 6% (A-share historical)
 * - Tax rate: 25% (standard, 15% for 高新 tech)
 * - Terminal growth: 2.5% (approx long-term GDP)
 */

import type { DcfResult, FinancialSnapshot } from "../types";

// ───── A-Share Defaults ─────

const DEFAULT_RF = 0.025;        // 10Y CGB yield
const DEFAULT_ERP = 0.06;        // A-share equity risk premium
const DEFAULT_BETA = 1.0;
const DEFAULT_TAX = 0.25;
const DEFAULT_TERMINAL_G = 0.025;
const DEFAULT_STAGE1_YEARS = 5;
const DEFAULT_STAGE2_YEARS = 5;
const DEFAULT_STAGE1_GROWTH = 0.10;
const DEFAULT_STAGE2_GROWTH = 0.05;
const DEFAULT_COST_OF_DEBT = 0.045;
const DEFAULT_TARGET_DEBT_RATIO = 0.30;

// ───── WACC Calculation ─────

function computeWacc(opts: {
  rf?: number; erp?: number; beta?: number;
  kd_pretax?: number; target_debt_ratio?: number; tax?: number;
}) {
  const rf = opts.rf ?? DEFAULT_RF;
  const erp = opts.erp ?? DEFAULT_ERP;
  const beta = opts.beta ?? DEFAULT_BETA;
  const kd = opts.kd_pretax ?? DEFAULT_COST_OF_DEBT;
  const debtRatio = opts.target_debt_ratio ?? DEFAULT_TARGET_DEBT_RATIO;
  const tax = opts.tax ?? DEFAULT_TAX;

  const costOfEquity = rf + beta * erp;
  const afterTaxKd = kd * (1 - tax);
  const equityWeight = 1 - debtRatio;
  const wacc = equityWeight * costOfEquity + debtRatio * afterTaxKd;

  return {
    wacc: +wacc.toFixed(4),
    cost_of_equity: +costOfEquity.toFixed(4),
    after_tax_kd: +afterTaxKd.toFixed(4),
    equity_weight: equityWeight,
    debt_weight: debtRatio,
    inputs: { rf, erp, beta, kd_pretax: kd, tax },
  };
}

// ───── Sensitivity Table (5x5) ─────

function buildSensitivity(
  baseFcf: number, wacc: number, terminalG: number,
  stage1Growth: number, stage2Growth: number,
  sharesYi: number, netDebtYi: number,
): Record<string, Record<string, number>> {
  const waccRange = [wacc - 0.02, wacc - 0.01, wacc, wacc + 0.01, wacc + 0.02];
  const growthRange = [
    stage1Growth - 0.04, stage1Growth - 0.02,
    stage1Growth, stage1Growth + 0.02, stage1Growth + 0.04,
  ];

  const table: Record<string, Record<string, number>> = {};
  for (const g of growthRange) {
    const rowKey = `g_${(g * 100).toFixed(0)}`;
    table[rowKey] = {};
    for (const w of waccRange) {
      const colKey = `w_${(w * 100).toFixed(1)}`;
      const ev = computeEnterpriseValue(baseFcf, w, terminalG, g, stage2Growth, 5, 5);
      const eq = ev - netDebtYi;
      const perShare = sharesYi > 0 ? eq / sharesYi : 0;
      table[rowKey][colKey] = +perShare.toFixed(2);
    }
  }
  return table;
}

// ───── Enterprise Value Computation ─────

function computeEnterpriseValue(
  fcf0: number, wacc: number, terminalG: number,
  stage1G: number, stage2G: number,
  stage1Years: number, stage2Years: number,
): number {
  const projectedFcf: number[] = [];
  let cur = fcf0;

  // Stage 1: high growth
  for (let i = 0; i < stage1Years; i++) {
    cur *= (1 + stage1G);
    projectedFcf.push(+cur.toFixed(3));
  }
  // Stage 2: transitional
  for (let i = 0; i < stage2Years; i++) {
    cur *= (1 + stage2G);
    projectedFcf.push(+cur.toFixed(3));
  }

  // Discount
  let pvExplicit = 0;
  for (let i = 0; i < projectedFcf.length; i++) {
    const df = 1 / Math.pow(1 + wacc, i + 1);
    pvExplicit += projectedFcf[i] * df;
  }

  // Terminal value (Gordon Growth)
  const terminalFcf = projectedFcf[projectedFcf.length - 1] * (1 + terminalG);
  const tvAtEnd = (wacc - terminalG) > 0 ? terminalFcf / (wacc - terminalG) : 0;
  const tvPv = tvAtEnd / Math.pow(1 + wacc, projectedFcf.length);

  return +(pvExplicit + tvPv).toFixed(3);
}

// ───── Main DCF Entry Point ─────

export interface DcfInput {
  fin: FinancialSnapshot;
  currentPrice: number;
  /** Override assumptions (optional) */
  assumptions?: {
    stage1Growth?: number;
    stage2Growth?: number;
    terminalGrowth?: number;
    stage1Years?: number;
    stage2Years?: number;
    beta?: number;
    riskFreeRate?: number;
    equityRiskPremium?: number;
    tax?: number;
    targetDebtRatio?: number;
  };
}

export function computeDcf(input: DcfInput): DcfResult {
  const { fin, currentPrice } = input;
  const a = input.assumptions ?? {};

  // ─── Determine base FCF ───
  let fcf0 = fin.fcff_back !== 0 ? fin.fcff_back : fin.fcff_forward;
  if (fcf0 === 0) {
    // Approximate from revenue * net_margin * 0.8
    fcf0 = fin.revenue * (fin.net_margin / 100) * 0.8;
  }
  if (fcf0 === 0) {
    // Last resort: market_cap * 5% yield
    fcf0 = currentPrice * fin.shares_outstanding * 0.05;
  }

  // ─── Growth Rates ───
  // Historical revenue growth (CAGR from 5 periods)
  let histGrowth = DEFAULT_STAGE1_GROWTH;
  if (fin.revenue_history.length >= 2) {
    const first = fin.revenue_history[0];
    const last = fin.revenue_history[fin.revenue_history.length - 1];
    if (first > 0) {
      const cagr = Math.pow(last / first, 1 / (fin.revenue_history.length - 1)) - 1;
      histGrowth = Math.max(0.01, Math.min(0.30, cagr));
    }
  }

  const stage1G = a.stage1Growth ?? histGrowth;
  const stage2G = a.stage2Growth ?? (stage1G / 2);
  const terminalG = a.terminalGrowth ?? DEFAULT_TERMINAL_G;
  const stage1Years = a.stage1Years ?? DEFAULT_STAGE1_YEARS;
  const stage2Years = a.stage2Years ?? DEFAULT_STAGE2_YEARS;
  const rf = a.riskFreeRate ?? DEFAULT_RF;
  const erp = a.equityRiskPremium ?? DEFAULT_ERP;
  const beta = a.beta ?? DEFAULT_BETA;
  const tax = a.tax ?? DEFAULT_TAX;
  const debtRatio = a.targetDebtRatio ?? DEFAULT_TARGET_DEBT_RATIO;
  const kd = DEFAULT_COST_OF_DEBT;

  // ─── WACC ───
  const waccInfo = computeWacc({ rf, erp, beta, kd_pretax: kd, target_debt_ratio: debtRatio, tax });
  const wacc = waccInfo.wacc;

  // ─── Net Debt (using total liabilities as approximation) ───
  // If we don't have cash data, use total liabilities * 0.3 as rough net debt
  const netDebtYi = fin.total_liabilities * 0.3 / 1e8; // 元 → 亿元
  const sharesYi = fin.shares_outstanding / 1e8;        // 股 → 亿股
  const fcfYi = fcf0 / 1e8;                             // 元 → 亿元

  // ─── Enterprise Value ───
  const ev = computeEnterpriseValue(fcfYi, wacc, terminalG, stage1G, stage2G, stage1Years, stage2Years);
  const equityValue = ev - netDebtYi;
  const intrinsicPerShare = sharesYi > 0 ? equityValue / sharesYi : 0;

  // ─── Safety Margin ───
  const safetyMarginPct = currentPrice > 0
    ? +((intrinsicPerShare - currentPrice) / currentPrice * 100).toFixed(1)
    : 0;

  // ─── Verdict ───
  let verdict: string;
  if (safetyMarginPct > 20) {
    verdict = "🟢 低估 — 安全边际充足 (>20%)";
  } else if (safetyMarginPct > 0) {
    verdict = "🟡 合理偏低 — 轻度低估";
  } else if (safetyMarginPct > -20) {
    verdict = "🟠 合理偏高 — 轻度高估";
  } else {
    verdict = "🔴 高估 — 安全边际为负 (<-20%)";
  }

  // ─── Sensitivity ───
  const sensitivity = buildSensitivity(
    fcfYi, wacc, terminalG, stage1G, stage2G, sharesYi, netDebtYi,
  );

  return {
    code: fin.code,
    name: fin.name,
    assumptions: {
      stage1_growth: +stage1G.toFixed(4),
      stage2_growth: +stage2G.toFixed(4),
      terminal_growth: terminalG,
      wacc: +wacc.toFixed(4),
      stage1_years: stage1Years,
      stage2_years: stage2Years,
      risk_free_rate: rf,
      beta,
      equity_risk_premium: erp,
    },
    enterprise_value: +ev.toFixed(2),
    net_debt: +netDebtYi.toFixed(2),
    equity_value: +equityValue.toFixed(2),
    intrinsic_per_share: +intrinsicPerShare.toFixed(2),
    current_price: currentPrice,
    safety_margin_pct: safetyMarginPct,
    verdict,
    sensitivity,
    methodology_log: [
      `基于 ${fin.name}(${fin.code}) ${fin.report_date} 财务数据`,
      `FCF base: ¥${(fcf0 / 1e8).toFixed(2)}亿`,
      `营收历史增长率: ${(histGrowth * 100).toFixed(1)}% → 采用 ${(stage1G * 100).toFixed(1)}% 作为高增阶段`,
      `WACC 计算: Rf=${(rf * 100).toFixed(1)}% + β=${beta} × ERP=${(erp * 100).toFixed(1)}% → ${(wacc * 100).toFixed(2)}%`,
      `5年高增(${(stage1G * 100).toFixed(0)}%) + 5年过渡(${(stage2G * 100).toFixed(0)}%) + 永续(${(terminalG * 100).toFixed(1)}%)`,
      `内含价值: ¥${intrinsicPerShare.toFixed(2)}/股 vs 现价: ¥${currentPrice.toFixed(2)}`,
      `安全边际: ${safetyMarginPct > 0 ? '+' : ''}${safetyMarginPct}%`,
    ],
  };
}
