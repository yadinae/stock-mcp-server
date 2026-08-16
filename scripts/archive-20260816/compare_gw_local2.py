#!/usr/bin/env python3
"""对比 Round 2: 东财系增量工具（公告/研报/资金流/解禁/可转债/股东/板块）"""
import json, sys, urllib.request, time
sys.path.insert(0, '/home/admin/.hermes/scripts')
from stock_mcp_client import call_tool as local_call

GATEWAY = "https://mcp-gateway.yadinae.workers.dev/mcp"
KEY = json.load(open('/home/admin/.hermes/scripts/secrets.json')).get('STOCK_GATEWAY_TOKEN', '')
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"

def gateway_call(name, args):
    payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                          "params": {"name": name, "arguments": args}}).encode()
    req = urllib.request.Request(GATEWAY, data=payload, headers={
        "Content-Type": "application/json", "Authorization": f"Bearer {KEY}", "User-Agent": UA})
    try:
        resp = json.loads(urllib.request.urlopen(req, timeout=45).read())
        if "error" in resp:
            return {"error": resp["error"]}
        return json.loads(resp["result"]["content"][0]["text"])
    except Exception as e:
        return {"error": str(e)}

def get_by_path(obj, path):
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
    if a is None or b is None:
        return a is None and b is None
    try:
        fa, fb = float(a), float(b)
        return abs(fa - fb) <= max(tol, abs(fa) * 0.005)
    except (ValueError, TypeError):
        return str(a).strip() == str(b).strip()

CASES = [
    ("get_announcements", [
        ("公告-茅台", {"code": "600519", "page_size": 3}, [("items.0.title", "items.0.title", 0), ("items.0.date", "items.0.date", 0)]),
    ]),
    ("get_research_reports", [
        ("研报-茅台", {"code": "600519"}, [("items.0.title", "items.0.title", 0), ("items.0.date", "items.0.date", 0)]),
    ]),
    ("get_fund_flow_120d", [
        ("资金流-茅台", {"code": "600519"}, [("items.0.date", "items.0.date", 0), ("items.0.main_net", "items.0.main_net", 0.011)]),
    ]),
    ("get_lockup_calendar", [
        ("解禁-茅台", {"code": "600519"}, [("future.0.date", "future.0.date", 0)]),
    ]),
    ("get_convertible_bonds", [
        # GW 字段是 items[] / 本地是 bonds[]（结构不同，映射对比）
        ("可转债", {"page_size": 5}, [("items.0.bond_code", "bonds.0.bond_code", 0), ("items.0.bond_abbr", "bonds.0.bond_abbr", 0)]),
    ]),
    ("get_top_shareholders", [
        ("十大股东-茅台", {"code": "600519"}, [("holders.0.holder_name", "holders.0.holder_name", 0), ("holders.0.hold_ratio", "holders.0.hold_ratio", 0.5)]),
    ]),
    ("get_company_profile", [
        ("公司资料-茅台", {"code": "600519"}, [("org_name", "org_name", 0), ("chairman", "chairman", 0)]),
    ]),
    ("get_dividend_history", [
        ("分红-茅台", {"code": "600519"}, [("items.0.plan_date", "items.0.plan_date", 0), ("items.0.cash_per_share", "items.0.cash_per_share", 0.05)]),
    ]),
    ("get_stock_boards", [
        # GW 结构是 boards[]/concept_tags[] / 本地是 industry/concepts[]（映射对比）
        ("所属板块-茅台", {"code": "600519"}, [("boards.0.name", "concepts.0.name", 0), ("total", "total", 0)]),
    ]),
]

print("=" * 70)
print(f"{'工具':<26}{'用例':<16}{'结果'}")
print("=" * 70)
fails = []
total = 0
for tool, cases in CASES:
    for label, args, fields in cases:
        total += 1
        gl = gateway_call(tool, args)
        lc = local_call(tool, args, timeout=60)
        time.sleep(0.3)

        if gl.get("error") and lc.get("error"):
            print(f"{tool:<26}{label:<16}⚠️ 双端均错误(跳过)")
            continue
        if gl.get("error"):
            print(f"{tool:<26}{label:<16}❌ GW错误: {str(gl['error'])[:60]}")
            fails.append((tool, label, f"GW error: {str(gl['error'])[:80]}"))
            continue
        if lc.get("error"):
            print(f"{tool:<26}{label:<16}❌ 本地错误: {str(lc['error'])[:60]}")
            fails.append((tool, label, f"LOCAL error: {str(lc['error'])[:80]}"))
            continue

        mismatches = []
        for gw_f, lc_f, tol in fields:
            gw_v = get_by_path(gl, gw_f)
            lc_v = get_by_path(lc, lc_f)
            if not num_equal(gw_v, lc_v, tol):
                mismatches.append(f"{lc_f}: GW={gw_v} vs LOCAL={lc_v}")

        if mismatches:
            print(f"{tool:<26}{label:<16}❌ {'; '.join(mismatches[:2])}")
            fails.append((tool, label, "; ".join(mismatches[:2])))
        else:
            sample = fields[1] if len(fields) > 1 else fields[0]
            v = get_by_path(lc, sample[1])
            print(f"{tool:<26}{label:<16}✅ 一致 ({sample[1]}={str(v)[:40]})")

print("=" * 70)
print(f"总计 {total} 用例 | 失败 {len(fails)}")
if fails:
    print("\n❌ 失败明细:")
    for t, l, m in fails:
        print(f"  {t}({l}): {m}")
