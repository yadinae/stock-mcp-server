/**
 * DD Checklist — 尽调清单
 *
 * Ported from UZI-Skill deep_analysis_methods.py build_dd_checklist()
 *
 * Auto-generates a due diligence checklist across 5 workstreams
 * and infers completion status from available data.
 */

import type { FinancialSnapshot, DcfResult, RiskReport, TrapReport } from "../types";

// ───── Types ─────

export interface DdItem {
  item: string;
  status: string; // ✅ 已有数据 | ❌ 缺失 | ⚪ 需人工核查
}

export interface DdWorkstream {
  workstream: string;
  items: DdItem[];
}

export interface DdChecklistResult {
  method: string;
  code: string;
  name: string;
  workstreams: DdWorkstream[];
  total_items: number;
  items_auto_verified: number;
  completion_pct: number;
  manual_review_required: number;
  methodology_log: string[];
}

function check(has: boolean): string {
  return has ? "✅ 已有数据" : "❌ 缺失";
}

// ───── DD Checklist ─────

export function buildDdChecklist(
  code: string,
  name: string,
  fin: FinancialSnapshot | null,
  dcf: DcfResult | null,
  trap: TrapReport | null,
  risk: RiskReport | null,
): DdChecklistResult {
  const hasFin = fin !== null && fin.code !== "";
  const hasDcf = dcf !== null;
  const hasTrap = trap !== null;
  const hasRisk = risk !== null;

  const workstreams: DdWorkstream[] = [
    {
      workstream: "财务尽调 (Financial DD)",
      items: [
        { item: "5 年营收 / 净利历史", status: check(hasFin && (fin?.revenue_history?.length || 0) >= 3) },
        { item: "ROE / 净利率", status: check(hasFin && (fin?.net_margin || 0) > 0) },
        { item: "资产负债率", status: check(hasFin && (fin?.total_liabilities || 0) > 0) },
        { item: "自由现金流", status: check(hasFin && ((fin?.fcff_forward || 0) > 0 || (fin?.fcff_back || 0) > 0)) },
        { item: "DCF 估值", status: check(hasDcf && (dcf?.intrinsic_per_share || 0) > 0) },
        { item: "EPS / BPS", status: check(hasFin && (fin?.eps || 0) > 0) },
        { item: "审计意见 / 会计政策", status: "⚪ 需人工核查" },
      ],
    },
    {
      workstream: "商业尽调 (Commercial DD)",
      items: [
        { item: "毛利率 / 净利率", status: check(hasFin && (fin?.net_margin || 0) > 0) },
        { item: "营收规模", status: check(hasFin && (fin?.revenue || 0) > 0) },
        { item: "竞争格局（可比公司分析）", status: "⚪ 需人工分析" },
        { item: "客户集中度", status: "⚪ 需年报披露" },
        { item: "上下游议价能力", status: "⚪ 需行业研究" },
      ],
    },
    {
      workstream: "法律尽调 (Legal DD)",
      items: [
        { item: "ST / 退市风险", status: check(hasRisk && (risk?.is_st || false) === false) },
        { item: "股权结构", status: "⚪ 需公开披露核查" },
        { item: "重大诉讼", status: "⚪ 需披露核查" },
        { item: "关联交易", status: "⚪ 需年报披露" },
        { item: "面值退市风险", status: check(hasRisk && (risk?.signals || []).some((s) => s.dimension === "面值退市" && s.level < 2)) },
      ],
    },
    {
      workstream: "运营尽调 (Operational DD)",
      items: [
        { item: "K 线形态分析", status: "✅ 已有数据" },
        { item: "技术面趋势（均线/MACD/RSI）", status: "✅ 已有数据" },
        { item: "成交量分析", status: "✅ 已有数据" },
        { item: "杀猪盘排查", status: check(hasTrap && trap.trap_level !== "unknown") },
        { item: "龙虎榜游资追踪", status: "✅ 已有数据" },
        { item: "管理层背景", status: "⚪ 需人工核查" },
      ],
    },
    {
      workstream: "市场尽调 (Market DD)",
      items: [
        { item: "新闻舆情扫描", status: "✅ 已有数据" },
        { item: "AI 综合分析", status: "✅ 已有数据" },
        { item: "技术面信号", status: "✅ 已有数据" },
        { item: "量价关系分析", status: "✅ 已有数据" },
      ],
    },
  ];

  const totalItems = workstreams.reduce((s, ws) => s + ws.items.length, 0);
  const done = workstreams.reduce((s, ws) => s + ws.items.filter((it) => it.status.includes("✅")).length, 0);
  const pct = totalItems > 0 ? Math.round((done / totalItems) * 100) : 0;

  return {
    method: "Due Diligence Checklist — 尽调清单",
    code,
    name,
    workstreams,
    total_items: totalItems,
    items_auto_verified: done,
    completion_pct: pct,
    manual_review_required: totalItems - done,
    methodology_log: [
      `Step 1 · 生成 5 大工作流 ${totalItems} 条尽调清单`,
      `Step 2 · 基于现有数据自动完成 ${done} 项`,
      `Step 3 · ${totalItems - done} 项需人工核查（${pct}% 自动完成）`,
    ],
  };
}
