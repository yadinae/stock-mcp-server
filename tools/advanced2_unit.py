#!/usr/bin/env python3
"""基本面分析工具（独立文件，避免与 advanced2.py 冲突）

移植自 Gateway tools/unit_econ.ts / value_plan.ts，纯规则实现，零 LLM：
- unit_economics: 单元经济分析 — SaaS/订阅类（名称含 软件/云/科技/传媒/数据 等）输出
  ARPU/LTV/CAC/回本周期；制造/消费/贸易等非 recurring 输出毛利瀑布分解
- value_creation_plan: 价值创造计划 — EBITDA Bridge，5 大价值杠杆
  （有机增长/交叉销售/定价优化/供应链/营运资本）

输入 fin 字典来自 data_sources.em_market.fetch_financials(code)：
  revenue / net_profit / operating_profit / net_margin(百分比) / total_liabilities /
  shares_outstanding 等，金额单位均为元（元 → 亿 换算 /1e8）。
两个函数均接受 fin dict；若传入字符串 code，则内部自动拉取财务数据。
"""
import json


# ─── 行业分类 ───

# 提示 recurring/SaaS 商业模式的名称关键词
RECURRING_KEYWORDS = ["软件", "服务", "云", "互联网", "SaaS", "科技", "传媒", "通信", "数据"]


def _f(v, default=0.0):
    """安全转 float，容忍 None / 字符串 / 非数字。"""
    if v is None:
        return float(default)
    try:
        return float(v)
    except (TypeError, ValueError):
        return float(default)


def _fetch_fin(fin):
    """兼容 str code 与 dict 两种入参。"""
    if isinstance(fin, str):
        from data_sources import em_market
        return em_market.fetch_financials(fin)
    return fin or {}


def is_recurring_business(name: str) -> bool:
    """按名称关键词判断是否为 recurring/SaaS 商业模式。"""
    name = name or ""
    return any(kw in name for kw in RECURRING_KEYWORDS)


# ─── unit_economics: 单元经济分析 ───

def unit_economics(fin) -> dict:
    """单元经济分析。

    Args: fin=财务报表字典（em_market.fetch_financials 输出），或股票代码字符串
    返回: SaaS/订阅类 → ARPU/LTV/CAC/回本周期；非 recurring → 毛利瀑布分解
    """
    fin = _fetch_fin(fin)
    if not fin or fin.get("error"):
        return {"error": (fin or {}).get("error", "无财务数据")}
    code = str(fin.get("code", ""))
    name = str(fin.get("name", "") or "")
    if is_recurring_business(name):
        return _build_saas_unit_economics(code, name, fin)
    return _build_non_recurring_unit_economics(code, name, fin)


def _build_saas_unit_economics(code: str, name: str, fin: dict) -> dict:
    """SaaS / recurring 商业模式：ARPU / LTV / CAC / 回本周期估算。"""
    revenue_yi = abs(_f(fin.get("revenue"))) / 1e8
    net_margin = _f(fin.get("net_margin"))
    # 净利率为正时按 净利率+20pp 估算毛利率，上限 85%；否则给默认 50%
    gross_margin = min(net_margin + 20, 85) if net_margin > 0 else 50

    # SaaS 代理指标（无真实用户数据，用固定假设）
    customer_count = 1000
    arpu = revenue_yi / customer_count if customer_count else 0.0
    churn_rate = 0.15  # 年流失率默认 15%
    ltv = (arpu * gross_margin / 100) / churn_rate if churn_rate > 0 else 0.0
    cac = arpu * 0.5  # 粗略代理: CAC ≈ 年 ARPU 的 50%
    ltv_cac = ltv / cac if cac > 0 else 0.0
    monthly_gross = arpu * gross_margin / 100 / 12
    payback_months = cac / monthly_gross if monthly_gross > 0 else 0.0

    healthy = ltv_cac >= 3 and payback_months <= 24
    verdict = "🟢 健康 — LTV/CAC ≥ 3x，回本周期 ≤ 24个月" if healthy else "🔴 不健康 — LTV/CAC 或回本周期不达标"

    return {
        "method": "Unit Economics (SaaS/recurring)",
        "code": code,
        "name": name,
        "business_type": "recurring",
        "metrics": {
            "revenue_yi": round(revenue_yi, 2),
            "gross_margin_pct": round(gross_margin, 1),
            "net_margin_pct": round(net_margin, 1),
            "arpu_yi": round(arpu, 4),
            "churn_rate_pct": round(churn_rate * 100, 1),
            "ltv_yi": round(ltv, 4),
            "cac_yi": round(cac, 4),
            "ltv_cac_ratio": round(ltv_cac, 2),
            "payback_months": round(payback_months, 1),
            "customer_count_est": customer_count,
        },
        "verdict": verdict,
        "healthy": healthy,
        "methodology_log": [
            f"Step 1 · 估计营收 {revenue_yi:.2f} 亿 · 毛利率 {gross_margin:.0f}% · 净利率 {net_margin:.0f}%",
            f"Step 2 · ARPU {arpu:.4f} 亿 · 年流失率 {churn_rate * 100:.0f}%",
            f"Step 3 · LTV {ltv:.2f} / CAC {cac:.2f} = {ltv_cac:.1f}x",
            f"Step 4 · 回本周期 {payback_months:.0f} 个月",
            f"Step 5 · 结论: {'健康' if healthy else '需改善'}",
        ],
    }


