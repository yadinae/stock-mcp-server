#!/usr/bin/env python3
"""组合诊断（移植自 Gateway tools/portfolio.ts 核心逻辑）

基于本地行情/K线数据计算: 风险诊断 / 相关性矩阵 / 组合总览 / 调仓信号
"""
import json
import statistics
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from data_sources import tencent


def _get_quote(code: str) -> dict:
    """获取实时行情，兼容 A股/美股/港股"""
    try:
        return tencent.get_realtime_quote(code)
    except Exception:
        return {}


def _get_kline(code: str, days: int = 60) -> list:
    """获取K线收盘价序列"""
    try:
        d = tencent.get_kline(code, days)
        records = d.get("records") or []
        return [{"date": r.get("date"), "close": r.get("close")} for r in records]
    except Exception:
        return []


def _market_of(code: str) -> str:
    c = code.strip().upper()
    if c.isalpha() and len(c) <= 5:
        return "美股"
    if c.isdigit() and len(c) == 5:
        return "港股"
    return "A股"


def _industry_of(code: str) -> str:
    """简化行业归类（从行情/板块数据推断）"""
    try:
        from data_sources.em_market import get_stock_boards
        b = get_stock_boards(code)
        return b.get("industry") or "未知"
    except Exception:
        return "未知"


def portfolio_risk_diagnosis(holdings: list) -> dict:
    """组合风险诊断 — 集中度/行业暴露/跨市场/浮动盈亏"""
    if not holdings or not isinstance(holdings, list):
        return {"error": "holdings 不能为空（格式: [{code, shares, cost_price}]）"}

    detail = []
    total_cost = 0.0
    total_value = 0.0
    market_exposure = {}
    industry_exposure = {}

    for h in holdings:
        code = str(h.get("code") or "").strip()
        shares = float(h.get("shares") or 0)
        cost = float(h.get("cost_price") or 0)
        if not code:
            continue
        q = _get_quote(code)
        price = q.get("price") or 0
        name = q.get("name") or code
        market = _market_of(code)
        industry = _industry_of(code)
        value = price * shares
        cost_total = cost * shares
        pl = value - cost_total
        pl_pct = round(pl / cost_total * 100, 2) if cost_total else 0
        detail.append({
            "code": code, "name": name, "market": market, "industry": industry,
            "shares": shares, "cost_price": cost, "price": price,
            "value": round(value, 2), "cost_total": round(cost_total, 2),
            "pl": round(pl, 2), "pl_pct": pl_pct,
        })
        total_cost += cost_total
        total_value += value
        market_exposure[market] = market_exposure.get(market, 0) + value
        industry_exposure[industry] = industry_exposure.get(industry, 0) + value

    total_pl = total_value - total_cost
    total_pl_pct = round(total_pl / total_cost * 100, 2) if total_cost else 0

    # 集中度: 最大持仓占比
    max_weight = 0
    if total_value > 0 and detail:
        max_weight = round(max(d["value"] for d in detail) / total_value * 100, 1)

    return {
        "generated_at": __import__("datetime").datetime.now().isoformat(),
        "summary": {
            "total_holdings": len(detail),
            "total_value": round(total_value, 2),
            "total_cost": round(total_cost, 2),
            "total_pl": round(total_pl, 2),
            "total_pl_pct": total_pl_pct,
            "max_weight_pct": max_weight,
            "risk_level": "高集中" if max_weight > 50 else ("中集中" if max_weight > 30 else "分散"),
        },
        "holdings": detail,
        "market_exposure": {k: round(v, 2) for k, v in market_exposure.items()},
        "industry_exposure": {k: round(v, 2) for k, v in industry_exposure.items()},
    }


