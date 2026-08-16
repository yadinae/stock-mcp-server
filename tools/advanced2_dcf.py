#!/usr/bin/env python3
"""高级估值工具（2026-08-16，移植自 Gateway src/tools/dcf.ts + src/tools/icmemo.ts）

纯 Python 规则移植，零 LLM 调用，零新数据源：
- dcf_valuation: 两阶段 DCF 估值 — WACC + 5×5 敏感性表 + 安全边际
- ic_memo:       投委会备忘录 — 质量分 × 估值分 → P0-P4 建议

数据来源：em_market.fetch_financials（财务快照）+ tencent.get_realtime_quote（行情）
"""

from __future__ import annotations

# ───── A-Share Defaults ─────

DEFAULT_RF = 0.025                 # 10Y 国债收益率
DEFAULT_ERP = 0.06                 # A股股权风险溢价
DEFAULT_BETA = 1.0
DEFAULT_TAX = 0.25
DEFAULT_TERMINAL_G = 0.025         # 永续增长率
DEFAULT_STAGE1_YEARS = 5
DEFAULT_STAGE2_YEARS = 5
DEFAULT_STAGE1_GROWTH = 0.10
DEFAULT_STAGE2_GROWTH = 0.05
DEFAULT_COST_OF_DEBT = 0.045
DEFAULT_TARGET_DEBT_RATIO = 0.30


# ───── WACC ─────

def _compute_wacc(rf=None, erp=None, beta=None, kd_pretax=None,
                  target_debt_ratio=None, tax=None) -> dict:
    """WACC 计算。对齐 dcf.ts computeWacc。"""
    rf = rf if rf is not None else DEFAULT_RF
    erp = erp if erp is not None else DEFAULT_ERP
    beta = beta if beta is not None else DEFAULT_BETA
    kd = kd_pretax if kd_pretax is not None else DEFAULT_COST_OF_DEBT
    debt_ratio = target_debt_ratio if target_debt_ratio is not None else DEFAULT_TARGET_DEBT_RATIO
    tax = tax if tax is not None else DEFAULT_TAX

    cost_of_equity = rf + beta * erp
    after_tax_kd = kd * (1 - tax)
    equity_weight = 1 - debt_ratio
    wacc = equity_weight * cost_of_equity + debt_ratio * after_tax_kd

    return {
        "wacc": round(wacc, 4),
        "cost_of_equity": round(cost_of_equity, 4),
        "after_tax_kd": round(after_tax_kd, 4),
        "equity_weight": equity_weight,
        "debt_weight": debt_ratio,
        "inputs": {"rf": rf, "erp": erp, "beta": beta, "kd_pretax": kd, "tax": tax},
    }


# ───── Enterprise Value ─────

def _compute_enterprise_value(fcf0, wacc, terminal_g, stage1_g, stage2_g,
                              stage1_years, stage2_years) -> float:
    """两阶段 DCF 企业价值（亿元）。对齐 dcf.ts computeEnterpriseValue。"""
    projected = []
    cur = fcf0

    # Stage 1: high growth
    for _ in range(stage1_years):
        cur *= (1 + stage1_g)
        projected.append(round(cur, 3))
    # Stage 2: transitional
    for _ in range(stage2_years):
        cur *= (1 + stage2_g)
        projected.append(round(cur, 3))

    # Discount
    pv_explicit = 0.0
    for i, fcf in enumerate(projected):
        df = 1 / (1 + wacc) ** (i + 1)
        pv_explicit += fcf * df

    # Terminal value (Gordon Growth)
    terminal_fcf = projected[-1] * (1 + terminal_g)
    tv_at_end = terminal_fcf / (wacc - terminal_g) if (wacc - terminal_g) > 0 else 0
    tv_pv = tv_at_end / (1 + wacc) ** len(projected)

    return round(pv_explicit + tv_pv, 3)


# ───── Sensitivity Table (5x5) ─────

