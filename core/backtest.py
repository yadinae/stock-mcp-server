"""
回测验证框架 — 用历史数据验证漏斗策略效果

借鉴 WyckoffTradingAgent 的回测设计：
- 信号日候选只由该日数据生成
- 禁止未来数据参与筛选
- 扣除交易成本后计算净收益

用法:
    from core.backtest import BacktestRunner
    runner = BacktestRunner()
    result = runner.run()
    result.print_report()
"""
from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger("stock-mcp.backtest")

_BAOSTOCK_DB = Path(__file__).parent.parent / "data" / "baostock_cache.db"

# 交易成本
ROUND_TRIP_COST_PCT = 0.202  # A 股双边交易成本（约 0.2%）


@dataclass
class TradeRecord:
    """单笔交易记录"""
    code: str
    signal_date: str
    signal_type: str
    entry_date: str
    entry_price: float
    exit_date: str
    exit_price: float
    holding_days: int
    pnl_pct: float
    net_pnl_pct: float  # 扣除交易成本后
    result: str  # "win" | "loss" | "neutral"


@dataclass
class BacktestResult:
    """回测结果"""
    start_date: str
    end_date: str
    total_trades: int
    win_count: int
    loss_count: int
    neutral_count: int
    win_rate: float
    avg_pnl_pct: float
    avg_net_pnl_pct: float
    max_win_pct: float
    max_loss_pct: float
    sharpe_ratio: float
    trades: List[TradeRecord] = field(default_factory=list)
    signal_type_stats: Dict[str, dict] = field(default_factory=dict)

    def print_report(self):
        """打印回测报告"""
        print("\n" + "=" * 60)
        print("回测报告")
        print("=" * 60)
        print(f"回测区间: {self.start_date} ~ {self.end_date}")
        print(f"总交易数: {self.total_trades}")
        print(f"胜率: {self.win_rate:.1%}")
        print(f"平均收益: {self.avg_pnl_pct:+.2f}%")
        print(f"平均净收益: {self.avg_net_pnl_pct:+.2f}% (扣 {ROUND_TRIP_COST_PCT}% 成本)")
        print(f"最大盈利: {self.max_win_pct:+.2f}%")
        print(f"最大亏损: {self.max_loss_pct:+.2f}%")
        print(f"Sharpe 比率: {self.sharpe_ratio:.2f}")

        if self.signal_type_stats:
            print(f"\n按信号类型:")
            for st, stats in self.signal_type_stats.items():
                print(f"  {st}: {stats['count']} trades, win_rate={stats['win_rate']:.1%}, "
                      f"avg_pnl={stats['avg_pnl']:+.2f}%")

        print("=" * 60)