def portfolio_correlation(codes: list, days: int = 60) -> dict:
    """持仓相关性矩阵 — Pearson 相关系数"""
    if not codes or len(codes) < 2:
        return {"error": "codes 需要至少 2 只持仓才能计算相关性"}

    # 获取各标的K线
    series = {}
    for code in codes:
        records = _get_kline(code, days)
        series[code] = {r["date"]: r["close"] for r in records if r.get("date") and r.get("close")}

    # 对齐日期
    all_dates = sorted(set.intersection(*[set(s.keys()) for s in series.values()]) if series else set())
    if len(all_dates) < 5:
        return {"error": "K线数据不足（需至少5个共同交易日）", "num_dates": len(all_dates)}

    def returns(prices: list) -> list:
        return [prices[i] / prices[i - 1] - 1 for i in range(1, len(prices)) if prices[i - 1]]

    rets = {}
    for code in codes:
        prices = [series[code][d] for d in all_dates]
        rets[code] = returns(prices)

    matrix = []
    n = len(codes)
    for i in range(n):
        for j in range(i + 1, n):
            a, b = rets[codes[i]], rets[codes[j]]
            m = min(len(a), len(b))
            if m < 3:
                corr = 0
            else:
                try:
                    corr = statistics.correlation(a[:m], b[:m])
                except Exception:
                    corr = 0
            matrix.append({
                "code_a": codes[i], "code_b": codes[j],
                "correlation": round(corr, 3),
            })

    avg = round(statistics.mean([m["correlation"] for m in matrix]), 3) if matrix else 0
    high = [m for m in matrix if m["correlation"] > 0.7]
    low = [m for m in matrix if abs(m["correlation"]) < 0.2]
    score = max(0, min(100, round(100 - abs(avg) * 100 / 2, 1)))

    return {
        "generated_at": __import__("datetime").datetime.now().isoformat(),
        "holdings": [{"code": c, "name": (_get_quote(c).get("name") or c), "market": _market_of(c)} for c in codes],
        "days_analyzed": len(all_dates),
        "matrix": matrix,
        "avg_correlation": avg,
        "high_correlation_pairs": high,
        "low_correlation_pairs": low,
        "diversification_score": score,
        "num_dates": len(all_dates),
    }


def portfolio_full_report(holdings: list, days: int = 60) -> dict:
    """综合组合报告 — 行情摘要 + 集中度 + 行业暴露 + 相关性"""
    risk = portfolio_risk_diagnosis(holdings)
    if risk.get("error"):
        return risk
    codes = [h["code"] for h in risk.get("holdings", [])]
    corr = portfolio_correlation(codes, days) if len(codes) >= 2 else {"matrix": [], "note": "不足2只，跳过相关性"}
    return {
        "generated_at": risk.get("generated_at"),
        "summary": risk.get("summary"),
        "holdings": risk.get("holdings"),
        "market_exposure": risk.get("market_exposure"),
        "industry_exposure": risk.get("industry_exposure"),
        "correlation": corr,
    }


def portfolio_rebalance(holdings: list, max_single_weight: float = 40) -> dict:
    """调仓建议 — 仓位调整 + 行业分散优化"""
    risk = portfolio_risk_diagnosis(holdings)
    if risk.get("error"):
        return risk
    summary = risk.get("summary") or {}
    suggestions = []
    for h in risk.get("holdings", []):
        weight = round(h["value"] / summary["total_value"] * 100, 1) if summary.get("total_value") else 0
        if weight > max_single_weight:
            suggestions.append({
                "code": h["code"], "name": h["name"], "weight_pct": weight,
                "action": "减仓", "reason": f"超过单标的权重上限 {max_single_weight}%",
            })
        elif h["pl_pct"] < -20:
            suggestions.append({
                "code": h["code"], "name": h["name"], "weight_pct": weight,
                "action": "评估", "reason": f"亏损 {h['pl_pct']}%，建议评估止损",
            })
    return {
        "summary": summary,
        "max_single_weight": max_single_weight,
        "suggestions": suggestions,
        "suggestion_count": len(suggestions),
    }


def portfolio_signal(holdings: list) -> dict:
    """组合调仓信号 — urgency high/medium/low"""
    risk = portfolio_risk_diagnosis(holdings)
    if risk.get("error"):
        return risk
    summary = risk.get("summary") or {}
    urgency = "low"
    reasons = []
    if summary.get("max_weight_pct", 0) > 50:
        urgency = "high"
        reasons.append(f"持仓集中度过高（{summary['max_weight_pct']}%）")
    elif summary.get("max_weight_pct", 0) > 30:
        urgency = "medium"
        reasons.append(f"持仓较集中（{summary['max_weight_pct']}%）")
    if summary.get("total_pl_pct", 0) < -15:
        urgency = "high" if urgency != "low" else "medium"
        reasons.append(f"组合亏损 {summary['total_pl_pct']}%")
    return {
        "generated_at": risk.get("generated_at"),
        "urgency": urgency,
        "holdings_count": summary.get("total_holdings", 0),
        "summary": summary,
        "reasons": reasons,
        "action": "建议调仓" if urgency == "high" else ("关注" if urgency == "medium" else "维持"),
    }
