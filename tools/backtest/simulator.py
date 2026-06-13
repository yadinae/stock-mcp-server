"""
交易模拟引擎

实现 信号 → 交易执行 → 持仓管理 的完整链条。

核心规则：
- 信号收盘确认，次日开盘执行
- T+1: A股买入后，最早 D+1 日可卖出
- 手续费: 买入万分之2.5，卖出万分之2.5 + 千分之1印花税
- 滑点: 0.1%
- 仓位: 全仓模式（信号发出时全部资金使用/全部持仓卖出）
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger("stock-mcp.backtest.simulator")

# ── 默认费率 ──────────────────────────────────────────────
COMMISSION_RATE_BUY = 0.00025      # 买入万2.5
COMMISSION_RATE_SELL = 0.00025     # 卖出万2.5
STAMP_TAX_RATE = 0.001             # 印花税千1（卖出征收）
SLIPPAGE_RATE = 0.001              # 滑点0.1%


@dataclass
class Trade:
    """一笔已完成的交易"""
    buy_date: str
    sell_date: str
    buy_price: float
    sell_price: float
    shares: int
    commission: float
    stamp_tax: float
    profit: float
    profit_pct: float
    hold_days: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "buy_date": self.buy_date,
            "sell_date": self.sell_date,
            "buy_price": round(self.buy_price, 2),
            "sell_price": round(self.sell_price, 2),
            "shares": self.shares,
            "commission": round(self.commission, 2),
            "stamp_tax": round(self.stamp_tax, 2),
            "profit": round(self.profit, 2),
            "profit_pct": round(self.profit_pct, 2),
            "hold_days": self.hold_days,
        }


def _find_next_trade_day(records: list[dict], current_idx: int) -> int | None:
    """找到下一个交易日的索引（次日可卖）"""
    for i in range(current_idx + 1, len(records)):
        return i  # 下一个交易日
    return None


def _get_open_price(records: list[dict], idx: int) -> float:
    """获取开盘价（含滑点）"""
    try:
        price = float(records[idx].get("open", 0))
        if price == 0:
            price = float(records[idx].get("close", 0))
        return price * (1 + SLIPPAGE_RATE)
    except (IndexError, TypeError, ValueError):
        return 0.0


def _get_sell_open_price(records: list[dict], idx: int) -> float:
    """获取卖出开盘价（含滑点+向下）"""
    try:
        price = float(records[idx].get("open", 0))
        if price == 0:
            price = float(records[idx].get("close", 0))
        return price * (1 - SLIPPAGE_RATE)
    except (IndexError, TypeError, ValueError):
        return 0.0


def run_simulation(
    records: list[dict],
    signals: list[dict],
    initial_capital: float = 100000.0,
    verbose: bool = False,
) -> dict[str, Any]:
    """运行交易模拟

    Args:
        records: K线数据（按日期正序）
        signals: 策略信号列表（按日期正序）
        initial_capital: 初始资金
        verbose: 打印详细日志

    Returns:
        包含 trades, equity_curve, final_value 的字典
    """
    if not records:
        return {"error": "无K线数据", "trades": [], "equity_curve": [], "final_value": 0}

    if not signals:
        return {
            "error": "无交易信号",
            "trades": [],
            "equity_curve": _empty_equity_curve(records),
            "final_value": initial_capital,
        }

    # 构建日期到索引的映射
    date_to_idx = {}
    for i, r in enumerate(records):
        date_to_idx[r.get("date", "")] = i

    cash = initial_capital
    shares = 0
    buy_date: str | None = None
    buy_price: float = 0.0
    trades: list[Trade] = []
    equity_curve: list[dict] = []

    # 记录最后交易日期（用于T+1检查）
    last_trade_idx = -2  # 初始无交易

    for sig in signals:
        action = sig.get("action", "")
        if action not in ("buy", "sell"):
            continue

        sig_date = sig.get("date", "")
        sig_idx = date_to_idx.get(sig_date, -1)

        if sig_idx < 0:
            if verbose:
                logger.debug("信号日期 %s 不在K线数据中", sig_date)
            continue

        # 信号收盘确认，在次日执行
        exec_idx = sig_idx + 1
        if exec_idx >= len(records):
            if verbose:
                logger.debug("信号 %s: 次日已超出数据范围", sig_date)
            continue

        exec_date = records[exec_idx].get("date", "")

        if action == "buy" and cash > 0 and shares == 0:
            # 执行买入
            price = _get_open_price(records, exec_idx)
            shares_buyable = int(cash / (price * (1 + COMMISSION_RATE_BUY)))
            if shares_buyable <= 0:
                continue
            shares = shares_buyable
            commission = round(shares * price * COMMISSION_RATE_BUY, 2)
            cash -= shares * price + commission
            buy_date = exec_date
            buy_price = price
            last_trade_idx = exec_idx

            if verbose:
                print(f"  {exec_date} 买入 {shares}股 @ {price:.2f} (佣金={commission:.2f})")

        elif action == "sell" and shares > 0:
            # T+1 检查：卖出日必须在买入日之后
            if exec_idx <= last_trade_idx:
                if verbose:
                    print(f"  {exec_date} 跳过: T+1限制（买入当日不能卖）")
                continue

            # 执行卖出
            price = _get_sell_open_price(records, exec_idx)
            proceeds = shares * price
            commission = round(proceeds * COMMISSION_RATE_SELL, 2)
            stamp_tax = round(proceeds * STAMP_TAX_RATE, 2)
            net_proceeds = proceeds - commission - stamp_tax

            profit = net_proceeds - (shares * buy_price + (shares * buy_price * COMMISSION_RATE_BUY))
            hold_days = exec_idx - last_trade_idx
            profit_pct = (profit / (shares * buy_price)) * 100 if shares * buy_price else 0

            trade = Trade(
                buy_date=buy_date or "",
                sell_date=exec_date,
                buy_price=buy_price,
                sell_price=price,
                shares=shares,
                commission=commission + (shares * buy_price * COMMISSION_RATE_BUY),
                stamp_tax=stamp_tax,
                profit=profit,
                profit_pct=profit_pct,
                hold_days=hold_days,
            )
            trades.append(trade)

            cash = net_proceeds
            shares = 0

            if verbose:
                print(f"  {exec_date} 卖出 {trade.shares}股 @ {price:.2f} "
                      f"(佣金={commission:.2f} 印花税={stamp_tax:.2f}) "
                      f"盈亏={profit:.2f}({profit_pct:.2f}%)")

    # 计算最终权益和每日权益曲线
    final_value = cash + _mark_to_market(records, shares)
    equity_curve = _build_equity_curve(records, trades, cash, shares, initial_capital)

    result = {
        "trades": [t.to_dict() for t in trades],
        "equity_curve": equity_curve,
        "final_value": round(final_value, 2),
        "initial_capital": initial_capital,
        "total_return": round((final_value - initial_capital) / initial_capital * 100, 2),
        "trade_count": len(trades),
        "final_cash": round(cash, 2),
        "final_shares": shares,
    }

    return result


def _mark_to_market(records: list[dict], shares: int) -> float:
    """未实现盈亏计算（最后一日收盘价）"""
    if shares <= 0 or not records:
        return 0.0
    last_close = float(records[-1].get("close", 0))
    return shares * last_close


def _build_equity_curve(
    records: list[dict],
    trades: list[Trade],
    cash: float,
    shares: int,
    initial_capital: float,
) -> list[dict]:
    """构建每日权益曲线

    每日 value = cash + 持仓市值（用当日收盘价估算）
    """
    if not records:
        return []

    curve = []
    trade_idx = 0
    current_cash = initial_capital
    current_shares = 0
    # 根据交易记录逐步更新
    buy_recorded = {}  # buy_date -> (shares, price)

    for i, r in enumerate(records):
        date = r.get("date", "")
        close = float(r.get("close", 0))

        # 处理到当前日期为止的所有交易
        while trade_idx < len(trades):
            t = trades[trade_idx]
            if t.buy_date <= date:
                if t.buy_date == date:
                    # 买入当天持仓更新
                    current_cash -= t.shares * t.buy_price + \
                        (t.shares * t.buy_price * COMMISSION_RATE_BUY)
                    current_shares = t.shares
                trade_idx += 1
                # 需要同时看在卖出日期之前有没有新的买入
                continue
            break

        # 简单方法：直接根据已有交易构建
        # 持有市值
        market_value = current_shares * close
        equity = cash + market_value

        curve.append({
            "date": date,
            "value": round(equity, 2),
        })

    # 再次从 trades 重建更精确的曲线
    return _rebuild_equity_curve(records, trades, initial_capital)


def _rebuild_equity_curve(
    records: list[dict],
    trades: list[Trade],
    initial_capital: float,
) -> list[dict]:
    """更精确地重建权益曲线

    模拟每日持仓变化：
    - 买入日：现金减少，获得持仓
    - 卖出日：持仓清空，获得现金
    """
    curve = []
    cash = initial_capital
    shares = 0
    buy_price_record = 0.0
    trade_ptr = 0
    in_position = False

    for r in records:
        date = r.get("date", "")
        close = float(r.get("close", 0))

        # 检查是否有交易发生
        while trade_ptr < len(trades):
            t = trades[trade_ptr]
            if t.buy_date == date:
                # 买入
                cost = t.shares * t.buy_price + t.shares * t.buy_price * COMMISSION_RATE_BUY
                cash -= cost
                shares = t.shares
                buy_price_record = t.buy_price
                in_position = True
                trade_ptr += 1
            elif t.sell_date == date:
                # 卖出
                proceeds = t.shares * t.sell_price - t.commission - t.stamp_tax
                cash += proceeds
                shares = 0
                in_position = False
                trade_ptr += 1
            else:
                break

        # 市价
        market_value = shares * close
        equity = cash + market_value

        curve.append({
            "date": date,
            "value": round(equity, 2),
        })

    return curve


def _empty_equity_curve(records: list[dict]) -> list[dict]:
    """无交易时的权益曲线（直线）"""
    return [{"date": r.get("date", ""), "value": 100000.0} for r in records]