def _build_non_recurring_unit_economics(code: str, name: str, fin: dict) -> dict:
    """非 recurring 商业模式：毛利瀑布分解。"""
    revenue_yi = abs(_f(fin.get("revenue"))) / 1e8
    net_margin = _f(fin.get("net_margin")) or 10
    # 估算: 毛利率 ≈ 净利率 * 2 + 10pp，上限 80%
    gross_margin = min(net_margin * 2 + 10, 80)
    opex_pct = max(0.0, gross_margin - net_margin)

    waterfall = [
        {"stage": "收入", "value": 100, "label": "100%"},
        {"stage": "毛利", "value": round(gross_margin, 1), "label": f"{gross_margin:.0f}%"},
        {"stage": "运营费用", "value": round(opex_pct, 1), "label": f"{opex_pct:.0f}%"},
        {"stage": "净利", "value": round(net_margin, 1), "label": f"{net_margin:.0f}%"},
    ]
    if net_margin > 15:
        verdict = "🟢 盈利能力良好 — 净利率 > 15%"
        conclusion = "盈利健康"
    elif net_margin > 5:
        verdict = "🟡 盈利能力一般 — 净利率 5%-15%"
        conclusion = "盈利一般"
    else:
        verdict = "🔴 盈利能力偏弱 — 净利率 < 5%"
        conclusion = "盈利偏弱"

    return {
        "method": "Margin Decomposition (毛利瀑布分解)",
        "code": code,
        "name": name,
        "business_type": "non-recurring",
        "metrics": {
            "revenue_yi": round(revenue_yi, 2),
            "net_margin_pct": round(net_margin, 1),
            "opex_pct_of_revenue": round(opex_pct, 1),
            "gross_margin_pct": round(gross_margin, 1),
        },
        "verdict": verdict,
        "waterfall": waterfall,
        "methodology_log": [
            f"Step 1 · 营收 {revenue_yi:.2f} 亿",
            f"Step 2 · 毛利约 {gross_margin:.0f}% · 运营费率 {opex_pct:.0f}% · 净利率 {net_margin:.0f}%",
            f"Step 3 · 结论: {conclusion}",
        ],
    }


# ─── value_creation_plan: 价值创造计划 (EBITDA Bridge) ───

def value_creation_plan(fin) -> dict:
    """价值创造计划 — EBITDA Bridge，5 大价值杠杆。

    Args: fin=财务报表字典（em_market.fetch_financials 输出），或股票代码字符串
    返回: current/target EBITDA + 5 杠杆影响 + 百日优先级 + methodology_log
    """
    fin = _fetch_fin(fin)
    if not fin or fin.get("error"):
        return {"error": (fin or {}).get("error", "无财务数据")}
    code = str(fin.get("code", ""))
    name = str(fin.get("name", "") or "")
    return _build_value_plan(code, name, fin)


