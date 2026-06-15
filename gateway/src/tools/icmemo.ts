/**
 * IC Memo — Investment Committee Memorandum
 *
 * Ported from UZI-Skill deep_analysis_methods.py
 * Combines quality scoring + DCF valuation → P0-P4 recommendation
 *
 * Quality × Valuation = Recommendation:
 *   P0 (PASS)         → 强烈建议建仓 (score ≥ 5)
 *   P1 (CONDITIONAL)  → 可建仓但分批 (score ≥ 3)
 *   P2 (HOLD)         → 观望 (score ≥ 0)
 *   P3 (AVOID)        → 回避 (score < 0)
 *   P4 (BLOCKED)      → 禁止 (特殊条件)
 */

import type { FinancialSnapshot, DcfResult, RealtimeQuote } from "../types";

// ───── Quality Score ─────

interface QualityMetrics {
  score: number;
  roe_years_above_15: number;
  fcf_positive: boolean;
  net_margin_pct: number;
  debt_ratio_pct: number;
  revenue_latest_yi: number;
  market_cap_yi: number;
  roe_latest: number;
  pe_ratio: number;
  gross_margin_pct: number;
  total_liabilities_yi: number;
}

function computeFeatures(fin: FinancialSnapshot, quote?: RealtimeQuote): QualityMetrics {
  // Estimate ROE from available data
  const bps = fin.bps || 1;
  const roe = fin.eps && bps > 0 ? (fin.eps / bps) * 100 : 0;

  // Count years with ROE > 15% from EPS history
  let roeYearsAbove15 = 0;
  if (fin.eps_history && fin.bps > 0) {
    for (const eps of fin.eps_history) {
      if (eps / fin.bps > 0.15) roeYearsAbove15++;
    }
  }

  const fcfPositive = (fin.fcff_forward || 0) > 0 || (fin.fcff_back || 0) > 0;
  const netMargin = fin.net_margin || 0;
  const debtRatio = fin.total_liabilities > 0 && fin.revenue > 0
    ? Math.abs(fin.total_liabilities) / Math.abs(fin.revenue) * 100
    : 0;

  const revenueYi = Math.abs(fin.revenue || 0) / 1e8;
  const liabilitiesYi = Math.abs(fin.total_liabilities || 0) / 1e8;
  const marketCapYi = quote?.market_cap
    ? quote.market_cap / 1e8
    : 0;

  const peRatio = quote?.pe_ratio || (fin.eps > 0 && quote?.price ? (quote.price || 0) / fin.eps : 0);

  return {
    score: 0,
    roe_years_above_15: roeYearsAbove15,
    fcf_positive: fcfPositive,
    net_margin_pct: netMargin,
    debt_ratio_pct: debtRatio,
    revenue_latest_yi: revenueYi,
    market_cap_yi: marketCapYi,
    roe_latest: roe,
    pe_ratio: peRatio,
    gross_margin_pct: 0,
    total_liabilities_yi: liabilitiesYi,
  };
}

// ───── IC Memo ─────

export interface IcMemoResult {
  method: string;
  code: string;
  name: string;
  sections: {
    exec_summary: {
      headline: string;
      recommendation: string;
      recommendation_level: string;
      quality_score: number;
      valuation_score: number;
      total_score: number;
      top_risks: RiskItem[];
    };
    company_overview: {
      name: string;
      market_cap_yi: number;
      revenue_latest_yi: number;
      fcf_positive: boolean;
      roe_latest_pct: number;
      net_margin_pct: number;
      debt_ratio_pct: number;
    };
    valuation_summary: {
      dcf_intrinsic: number | null;
      current_price: number;
      safety_margin_pct: number | null;
      dcf_verdict: string | null;
      pe_ratio: number;
    };
    scenarios: Scenario[];
    risks: RiskItem[];
  };
  methodology_log: string[];
}

interface RiskItem {
  risk: string;
  detail: string;
  severity: "High" | "Medium" | "Low";
  mitigant: string;
}

interface Scenario {
  scenario: string;
  price_target: number;
  return_pct: number;
  probability_pct: number;
  assumptions: string;
}

function computeRecommendation(
  features: QualityMetrics,
  dcf: DcfResult | null,
): { headline: string; recommendation: string; level: string; quality_score: number; val_score: number; total: number } {
  let qualityScore = 0;
  if (features.roe_years_above_15 >= 3) qualityScore += 2;
  if (features.fcf_positive) qualityScore += 1;
  if (features.net_margin_pct > 15) qualityScore += 1;
  if (features.debt_ratio_pct < 50) qualityScore += 1; // debt ratio proxy for moat

  let valScore = 0;
  let safetyMargin = 0;
  if (dcf) {
    safetyMargin = dcf.safety_margin_pct || 0;
    if (safetyMargin > 20) valScore = 2;
    else if (safetyMargin > 0) valScore = 1;
    else if (safetyMargin > -20) valScore = 0;
    else valScore = -1;
  }

  const total = qualityScore + valScore;

  if (total >= 5) {
    return {
      headline: "🟢 强烈建议通过 (P0 — PASS)",
      recommendation: "推荐投委会批准建仓 — 高质量 × 安全边际充足",
      level: "P0",
      quality_score: qualityScore,
      val_score: valScore,
      total,
    };
  }
  if (total >= 3) {
    return {
      headline: "🟡 建议通过 (P1 — CONDITIONAL PASS)",
      recommendation: "可批准但建议分批建仓，控制初始仓位",
      level: "P1",
      quality_score: qualityScore,
      val_score: valScore,
      total,
    };
  }
  if (total >= 0) {
    return {
      headline: "⚪ 观望 (P2 — HOLD)",
      recommendation: "暂不建议建仓，等待估值回落或信号强化",
      level: "P2",
      quality_score: qualityScore,
      val_score: valScore,
      total,
    };
  }
  return {
    headline: "🔴 建议回避 (P3 — AVOID)",
    recommendation: "质量或估值不达标 — 投委会建议不进场",
    level: "P3",
    quality_score: qualityScore,
    val_score: valScore,
    total,
  };
}

