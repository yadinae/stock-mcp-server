#!/usr/bin/env python3
"""
Stock MCP Server — 工具测试脚本

验证所有 11 个工具的可用性。
用法：
  python3 scripts/test_tools.py           # 快速测试（只需 MCP SDK）
  python3 scripts/test_tools.py --full     # 包含实际API调用

在不带 --full 时，只测试输入校验和模块加载，
不发起外部 HTTP/TCP 请求。
"""

from __future__ import annotations

import json
import re
import sys
import os
from pathlib import Path

# 加入项目根目录
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# ── 测试配置 ──────────────────────────────────────────────
FULL_TEST = "--full" in sys.argv
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


# ═══════════════════════════════════════════════════════════
# 1. 模块导入
# ═══════════════════════════════════════════════════════════

section("模块导入")

try:
    from core.cache import TTLCache, get_cache, make_cache_key
    from core.parallel import run_parallel, parallel_map
    from core.health import DataSourceHealth, get_health_tracker
    test("core.* 全部导入成功", True)
except ImportError as e:
    test("core.* 导入失败", False, str(e))

try:
    from tools.technical import (
        calc_ma, calc_macd, calc_rsi, calc_bollinger,
        calc_ichimoku, identify_candle_patterns, analyze,
    )
    test("tools.technical 全部导入成功", True)
except ImportError as e:
    test("tools.technical 导入失败", False, str(e))

try:
    from tools.st_risk import assess_risk, get_st_risk, check_st_status, RiskSignal
    test("tools.st_risk 全部导入成功", True)
except ImportError as e:
    test("tools.st_risk 导入失败", False, str(e))

try:
    from data_sources import tencent, yahoo
    from data_sources.mootdx import get_kline as md_get_kline, _is_supported
    test("data_sources.* 全部导入成功", True)
except ImportError as e:
    test("data_sources.* 导入失败", False, str(e))

# ═══════════════════════════════════════════════════════════
# 2. 缓存测试
# ═══════════════════════════════════════════════════════════

section("缓存子系统")

cache = get_cache()

# 基础操作
cache.set("test_a", "hello", ttl=10)
test("cache.set", cache.get("test_a") == "hello", f"got {cache.get('test_a')}")

# get_or_compute
result = cache.get_or_compute("test_b", lambda: "computed", ttl=10)
test("cache.get_or_compute", result == "computed")

# TTL 过期
import time
cache.set("test_expire", "expire_me", ttl=1)
time.sleep(1.01)
test("cache TTL 过期", cache.get("test_expire") is None)

# 统计
stats = cache.stats
test("cache.stats 包含 hits", "hits" in stats)
test("cache.stats 包含 misses", "misses" in stats)
test("cache.stats 包含 ratio", "ratio" in stats)

# 清理
cache.clear()
test("cache.clear() 清空", len(cache) == 0)

# ═══════════════════════════════════════════════════════════
# 3. 健康追踪
# ═══════════════════════════════════════════════════════════

section("健康追踪子系统")

h = get_health_tracker()
h.record_success("test_source")
h.record_success("test_source")
h.record_failure("test_source", "timeout")
report = h.get_report()
sources = {r["name"]: r for r in report}

test("健康追踪记录成功/失败", "test_source" in sources, f"found {len(sources)} source(s)")
if "test_source" in sources:
    s = sources["test_source"]
    test("  请求计数", s["total_requests"] >= 3)
    test("  成功计数", s["success"] >= 2)
    test("  失败计数", s["failures"] >= 1)

# ═══════════════════════════════════════════════════════════
# 4. ST 风险检测
# ═══════════════════════════════════════════════════════════

section("ST 风险检测")

# 正常股票
result = assess_risk("600519", "贵州茅台", price=150.0)
test("茅台判定为正常", result["level_name"] == "正常", f'level={result["level_name"]}')

# *ST 股票
result = assess_risk("600666", "*ST瑞德", price=0.8)
test("*ST瑞德判定为高风险", result["level_name"] == "高风险", f'level={result["level_name"]}')
test("  *ST状态正确识别", result["is_st"] is True)
has_st_signal = any(s["dimension"] == "ST/退市状态" for s in result["signals"])
test("  包含ST/退市信号", has_st_signal)

# 面值退市
result = assess_risk("000999", "华润三九", price=0.48)
test("股价 < 0.5 面值退市风险", result["max_level"] >= 2)

# 放量下跌
result = assess_risk("000001", "平安银行", price=10.0, change_pct=-8, volume_ratio=3.5)
test("放量下跌检测", any(s["dimension"] == "放量下跌" for s in result["signals"]))

# ═══════════════════════════════════════════════════════════
# 5. 技术分析
# ═══════════════════════════════════════════════════════════

section("技术分析")

# 构造模拟K线数据
mock_records = []
for i in range(60):
    mock_records.append({
        "date": f"2025-0{i%12+1:02d}-{i%28+1:02d}",
        "open": round(100 + i * 0.5, 2),
        "close": round(100 + i * 0.5 + (i % 10 - 5) * 0.3, 2),
        "high": round(100 + i * 0.5 + 2, 2),
        "low": round(100 + i * 0.5 - 2, 2),
        "volume": 1000000 + i * 10000,
    })

