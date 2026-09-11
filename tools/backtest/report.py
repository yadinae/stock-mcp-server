"""
回测报告格式化

将模拟结果和绩效指标格式化为统一的输出字典。
"""

from __future__ import annotations

from typing import Any

from .strategies import STRATEGY_NAMES
from .metrics import calc_all_metrics


# ══════════════════════════════════════════════════════════
# 回测数据评级系统（参考 easy_tdx S/A/B/C/D 评级）
#
# 不看收益率（避免被近期大涨误导），只看风险调整后的持有体验：
# 卡玛比率、最大回撤、胜率、利润因子、夏普、波动率 六维加权
# + 一票否决（系统亏损/深回撤/低胜率直接低评）
# ══════════════════════════════════════════════════════════


def _compute_rating(metrics: dict[str, Any]) -> dict[str, Any]:
    """根据绩效指标计算 S/A/B/C/D 评级

    评级逻辑：
    1. 先检查一票否决条件
    2. 六维指标分别打分（0-100）
    3. 加权平均得到总分
    4. 映射到 S/A/B/C/D 档位
    """
    calmar = metrics.get("calmar_ratio", 0)
    max_dd = metrics.get("max_drawdown_pct", 0)
    win_rate = metrics.get("win_rate_pct", 0)
    pf = metrics.get("profit_factor", 0)
    sharpe = metrics.get("sharpe_ratio", 0)
    volatility = metrics.get("volatility_pct", 0)
    total_return = metrics.get("total_return_pct", 0)
    total_trades = metrics.get("total_trades", 0)

    # ── 一票否决 ──
    veto = None
    if total_return < 0:
        veto = "系统亏损（总收益率为负）"
    elif max_dd > 40:
        veto = f"深回撤（最大回撤 {max_dd:.1f}% > 40%）"
    elif total_trades > 5 and win_rate < 30:
        veto = f"低胜率（{win_rate:.1f}% < 30%）"

    if veto:
        return {
            "rating": "D",
            "rating_score": 0,
            "rating_label": "回避",
            "veto": veto,
            "dimensions": {},
        }

    # ── 六维打分（0-100） ──
    dims = {}

    # 1. Calmar 比率（权重 25%）— 风险调整后收益
    if calmar >= 2:
        dims["calmar"] = 100
    elif calmar >= 1:
        dims["calmar"] = 80
    elif calmar >= 0.5:
        dims["calmar"] = 60
    elif calmar >= 0:
        dims["calmar"] = 40
    else:
        dims["calmar"] = 10

    # 2. 最大回撤（权重 20%）— 越小越好
    if max_dd <= 10:
        dims["drawdown"] = 100
    elif max_dd <= 15:
        dims["drawdown"] = 85
    elif max_dd <= 25:
        dims["drawdown"] = 65
    elif max_dd <= 35:
        dims["drawdown"] = 45
    else:
        dims["drawdown"] = 20

    # 3. 胜率（权重 15%）— 越高越好
    if win_rate >= 60:
        dims["win_rate"] = 100
    elif win_rate >= 50:
        dims["win_rate"] = 80
    elif win_rate >= 40:
        dims["win_rate"] = 60
    elif win_rate >= 30:
        dims["win_rate"] = 40
    else:
        dims["win_rate"] = 15

    # 4. 利润因子（权重 15%）— 越高越好
    if pf >= 3:
        dims["profit_factor"] = 100
    elif pf >= 2:
        dims["profit_factor"] = 80
    elif pf >= 1.5:
        dims["profit_factor"] = 65
    elif pf >= 1:
        dims["profit_factor"] = 40
    else:
        dims["profit_factor"] = 10

    # 5. 夏普比率（权重 15%）— 越高越好
    if sharpe >= 2:
        dims["sharpe"] = 100
    elif sharpe >= 1.5:
        dims["sharpe"] = 85
    elif sharpe >= 1:
        dims["sharpe"] = 70
    elif sharpe >= 0.5:
        dims["sharpe"] = 50
    elif sharpe >= 0:
        dims["sharpe"] = 30
    else:
        dims["sharpe"] = 10

    # 6. 波动率（权重 10%）— 越低越好
    if volatility <= 15:
        dims["volatility"] = 100
    elif volatility <= 25:
        dims["volatility"] = 75
    elif volatility <= 35:
        dims["volatility"] = 55
    elif volatility <= 50:
        dims["volatility"] = 35
    else:
        dims["volatility"] = 15

    # ── 加权总分 ──
    weights = {
        "calmar": 0.25,
        "drawdown": 0.20,
        "win_rate": 0.15,
        "profit_factor": 0.15,
        "sharpe": 0.15,
        "volatility": 0.10,
    }
    total_score = sum(dims[k] * weights[k] for k in weights)

    # ── 映射到档位 ──
    if total_score >= 85:
        grade, label = "S", "卓越"
    elif total_score >= 70:
        grade, label = "A", "优秀"
    elif total_score >= 50:
        grade, label = "B", "良好"
    elif total_score >= 30:
        grade, label = "C", "一般"
    else:
        grade, label = "D", "回避"

    return {
        "rating": grade,
        "rating_score": round(total_score, 1),
        "rating_label": label,
        "dimensions": dims,
        "veto": None,
    }


def format_report(
    code: str,
    strategy_id: str,
    strategy_params: dict[str, Any],
    records: list[dict],
    simulation_result: dict[str, Any],
) -> dict[str, Any]:
    """格式化完整回测报告

    Args:
        code: 股票代码
        strategy_id: 策略ID
        strategy_params: 策略参数
        records: K线数据
        simulation_result: 模拟结果 (from run_simulation)

    Returns:
        格式化的回测报告字典
    """
    trades = simulation_result.get("trades", [])
    equity_curve = simulation_result.get("equity_curve", [])
    final_value = simulation_result.get("final_value", 0)
    initial_capital = simulation_result.get("initial_capital", 100000)
    error = simulation_result.get("error")

    # 计算起止日期
    start_date = records[0].get("date", "") if records else ""
    end_date = records[-1].get("date", "") if records else ""
    total_days = len(records) if records else 0

    # 计算绩效指标
    if error:
        metrics = {"error": error}
    else:
        metrics = calc_all_metrics(trades, equity_curve, final_value, initial_capital, total_days)

    # 计算评级
    rating = _compute_rating(metrics) if not error else {
        "rating": "N/A", "rating_score": 0, "rating_label": "数据不足",
        "dimensions": {}, "veto": error,
    }

    # 构建报告
    report = {
        "code": code,
        "strategy_id": strategy_id,
        "strategy_name": STRATEGY_NAMES.get(strategy_id, strategy_id),
        "strategy_params": strategy_params,
        "period": {
            "start": start_date,
            "end": end_date,
            "trading_days": total_days,
        },
        "capital": {
            "initial": initial_capital,
            "final": round(final_value, 2),
        },
        "metrics": metrics,
        "rating": rating,
        "trades": trades,
        "trade_count": len(trades),
        "equity_curve": equity_curve,
        "equity_curve_points": len(equity_curve),
        "slippage_model": simulation_result.get("slippage_model", "percentage (默认)"),
        "total_slippage_cost": simulation_result.get("total_slippage_cost", 0),
        "success": error is None,
        "note": "⚠️ 回测结果仅作研究参考，不代表未来收益",
    }

    return report