def _build_sensitivity(base_fcf, wacc, terminal_g, stage1_growth, stage2_growth,
                       shares_yi, net_debt_yi) -> dict:
    """5×5 敏感性表：wacc ±2% × growth ±4%。对齐 dcf.ts buildSensitivity。
    返回 {wacc_range, growth_range, table}，table 键如 g_6 / w_7.0。"""
    wacc_range = [
        round(wacc - 0.02, 4), round(wacc - 0.01, 4),
        wacc,
        round(wacc + 0.01, 4), round(wacc + 0.02, 4),
    ]
    growth_range = [
        stage1_growth - 0.04, stage1_growth - 0.02,
        stage1_growth, stage1_growth + 0.02, stage1_growth + 0.04,
    ]

    table = {}
    for g in growth_range:
        row_key = f"g_{round(g * 100)}"
        table[row_key] = {}
        for w in wacc_range:
            col_key = f"w_{round(w * 100, 1)}"
            ev = _compute_enterprise_value(
                base_fcf, w, terminal_g, g, stage2_growth,
                DEFAULT_STAGE1_YEARS, DEFAULT_STAGE2_YEARS,
            )
            eq = ev - net_debt_yi
            per_share = eq / shares_yi if shares_yi > 0 else 0
            table[row_key][col_key] = round(per_share, 2)

    return {"wacc_range": wacc_range, "growth_range": growth_range, "table": table}


# ───── Main DCF ─────

