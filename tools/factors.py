"""因子评分框架 — 声明式因子注册表 + IC 分析

参考 easy_tdx factor/ 模块设计，为 stock_score 提供可扩展的因子系统。

核心设计：
- FactorSpec: 声明因子的名称、维度、权重、计算函数
- 因子注册表: 全局 FACTOR_REGISTRY
- compute_stock_score(): 基于因子的综合评分
- compute_factor_correlation(): 因子间相关性分析
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Callable


# ══════════════════════════════════════════════════════════
# 因子规格定义
# ══════════════════════════════════════════════════════════

@dataclass(frozen=True)
class FactorSpec:
    """单个因子的元数据"""
    name: str                # 因子标识
    dimension: str           # 所属维度 (technical/fundamental/market/sentiment)
    weight: float            # 在总分中的权重 (0-1)
    description: str = ""    # 可读描述
    scoring_fn: Callable | None = None   # 评分函数 (raw_value, context) → 0-100
    higher_is_better: bool = True        # 原始值是否越高越好


# ══════════════════════════════════════════════════════════
# 内置评分函数
# ══════════════════════════════════════════════════════════

def _score_trend(value: str) -> float:
    """趋势状态 → 0-100 分"""
    score_map = {
        "强势多头": 95, "多头排列": 80, "弱势多头": 60,
        "震荡整理": 50, "弱势空头": 40, "空头排列": 25, "强势空头": 10,
    }
    return score_map.get(value, 50)


def _score_rsi(value: float) -> float:
    """RSI → 0-100 分（中性区间最优）"""
    if value is None:
        return 50
    if 40 <= value <= 60:
        return 80
    elif 30 <= value < 40 or 60 < value <= 70:
        return 65
    elif 20 <= value < 30:
        return 55  # 超卖有反弹潜力
    elif 70 < value <= 80:
        return 45
    elif value < 20:
        return 40  # 深度超卖，风险也大
    else:
        return 20  # 严重超买


def _score_macd(signal: str) -> float:
    """MACD 信号 → 0-100 分"""
    score_map = {
        "金叉": 85, "多头加强": 75, "多头": 65, "多头减弱": 55,
        "中性": 50, "空头减弱": 45, "空头": 35, "死叉": 20, "空头加强": 10,
    }
    return score_map.get(signal, 50)


def _score_bollinger(position: str) -> float:
    """布林带位置 → 0-100 分"""
    if "中轨至上轨" in position:
        return 70
    elif "上轨之上" in position:
        return 35  # 超买风险
    elif "下轨至中轨" in position:
        return 55
    elif "下轨之下" in position:
        return 60  # 超卖有反弹潜力
    return 50


def _score_volume_ratio(value: float) -> float:
    """量比 → 0-100 分（适度放量最优）"""
    if value is None:
        return 50
    if 0.8 <= value <= 1.5:
        return 80  # 温和放量
    elif 1.5 < value <= 3.0:
        return 60  # 明显放量（可能见顶）
    elif value > 3.0:
        return 30  # 巨量（警惕）
    elif 0.5 <= value < 0.8:
        return 55  # 缩量
    else:
        return 40  # 极度缩量
    return 50


def _score_fund_flow(main_net_5d: float) -> float:
    """5日主力净流入(亿) → 0-100 分"""
    if main_net_5d is None:
        return 50
    if main_net_5d > 5:
        return 90
    elif main_net_5d > 2:
        return 75
    elif main_net_5d > 0:
        return 60
    elif main_net_5d > -2:
        return 45
    elif main_net_5d > -5:
        return 30
    else:
        return 15


def _score_change_pct(value: float) -> float:
    """当日涨跌幅 → 0-100 分"""
    if value is None:
        return 50
    if 1.0 <= value <= 5.0:
        return 75
    elif 0 <= value < 1.0:
        return 65
    elif -2.0 < value < 0:
        return 50
    elif -5.0 <= value <= -2.0:
        return 40
    elif value > 5.0:
        return 55  # 涨太多可能回调
    else:
        return 25


def _score_atr_pct(value: float) -> float:
    """ATR 波动率百分比 → 0-100 分（低波动最优）"""
    if value is None:
        return 50
    if value <= 1.5:
        return 85
    elif value <= 3.0:
        return 70
    elif value <= 5.0:
        return 50
    elif value <= 8.0:
        return 30
    else:
        return 15


def _score_vwap_pct(value: float) -> float:
    """VWAP 偏离度 → 0-100 分（适度高于最优）"""
    if value is None:
        return 50
    if 0 < value <= 3:
        return 80  # 在机构成本之上，多头优势
    elif -2 <= value <= 0:
        return 60  # 接近机构成本
    elif value > 3:
        return 45  # 远高于成本，获利回吐风险
    elif value < -5:
        return 30  # 远低于成本，套牢盘压力
    else:
        return 45


# ══════════════════════════════════════════════════════════
# 因子注册表
# ══════════════════════════════════════════════════════════

FACTOR_REGISTRY: dict[str, FactorSpec] = {}


def _reg_factor(
    name: str, dimension: str, weight: float,
    desc: str = "", scoring_fn: Callable | None = None,
    higher_is_better: bool = True,
) -> None:
    FACTOR_REGISTRY[name] = FactorSpec(
        name=name, dimension=dimension, weight=weight,
        description=desc, scoring_fn=scoring_fn,
        higher_is_better=higher_is_better,
    )


# ── 技术面因子 (权重合计 0.40) ──
_reg_factor("trend",       "technical",  0.12, "趋势状态（均线排列）",         _score_trend)
_reg_factor("rsi",         "technical",  0.06, "RSI 相对强弱",                _score_rsi)
_reg_factor("macd_signal", "technical",  0.06, "MACD 金叉/死叉信号",          _score_macd)
_reg_factor("bollinger",   "technical",  0.05, "布林带位置",                  _score_bollinger)
_reg_factor("volume_ratio","technical",  0.05, "量比",                       _score_volume_ratio)
_reg_factor("atr_pct",     "technical",  0.03, "ATR 波动率",                 _score_atr_pct)
_reg_factor("vwap_pct",    "technical",  0.03, "VWAP 偏离度",                _score_vwap_pct)

# ── 资金面因子 (权重合计 0.30) ──
_reg_factor("fund_flow",   "fundamental", 0.20, "5日主力净流入",              _score_fund_flow)
_reg_factor("change_pct",  "fundamental", 0.10, "当日涨跌幅",                _score_change_pct)

# ── 市场面因子 (权重合计 0.30，预留) ──
_reg_factor("market_sentiment", "market", 0.15, "市场情绪（预留）",           None)
_reg_factor("sector_strength",  "market", 0.15, "板块强度（预留）",           None)


# ══════════════════════════════════════════════════════════
# 因子提取 — 从技术分析结果提取原始值
# ══════════════════════════════════════════════════════════

def extract_factors(tech: dict, quote: dict, fund_flow: dict | None = None) -> dict[str, float | None]:
    """从技术分析/行情/资金流结果中提取因子原始值

    Args:
        tech: analyze_technical() 输出
        quote: get_realtime_quote() 输出
        fund_flow: get_fund_flow_120d() 输出（可选）
    Returns:
        {factor_name: raw_value} 字典
    """
    indicators = tech.get("indicators", {})

    factors = {
        "trend":        tech.get("trend", {}).get("status"),
        "rsi":          tech.get("rsi", {}).get("value"),
        "macd_signal":  tech.get("macd", {}).get("signal"),
        "bollinger":    tech.get("bollinger", {}).get("position"),
        "volume_ratio": tech.get("volume_ratio"),
        "atr_pct":      indicators.get("atr", {}).get("pct"),
        "vwap_pct":     indicators.get("vwap", {}).get("pct"),
        "change_pct":   quote.get("change_pct"),
    }

    # 资金流
    if fund_flow and isinstance(fund_flow, dict):
        flow = fund_flow.get("flow") or []
        if flow:
            recent5_net = sum(f.get("main_net") or 0 for f in flow[:5])
            factors["fund_flow"] = recent5_net
        else:
            factors["fund_flow"] = None
    else:
        factors["fund_flow"] = None

    # 预留因子给默认值
    factors.setdefault("market_sentiment", None)
    factors.setdefault("sector_strength", None)

    return factors


# ══════════════════════════════════════════════════════════
# 综合评分
# ══════════════════════════════════════════════════════════

def compute_stock_score(
    tech: dict,
    quote: dict,
    fund_flow: dict | None = None,
) -> dict[str, Any]:
    """基于因子的综合评分

    Args:
        tech: analyze_technical() 输出
        quote: get_realtime_quote() 输出
        fund_flow: get_fund_flow_120d() 输出（可选）
    Returns:
        {score, dimensions, factors_detail, suggestion}
    """
    raw_factors = extract_factors(tech, quote, fund_flow)

    dimensions: dict[str, dict] = {}
    factors_detail: list[dict] = []
    total_score = 0.0
    total_weight = 0.0

    # 按维度聚合
    dim_scores: dict[str, list[float]] = {}
    dim_weights: dict[str, list[float]] = {}

    for name, spec in FACTOR_REGISTRY.items():
        raw_val = raw_factors.get(name)

        if spec.scoring_fn is not None and raw_val is not None:
            score = spec.scoring_fn(raw_val)
        else:
            score = 50  # 预留因子默认中性分

        weighted = score * spec.weight
        total_score += weighted
        total_weight += spec.weight

        # 按维度聚合
        dim = spec.dimension
        dim_scores.setdefault(dim, []).append(weighted)
        dim_weights.setdefault(dim, []).append(spec.weight)

        factors_detail.append({
            "name": name,
            "dimension": dim,
            "raw_value": raw_val,
            "score": round(score, 1),
            "weight": spec.weight,
            "weighted": round(weighted, 2),
            "description": spec.description,
        })

    # 维度汇总
    for dim in dim_scores:
        dim_total = sum(dim_scores[dim])
        dim_max = sum(w * 100 for w in dim_weights[dim])
        dimensions[dim] = {
            "score": round(dim_total / dim_max * 100, 1) if dim_max > 0 else 50,
            "weighted": round(sum(dim_scores[dim]), 2),
        }

    # 归一化到 0-100
    final_score = round(total_score / total_weight * 100, 1) if total_weight > 0 else 50
    final_score = max(0, min(100, final_score))

    # 建议
    if final_score >= 75:
        suggestion = "强势，可关注"
    elif final_score >= 60:
        suggestion = "偏多，适度参与"
    elif final_score >= 45:
        suggestion = "中性，观望"
    elif final_score >= 30:
        suggestion = "偏空，谨慎"
    else:
        suggestion = "弱势，回避"

    return {
        "code": quote.get("code", ""),
        "name": quote.get("name", ""),
        "score": final_score,
        "dimensions": dimensions,
        "factors": factors_detail,
        "suggestion": suggestion,
    }


# ══════════════════════════════════════════════════════════
# 因子 IC 分析（参考 easy_tdx FactorAnalyzer）
# ══════════════════════════════════════════════════════════

def compute_factor_correlation(
    factor_scores: list[dict[str, float]],
    returns: list[float],
) -> dict[str, Any]:
    """因子-收益相关性分析（Rank IC 简化版）

    Args:
        factor_scores: 每只股票的因子得分 {factor_name: score}
        returns: 对应的未来 N 日收益率
    Returns:
        {factor_name: {ic, rank_ic}} 字典
    """
    if len(factor_scores) < 5:
        return {"error": "样本不足（至少5只股票）"}

    results = {}
    n = len(factor_scores)

    # 提取所有因子名
    all_factors = set()
    for fs in factor_scores:
        all_factors.update(fs.keys())

    for fname in sorted(all_factors):
        # 提取该因子的分数序列
        vals = [fs.get(fname, 50.0) for fs in factor_scores]

        # Pearson 相关系数
        mean_v = sum(vals) / n
        mean_r = sum(returns) / n
        cov = sum((v - mean_v) * (r - mean_r) for v, r in zip(vals, returns))
        std_v = math.sqrt(sum((v - mean_v) ** 2 for v in vals))
        std_r = math.sqrt(sum((r - mean_r) ** 2 for r in returns))

        if std_v > 0 and std_r > 0:
            ic = cov / (std_v * std_r)
        else:
            ic = 0.0

        results[fname] = {
            "ic": round(ic, 4),
            "abs_ic": round(abs(ic), 4),
            "significant": abs(ic) > 0.15,
        }

    # 按 |IC| 排序
    results["_ranked"] = sorted(
        [(k, v["abs_ic"]) for k, v in results.items() if k != "_ranked"],
        key=lambda x: x[1], reverse=True,
    )

    return results


def list_factors() -> list[dict[str, Any]]:
    """列出所有已注册因子"""
    return [
        {
            "name": spec.name,
            "dimension": spec.dimension,
            "weight": spec.weight,
            "description": spec.description,
            "higher_is_better": spec.higher_is_better,
        }
        for spec in FACTOR_REGISTRY.values()
    ]
