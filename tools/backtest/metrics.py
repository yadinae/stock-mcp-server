"""
绩效指标计算

基于交易记录和权益曲线计算各种绩效指标。
全部使用纯 Python 标准库（无 numpy/pandas）。
"""

from __future__ import annotations

import math
from typing import Any


def calc_total_return(final_value: float, initial_capital: float) -> dict[str, Any]:
    """总收益率"""
    if initial_capital <= 0:
        return {"total_return_pct": 0.0}
    ret = (final_value - initial_capital) / initial_capital * 100
    return {"total_return_pct": round(ret, 2)}


def calc_annual_return(total_return_pct: float, days: int) -> dict[str, Any]:
    """年化收益率（按250个交易日）"""
    if days <= 0 or total_return_pct <= -100:
        return {"annual_return_pct": 0.0, "note": "数据不足"}
    years = days / 250
    if years <= 0:
        return {"annual_return_pct": 0.0}
    # (1 + r)^(1/years) - 1
    factor = 1 + total_return_pct / 100
    if factor <= 0:
        return {"annual_return_pct": -100.0}
    annual = (factor ** (1 / years) - 1) * 100
    return {"annual_return_pct": round(annual, 2)}


def calc_max_drawdown(equity_curve: list[dict]) -> dict[str, Any]:
    """最大回撤 (MDD)

    遍历权益曲线，记录从峰值到谷值的最大跌幅。
    算法：O(n)，只保留峰值值和当前回撤。
    """
    if not equity_curve:
        return {"max_drawdown_pct": 0.0}

    peak = float(equity_curve[0].get("value", 0))
    max_dd = 0.0
    max_dd_start = ""
    max_dd_end = ""
    current_start = ""

    for point in equity_curve:
        value = float(point.get("value", 0))
        date = point.get("date", "")

        if value > peak:
            peak = value
            current_start = date

        dd = (peak - value) / peak * 100 if peak > 0 else 0
        if dd > max_dd:
            max_dd = dd
            max_dd_start = current_start
            max_dd_end = date

    return {
        "max_drawdown_pct": round(max_dd, 2),
        "max_drawdown_start": max_dd_start,
        "max_drawdown_end": max_dd_end,
    }


def calc_sharpe_ratio(equity_curve: list[dict], risk_free_rate: float = 0.02) -> dict[str, Any]:
    """夏普比率

    计算每日收益率的标准差，年化后算 Sharpe。
    Sharpe = (年化收益 - 无风险利率) / 年化波动率

    注意：权益曲线不足30个点时不计算（统计不显著）。
    """
    if len(equity_curve) < 30:
        return {"sharpe_ratio": 0.0, "note": "数据不足30个交易日，统计不显著"}

    values = [float(p.get("value", 0)) for p in equity_curve]
    if values[0] <= 0:
        return {"sharpe_ratio": 0.0}

    # 每日收益率
    daily_returns = []
    for i in range(1, len(values)):
        if values[i - 1] > 0:
            ret = (values[i] - values[i - 1]) / values[i - 1]
            daily_returns.append(ret)

    if len(daily_returns) < 20:
        return {"sharpe_ratio": 0.0, "note": "有效交易天数不足20"}

    # 年化
    avg_daily_return = sum(daily_returns) / len(daily_returns)
    variance = sum((r - avg_daily_return) ** 2 for r in daily_returns) / len(daily_returns)
    daily_std = math.sqrt(variance)

    if daily_std == 0:
        return {"sharpe_ratio": 0.0, "note": "无波动"}

    # 年化: 250个交易日
    annual_return = avg_daily_return * 250
    annual_std = daily_std * math.sqrt(250)
    risk_free_annual = risk_free_rate

    sharpe = (annual_return - risk_free_annual) / annual_std

    return {
        "sharpe_ratio": round(sharpe, 3),
        "annual_volatility_pct": round(annual_std * 100, 2),
    }


def calc_win_rate(trades: list[dict]) -> dict[str, Any]:
    """胜率"""
    if not trades:
        return {"win_rate_pct": 0.0, "total_trades": 0}

    wins = sum(1 for t in trades if t.get("profit", 0) > 0)
    total = len(trades)
    return {
        "win_rate_pct": round(wins / total * 100, 2) if total else 0.0,
        "win_count": wins,
        "loss_count": total - wins,
        "total_trades": total,
    }


def calc_profit_factor(trades: list[dict]) -> dict[str, Any]:
    """盈亏比 (Profit Factor)

    Profit Factor = 总盈利 / 总亏损的绝对值
    PF > 2 = 优秀, PF > 1.5 = 良好, PF < 1 = 亏损
    """
    if not trades:
        return {"profit_factor": 0.0}

    gross_profit = sum(t.get("profit", 0) for t in trades if t.get("profit", 0) > 0)
    gross_loss = abs(sum(t.get("profit", 0) for t in trades if t.get("profit", 0) < 0))

    if gross_loss == 0:
        return {"profit_factor": float("inf") if gross_profit > 0 else 0.0}

    return {"profit_factor": round(gross_profit / gross_loss, 3)}