def dcf_valuation(code: str, assumptions: dict = None) -> dict:
    """两阶段 DCF 估值。

    Args:
        code: 股票代码（如 600519）
        assumptions: 可选覆盖参数 dict：
            stage1_growth / stage2_growth / terminal_growth /
            stage1_years / stage2_years / beta / risk_free_rate /
            equity_risk_premium / tax / target_debt_ratio / kd_pretax

    返回: method/code/name/intrinsic_per_share/current_price/safety_margin_pct/
          wacc/sensitivity/methodology_log（另附 verdict/assumptions/ev 明细）
    """
    from data_sources import em_market, tencent

    fin = em_market.fetch_financials(code)
    if "error" in fin:
        return {"method": "DCF 两阶段估值", "code": code, "error": fin["error"]}

    quote = tencent.get_realtime_quote(code)
    if "error" in quote:
        quote = {}

    code_ = fin.get("code") or code
    name = fin.get("name") or code

    # ─── 现价 ───
    if "error" in quote or not quote.get("price"):
        current_price = 0.0
        quote_price = 0.0
    else:
        quote_price = float(quote.get("price") or 0)
        current_price = quote_price

    a = assumptions or {}

    # ─── 财务字段 ───
    fcff_back = float(fin.get("fcff_back") or 0)
    fcff_forward = float(fin.get("fcff_forward") or 0)
    revenue = float(fin.get("revenue") or 0)
    net_margin = float(fin.get("net_margin") or 0)
    shares_outstanding = float(fin.get("shares_outstanding") or 0)

    # ─── Base FCF ───
    fcf0 = fcff_back if fcff_back != 0 else fcff_forward
    fcf_source = "FCFF(回溯)" if fcff_back != 0 else "FCFF(前瞻)"
    if fcf0 == 0:
        # Approximate from revenue * net_margin * 0.8
        fcf0 = revenue * (net_margin / 100) * 0.8
        fcf_source = "营收×净利率×0.8 近似"
    if fcf0 == 0:
        # Last resort: market_cap * 5% yield
        fcf0 = current_price * shares_outstanding * 0.05
        fcf_source = "市值×5% 兜底"

    # ─── 增长率 ───
    hist_growth = DEFAULT_STAGE1_GROWTH
    rev_hist = fin.get("revenue_history") or []
    if len(rev_hist) >= 2:
        first = float(rev_hist[0] or 0)
        last = float(rev_hist[-1] or 0)
        if first > 0:
            cagr = (last / first) ** (1 / (len(rev_hist) - 1)) - 1
            hist_growth = max(0.01, min(0.30, cagr))

    stage1_g = a.get("stage1_growth", hist_growth)
    stage2_g = a.get("stage2_growth", stage1_g / 2)
    terminal_g = a.get("terminal_growth", DEFAULT_TERMINAL_G)
    stage1_years = int(a.get("stage1_years", DEFAULT_STAGE1_YEARS))
    stage2_years = int(a.get("stage2_years", DEFAULT_STAGE2_YEARS))
    rf = a.get("risk_free_rate", DEFAULT_RF)
    erp = a.get("equity_risk_premium", DEFAULT_ERP)
    beta = a.get("beta", DEFAULT_BETA)
    tax = a.get("tax", DEFAULT_TAX)
    debt_ratio = a.get("target_debt_ratio", DEFAULT_TARGET_DEBT_RATIO)
    kd = a.get("kd_pretax", DEFAULT_COST_OF_DEBT)

    # ─── WACC ───
    wacc_info = _compute_wacc(rf, erp, beta, kd, debt_ratio, tax)
    wacc = wacc_info["wacc"]

    # ─── 净债务 / 股本 / FCF（元 → 亿元） ───
    total_liabilities = float(fin.get("total_liabilities") or 0)
    net_debt_yi = total_liabilities * 0.3 / 1e8
    shares_yi = shares_outstanding / 1e8 if shares_outstanding else 0
    fcf_yi = fcf0 / 1e8

    # ─── 企业价值 → 每股内在价值 ───
    ev = _compute_enterprise_value(fcf_yi, wacc, terminal_g, stage1_g, stage2_g,
                                   stage1_years, stage2_years)
    equity_value = ev - net_debt_yi
    intrinsic_per_share = equity_value / shares_yi if shares_yi > 0 else 0

    # ─── 安全边际 ───
    safety_margin_pct = round(
        (intrinsic_per_share - current_price) / current_price * 100, 1
    ) if current_price > 0 else 0.0

    # ─── Verdict ───
    if safety_margin_pct > 20:
        verdict = "🟢 低估 — 安全边际充足 (>20%)"
    elif safety_margin_pct > 0:
        verdict = "🟡 合理偏低 — 轻度低估"
    elif safety_margin_pct > -20:
        verdict = "🟠 合理偏高 — 轻度高估"
    else:
        verdict = "🔴 高估 — 安全边际为负 (<-20%)"

    # ─── 敏感性表 ───
    sensitivity = _build_sensitivity(fcf_yi, wacc, terminal_g, stage1_g, stage2_g,
                                     shares_yi, net_debt_yi)

    return {
        "method": "DCF 两阶段估值 (Two-Stage DCF)",
        "code": code_,
        "name": name,
        "intrinsic_per_share": round(intrinsic_per_share, 2),
        "current_price": current_price,
        "safety_margin_pct": safety_margin_pct,
        "verdict": verdict,
        "assumptions": {
            "stage1_growth": round(stage1_g, 4),
            "stage2_growth": round(stage2_g, 4),
            "terminal_growth": terminal_g,
            "wacc": round(wacc, 4),
            "stage1_years": stage1_years,
            "stage2_years": stage2_years,
            "risk_free_rate": rf,
            "beta": beta,
            "equity_risk_premium": erp,
            "tax": tax,
            "target_debt_ratio": debt_ratio,
        },
        "wacc": wacc_info,
        "enterprise_value": round(ev, 2),
        "net_debt": round(net_debt_yi, 2),
        "equity_value": round(equity_value, 2),
        "shares_outstanding_yi": round(shares_yi, 2),
        "base_fcf_yi": round(fcf_yi, 2),
        "sensitivity": sensitivity,
        "methodology_log": [
            f"基于 {name}({code_}) {fin.get('report_date', '')} 财务数据",
            f"FCF base: ¥{fcf_yi:.2f}亿（{fcf_source}）",
            f"营收历史增长率: {hist_growth * 100:.1f}% → 采用 {stage1_g * 100:.1f}% 作为高增阶段",
            f"WACC 计算: Rf={rf * 100:.1f}% + β={beta} × ERP={erp * 100:.1f}% → {wacc * 100:.2f}%"
            f"（Ke={wacc_info['cost_of_equity'] * 100:.2f}%, 税后Kd={wacc_info['after_tax_kd'] * 100:.2f}%）",
            f"{stage1_years}年高增({stage1_g * 100:.0f}%) + {stage2_years}年过渡({stage2_g * 100:.0f}%) + 永续({terminal_g * 100:.1f}%)",
            f"净债务≈总负债×0.3 = ¥{net_debt_yi:.2f}亿，股本 {shares_yi:.2f}亿股",
            f"内含价值: ¥{intrinsic_per_share:.2f}/股 vs 现价: ¥{current_price:.2f}",
            f"安全边际: {'+' if safety_margin_pct > 0 else ''}{safety_margin_pct}%",
        ],
    }


