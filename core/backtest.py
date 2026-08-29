"""
回测验证框架 v2 — 向量化重写

核心变化（参考 vectorbt 向量化思路）：
- 使用 BaostockMemoryCache 内存缓存（消除 SQLite I/O）
- 所有 MA/信号计算使用 pandas rolling 向量化
- 交易模拟使用 NumPy 矩阵运算替代逐 Bar 循环
- 支持批量参数扫描：预加载数据一次，仅变换参数

用法:
    from core.backtest import BacktestRunner
    runner = BacktestRunner()
    result = runner.run()
    result.print_report()

    # 参数扫描（预加载一次，快速扫描）
    from core.backtest import param_scan
    results = param_scan(
        holding_days=[3, 5, 10],
        stop_loss_pct=[-5, -8, -10],
        take_profit_pct=[10, 15, 20],
    )
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from itertools import product
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger("stock-mcp.backtest")

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
    net_pnl_pct: float
    result: str


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


# ═══════════════════════════════════════════════════════════════
# 向量化工具函数
# ═══════════════════════════════════════════════════════════════

def _vectorized_ma(closes: np.ndarray, period: int) -> np.ndarray:
    """向量化 N 日均线（返回完整序列）"""
    return pd.Series(closes).rolling(period, min_periods=period).mean().values


def _vectorized_signal_detect(
    closes: np.ndarray,
    ma_s: np.ndarray,
    ma_l: np.ndarray,
) -> np.ndarray:
    """
    向量化信号检测：MA 短期上穿长期

    Args:
        closes: 收盘价数组
        ma_s: 短期 MA 序列（已预计算）
        ma_l: 长期 MA 序列（已预计算）

    Returns:
        布尔数组，True = 该 Bar 产生买入信号
    """
    if len(closes) < 2 or len(ma_s) < 2 or len(ma_l) < 2:
        return np.zeros(len(closes), dtype=bool)

    # 金叉：前一根 ma_s <= ma_l，当前 ma_s > ma_l
    cross_up = np.zeros(len(closes), dtype=bool)
    cross_up[1:] = (ma_s[:-1] <= ma_l[:-1]) & (ma_s[1:] > ma_l[1:])

    # 额外条件：收盘价 > MA 短期（趋势确认）
    valid = ~np.isnan(ma_s) & ~np.isnan(ma_l)
    cross_up &= valid & (closes > ma_s)

    return cross_up


def _vectorized_simulate_trades(
    dates: np.ndarray,
    opens: np.ndarray,
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    signal_mask: np.ndarray,
    holding_days: int,
    stop_loss_pct: float,
    take_profit_pct: float,
    code: str = "",
    signal_type: str = "trend",
) -> List[TradeRecord]:
    """
    向量化交易模拟

    对给定的信号位置，模拟持仓并计算收益。
    """
    trades = []
    signal_indices = np.where(signal_mask)[0]

    for idx in signal_indices:
        entry_bar = idx + 1
        if entry_bar >= len(opens):
            continue

        entry_price = opens[entry_bar]
        if not entry_price or entry_price <= 0 or np.isnan(entry_price):
            continue

        entry_date = str(dates[entry_bar])
        exit_price = entry_price
        exit_date = entry_date
        actual_days = 0

        for j in range(1, min(holding_days + 1, len(opens) - entry_bar)):
            bar = entry_bar + j
            high = highs[bar]
            low = lows[bar]
            close = closes[bar]

            if low and not np.isnan(low):
                pnl_low = (low - entry_price) / entry_price * 100
                if pnl_low <= stop_loss_pct:
                    exit_price = entry_price * (1 + stop_loss_pct / 100)
                    exit_date = str(dates[bar])
                    actual_days = j
                    break

            if high and not np.isnan(high):
                pnl_high = (high - entry_price) / entry_price * 100
                if pnl_high >= take_profit_pct:
                    exit_price = entry_price * (1 + take_profit_pct / 100)
                    exit_date = str(dates[bar])
                    actual_days = j
                    break

            if close and not np.isnan(close):
                exit_price = close
                exit_date = str(dates[bar])
            actual_days = j

        pnl_pct = (exit_price - entry_price) / entry_price * 100
        net_pnl_pct = pnl_pct - ROUND_TRIP_COST_PCT
        result = "win" if net_pnl_pct > 0.5 else ("loss" if net_pnl_pct < -0.5 else "neutral")

        trades.append(TradeRecord(
            code=code, signal_date=str(dates[idx]), signal_type=signal_type,
            entry_date=entry_date, entry_price=round(entry_price, 2),
            exit_date=exit_date, exit_price=round(exit_price, 2),
            holding_days=actual_days, pnl_pct=round(pnl_pct, 2),
            net_pnl_pct=round(net_pnl_pct, 2), result=result,
        ))

    return trades


# ═══════════════════════════════════════════════════════════════
# 预加载数据层（参数扫描核心优化）
# ═══════════════════════════════════════════════════════════════

@dataclass
class PreloadedStock:
    """预加载的单只股票数据（numpy 数组）"""
    symbol: str
    dates: np.ndarray
    opens: np.ndarray
    highs: np.ndarray
    lows: np.ndarray
    closes: np.ndarray
    # 预计算的 MA（按 period 索引）
    _ma_cache: Dict[int, np.ndarray] = field(default_factory=dict)

    def get_ma(self, period: int) -> np.ndarray:
        """获取预计算的 MA（懒计算+缓存）"""
        if period not in self._ma_cache:
            self._ma_cache[period] = _vectorized_ma(self.closes, period)
        return self._ma_cache[period]


class PreloadedData:
    """
    预加载的全市场数据

    从 BaostockMemoryCache 一次性加载所有数据到内存，
    参数扫描时只变换参数，不重复 I/O。

    v2 优化：预计算所有可能的 MA 组合，参数扫描时直接查表。
    """

    def __init__(self, start_date: Optional[str] = None, end_date: Optional[str] = None,
                 ma_periods: Optional[List[int]] = None):
        from core.baostock_cache import BaostockMemoryCache
        cache = BaostockMemoryCache.instance()

        self.stocks: List[PreloadedStock] = []
        self.start_date = start_date or (datetime.now() - timedelta(days=120)).strftime("%Y-%m-%d")
        self.end_date = end_date or datetime.now().strftime("%Y-%m-%d")

        t0 = time.time()
        for symbol in cache.symbols():
            df = cache.get(symbol)
            if df is None or len(df) < 60:
                continue

            dates = df["date"].values
            mask = (dates >= self.start_date) & (dates <= self.end_date)
            if mask.sum() < 30:
                continue

            self.stocks.append(PreloadedStock(
                symbol=symbol,
                dates=dates,
                opens=df["open"].values.astype(float),
                highs=df["high"].values.astype(float),
                lows=df["low"].values.astype(float),
                closes=df["close"].values.astype(float),
            ))

        # ── 预计算所有 MA 周期（避免参数扫描时重复计算） ──
        if ma_periods:
            for stock in self.stocks:
                for period in ma_periods:
                    stock.get_ma(period)  # 触发懒计算并缓存

        elapsed = (time.time() - t0) * 1000
        logger.info("Preloaded %d stocks (%s ~ %s) + %d MA periods in %.0fms",
                     len(self.stocks), self.start_date, self.end_date,
                     len(ma_periods or []), elapsed)

    def __len__(self):
        return len(self.stocks)


# ═══════════════════════════════════════════════════════════════
# 回测运行器
# ═══════════════════════════════════════════════════════════════

class BacktestRunner:
    """
    向量化回测运行器

    Args:
        holding_days: 持仓天数（默认 5 天）
        stop_loss_pct: 止损百分比（默认 -8%）
        take_profit_pct: 止盈百分比（默认 +15%）
        ma_short: 短期均线周期（默认 20）
        ma_long: 长期均线周期（默认 50）
    """

    def __init__(
        self,
        holding_days: int = 5,
        stop_loss_pct: float = -8.0,
        take_profit_pct: float = 15.0,
        ma_short: int = 20,
        ma_long: int = 50,
    ):
        self.holding_days = holding_days
        self.stop_loss_pct = stop_loss_pct
        self.take_profit_pct = take_profit_pct
        self.ma_short = ma_short
        self.ma_long = ma_long

    def run(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        preloaded: Optional[PreloadedData] = None,
    ) -> BacktestResult:
        """
        运行回测（向量化版）

        Args:
            start_date: 开始日期
            end_date: 结束日期
            preloaded: 预加载数据（可选，避免重复加载）
        """
        if preloaded is None:
            preloaded = PreloadedData(start_date, end_date)

        all_trades: List[TradeRecord] = []
        min_period = max(self.ma_short, self.ma_long) + 10

        for stock in preloaded.stocks:
            # 日期范围过滤
            date_mask = (stock.dates >= (start_date or preloaded.start_date)) & \
                        (stock.dates <= (end_date or preloaded.end_date))
            if not date_mask.any():
                continue

            # 获取预计算的 MA（从缓存）
            ma_s = stock.get_ma(self.ma_short)
            ma_l = stock.get_ma(self.ma_long)

            # 信号检测（向量化）
            signal_mask = _vectorized_signal_detect(stock.closes, ma_s, ma_l)
            signal_mask &= date_mask

            if not signal_mask.any():
                continue

            # 交易模拟
            trades = _vectorized_simulate_trades(
                stock.dates, stock.opens, stock.highs, stock.lows, stock.closes,
                signal_mask,
                holding_days=self.holding_days,
                stop_loss_pct=self.stop_loss_pct,
                take_profit_pct=self.take_profit_pct,
                code=stock.symbol,
                signal_type="trend",
            )
            all_trades.extend(trades)

        return self._compute_stats(all_trades, start_date or preloaded.start_date, end_date or preloaded.end_date)

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

        returns = [t.net_pnl_pct for t in trades]
        if len(returns) > 1:
            mean_r = sum(returns) / len(returns)
            std_r = (sum((r - mean_r) ** 2 for r in returns) / (len(returns) - 1)) ** 0.5
            sharpe = (mean_r / std_r * (252 ** 0.5)) if std_r > 0 else 0
        else:
            sharpe = 0

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
            start_date=start_date, end_date=end_date, total_trades=len(trades),
            win_count=len(wins), loss_count=len(losses), neutral_count=len(neutrals),
            win_rate=len(wins) / len(trades), avg_pnl_pct=round(avg_pnl, 2),
            avg_net_pnl_pct=round(avg_net, 2), max_win_pct=round(max_win, 2),
            max_loss_pct=round(max_loss, 2), sharpe_ratio=round(sharpe, 2),
            trades=trades, signal_type_stats=type_stats,
        )


# ═══════════════════════════════════════════════════════════════
# 参数扫描（预加载一次，快速扫描）
# ═══════════════════════════════════════════════════════════════

def param_scan(
    holding_days: Optional[List[int]] = None,
    stop_loss_pct: Optional[List[float]] = None,
    take_profit_pct: Optional[List[float]] = None,
    ma_short: Optional[List[int]] = None,
    ma_long: Optional[List[int]] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> List[dict]:
    """
    参数扫描：预加载数据一次，仅变换参数快速扫描

    核心优化：
    1. PreloadedData 一次性从内存缓存加载所有股票数据
    2. 每只股票的 MA 按需计算并缓存（不同 ma_short/ma_long 共享缓存）
    3. 每个参数组合只做信号检测+交易模拟，无重复 I/O

    示例:
        results = param_scan(
            holding_days=[3, 5, 10],
            stop_loss_pct=[-5, -8, -10],
            take_profit_pct=[10, 15, 20],
        )
    """
    holding_days = holding_days or [5]
    stop_loss_pct = stop_loss_pct or [-8.0]
    take_profit_pct = take_profit_pct or [15.0]
    ma_short = ma_short or [20]
    ma_long = ma_long or [50]

    combos = list(product(holding_days, stop_loss_pct, take_profit_pct, ma_short, ma_long))
    # 过滤无效组合
    combos = [(hd, sl, tp, ms, ml) for hd, sl, tp, ms, ml in combos if ms < ml]

    logger.info("Param scan: %d valid combinations", len(combos))

    # ── 核心优化：预加载一次 + 预计算所有 MA ──
    all_ma_periods = sorted(set(ma_short + ma_long))
    t_load = time.time()
    preloaded = PreloadedData(start_date, end_date, ma_periods=all_ma_periods)
    load_ms = (time.time() - t_load) * 1000

    t0 = time.time()
    results = []

    for hd, sl, tp, ms, ml in combos:
        runner = BacktestRunner(
            holding_days=hd, stop_loss_pct=sl, take_profit_pct=tp,
            ma_short=ms, ma_long=ml,
        )
        bt_result = runner.run(preloaded=preloaded)
        results.append({
            "params": {"holding_days": hd, "stop_loss_pct": sl,
                       "take_profit_pct": tp, "ma_short": ms, "ma_long": ml},
            "result": bt_result,
        })

    results.sort(key=lambda x: x["result"].avg_net_pnl_pct, reverse=True)

    elapsed = (time.time() - t0) * 1000
    logger.info("Param scan: load=%.0fms, scan=%.0fms (%.1fms/comb)",
                load_ms, elapsed, elapsed / len(combos) if combos else 0)

    return results


def print_scan_results(results: List[dict], top_n: int = 10):
    """打印参数扫描结果"""
    print("\n" + "=" * 80)
    print("参数扫描结果")
    print("=" * 80)
    print(f"{'排名':>4} {'持仓':>4} {'止损':>6} {'止盈':>6} {'MA短':>5} {'MA长':>5} "
          f"{'交易数':>6} {'胜率':>6} {'净收益':>8} {'Sharpe':>7}")
    print("-" * 80)

    for i, r in enumerate(results[:top_n], 1):
        p = r["params"]
        res = r["result"]
        print(f"{i:>4} {p['holding_days']:>4} {p['stop_loss_pct']:>6.1f} "
              f"{p['take_profit_pct']:>6.1f} {p['ma_short']:>5} {p['ma_long']:>5} "
              f"{res.total_trades:>6} {res.win_rate:>5.1%} "
              f"{res.avg_net_pnl_pct:>+7.2f}% {res.sharpe_ratio:>7.2f}")

    print("=" * 80)