def calc_sortino_ratio(equity_curve: list[dict], risk_free_rate: float = 0.02) -> dict[str, Any]:
    """Sortino 比率 — 只惩罚下行波动

    Sortino = (年化收益 - 无风险利率) / 下行波动率
    比 Sharpe 更合理：上涨波动不应被惩罚。
    """
    if len(equity_curve) < 30:
        return {"sortino_ratio": 0.0, "note": "数据不足30个交易日"}

    values = [float(p.get("value", 0)) for p in equity_curve]
    if values[0] <= 0:
        return {"sortino_ratio": 0.0}

    daily_returns = []
    for i in range(1, len(values)):
        if values[i - 1] > 0:
            daily_returns.append((values[i] - values[i - 1]) / values[i - 1])

    if len(daily_returns) < 20:
        return {"sortino_ratio": 0.0, "note": "有效交易天数不足20"}

    avg_daily = sum(daily_returns) / len(daily_returns)
    # 下行偏差：只计算负收益
    downside_returns = [r for r in daily_returns if r < 0]
    if not downside_returns:
        return {"sortino_ratio": float("inf") if avg_daily > 0 else 0.0, "note": "无下行波动"}

    downside_var = sum(r ** 2 for r in downside_returns) / len(daily_returns)  # 用全部天数做分母
    downside_std = math.sqrt(downside_var) if downside_var > 0 else 1e-10

    annual_return = avg_daily * 250
    annual_downside = downside_std * math.sqrt(250)
    sortino = (annual_return - risk_free_rate) / annual_downside

    return {"sortino_ratio": round(sortino, 3)}


def calc_calmar_ratio(total_return_pct: float, max_drawdown_pct: float, days: int) -> dict[str, Any]:
    """Calmar 比率 — 年化收益 / 最大回撤

    Calmar > 1 = 优秀（每承受1%回撤换1%年化）
    Calmar > 2 = 卓越
    """
    if max_drawdown_pct <= 0 or days <= 0:
        return {"calmar_ratio": 0.0, "note": "无回撤或数据不足"}

    years = days / 250
    factor = 1 + total_return_pct / 100
    if factor <= 0:
        return {"calmar_ratio": 0.0}

    annual_return = (factor ** (1 / years) - 1) * 100 if years > 0 else 0
    calmar = annual_return / max_drawdown_pct

    return {"calmar_ratio": round(calmar, 3)}


def calc_volatility(equity_curve: list[dict]) -> dict[str, Any]:
    """年化波动率"""
    if len(equity_curve) < 30:
        return {"volatility_pct": 0.0, "note": "数据不足"}

    values = [float(p.get("value", 0)) for p in equity_curve]
    if values[0] <= 0:
        return {"volatility_pct": 0.0}

    daily_returns = []
    for i in range(1, len(values)):
        if values[i - 1] > 0:
            daily_returns.append((values[i] - values[i - 1]) / values[i - 1])

    if len(daily_returns) < 20:
        return {"volatility_pct": 0.0}

    avg = sum(daily_returns) / len(daily_returns)
    var = sum((r - avg) ** 2 for r in daily_returns) / len(daily_returns)
    daily_std = math.sqrt(var)
    annual_vol = daily_std * math.sqrt(250) * 100

    return {"volatility_pct": round(annual_vol, 2)}


def calc_max_drawdown_duration(equity_curve: list[dict]) -> dict[str, Any]:
    """最大回撤持续天数（从峰值到恢复的最长天数）"""
    if not equity_curve:
        return {"max_dd_duration_days": 0}

    peak = float(equity_curve[0].get("value", 0))
    peak_idx = 0
    max_duration = 0

    for i, point in enumerate(equity_curve):
        value = float(point.get("value", 0))
        if value >= peak:
            peak = value
            peak_idx = i
        duration = i - peak_idx
        if duration > max_duration:
            max_duration = duration

    return {"max_dd_duration_days": max_duration}


def calc_avg_hold_days(trades: list[dict]) -> dict[str, Any]:
    """平均持仓天数"""
    if not trades:
        return {"avg_hold_days": 0}
    hold_days = [t.get("hold_days", 0) for t in trades]
    avg = sum(hold_days) / len(hold_days)
    return {
        "avg_hold_days": round(avg, 1),
        "min_hold_days": min(hold_days),
        "max_hold_days": max(hold_days),
    }


def calc_all_metrics(
    trades: list[dict],
    equity_curve: list[dict],
    final_value: float,
    initial_capital: float,
    days: int,
) -> dict[str, Any]:
    """计算所有绩效指标"""
    metrics = {}

    # 总收益率
    ret = calc_total_return(final_value, initial_capital)
    metrics.update(ret)

    # 年化收益率
    annual = calc_annual_return(ret["total_return_pct"], days)
    metrics.update(annual)

    # 最大回撤
    mdd = calc_max_drawdown(equity_curve)
    metrics.update(mdd)

    # 夏普比率
    sharpe = calc_sharpe_ratio(equity_curve)
    metrics.update(sharpe)

    # 胜率
    win = calc_win_rate(trades)
    metrics.update(win)

    # 盈亏比
    pf = calc_profit_factor(trades)
    metrics.update(pf)

    # 平均持仓
    hold = calc_avg_hold_days(trades)
    metrics.update(hold)

    # Sortino 比率
    sortino = calc_sortino_ratio(equity_curve)
    metrics.update(sortino)

    # Calmar 比率
    calmar = calc_calmar_ratio(
        ret["total_return_pct"], mdd.get("max_drawdown_pct", 0), days
    )
    metrics.update(calmar)

    # 年化波动率
    vol = calc_volatility(equity_curve)
    metrics.update(vol)

    # 最大回撤持续天数
    dd_dur = calc_max_drawdown_duration(equity_curve)
    metrics.update(dd_dur)

    # 总天数
    metrics["total_days"] = days

    return metrics