# ───── IC Memo: 质量特征 ─────

def _compute_features(fin: dict, quote: dict) -> dict:
    """提取质量特征。对齐 icmemo.ts computeFeatures。"""
    eps = float(fin.get("eps") or 0)
    bps = float(fin.get("bps") or 0) or 1
    roe = (eps / bps) * 100 if bps > 0 else 0

    # 统计 EPS 历史中 ROE > 15% 的年数
    roe_years_above_15 = 0
    eps_hist = fin.get("eps_history") or []
    if eps_hist and bps > 0:
        for e in eps_hist:
            if float(e or 0) / bps > 0.15:
                roe_years_above_15 += 1

    fcff_forward = float(fin.get("fcff_forward") or 0)
    fcff_back = float(fin.get("fcff_back") or 0)
    fcf_positive = fcff_forward > 0 or fcff_back > 0

    net_margin = float(fin.get("net_margin") or 0)
    total_liabilities = float(fin.get("total_liabilities") or 0)
    revenue = float(fin.get("revenue") or 0)
    debt_ratio = abs(total_liabilities) / abs(revenue) * 100 if revenue else 0

    revenue_yi = abs(revenue) / 1e8
    liabilities_yi = abs(total_liabilities) / 1e8

    quote = quote or {}
    price = float(quote.get("price") or 0)
    market_cap = quote.get("market_cap")
    if market_cap:
        market_cap_yi = float(market_cap) / 1e8
        market_cap_source = "quote"
    else:
        market_cap_yi = float(fin.get("shares_outstanding") or 0) * price / 1e8
        market_cap_source = "estimate(股本×现价)"

    pe_ratio = quote.get("pe_ratio")
    if not pe_ratio:
        pe_ratio = price / eps if (eps > 0 and price > 0) else 0

    return {
        "roe_years_above_15": roe_years_above_15,
        "fcf_positive": fcf_positive,
        "net_margin_pct": net_margin,
        "debt_ratio_pct": debt_ratio,
        "revenue_latest_yi": revenue_yi,
        "market_cap_yi": market_cap_yi,
        "market_cap_source": market_cap_source,
        "roe_latest": roe,
        "pe_ratio": float(pe_ratio or 0),
        "gross_margin_pct": 0.0,
        "total_liabilities_yi": liabilities_yi,
    }


# ───── IC Memo: 推荐 ─────