class BacktestRunner:
    """
    回测运行器

    Args:
        holding_days: 持仓天数（默认 5 天）
        stop_loss_pct: 止损百分比（默认 -8%）
        take_profit_pct: 止盈百分比（默认 +15%）
    """

    def __init__(
        self,
        holding_days: int = 5,
        stop_loss_pct: float = -8.0,
        take_profit_pct: float = 15.0,
    ):
        self.holding_days = holding_days
        self.stop_loss_pct = stop_loss_pct
        self.take_profit_pct = take_profit_pct

    def run(self, start_date: Optional[str] = None, end_date: Optional[str] = None) -> BacktestResult:
        """
        运行回测

        Args:
            start_date: 开始日期（默认 60 天前）
            end_date: 结束日期（默认今天）
        """
        if not _BAOSTOCK_DB.exists():
            logger.error("Baostock cache not found")
            return BacktestResult(
                start_date="", end_date="", total_trades=0,
                win_count=0, loss_count=0, neutral_count=0,
                win_rate=0, avg_pnl_pct=0, avg_net_pnl_pct=0,
                max_win_pct=0, max_loss_pct=0, sharpe_ratio=0,
            )

        # 默认日期范围
        if not end_date:
            end_date = datetime.now().strftime("%Y-%m-%d")
        if not start_date:
            start_date = (datetime.now() - timedelta(days=120)).strftime("%Y-%m-%d")

        conn = sqlite3.connect(str(_BAOSTOCK_DB))
        try:
            # 获取所有股票
            symbols = [r[0] for r in conn.execute(
                "SELECT DISTINCT symbol FROM stock_daily"
            ).fetchall()]

            trades = []
            for symbol in symbols:
                # 获取该股票的 K 线数据
                df = conn.execute(
                    "SELECT date, open, high, low, close, volume "
                    "FROM stock_daily WHERE symbol = ? ORDER BY date",
                    (symbol,),
                ).fetchall()

                if len(df) < 60:
                    continue

                # 模拟信号检测 + 持有
                for i in range(60, len(df) - self.holding_days):
                    signal_date = df[i][0]
                    if signal_date < start_date or signal_date > end_date:
                        continue

                    # 模拟信号检测（简化：用趋势通道逻辑）
                    closes = [r[4] for r in df[max(0, i-50):i+1] if r[4]]
                    volumes = [r[5] for r in df[max(0, i-20):i+1] if r[5]]

                    if len(closes) < 20 or len(volumes) < 10:
                        continue

                    # 简化趋势检测
                    ma20 = sum(closes[-20:]) / 20
                    ma50 = sum(closes[-50:]) / 50 if len(closes) >= 50 else ma20
                    current_close = closes[-1]

                    if current_close <= ma20 or ma20 <= ma50:
                        continue

                    # 入场价 = 次日开盘价
                    entry_price = df[i+1][1]  # open
                    if not entry_price or entry_price <= 0:
                        continue

                    # 模拟持有
                    exit_price = entry_price
                    exit_date = signal_date
                    for j in range(1, min(self.holding_days + 1, len(df) - i)):
                        day = df[i + j]
                        high = day[2]
                        low = day[3]
                        close = day[4]

                        # 止损
                        pnl = (low - entry_price) / entry_price * 100
                        if pnl <= self.stop_loss_pct:
                            exit_price = entry_price * (1 + self.stop_loss_pct / 100)
                            exit_date = day[0]
                            break

                        # 止盈
                        pnl = (high - entry_price) / entry_price * 100
                        if pnl >= self.take_profit_pct:
                            exit_price = entry_price * (1 + self.take_profit_pct / 100)
                            exit_date = day[0]
                            break

                        # 到期平仓
                        exit_price = close
                        exit_date = day[0]

                    # 计算收益
                    pnl_pct = (exit_price - entry_price) / entry_price * 100
                    net_pnl_pct = pnl_pct - ROUND_TRIP_COST_PCT

                    result = "win" if net_pnl_pct > 0.5 else ("loss" if net_pnl_pct < -0.5 else "neutral")

                    actual_days = min(self.holding_days, len(df) - i - 1)
                    trades.append(TradeRecord(
                        code=symbol,
                        signal_date=signal_date,
                        signal_type="trend",
                        entry_date=df[i+1][0],
                        entry_price=round(entry_price, 2),
                        exit_date=exit_date,
                        exit_price=round(exit_price, 2),
                        holding_days=actual_days,
                        pnl_pct=round(pnl_pct, 2),
                        net_pnl_pct=round(net_pnl_pct, 2),
                        result=result,
                    ))
        finally:
            conn.close()

        # 统计
        return self._compute_stats(trades, start_date, end_date)

    def _compute_stats(self, trades: List[TradeRecord], start_date: str, end_date: str) -> BacktestResult:
        """计算回测统计"""
        if not trades:
            return BacktestResult(
                start_date=start_date, end_date=end_date, total_trades=0,
                win_count=0, loss_count=0, neutral_count=0,
                win_rate=0, avg_pnl_pct=0, avg_net_pnl_pct=0,
                max_win_pct=0, max_loss_pct=0, sharpe_ratio=0,
            )

        wins = [t for t in trades if t.result == "win"]
        losses = [t for t in trades if t.result == "loss"]
        neutrals = [t for t in trades if t.result == "neutral"]

        avg_pnl = sum(t.pnl_pct for t in trades) / len(trades)
        avg_net = sum(t.net_pnl_pct for t in trades) / len(trades)
        max_win = max(t.pnl_pct for t in trades)
        max_loss = min(t.pnl_pct for t in trades)

        # Sharpe 比率（简化版）
        returns = [t.net_pnl_pct for t in trades]
        if len(returns) > 1:
            mean_r = sum(returns) / len(returns)
            std_r = (sum((r - mean_r) ** 2 for r in returns) / (len(returns) - 1)) ** 0.5
            sharpe = (mean_r / std_r * (252 ** 0.5)) if std_r > 0 else 0
        else:
            sharpe = 0

        # 按信号类型统计
        type_stats = {}
        for t in trades:
            st = t.signal_type
            if st not in type_stats:
                type_stats[st] = {"count": 0, "wins": 0, "pnl_sum": 0}
            type_stats[st]["count"] += 1
            if t.result == "win":
                type_stats[st]["wins"] += 1
            type_stats[st]["pnl_sum"] += t.pnl_pct

        for st, stats in type_stats.items():
            stats["win_rate"] = stats["wins"] / stats["count"] if stats["count"] > 0 else 0
            stats["avg_pnl"] = stats["pnl_sum"] / stats["count"] if stats["count"] > 0 else 0

        return BacktestResult(
            start_date=start_date,
            end_date=end_date,
            total_trades=len(trades),
            win_count=len(wins),
            loss_count=len(losses),
            neutral_count=len(neutrals),
            win_rate=len(wins) / len(trades),
            avg_pnl_pct=round(avg_pnl, 2),
            avg_net_pnl_pct=round(avg_net, 2),
            max_win_pct=round(max_win, 2),
            max_loss_pct=round(max_loss, 2),
            sharpe_ratio=round(sharpe, 2),
            trades=trades,
            signal_type_stats=type_stats,
        )