function computeRisks(features: QualityMetrics): RiskItem[] {
  const risks: RiskItem[] = [];
  if (features.debt_ratio_pct > 60) {
    risks.push({
      risk: "财务杠杆风险",
      detail: `资产负债率 ${features.debt_ratio_pct.toFixed(0)}% 偏高`,
      severity: "High",
      mitigant: "监控利息覆盖倍数与再融资窗口",
    });
  }
  if (features.net_margin_pct < 5) {
    risks.push({
      risk: "盈利能力偏弱",
      detail: `净利率仅 ${features.net_margin_pct.toFixed(1)}%`,
      severity: "Medium",
      mitigant: "跟踪毛利率变化和费用管控措施",
    });
  }
  if (features.pe_ratio > 60) {
    risks.push({
      risk: "估值偏贵",
      detail: `PE ${features.pe_ratio.toFixed(0)}x`,
      severity: "Medium",
      mitigant: "等待 PE 回归合理区间再建仓",
    });
  }
  if (!features.fcf_positive) {
    risks.push({
      risk: "自由现金流为负",
      detail: "经营现金流无法覆盖资本支出",
      severity: "High",
      mitigant: "要求管理层提供现金流改善路线图",
    });
  }
  risks.push({
    risk: "行业周期下行",
    detail: "需求侧宏观冲击可能影响业绩",
    severity: "Medium",
    mitigant: "行业景气度月度跟踪",
  });
  return risks;
}

function computeScenarios(price: number, dcf: DcfResult | null): Scenario[] {
  if (!dcf || price <= 0) return [];
  const intrinsic = dcf.intrinsic_per_share || price;
  return [
    {
      scenario: "Bull (乐观)",
      price_target: +((intrinsic * 1.3).toFixed(2)),
      return_pct: +((((intrinsic * 1.3 - price) / price) * 100).toFixed(1)),
      probability_pct: 25,
      assumptions: "超预期增速 + 估值扩张",
    },
    {
      scenario: "Base (中性)",
      price_target: +(intrinsic.toFixed(2)),
      return_pct: +((((intrinsic - price) / price) * 100).toFixed(1)),
      probability_pct: 50,
      assumptions: "DCF 基础假设",
    },
    {
      scenario: "Bear (悲观)",
      price_target: +((intrinsic * 0.7).toFixed(2)),
      return_pct: +((((intrinsic * 0.7 - price) / price) * 100).toFixed(1)),
      probability_pct: 25,
      assumptions: "增速放缓 + 估值压缩",
    },
  ];
}

export function buildIcMemo(
  code: string,
  name: string,
  fin: FinancialSnapshot,
  dcf: DcfResult | null,
  quote?: RealtimeQuote,
): IcMemoResult {
  const features = computeFeatures(fin, quote);
  const price = quote?.price || dcf?.current_price || 0;
  const rec = computeRecommendation(features, dcf);
  const risks = computeRisks(features);
  const scenarios = computeScenarios(price, dcf);

  return {
    method: "Investment Committee Memo (投委会备忘录)",
    code,
    name,
    sections: {
      exec_summary: {
        headline: rec.headline,
        recommendation: rec.recommendation,
        recommendation_level: rec.level,
        quality_score: rec.quality_score,
        valuation_score: rec.val_score,
        total_score: rec.total,
        top_risks: risks.slice(0, 3),
      },
      company_overview: {
        name,
        market_cap_yi: +features.market_cap_yi.toFixed(2),
        revenue_latest_yi: +features.revenue_latest_yi.toFixed(2),
        fcf_positive: features.fcf_positive,
        roe_latest_pct: +features.roe_latest.toFixed(1),
        net_margin_pct: +features.net_margin_pct.toFixed(1),
        debt_ratio_pct: +features.debt_ratio_pct.toFixed(1),
      },
      valuation_summary: {
        dcf_intrinsic: dcf?.intrinsic_per_share ?? null,
        current_price: price,
        safety_margin_pct: dcf?.safety_margin_pct ?? null,
        dcf_verdict: dcf?.verdict ?? null,
        pe_ratio: +features.pe_ratio.toFixed(1),
      },
      scenarios,
      risks,
    },
    methodology_log: [
      "Step 1 · 提取财务特征（ROE/FCF/净利率/负债率）",
      `Step 2 · 质量评分 ${rec.quality_score}/6（ROE持续≥15% + FCF正 + 净利率>15% + 负债率<50%）`,
      `Step 3 · 估值评分 ${rec.val_score}/2（DCF安全边际>20%=2分, >0%=1分, >-20%=0分）`,
      `Step 4 · 综合 ${rec.quality_score}+${rec.val_score}=${rec.total} → ${rec.level}`,
      `Step 5 · 三情景回报（Bull/Base/Bear）`,
    ],
  };
}
