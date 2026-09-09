"""
Backtesting Engine — 借鉴 tradingview-mcp (https://github.com/atilaahmettaner/tradingview-mcp) backtest_service.py

支持 9 种策略 + Walk-Forward 回测。
纯 Python 实现（无 pandas/numpy 依赖）。
数据源: Yahoo Finance（通过 core.proxy 代理）

策略:
  rsi, bollinger, macd, ema_cross, supertrend, donchian,
  rsi_pullback, keltner_breakout, triple_ema
"""
from __future__ import annotations

import json
import math
import statistics
import urllib.request
from datetime import datetime, timezone
from typing import Any, Optional


# ── Data Fetching ──────────────────────────────────────────────────────────

_YF_BASE = "https://query1.finance.yahoo.com/v8/finance/chart"
_UA = "stock-mcp/1.0 backtest-bot"


def fetch_ohlcv(symbol: str, period: str = "2y", interval: str = "1d") -> list[dict]:
    """从 Yahoo Finance 获取 OHLCV 数据。"""
    url = f"{_YF_BASE}/{symbol}?interval={interval}&range={period}"
    try:
        from core.proxy import proxy_request
        raw = proxy_request(url, headers={"Accept": "application/json"}, timeout=15)
        data = json.loads(raw)
    except Exception:
        # Fallback: direct
        req = urllib.request.Request(url, headers={"User-Agent": _UA})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())

    result = data["chart"]["result"][0]
    timestamps = result.get("timestamp", [])
    q = result["indicators"]["quote"][0]
    date_fmt = "%Y-%m-%d %H:%M" if interval == "1h" else "%Y-%m-%d"

    candles = []
    for i, ts in enumerate(timestamps):
        o, h, l, c, v = q["open"][i], q["high"][i], q["low"][i], q["close"][i], q["volume"][i]
        if None in (o, h, l, c):
            continue
        candles.append({
            "date": datetime.fromtimestamp(ts, tz=timezone.utc).strftime(date_fmt),
            "open": round(o, 4),
            "high": round(h, 4),
            "low": round(l, 4),
            "close": round(c, 4),
            "volume": v or 0,
        })
    return candles


# ── Indicators ─────────────────────────────────────────────────────────────