def _compute_recommendation(features: dict, dcf: dict) -> dict:
    """质量分 × 估值分 → 建议。对齐 icmemo.ts computeRecommendation。"""
    quality_score = 0
    if features["roe_years_above_15"] >= 3:
        quality_score += 2
    if features["fcf_positive"]:
        quality_score += 1
    if features["net_margin_pct"] > 15:
        quality_score += 1
    if features["debt_ratio_pct"] < 50:
        quality_score += 1

    val_score = 0
    safety_margin = 0
    if dcf:
        safety_margin = float(dcf.get("safety_margin_pct") or 0)
        if safety_margin > 20:
            val_score = 2
        elif safety_margin > 0:
            val_score = 1
        elif safety_margin > -20:
            val_score = 0
        else:
            val_score = -1

    total = quality_score + val_score

    if total >= 5:
        return {
            "headline": "🟢 强烈建议通过 (P0 — PASS)",
            "recommendation": "推荐投委会批准建仓 — 高质量 × 安全边际充足",
            "level": "P0",
            "quality_score": quality_score,
            "val_score": val_score,
            "total": total,
        }
    if total >= 3:
        return {
            "headline": "🟡 建议通过 (P1 — CONDITIONAL PASS)",
            "recommendation": "可批准但建议分批建仓，控制初始仓位",
            "level": "P1",
            "quality_score": quality_score,
            "val_score": val_score,
            "total": total,
        }
    if total >= 0:
        return {
            "headline": "⚪ 观望 (P2 — HOLD)",
            "recommendation": "暂不建议建仓，等待估值回落或信号强化",
            "level": "P2",
            "quality_score": quality_score,
            "val_score": val_score,
            "total": total,
        }
    return {
        "headline": "🔴 建议回避 (P3 — AVOID)",
        "recommendation": "质量或估值不达标 — 投委会建议不进场",
        "level": "P3",
        "quality_score": quality_score,
        "val_score": val_score,
        "total": total,
    }


# ───── IC Memo: 风险清单 ─────

def _compute_risks(features: dict) -> list:
    """风险清单。对齐 icmemo.ts computeRisks。"""
    risks = []
    debt = features["debt_ratio_pct"]
    if debt > 60:
        risks.append({
            "risk": "财务杠杆风险",
            "detail": f"资产负债率 {debt:.0f}% 偏高",
            "severity": "High",
            "mitigant": "监控利息覆盖倍数与再融资窗口",
        })
    margin = features["net_margin_pct"]
    if margin < 5:
        risks.append({
            "risk": "盈利能力偏弱",
            "detail": f"净利率仅 {margin:.1f}%",
            "severity": "Medium",
            "mitigant": "跟踪毛利率变化和费用管控措施",
        })
    pe = features["pe_ratio"]
    if pe > 60:
        risks.append({
            "risk": "估值偏贵",
            "detail": f"PE {pe:.0f}x",
            "severity": "Medium",
            "mitigant": "等待 PE 回归合理区间再建仓",
        })
    if not features["fcf_positive"]:
        risks.append({
            "risk": "自由现金流为负",
            "detail": "经营现金流无法覆盖资本支出",
            "severity": "High",
            "mitigant": "要求管理层提供现金流改善路线图",
        })
    risks.append({
        "risk": "行业周期下行",
        "detail": "需求侧宏观冲击可能影响业绩",
        "severity": "Medium",
        "mitigant": "行业景气度月度跟踪",
    })
    return risks


# ───── IC Memo: 三情景 ─────

def _compute_scenarios(price: float, dcf: dict) -> list:
    """三情景回报。对齐 icmemo.ts computeScenarios。"""
    if not dcf or price <= 0:
        return []
    intrinsic = float(dcf.get("intrinsic_per_share") or price)
    return [
        {
            "scenario": "Bull (乐观)",
            "price_target": round(intrinsic * 1.3, 2),
            "return_pct": round((intrinsic * 1.3 - price) / price * 100, 1),
            "probability_pct": 25,
            "assumptions": "超预期增速 + 估值扩张",
        },
        {
            "scenario": "Base (中性)",
            "price_target": round(intrinsic, 2),
            "return_pct": round((intrinsic - price) / price * 100, 1),
            "probability_pct": 50,
            "assumptions": "DCF 基础假设",
        },
        {
            "scenario": "Bear (悲观)",
            "price_target": round(intrinsic * 0.7, 2),
            "return_pct": round((intrinsic * 0.7 - price) / price * 100, 1),
            "probability_pct": 25,
            "assumptions": "增速放缓 + 估值压缩",
        },
    ]


