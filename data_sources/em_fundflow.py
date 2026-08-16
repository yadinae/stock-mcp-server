#!/usr/bin/env python3
"""个股资金流系列（移植自 Gateway em_fundflow.ts / em_bk_fundflow.ts / sina 日级资金流）

数据源策略（本地实测 2026-08-16）:
- push2.eastmoney.com fflow: 502 ❌（东财对数据中心IP风控）→ 替代:
  - get_fund_flow_120d: 新浪日级资金流 MoneyFlow.ssl_qsfx_zjlrqs（200 ✅）
  - get_fund_flow_minute: push2 重试 3 次（[3s,5s,8s] 退避，偶尔可过）；失败返回 error
  - get_concept_fund_flow: 腾讯板块接口 board_type=gn（200 ✅，字段 zljlr=主力净流入万元）
"""
import json
import time
import urllib.request
import urllib.parse

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"

SINA_FF_API = "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/MoneyFlow.ssl_qsfx_zjlrqs"
QQ_RANK_API = "https://proxy.finance.qq.com/cgi/cgi-bin/rank/pt/getRank"
PUSH2_FF_KL = "https://push2.eastmoney.com/api/qt/stock/fflow/kline/get"
PUSH2_FF_DAY = "https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get"


def _http_get(url: str, timeout: float = 12.0) -> str:
    req = urllib.request.Request(url, headers={
        "User-Agent": UA, "Referer": "https://finance.sina.com.cn/",
        "Accept": "*/*",
    })
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", "replace")


def _code_to_sina(code: str) -> str:
    """600519 → sh600519, 000001 → sz000001"""
    code = code.strip().lower()
    if code.startswith(("sh", "sz", "bj")):
        return code
    if code.startswith("6"):
        return f"sh{code}"
    return f"sz{code}"


def _code_to_secid(code: str) -> str:
    """600519 → 1.600519, 000001 → 0.000001"""
    code = code.strip()
    if code.startswith("6") or code.startswith("9"):
        return f"1.{code}"
    return f"0.{code}"


# ─── 120日资金流（新浪日级） ───

def get_fund_flow_120d(code: str, days: int = 120):
    """获取个股120日资金流向（日级主力/大单/中单/小单净流入）。新浪日级资金流。"""
    code = code.strip()
    if not code:
        return {"error": "股票代码不能为空"}
    days = max(1, min(int(days or 120), 120))
    sina_code = _code_to_sina(code)
    url = f"{SINA_FF_API}?daima={sina_code}&num={max(days, 10)}"
    try:
        raw = _http_get(url)
        # 新浪返回 JSONP 或纯 JSON 数组；剥函数包装
        start = raw.find("[")
        end = raw.rfind("]")
        if start < 0 or end < start:
            return {"code": code, "total_days": 0, "total_main_net_yi": 0, "flow": [], "error": "解析失败"}
        data = json.loads(raw[start:end + 1])
    except Exception as e:
        return {"code": code, "total_days": 0, "total_main_net_yi": 0, "flow": [], "error": str(e)[:120]}

    flow = []
    for row in data[:days]:
        try:
            flow.append({
                "date": str(row.get("opendate", ""))[:10],
                "main_net": round(float(row.get("r0_net") or 0)),      # 主力净流入(元)
                "small_net": 0,
                "mid_net": 0,
                "large_net": 0,
                "super_net": 0,
                "netamount": round(float(row.get("netamount") or 0)),  # 总净流入(元)
                "ratioamount": float(row.get("ratioamount") or 0),     # 净流入占比
            })
        except (TypeError, ValueError):
            continue

    total = sum(f["main_net"] for f in flow)
    return {
        "code": code,
        "total_days": len(flow),
        "total_main_net_yi": round(total / 1e8, 2),
        "flow": flow,
    }


# ─── 分钟级资金流（push2 重试，502 概率性可过） ───

def _push2_get_with_retry(url: str, timeout: float = 10.0, attempts: int = 3) -> dict | None:
    """push2 对数据中心 IP 概率性限流：3 次重试 + [3s,5s,8s] 退避（skill: ≥5s 成功率明显提升）"""
    delays = [3, 5, 8]
    last_err = None
    for i in range(attempts):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": UA, "Referer": "https://quote.eastmoney.com/",
                "Accept": "*/*",
            })
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8", "replace"))
        except Exception as e:
            last_err = e
            if i < attempts - 1:
                time.sleep(delays[i])
    raise last_err


