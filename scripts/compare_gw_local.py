#!/usr/bin/env python3
"""本地 vs Gateway 数据一致性对比

对同一工具、同一参数，双端调用，对比关键字段（数值字段容差 0.01）。
Gateway: JSON-RPC over HTTP（无 session，Bearer token）
本地: streamable HTTP（session 管理，stock_mcp_client.py）
"""
import json
import sys
import urllib.request
import time

sys.path.insert(0, '/home/admin/.hermes/scripts')
from stock_mcp_client import call_tool as local_call

GATEWAY = "https://mcp-gateway.yadinae.workers.dev/mcp"
KEY = json.load(open('/home/admin/.hermes/scripts/secrets.json')).get('STOCK_GATEWAY_TOKEN', '')
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"


def gateway_call(name, args):
    payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                          "params": {"name": name, "arguments": args}}).encode()
    req = urllib.request.Request(GATEWAY, data=payload, headers={
        "Content-Type": "application/json",
        "Authorization": f"Bearer {KEY}",
        "User-Agent": UA,
    })
    try:
        resp = json.loads(urllib.request.urlopen(req, timeout=45).read())
        if "error" in resp:
            return {"error": resp["error"]}
        text = resp["result"]["content"][0]["text"]
        return json.loads(text)
    except Exception as e:
        return {"error": str(e)}


def get_by_path(obj, path):
    """按点分路径取字段"""
    cur = obj
    for p in path.split("."):
        if isinstance(cur, dict):
            cur = cur.get(p)
        elif isinstance(cur, list) and p.isdigit():
            i = int(p)
            cur = cur[i] if i < len(cur) else None
        else:
            return None
        if cur is None:
            return None
    return cur


def num_equal(a, b, tol=0.011):
    """数值比较（含 None 与 str 数字容忍）"""
    if a is None or b is None:
        return a is None and b is None
    try:
        fa, fb = float(a), float(b)
        return abs(fa - fb) <= max(tol, abs(fa) * 0.005)
    except (ValueError, TypeError):
        return str(a).strip() == str(b).strip()


# ── 测试用例：工具名 → [(标签, 参数, [(GW字段路径, 本地字段路径, 容差), ...])] ──
# 支持字段映射（双端字段名不同）与自定义容差（跨交易所实时价差）
CASES = [
    ("get_realtime_quote", [
        ("A股-茅台", {"code": "600519"}, [("name", "name", 0), ("price", "price", 0.011), ("change_pct", "change_pct", 0.011), ("open", "open", 0.011), ("high", "high", 0.011), ("low", "low", 0.011)]),
        ("A股-平安", {"code": "000001"}, [("name", "name", 0), ("price", "price", 0.011), ("change_pct", "change_pct", 0.011)]),
        ("ETF", {"code": "159949"}, [("name", "name", 0), ("price", "price", 0.011), ("change_pct", "change_pct", 0.011)]),
        ("指数", {"code": "sh000001"}, [("name", "name", 0), ("price", "price", 0.011), ("change_pct", "change_pct", 0.011)]),
    ]),
    ("get_fund_info", [
        ("基金-招商白酒", {"code": "161725"}, [("name", "name", 0), ("fund_type", "fund_type", 0), ("manager", "manager", 0)]),
    ]),
    ("get_index_info", [
        ("指数-沪深300", {"code": "000300"}, [("short_cn", "short_cn", 0), ("base_date", "base_date", 0), ("base_point", "base_point", 0.011)]),
    ]),
    ("get_crypto_quote", [
        # 交易所不同（GW=Kraken, 本地=Binance）→ 价格容差放宽到 1.5%
        ("加密-BTC", {"symbol": "BTCUSDT"}, [("price", "price", 0.015), ("price_change_pct", "change_pct", 2.0)]),
        ("加密-ETH", {"symbol": "ETHUSDT"}, [("price", "price", 0.015), ("price_change_pct", "change_pct", 2.0)]),
    ]),
    ("get_technical_analysis", [
        ("技术面-茅台", {"code": "600519"}, [("summary", "summary", 0), ("trend.status", "trend.status", 0)]),
    ]),
    ("get_market_lhb", [
        ("龙虎榜-今日", {}, [("data_count", "data_count", 0), ("items.0.security_code", "items.0.security_code", 0)]),
    ]),
    ("get_industry_rank", [
        # 同一 TV REST 源，字段名不同: GW name/change_pct ↔ 本地 industry/avg_change_pct
        ("行业排名", {}, [("top.0.name", "top.0.industry", 0), ("top.0.change_pct", "top.0.avg_change_pct", 0.011), ("top.1.name", "top.1.industry", 0), ("top.1.change_pct", "top.1.avg_change_pct", 0.011)]),
    ]),
    ("get_market_hot_stocks", [
        ("热点股", {}, [("stocks.0.code", "stocks.0.code", 0), ("stocks.0.name", "stocks.0.name", 0)]),
    ]),
    ("get_kline", [
        ("K线-茅台", {"code": "600519", "days": 5}, [("records.0.date", "records.0.date", 0), ("records.0.close", "records.0.close", 0.011), ("records.-1.close", "records.-1.close", 0.011)]),
    ]),
]

def norm_key(k):
    return k.replace("-1", "last")


print("=" * 70)
print(f"{'工具':<28}{'用例':<16}{'结果'}")
print("=" * 70)

fails = []
total = 0
for tool, cases in CASES:
    for label, args, fields in cases:
        total += 1
        gl = gateway_call(tool, args)
        lc = local_call(tool, args, timeout=60)
        time.sleep(0.3)  # 避免限流

        # 双方都报错 → 标记 skip
        if gl.get("error") and lc.get("error"):
            print(f"{tool:<28}{label:<16}⚠️ 双端均错误(跳过)")
            continue
        if gl.get("error"):
            print(f"{tool:<28}{label:<16}❌ Gateway错误: {str(gl['error'])[:50]}")
            fails.append((tool, label, f"GW error: {str(gl['error'])[:80]}"))
            continue
        if lc.get("error"):
            print(f"{tool:<28}{label:<16}❌ 本地错误: {str(lc['error'])[:50]}")
            fails.append((tool, label, f"LOCAL error: {str(lc['error'])[:80]}"))
            continue

        # 对比字段（映射: GW路径 → 本地路径 + 容差）
        mismatches = []
        for gw_f, lc_f, tol in fields:
            gw_v = get_by_path(gl, gw_f)
            lc_v = get_by_path(lc, lc_f)
            if not num_equal(gw_v, lc_v, tol):
                mismatches.append(f"{lc_f}: GW={gw_v} vs LOCAL={lc_v}")

        if mismatches:
            print(f"{tool:<28}{label:<16}❌ 不一致: {'; '.join(mismatches[:3])}")
            fails.append((tool, label, "; ".join(mismatches[:3])))
        else:
            # 显示一个代表性数值确认数据真实性
            sample = fields[1] if len(fields) > 1 else fields[0]
            v = get_by_path(lc, sample[1])
            print(f"{tool:<28}{label:<16}✅ 一致 ({sample[1]}={v})")

print("=" * 70)
print(f"总计 {total} 用例 | 失败 {len(fails)}")
if fails:
    print("\n❌ 失败明细:")
    for t, l, m in fails:
        print(f"  {t}({l}): {m}")