# ───── IC Memo 主入口 ─────

def ic_memo(code: str) -> dict:
    """投委会备忘录 — 质量评分 + DCF 估值 → P0-P4 建议。

    Args:
        code: 股票代码（如 600519）

    返回: exec_summary / company_overview / valuation_summary /
          scenarios / risks / methodology_log
    """
    from data_sources import em_market, tencent

    fin = em_market.fetch_financials(code)
    if "error" in fin:
        return {
            "method": "Investment Committee Memo (投委会备忘录)",
            "code": code,
            "error": fin["error"],
        }

    quote = tencent.get_realtime_quote(code)
    if "error" in quote:
        quote = {}

    code_ = fin.get("code") or code
    name = fin.get("name") or code

    features = _compute_features(fin, quote)
    price = float(quote.get("price") or 0)

    # DCF 估值（失败则降级，不阻断备忘录）
    dcf = None
    dcf_err = None
    try:
        dcf = dcf_valuation(code_, assumptions=None)
        if "error" in dcf:
            dcf_err = dcf["error"]
            dcf = None
    except Exception as e:
        dcf_err = str(e)[:120]
        dcf = None

    if dcf is None:
        dcf = {
            "intrinsic_per_share": 0.0,
            "current_price": price or 0,
            "safety_margin_pct": None,
            "verdict": None,
        }

    rec = _compute_recommendation(features, dcf)
    risks = _compute_risks(features)
    scenarios = _compute_scenarios(price, dcf)

    log = [
        "Step 1 · 提取财务特征（ROE/FCF/净利率/负债率）",
        f"Step 2 · 质量评分 {rec['quality_score']}/6（ROE持续≥15% + FCF正 + 净利率>15% + 负债率<50%）",
        f"Step 3 · 估值评分 {rec['val_score']}/2（DCF安全边际>20%=2分, >0%=1分, >-20%=0分, <-20%=-1分）",
        f"Step 4 · 综合 {rec['quality_score']}+{rec['val_score']}={rec['total']} → {rec['level']}",
        "Step 5 · 三情景回报（Bull/Base/Bear）",
    ]
    if dcf_err:
        log.append(f"Note · DCF 计算失败已降级: {dcf_err}")

    return {
        "method": "Investment Committee Memo (投委会备忘录)",
        "code": code_,
        "name": name,
        "exec_summary": {
            "headline": rec["headline"],
            "recommendation": rec["recommendation"],
            "recommendation_level": rec["level"],
            "quality_score": rec["quality_score"],
            "valuation_score": rec["val_score"],
            "total_score": rec["total"],
            "top_risks": risks[None:3],
        },
        "company_overview": {
            "name": name,
            "market_cap_yi": round(features["market_cap_yi"], 2),
            "market_cap_source": features["market_cap_source"],
            "revenue_latest_yi": round(features["revenue_latest_yi"], 2),
            "fcf_positive": features["fcf_positive"],
            "roe_latest_pct": round(features["roe_latest"], 1),
            "net_margin_pct": round(features["net_margin_pct"], 1),
            "debt_ratio_pct": round(features["debt_ratio_pct"], 1),
        },
        "valuation_summary": {
            "dcf_intrinsic": dcf.get("intrinsic_per_share"),
            "current_price": price,
            "safety_margin_pct": dcf.get("safety_margin_pct"),
            "dcf_verdict": dcf.get("verdict"),
            "pe_ratio": round(features["pe_ratio"], 1),
        },
        "scenarios": scenarios,
        "risks": risks,
        "methodology_log": log,
    }


if __name__ == "__main__":
    import json
    r = dcf_valuation("600519")
    print(json.dumps(r, ensure_ascii=False, indent=2)[:2000])
    print("...")
    m = ic_memo("600519")
    print(json.dumps(m, ensure_ascii=False, indent=2)[:2000])
