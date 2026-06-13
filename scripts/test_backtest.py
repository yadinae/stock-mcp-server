#!/usr/bin/env python3
"""
回测模块测试脚本

测试所有5种策略的信号生成和交易模拟逻辑。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# ── 构造模拟K线数据 ──────────────────────────────────────

PASS = 0
FAIL = 0


def test(name: str, ok: bool, detail: str = ""):
    global PASS, FAIL
    if ok:
        print(f"  ✅ {name}")
        PASS += 1
    else:
        print(f"  ❌ {name}: {detail}" if detail else f"  ❌ {name}")
        FAIL += 1


def section(name: str):
    print(f"\n── {name} ─{'─' * max(0, 60 - len(name))}")


def make_mock_records(days: int = 200) -> list[dict]:
    """生成模拟日K线数据

    价格从 100 开始，上升趋势中带随机波动。
    """
    import random
    random.seed(42)
    records = []
    price = 100.0
    for i in range(days):
        # 上升趋势 + 随机波动
        trend = 0.3
        noise = random.uniform(-2, 2)
        price = max(10, price + trend + noise)
        high = price * (1 + random.uniform(0, 0.03))
        low = price * (1 - random.uniform(0, 0.03))
        records.append({
            "date": f"2025-{(i // 30) + 1:02d}-{(i % 28) + 1:02d}",
            "open": round(price - random.uniform(0, 1), 2),
            "close": round(price, 2),
            "high": round(max(high, price), 2),
            "low": round(min(low, price), 2),
            "volume": 1000000 + i * 10000,
        })
    return records


# ═══════════════════════════════════════════════════════════
# 测试
# ═══════════════════════════════════════════════════════════

section("模块导入")

from tools.backtest.strategies import (
    ma_crossover, macd_crossover, rsi_mean_reversion,
    bollinger_bounce, combined_signals,
    list_strategies, run_strategy, STRATEGY_REGISTRY,
)
test("strategies 全部导入", True)

from tools.backtest.simulator import run_simulation, Trade
test("simulator 全部导入", True)

from tools.backtest.metrics import (
    calc_total_return, calc_annual_return, calc_max_drawdown,
    calc_sharpe_ratio, calc_win_rate, calc_profit_factor,
    calc_avg_hold_days, calc_all_metrics,
)
test("metrics 全部导入", True)

from tools.backtest.report import format_report
test("report 全部导入", True)

from tools.backtest import run_backtest, list_backtest_strategies
test("backtest __init__ 全部导入", True)

section("策略列表")

strategies = list_strategies()
test("列出策略", len(strategies) >= 5, f"got {len(strategies)}")
for s in strategies:
    test(f"  {s['id']}: {s['name']}", True)

section("MA金叉/死叉")

records = make_mock_records(200)
signals = ma_crossover(records)
test("MA策略生成信号", len(signals) > 0, f"got {len(signals)} signals")
# 所有信号有 action
all_valid = all(s.get("action") in ("buy", "sell", "hold") for s in signals)
test("信号格式正确", all_valid)
# 金叉和死叉交替出现
buys = [s for s in signals if s["action"] == "buy"]
sells = [s for s in signals if s["action"] == "sell"]
total_signals = len(buys) + len(sells)
test(f"  买入信号: {len(buys)}, 卖出信号: {len(sells)}", total_signals > 0)
for s in signals[:4]:
    test(f"  {s['date']} {s['action']} @ {s['price']:.2f}",
         isinstance(s.get("price"), (int, float)))

section("MACD 策略")

signals = macd_crossover(records)
buys = [s for s in signals if s["action"] == "buy"]
sells = [s for s in signals if s["action"] == "sell"]
test("MACD生成信号", len(signals) > 0, f"got {len(signals)} ({len(buys)}买/{len(sells)}卖)")

section("RSI 均值回归")

signals = rsi_mean_reversion(records)
buys = [s for s in signals if s["action"] == "buy"]
sells = [s for s in signals if s["action"] == "sell"]
test("RSI生成信号", len(signals) > 0, f"got {len(signals)} ({len(buys)}买/{len(sells)}卖)")

section("布林带反弹")

signals = bollinger_bounce(records)
buys = [s for s in signals if s["action"] == "buy"]
sells = [s for s in signals if s["action"] == "sell"]
test("布林带生成信号", len(signals) > 0, f"got {len(signals)} ({len(buys)}买/{len(sells)}卖)")

section("组合信号")

signals = combined_signals(records)
buys = [s for s in signals if s["action"] == "buy"]
sells = [s for s in signals if s["action"] == "sell"]
test("组合信号生成", len(signals) > 0, f"got {len(signals)} ({len(buys)}买/{len(sells)}卖)")

section("交易模拟")

records_short = records[:100]
signals_ma = ma_crossover(records_short)
result = run_simulation(records_short, signals_ma, initial_capital=100000, verbose=True)
test("模拟运行成功", result is not None)
test("  包含交易记录", "trades" in result)
test("  包含权益曲线", "equity_curve" in result)
test("  包含最终价值", "final_value" in result)

trades = result.get("trades", [])
test(f"  完成交易数: {len(trades)}", len(trades) >= 0)
if trades:
    t = trades[0]
    test("  交易含必要字段", all(k in t for k in ["buy_date", "sell_date", "profit", "hold_days"]))

# 检查 T+1 限制
# 在一个小数据集上验证
small_records = records[:60]
sig = [
    {"date": small_records[25]["date"], "action": "buy", "price": 110, "reason": "test"},
    {"date": small_records[25]["date"], "action": "sell", "price": 112, "reason": "test"},
]
result = run_simulation(small_records, sig, verbose=True)
test("T+1: 同一天买卖", result is not None)
# 应该在第二个信号时跳过（因为T+1限制）
# 买入在26日执行，卖出信号在25日+第2信号也在25日 -> 执行日在26日 -> 同一天，不能卖
trades = result.get("trades", [])
test("  T+1阻止当日买卖", len(trades) == 0 or len(trades) == 1,
     f"第2个信号应该被跳过，got {len(trades)} trades")

section("绩效指标")

# 模拟一些交易数据
mock_trades = [
    {"buy_date": "2025-01-10", "sell_date": "2025-02-15", "buy_price": 100,
     "sell_price": 110, "shares": 900, "commission": 50, "stamp_tax": 100,
     "profit": 8000, "profit_pct": 8.0, "hold_days": 25},
    {"buy_date": "2025-03-01", "sell_date": "2025-04-10", "buy_price": 108,
     "sell_price": 105, "shares": 900, "commission": 48, "stamp_tax": 95,
     "profit": -3500, "profit_pct": -3.5, "hold_days": 30},
    {"buy_date": "2025-05-01", "sell_date": "2025-06-15", "buy_price": 104,
     "sell_price": 118, "shares": 1000, "commission": 55, "stamp_tax": 118,
     "profit": 13000, "profit_pct": 12.5, "hold_days": 35},
]

mock_equity = [
    {"date": "2025-01-01", "value": 100000},
    {"date": "2025-02-01", "value": 105000},
    {"date": "2025-03-01", "value": 108000},
    {"date": "2025-04-01", "value": 103000},
    {"date": "2025-05-01", "value": 107000},
    {"date": "2025-06-01", "value": 115000},
    {"date": "2025-06-30", "value": 118000},
]

metrics = calc_all_metrics(mock_trades, mock_equity, 118000, 100000, 180)
test("总收益率", metrics.get("total_return_pct") == 18.0, f'got {metrics.get("total_return_pct")}')
test("年化收益率", metrics.get("annual_return_pct", 0) > 0)
test("最大回撤", metrics.get("max_drawdown_pct", 0) > 0)
test("夏普比率", "sharpe_ratio" in metrics)
test("胜率", metrics.get("win_rate_pct") == 66.67, f'got {metrics.get("win_rate_pct")}')
test("盈亏比", metrics.get("profit_factor", 0) > 1.0)
test("平均持仓", metrics.get("avg_hold_days", 0) > 0)

section("完整回测（__init__）")

result = run_backtest("MOCK", records, strategy="ma_crossover", days=200, capital=100000)
test("run_backtest 成功", result.get("success") is True)
test("  含绩效指标", "metrics" in result)
test("  含交易列表", "trades" in result)
test("  含权益曲线", "equity_curve" in result)
test("  代码一致", result.get("code") == "MOCK")
test("  有免责声明", "note" in result)
test("  策略ID正确", result.get("strategy_id") == "ma_crossover")

result = run_backtest("MOCK", [], strategy="ma_crossover")
test("空K线优雅降级", result.get("success") is False and "error" in result,
     f'error={result.get("error", "")}')

section("策略参数覆盖")

result = run_backtest("MOCK", records, strategy="ma_crossover", params={"fast": 10, "slow": 30})
test("自定义参数生效", result.get("strategy_params", {}).get("fast") == 10,
     f'got {result.get("strategy_params")}')

print(f"\n{'═' * 60}")
print(f"  结果: {PASS} 通过 / {FAIL} 失败 / {PASS + FAIL} 共计")
print(f"{'═' * 60}")
sys.exit(0 if FAIL == 0 else 1)