def _build_value_plan(code: str, name: str, fin: dict) -> dict:
    rev = abs(_f(fin.get("revenue"))) / 1e8
    net_margin = _f(fin.get("net_margin")) or 10

    # 估算 EBITDA: max(营业利润, 净利润 * 1.3)（净利润口径粗估折旧摊销等回加）
    operating_profit_yi = abs(_f(fin.get("operating_profit"))) / 1e8
    net_profit_yi = abs(_f(fin.get("net_profit"))) / 1e8
    ebitda_est = max(operating_profit_yi, net_profit_yi * 1.3)
    ebitda_margin = (ebitda_est / rev * 100) if rev > 0 else 0.0

    # 5 大价值杠杆: ebitda_impact_yi = rev * pct * margin
    levers = [
        {
            "category": "Revenue · Organic Growth",
            "lever": "现有市场渗透率提升",
            "current_state": f"营收 {rev:.1f} 亿",
            "target_state": "5 年内提升 +3pp 市场份额",
            "ebitda_impact_yi": round(rev * 0.03 * 0.25, 2),
            "timeline": "Y1-Y5",
            "confidence": "Medium",
        },
        {
            "category": "Revenue · Cross-Sell",
            "lever": "新产品/新渠道交叉销售",
            "current_state": "核心产品驱动",
            "target_state": "5 年新增 20% 营收占比",
            "ebitda_impact_yi": round(rev * 0.20 * 0.20, 2),
            "timeline": "Y2-Y5",
            "confidence": "Medium",
        },
        {
            "category": "Margin · Pricing Power",
            "lever": "定价优化 / 产品升级",
            "current_state": f"净利率 {net_margin:.1f}%",
            "target_state": "+300bps",
            "ebitda_impact_yi": round(rev * 0.03 * 1.0, 2),
            "timeline": "Y1-Y3",
            "confidence": "High",
        },
        {
            "category": "Margin · COGS",
            "lever": "采购集中 + 供应链优化",
            "current_state": "现有采购模式",
            "target_state": "−200bps COGS",
            "ebitda_impact_yi": round(rev * 0.02 * 1.0, 2),
            "timeline": "Y1-Y2",
            "confidence": "High",
        },
        {
            "category": "Capital Efficiency",
            "lever": "营运资本优化",
            "current_state": "现有运转效率",
            "target_state": "存货周转 +20%",
            "ebitda_impact_yi": round(rev * 0.01 * 1.0, 2),
            "timeline": "Y1-Y3",
            "confidence": "Medium",
        },
    ]

    total_uplift = round(sum(l["ebitda_impact_yi"] for l in levers), 2)
    target_ebitda = ebitda_est + total_uplift
    target_margin = (target_ebitda / rev * 100) if rev > 0 else 0.0

    if ebitda_margin > 0:
        margin_gain = f"+{((target_margin - ebitda_margin) / ebitda_margin * 100):.0f}% 利润率改善"
    else:
        margin_gain = "N/A (基期为负)"

    return {
        "method": "Value Creation Plan (EBITDA Bridge) — 价值创造计划",
        "code": code,
        "name": name,
        "current_ebitda_yi": round(ebitda_est, 2),
        "current_margin_pct": round(ebitda_margin, 1),
        "levers": levers,
        "total_uplift_yi": total_uplift,
        "target_ebitda_yi": round(target_ebitda, 2),
        "target_margin_pct": round(target_margin, 1),
        "hundred_day_priorities": [
            "Day 30 · 财务 QoE 验证",
            "Day 60 · 关键绩效指标 Baseline 建立",
            "Day 90 · 季度业务复盘仪表盘上线",
        ],
        "methodology_log": [
            f"Step 1 · 现 EBITDA {ebitda_est:.1f} 亿 ({ebitda_margin:.0f}% 利润率)",
            f"Step 2 · 5 大杠杆合计加厚 {total_uplift:.1f} 亿",
            f"Step 3 · 目标 EBITDA {target_ebitda:.1f} 亿 ({target_margin:.0f}%)",
            f"Step 4 · {margin_gain}",
        ],
    }


if __name__ == "__main__":
    import sys
    test = sys.argv[1] if len(sys.argv) > 1 else "unit"
    code = sys.argv[2] if len(sys.argv) > 2 else "600519"
    from data_sources import em_market
    fin = em_market.fetch_financials(code)
    if test == "unit":
        print(json.dumps(unit_economics(fin), ensure_ascii=False, default=str)[:800])
    elif test == "value":
        print(json.dumps(value_creation_plan(fin), ensure_ascii=False, default=str)[:800])
    elif test == "both":
        print(json.dumps({"unit": unit_economics(fin), "value": value_creation_plan(fin)},
                         ensure_ascii=False, default=str)[:1600])
