"""
回测模块入口

提供 run_backtest() 函数，供 server.py 的 MCP 工具调用。
"""

from __future__ import annotations

from typing import Any

from .strategies import list_strategies, run_strategy, STRATEGY_DEFAULT_PARAMS
from .simulator import run_simulation
from .report import format_report


def run_backtest(
    code: str,
    records: list[dict],
    strategy: str = "ma_crossover",
    days: int = 365,
    capital: float = 100000.0,
    params: dict | None = None,
) -> dict[str, Any]:
    """运行回测

    Args:
        code: 股票代码
        records: K线数据（按日期正序）
        strategy: 策略ID
        days: 实际使用的K线天数
        capital: 初始资金
        params: 策略参数覆盖

    Returns:
        回测报告字典
    """
    if not records:
        return {
            "code": code,
            "error": "无K线数据",
            "success": False,
        }

    # 合并策略参数
    strategy_params = dict(STRATEGY_DEFAULT_PARAMS.get(strategy, {}))
    if params:
        strategy_params.update(params)

    # 运行策略生成信号
    signals = run_strategy(strategy, records, **strategy_params)

    # 运行模拟
    sim_result = run_simulation(
        records=records,
        signals=signals,
        initial_capital=capital,
    )

    # 格式化报告
    report = format_report(
        code=code,
        strategy_id=strategy,
        strategy_params=strategy_params,
        records=records,
        simulation_result=sim_result,
    )

    report["data_days"] = days
    return report


def list_backtest_strategies() -> list[dict]:
    """列出可用回测策略"""
    return list_strategies()
