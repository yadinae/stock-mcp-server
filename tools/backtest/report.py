"""
回测报告格式化

将模拟结果和绩效指标格式化为统一的输出字典。
"""

from __future__ import annotations

from typing import Any

from .strategies import STRATEGY_NAMES
from .metrics import calc_all_metrics


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
        "trades": trades,
        "trade_count": len(trades),
        "equity_curve": equity_curve,
        "equity_curve_points": len(equity_curve),
        "success": error is None,
        "note": "⚠️ 回测结果仅作研究参考，不代表未来收益",
    }

    return report