def calc_rsi(closes: list[float], period: int = 14) -> list[Optional[float]]:
    rsi = [None] * len(closes)
    if len(closes) < period + 1:
        return rsi
    gains, losses = [], []
    for i in range(1, len(closes)):
        d = closes[i] - closes[i - 1]
        gains.append(max(d, 0))
        losses.append(max(-d, 0))
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(closes)):
        if avg_loss == 0:
            rsi[i] = 100.0
        else:
            rs = avg_gain / avg_loss
            rsi[i] = 100 - 100 / (1 + rs)
        if i < len(gains):
            avg_gain = (avg_gain * (period - 1) + gains[i]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    return rsi


def calc_bollinger(closes: list[float], period: int = 20, mult: float = 2.0) -> dict:
    n = len(closes)
    upper = [None] * n
    middle = [None] * n
    lower = [None] * n
    for i in range(period - 1, n):
        window = closes[i - period + 1: i + 1]
        ma = sum(window) / period
        std = (sum((x - ma) ** 2 for x in window) / period) ** 0.5
        middle[i] = ma
        upper[i] = ma + mult * std
        lower[i] = ma - mult * std
    return {"upper": upper, "middle": middle, "lower": lower}


def calc_macd(closes: list[float], fast: int = 12, slow: int = 26, signal: int = 9) -> dict:
    def ema(data, period):
        result = [None] * len(data)
        if len(data) < period:
            return result
        result[period - 1] = sum(data[:period]) / period
        k = 2 / (period + 1)
        for i in range(period, len(data)):
            result[i] = data[i] * k + result[i - 1] * (1 - k)
        return result

    ema_fast = ema(closes, fast)
    ema_slow = ema(closes, slow)
    macd_line = [None] * len(closes)
    for i in range(len(closes)):
        if ema_fast[i] is not None and ema_slow[i] is not None:
            macd_line[i] = ema_fast[i] - ema_slow[i]

    valid = [x for x in macd_line if x is not None]
    signal_line = [None] * len(closes)
    if len(valid) >= signal:
        s_ema = [None] * len(valid)
        s_ema[signal - 1] = sum(valid[:signal]) / signal
        k = 2 / (signal + 1)
        for i in range(signal, len(valid)):
            s_ema[i] = valid[i] * k + s_ema[i - 1] * (1 - k)
        j = 0
        for i in range(len(closes)):
            if macd_line[i] is not None:
                signal_line[i] = s_ema[j] if j < len(s_ema) else None
                j += 1

    return {"macd": macd_line, "signal": signal_line}


def calc_ema(closes: list[float], period: int) -> list[Optional[float]]:
    result = [None] * len(closes)
    if len(closes) < period:
        return result
    result[period - 1] = sum(closes[:period]) / period
    k = 2 / (period + 1)
    for i in range(period, len(closes)):
        result[i] = closes[i] * k + result[i - 1] * (1 - k)
    return result


def calc_sma(closes: list[float], period: int) -> list[Optional[float]]:
    result = [None] * len(closes)
    for i in range(period - 1, len(closes)):
        result[i] = sum(closes[i - period + 1: i + 1]) / period
    return result


def calc_atr(highs, lows, closes, period: int = 14) -> list[Optional[float]]:
    n = len(closes)
    tr = [0.0] * n
    for i in range(1, n):
        tr[i] = max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
    atr = [None] * n
    if n < period + 1:
        return atr
    atr[period] = sum(tr[1:period + 1]) / period
    for i in range(period + 1, n):
        atr[i] = (atr[i - 1] * (period - 1) + tr[i]) / period
    return atr


def calc_supertrend(highs, lows, closes, period: int = 10, multiplier: float = 3.0) -> dict:
    n = len(closes)
    atr = calc_atr(highs, lows, closes, period)
    upper = [None] * n
    lower = [None] * n
    direction = [None] * n  # 1=up, -1=down

    for i in range(period, n):
        if atr[i] is None:
            continue
        hl2 = (highs[i] + lows[i]) / 2
        upper[i] = hl2 + multiplier * atr[i]
        lower[i] = hl2 - multiplier * atr[i]

    for i in range(period + 1, n):
        if upper[i] is None or upper[i - 1] is None:
            continue
        if lower[i] is None or lower[i - 1] is None:
            continue
        if closes[i] > upper[i - 1]:
            direction[i] = 1
        elif closes[i] < lower[i - 1]:
            direction[i] = -1
        else:
            direction[i] = direction[i - 1] if direction[i - 1] else 1

    return {"direction": direction, "upper": upper, "lower": lower}


def calc_donchian(highs, lows, period: int = 20) -> dict:
    n = len(highs)
    upper = [None] * n
    lower = [None] * n
    for i in range(period, n):
        upper[i] = max(highs[i - period: i])
        lower[i] = min(lows[i - period: i])
    return {"upper": upper, "lower": lower}


# ── Strategy Engines ───────────────────────────────────────────────────────

def _run_rsi(candles, oversold=40, overbought=60, period=14, **_):
    closes = [c["close"] for c in candles]
    rsi = calc_rsi(closes, period)
    trades, position = [], None
    for i in range(1, len(candles)):
        if rsi[i] is None:
            continue
        price, date = candles[i]["close"], candles[i]["date"]
        if position is None and rsi[i] < oversold:
            position = {"entry_date": date, "entry_price": price, "strategy": "rsi"}
        elif position is not None and rsi[i] > overbought:
            trades.append({**position, "exit_date": date, "exit_price": price})
            position = None
    return trades


def _run_bollinger(candles, period=20, std_mult=2.0, **_):
    closes = [c["close"] for c in candles]
    bb = calc_bollinger(closes, period, std_mult)
    trades, position = [], None
    for i in range(1, len(candles)):
        if bb["lower"][i] is None:
            continue
        price, date = candles[i]["close"], candles[i]["date"]
        if position is None and price < bb["lower"][i]:
            position = {"entry_date": date, "entry_price": price, "strategy": "bollinger"}
        elif position is not None and price > bb["middle"][i]:
            trades.append({**position, "exit_date": date, "exit_price": price})
            position = None
    return trades


def _run_macd(candles, fast=12, slow=26, signal=9, **_):
    closes = [c["close"] for c in candles]
    macd = calc_macd(closes, fast, slow, signal)
    trades, position = [], None
    for i in range(1, len(candles)):
        m, s, mp, sp = macd["macd"][i], macd["signal"][i], macd["macd"][i - 1], macd["signal"][i - 1]
        if None in (m, s, mp, sp):
            continue
        price, date = candles[i]["close"], candles[i]["date"]
        if position is None and mp < sp and m >= s:
            position = {"entry_date": date, "entry_price": price, "strategy": "macd"}
        elif position is not None and mp > sp and m <= s:
            trades.append({**position, "exit_date": date, "exit_price": price})
            position = None
    return trades


def _run_ema_cross(candles, fast_period=20, slow_period=50, **_):
    closes = [c["close"] for c in candles]
    ema_fast = calc_ema(closes, fast_period)
    ema_slow = calc_ema(closes, slow_period)
    trades, position = [], None
    for i in range(1, len(candles)):
        f, s, fp, sp = ema_fast[i], ema_slow[i], ema_fast[i - 1], ema_slow[i - 1]
        if None in (f, s, fp, sp):
            continue
        price, date = candles[i]["close"], candles[i]["date"]
        if position is None and fp < sp and f >= s:
            position = {"entry_date": date, "entry_price": price, "strategy": "ema_cross"}
        elif position is not None and fp > sp and f <= s:
            trades.append({**position, "exit_date": date, "exit_price": price})
            position = None
    return trades


def _run_supertrend(candles, atr_period=10, multiplier=3.0, **_):
    highs = [c["high"] for c in candles]
    lows = [c["low"] for c in candles]
    closes = [c["close"] for c in candles]
    st = calc_supertrend(highs, lows, closes, atr_period, multiplier)
    trades, position = [], None
    for i in range(1, len(candles)):
        d, dp = st["direction"][i], st["direction"][i - 1]
        if d is None or dp is None:
            continue
        price, date = candles[i]["close"], candles[i]["date"]
        if position is None and dp == -1 and d == 1:
            position = {"entry_date": date, "entry_price": price, "strategy": "supertrend"}
        elif position is not None and dp == 1 and d == -1:
            trades.append({**position, "exit_date": date, "exit_price": price})
            position = None
    return trades


def _run_donchian(candles, period=20, **_):
    highs = [c["high"] for c in candles]
    lows = [c["low"] for c in candles]
    dc = calc_donchian(highs, lows, period)
    trades, position = [], None
    for i in range(1, len(candles)):
        if dc["upper"][i - 1] is None or dc["lower"][i - 1] is None:
            continue
        price, date = candles[i]["close"], candles[i]["date"]
        if position is None and highs[i] > dc["upper"][i - 1]:
            position = {"entry_date": date, "entry_price": price, "strategy": "donchian"}
        elif position is not None and lows[i] < dc["lower"][i - 1]:
            trades.append({**position, "exit_date": date, "exit_price": price})
            position = None
    return trades


def _run_rsi_pullback(candles, rsi_period=14, oversold=40, overbought=70, fast_ma=50, slow_ma=200, **_):
    closes = [c["close"] for c in candles]
    rsi = calc_rsi(closes, rsi_period)
    sma_fast = calc_sma(closes, fast_ma)
    sma_slow = calc_sma(closes, slow_ma)
    trades, position = [], None
    for i in range(1, len(candles)):
        if rsi[i] is None or sma_fast[i] is None or sma_slow[i] is None:
            continue
        price, date = candles[i]["close"], candles[i]["date"]
        in_uptrend = sma_fast[i] > sma_slow[i]
        if position is None and in_uptrend and rsi[i] < oversold:
            position = {"entry_date": date, "entry_price": price, "strategy": "rsi_pullback"}
        elif position is not None and (rsi[i] > overbought or price < sma_fast[i]):
            trades.append({**position, "exit_date": date, "exit_price": price})
            position = None
    return trades


def _run_keltner_breakout(candles, ema_period=20, atr_period=14, multiplier=2.0, **_):
    highs = [c["high"] for c in candles]
    lows = [c["low"] for c in candles]
    closes = [c["close"] for c in candles]
    ema = calc_ema(closes, ema_period)
    atr = calc_atr(highs, lows, closes, atr_period)
    trades, position = [], None
    for i in range(1, len(candles)):
        if ema[i] is None or atr[i] is None:
            continue
        price, date = candles[i]["close"], candles[i]["date"]
        upper = ema[i] + multiplier * atr[i]
        if position is None and price > upper:
            position = {"entry_date": date, "entry_price": price, "strategy": "keltner_breakout"}
        elif position is not None and price < ema[i]:
            trades.append({**position, "exit_date": date, "exit_price": price})
            position = None
    return trades


def _run_triple_ema(candles, fast_period=20, slow_period=50, trend_period=200, **_):
    closes = [c["close"] for c in candles]
    ema_fast = calc_ema(closes, fast_period)
    ema_slow = calc_ema(closes, slow_period)
    sma_trend = calc_sma(closes, trend_period)
    trades, position = [], None
    for i in range(1, len(candles)):
        f, s, fp, sp, t = ema_fast[i], ema_slow[i], ema_fast[i - 1], ema_slow[i - 1], sma_trend[i]
        if None in (f, s, fp, sp, t):
            continue
        price, date = candles[i]["close"], candles[i]["date"]
        bull_cross = fp < sp and f >= s
        bear_cross = fp > sp and f <= s
        if position is None and bull_cross and price > t:
            position = {"entry_date": date, "entry_price": price, "strategy": "triple_ema"}
        elif position is not None and bear_cross:
            trades.append({**position, "exit_date": date, "exit_price": price})
            position = None
    return trades


STRATEGY_MAP = {
    "rsi": _run_rsi,
    "bollinger": _run_bollinger,
    "macd": _run_macd,
    "ema_cross": _run_ema_cross,
    "supertrend": _run_supertrend,
    "donchian": _run_donchian,
    "rsi_pullback": _run_rsi_pullback,
    "keltner_breakout": _run_keltner_breakout,
    "triple_ema": _run_triple_ema,
}

STRATEGY_LABELS = {
    "rsi": "RSI Oversold/Overbought",
    "bollinger": "Bollinger Band Mean Reversion",
    "macd": "MACD Crossover",
    "ema_cross": "EMA 20/50 Golden/Death Cross",
    "supertrend": "Supertrend (ATR-based Trend Following)",
    "donchian": "Donchian Channel Breakout",
    "rsi_pullback": "RSI Pullback in Uptrend",
    "keltner_breakout": "Keltner Channel Breakout",
    "triple_ema": "Triple EMA with SMA200 Trend Filter",
}


# ── Metrics ────────────────────────────────────────────────────────────────

def _calc_metrics(trades: list[dict], initial_capital: float = 10000, interval: str = "1d") -> dict:
    if not trades:
        return {
            "total_trades": 0, "win_rate_pct": 0, "total_return_pct": 0,
            "sharpe_ratio": 0, "max_drawdown_pct": 0, "profit_factor": 0,
        }

    capital = initial_capital
    peak = capital
    max_dd = 0
    returns = []
    wins = 0
    gross_profit = 0
    gross_loss = 0

    for t in trades:
        pnl = (t["exit_price"] - t["entry_price"]) / t["entry_price"]
        capital *= (1 + pnl)
        returns.append(pnl)
        if pnl > 0:
            wins += 1
            gross_profit += pnl
        else:
            gross_loss += abs(pnl)
        peak = max(peak, capital)
        dd = (peak - capital) / peak
        max_dd = max(max_dd, dd)

    n = len(trades)
    ann_factor = 252 if interval == "1d" else 252 * 6
    avg_ret = statistics.mean(returns) if returns else 0
    std_ret = statistics.stdev(returns) if len(returns) > 1 else 1
    sharpe = (avg_ret / std_ret * math.sqrt(ann_factor)) if std_ret > 0 else 0

    return {
        "total_trades": n,
        "win_rate_pct": round(wins / n * 100, 1),
        "total_return_pct": round((capital / initial_capital - 1) * 100, 2),
        "sharpe_ratio": round(sharpe, 2),
        "max_drawdown_pct": round(max_dd * 100, 2),
        "profit_factor": round(gross_profit / gross_loss, 2) if gross_loss > 0 else 999,
    }


def _buy_and_hold_return(candles: list[dict]) -> float:
    if len(candles) < 2:
        return 0
    return round((candles[-1]["close"] - candles[0]["close"]) / candles[0]["close"] * 100, 2)


# ── Main Backtest Function ────────────────────────────────────────────────

def run_backtest(
    symbol: str,
    strategy: str = "rsi",
    period: str = "2y",
    interval: str = "1d",
    commission_pct: float = 0.1,
    slippage_pct: float = 0.05,
    initial_capital: float = 10000,
    **strategy_params,
) -> dict:
    """
    运行单策略回测。

    Args:
        symbol: 交易标的 (e.g. "AAPL", "BTC-USD")
        strategy: 策略名 (rsi/bollinger/macd/ema_cross/supertrend/donchian/rsi_pullback/keltner_breakout/triple_ema)
        period: 数据周期
        interval: K 线周期
        commission_pct: 手续费率 (%)
        slippage_pct: 滑点率 (%)
        initial_capital: 初始资金

    Returns:
        回测结果字典
    """
    if strategy not in STRATEGY_MAP:
        return {"error": f"未知策略: {strategy}。可选: {', '.join(STRATEGY_MAP.keys())}"}

    try:
        candles = fetch_ohlcv(symbol, period, interval)
    except Exception as e:
        return {"error": f"数据获取失败: {e}"}

    if len(candles) < 30:
        return {"error": f"数据不足: {len(candles)} 条 (需要至少 30)"}

    # Apply transaction costs
    fn = STRATEGY_MAP[strategy]
    trades = fn(candles, **strategy_params)
    total_cost = (commission_pct + slippage_pct) * 2
    for t in trades:
        gross = (t["exit_price"] - t["entry_price"]) / t["entry_price"] * 100
        t["return_pct"] = round(gross - total_cost, 3)
        t["gross_return_pct"] = round(gross, 3)
        t["cost_pct"] = round(-total_cost, 3)

    metrics = _calc_metrics(trades, initial_capital, interval)

    return {
        "symbol": symbol.upper(),
        "strategy": strategy,
        "strategy_label": STRATEGY_LABELS.get(strategy, strategy),
        "period": period,
        "interval": interval,
        "total_candles": len(candles),
        "date_from": candles[0]["date"],
        "date_to": candles[-1]["date"],
        "initial_capital": initial_capital,
        "commission_pct": commission_pct,
        "slippage_pct": slippage_pct,
        "buy_and_hold_return_pct": _buy_and_hold_return(candles),
        **metrics,
        "trades": trades[-10:],  # Last 10 trades
        "source": "yahoo_finance",
        "disclaimer": "Past performance does not guarantee future results. For educational use only.",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def compare_strategies(
    symbol: str,
    period: str = "2y",
    interval: str = "1d",
    strategies: Optional[list[str]] = None,
) -> dict:
    """比较多个策略的回测结果。"""
    if strategies is None:
        strategies = list(STRATEGY_MAP.keys())

    results = []
    for s in strategies:
        result = run_backtest(symbol, strategy=s, period=period, interval=interval)
        if "error" not in result:
            results.append(result)

    results.sort(key=lambda x: x.get("total_return_pct", 0), reverse=True)

    return {
        "symbol": symbol.upper(),
        "strategies_tested": len(results),
        "rankings": [
            {
                "rank": i + 1,
                "strategy": r["strategy"],
                "label": r["strategy_label"],
                "return_pct": r["total_return_pct"],
                "sharpe": r["sharpe_ratio"],
                "win_rate": r["win_rate_pct"],
                "max_dd": r["max_drawdown_pct"],
                "trades": r["total_trades"],
            }
            for i, r in enumerate(results)
        ],
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def walk_forward_backtest(
    symbol: str,
    strategy: str = "rsi",
    period: str = "2y",
    interval: str = "1d",
    n_splits: int = 5,
    train_ratio: float = 0.7,
) -> dict:
    """
    Walk-Forward 回测（过拟合检测）。

    将数据分为 N 个 fold，每个 fold 内 70% 训练 + 30% 测试。
    """
    if strategy not in STRATEGY_MAP:
        return {"error": f"未知策略: {strategy}"}

    try:
        candles = fetch_ohlcv(symbol, period, interval)
    except Exception as e:
        return {"error": f"数据获取失败: {e}"}

    min_bars = max(60, n_splits * 20)
    if len(candles) < min_bars:
        return {"error": f"数据不足: {len(candles)} 条 (需要至少 {min_bars})"}

    fn = STRATEGY_MAP[strategy]
    fold_size = len(candles) // n_splits
    folds = []
    all_test_trades = []

    for fold_i in range(n_splits):
        start = fold_i * fold_size
        end = (start + fold_size) if fold_i < n_splits - 1 else len(candles)
        window = candles[start:end]
        split = int(len(window) * train_ratio)
        train_c = window[:split]
        test_c = window[split:]

        if len(train_c) < 20 or len(test_c) < 5:
            continue

        train_trades = fn(train_c)
        test_trades = fn(test_c)
        all_test_trades.extend(test_trades)

        train_m = _calc_metrics(train_trades)
        test_m = _calc_metrics(test_trades)

        tr, te = train_m["total_return_pct"], test_m["total_return_pct"]
        if tr == 0:
            fold_rob = 1.0 if te == 0 else 0.0
        elif tr < 0 and te < 0:
            fold_rob = round(min(te / tr, 2.0), 2)
        elif tr < 0:
            fold_rob = 0.0
        else:
            fold_rob = round(max(min(te / tr, 2.0), -1.0), 2)

        folds.append({
            "fold": fold_i + 1,
            "train_candles": len(train_c),
            "train_return_pct": train_m["total_return_pct"],
            "test_candles": len(test_c),
            "test_return_pct": test_m["total_return_pct"],
            "fold_robustness_score": fold_rob,
        })

    if not folds:
        return {"error": "无法生成有效 fold"}

    avg_train = round(statistics.mean(f["train_return_pct"] for f in folds), 2)
    avg_test = round(statistics.mean(f["test_return_pct"] for f in folds), 2)
    avg_rob = round(statistics.mean(f["fold_robustness_score"] for f in folds), 2)

    if avg_rob >= 0.8:
        verdict = "ROBUST — 策略样本内外表现一致"
    elif avg_rob >= 0.5:
        verdict = "MODERATE — 有一定过拟合迹象，谨慎使用"
    elif avg_rob >= 0.2:
        verdict = "WEAK — 明显过拟合，实盘风险大"
    else:
        verdict = "OVERFitted — 样本外失效，不可实盘"

    oos_m = _calc_metrics(all_test_trades)

    return {
        "symbol": symbol.upper(),
        "strategy": strategy,
        "strategy_label": STRATEGY_LABELS.get(strategy, strategy),
        "period": period,
        "interval": interval,
        "total_candles": len(candles),
        "n_splits": n_splits,
        "date_from": candles[0]["date"],
        "date_to": candles[-1]["date"],
        "avg_train_return_pct": avg_train,
        "avg_test_return_pct": avg_test,
        "robustness_score": avg_rob,
        "verdict": verdict,
        "oos_total_trades": oos_m["total_trades"],
        "oos_win_rate_pct": oos_m["win_rate_pct"],
        "oos_sharpe_ratio": oos_m["sharpe_ratio"],
        "oos_max_drawdown_pct": oos_m["max_drawdown_pct"],
        "oos_total_return_pct": oos_m["total_return_pct"],
        "buy_and_hold_return_pct": _buy_and_hold_return(candles),
        "folds": folds,
        "disclaimer": "Past performance does not guarantee future results.",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