def get_fund_flow_minute(code: str):
    """获取个股当日盘中分钟级资金流向。push2 主源（重试），失败返回 error。"""
    code = code.strip()
    if not code:
        return {"error": "股票代码不能为空"}
    secid = _code_to_secid(code)
    url = (f"{PUSH2_FF_KL}?secid={secid}&klt=1&fields1=f1,f2,f3,f7"
           f"&fields2=f51,f52,f53,f54,f55,f56,f57")
    try:
        d = _push2_get_with_retry(url)
    except Exception as e:
        return {
            "code": code, "points": 0, "total_main_net_wan": 0, "flow": [],
            "error": f"push2 限流不可达（数据中心IP风控）: {type(e).__name__}", "retryable": True,
        }

    klines = (d or {}).get("data", {}).get("klines") or []
    flow = []
    for line in klines:
        parts = line.split(",")
        try:
            flow.append({
                "time": parts[0] if parts else "",
                "main_net": float(parts[1]) if len(parts) > 1 else 0,
                "small_net": float(parts[2]) if len(parts) > 2 else 0,
                "mid_net": float(parts[3]) if len(parts) > 3 else 0,
                "large_net": float(parts[4]) if len(parts) > 4 else 0,
                "super_net": float(parts[5]) if len(parts) > 5 else 0,
            })
        except (ValueError, IndexError):
            continue

    total = sum(p["main_net"] for p in flow)
    return {
        "code": code,
        "points": len(flow),
        "total_main_net_wan": round(total / 10000),
        "flow": flow[-60:],
    }


# ─── 概念板块资金流（腾讯板块接口替代 push2） ───

def get_concept_fund_flow(top_n: int = 20, sort_by: str = "net_inflow"):
    """获取概念板块资金流向排名（主力净流入/流出）。腾讯板块接口 board_type=gn。"""
    top_n = max(1, min(int(top_n or 20), 50))
    params = {
        "board_type": "gn",
        "sort_type": "price",
        "direct": "down",
        "offset": "0",
        "count": str(top_n * 3),  # 多取些再按 zljlr 排序
    }
    url = f"{QQ_RANK_API}?{urllib.parse.urlencode(params)}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=12) as resp:
            d = json.loads(resp.read().decode("utf-8", "replace"))
    except Exception as e:
        return {"type": "concept", "records": [], "count": 0, "sorted_by": sort_by, "error": str(e)[:120]}

    rank_list = (d or {}).get("data", {}).get("rank_list") or []
    records = []
    for item in rank_list:
        try:
            zljlr = float(item.get("zljlr") or 0)
            records.append({
                "code": str(item.get("code", "")),
                "name": str(item.get("name", "")),
                "net_inflow": round(zljlr * 10000),  # 万元 → 元
            })
        except (TypeError, ValueError):
            continue

    records.sort(key=lambda r: r["net_inflow"], reverse=(sort_by != "net_outflow"))
    records = records[:top_n]
    return {"type": "concept", "records": records, "count": len(records), "sorted_by": sort_by}


if __name__ == "__main__":
    import sys
    test = sys.argv[1] if len(sys.argv) > 1 else "120d"
    code = sys.argv[2] if len(sys.argv) > 2 else "600519"
    if test == "120d":
        r = get_fund_flow_120d(code)
        print(f"120日: {r['total_days']}天 主力净流入{r['total_main_net_yi']}亿 | 最新: {r['flow'][0] if r['flow'] else '无'}")
    elif test == "minute":
        r = get_fund_flow_minute(code)
        print(f"分钟: points={r['points']} | 主力净流入{r['total_main_net_wan']}万 | error={r.get('error', '')}")
    elif test == "concept":
        r = get_concept_fund_flow(5)
        print(f"概念: {r['count']}条 | 前3: {[x['name'] for x in r['records'][:3]]}")
        for rec in r["records"][:3]:
            print(f"  {rec['name']}: {rec['net_inflow']/1e8:.2f}亿")