result = analyze(mock_records, "MOCK")
test("技术分析返回结果", result is not None)
test("  包含趋势数据", "trend" in result and "status" in result["trend"])
test("  包含 MACD", "macd" in result)
test("  包含 RSI", "rsi" in result)
test("  包含布林带", "bollinger" in result)
test("  包含 Ichimoku", "ichimoku" in result)
test("  包含 K线形态", "candle_patterns" in result)
test("  包含评分", "score" in result)
test("  包含建议", "advice" in result)

# ═══════════════════════════════════════════════════════════
# 6. 代码类型识别
# ═══════════════════════════════════════════════════════════

section("代码类型识别")

from data_sources.tencent import code_type
test("600519 -> a", code_type("600519") == "a")
test("000001 -> a", code_type("000001") == "a")
test("688001 -> a", code_type("688001") == "a")
test("AAPL -> us", code_type("AAPL") == "us")
test("MSFT -> us", code_type("MSFT") == "us")
test("HK00700 -> hk", code_type("HK00700") == "hk")
test("sh600519 -> a", code_type("sh600519") == "a")

# ═══════════════════════════════════════════════════════════
# 7. 输入校验（server.py 逻辑）
# ═══════════════════════════════════════════════════════════

section("输入校验")

# 模拟 _validate_code 和 _validate_days
CODE_RE = re.compile(r"^[A-Za-z0-9]{2,10}$")

def val_code(code):
    if not code or not code.strip():
        return "不能为空"
    if not CODE_RE.match(code.strip()):
        return "格式异常"
    return None

def val_days(days):
    if not isinstance(days, int) or days < 1:
        return "天数>=1"
    if days > 730:
        return "不能超过730"
    return None

test("空代码", val_code("") is not None)
test("空白代码", val_code("   ") is not None)
test("合法代码 600519", val_code("600519") is None)
test("合法代码 AAPL", val_code("AAPL") is None)
test("合法代码 HK00700", val_code("HK00700") is None)
test("非法代码 abcdefghijk（超长）", val_code("abcdefghijk") is not None)
test("特殊字符 $AAPL", val_code("$AAPL") is not None)
test("days=0", val_days(0) is not None)
test("days=60 合法", val_days(60) is None)
test("days=800 超限", val_days(800) is not None)

# ═══════════════════════════════════════════════════════════
# 8. 并行执行
# ═══════════════════════════════════════════════════════════

section("并行执行")

from core.parallel import run_parallel

tasks = {
    "a": lambda: "result_a",
    "b": lambda: "result_b",
    "c": lambda: "result_c",
}
results = run_parallel(tasks, timeout=10)
test("并行任务全部完成", len(results) == 3)
test("  任务a结果正确", results.get("a") == "result_a")
test("  任务b结果正确", results.get("b") == "result_b")
test("  任务c结果正确", results.get("c") == "result_c")

# 异常任务
tasks_with_error = {
    "good": lambda: "ok",
    "bad": lambda: (_ for _ in ()).throw(ValueError("模拟错误")),
}
results = run_parallel(tasks_with_error, timeout=10)
test("异常任务不阻塞其他任务", "good" in results and "bad" in results)
test("  正常任务有结果", results["good"] == "ok")
test("  异常任务有错误信息", "error" in results["bad"])

# ═══════════════════════════════════════════════════════════
# 9. 外部 API 测试（仅 --full 模式）
# ═══════════════════════════════════════════════════════════

if FULL_TEST:
    section("外部 API 测试")

    # 腾讯行情
    from data_sources import tencent
    result = tencent.get_realtime_quote("600519")
    test("腾讯行情 600519 成功", result is not None and "price" in result,
         f'error={result.get("error", "")}' if "error" in result else "")

    # mootdx K线
    md_result = md_get_kline("600519", days=30)
    test("mootdx 600519 K线 成功", md_result is not None and "records" in md_result,
         f'error={md_result.get("error", "")}')
    if md_result and md_result.get("records"):
        test("  K线记录数 > 0", len(md_result["records"]) > 0,
             f'got {len(md_result["records"])} records')

    # Yahoo 行情（美股）
    yf_result = yahoo.get_realtime_quote("AAPL")
    test("Yahoo AAPL 行情", yf_result is not None and "price" in yf_result,
         f'error={yf_result.get("error", "")}')

    # Yahoo K线
    yf_kline = yahoo.get_kline("AAPL", days=30)
    test("Yahoo AAPL K线", yf_kline is not None and "records" in yf_kline,
         f'error={yf_kline.get("error", "")}')

    # ST 风险（实际数据）
    from tools.st_risk import get_st_risk
    rt = tencent.get_realtime_quote("600519")
    st_result = get_st_risk("600519", rt)
    test("ST 风险 600519 可运行", st_result is not None,
         f'error={st_result.get("error", "")}')
else:
    section("外部 API 测试（跳过）")
    print("  提示: 添加 --full 参数运行实际 API 测试")

# ═══════════════════════════════════════════════════════════
# 总结
# ═══════════════════════════════════════════════════════════

print(f"\n{'═' * 60}")
print(f"  结果: {PASS} 通过 / {FAIL} 失败 / {PASS + FAIL} 共计")
print(f"{'═' * 60}")

sys.exit(0 if FAIL == 0 else 1)
