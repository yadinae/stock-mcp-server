#!/usr/bin/env python3
"""东财市场数据系列（移植自 Gateway em_market_lhb.ts / em_fundflow.ts / em_blocks.ts / em_reports.ts / cninfo.ts / em_bk_fundflow.ts / em_limitup.ts / ths_hot.ts）

数据源策略（本地实测）:
- datacenter-web.eastmoney.com: 200 ✅ — 龙虎榜/解禁/研报/财务
- emweb.securities.eastmoney.com: 200 ✅ — F10
- push2.eastmoney.com: 502 ❌（东财对数据中心IP风控）→ 行业排名/资金流用 TV REST 替代
- www.cninfo.com.cn: 200 ✅ — 公告
- danjuanfunds.com: 200 ✅ — 基金
- zx.10jqka.com.cn: 200 ✅ — 同花顺热点
"""
import json
import time
import urllib.request
import urllib.parse

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
DATACENTER_API = "https://datacenter-web.eastmoney.com/api/data/v1/get"
PUSH2_API = "https://push2.eastmoney.com/api/qt/clist/get"


def _http_get(url: str, referer: str = "https://data.eastmoney.com/", timeout: float = 12.0):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA, "Referer": referer, "Accept": "application/json, text/plain, */*",
    })
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", "replace")


def _http_post(url: str, data: dict, referer: str = "https://data.eastmoney.com/", timeout: float = 12.0):
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(url, data=body, headers={
        "User-Agent": UA, "Referer": referer, "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json, text/plain, */*",
    })
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", "replace")


def _datacenter(report_name: str, filter_str: str, page_size: int = 50,
                sort_columns: str = "", sort_types: str = "-1") -> list:
    params = {
        "reportName": report_name, "columns": "ALL",
        "pageNumber": "1", "pageSize": str(page_size),
        "sortTypes": sort_types, "source": "WEB", "client": "WEB",
    }
    if sort_columns:
        params["sortColumns"] = sort_columns
    if filter_str:
        params["filter"] = filter_str
    url = f"{DATACENTER_API}?{urllib.parse.urlencode(params)}"
    try:
        raw = _http_get(url, referer="https://data.eastmoney.com/")
        data = json.loads(raw)
        return (data.get("result") or {}).get("data") or []
    except Exception:
        return []


def extract_code(code: str) -> str:
    c = code.strip().upper()
    for suf in (".SH", ".SZ", ".BJ", "SH", "SZ", "BJ"):
        c = c.replace(suf, "")
    return c.strip()


def get_market_lhb(trade_date: str = "", min_net_buy_wan: float = 0) -> dict:
    """全市场龙虎榜（datacenter RPT_DAILYBILLBOARD_DETAILSNEW，本地 200 ✅）"""
    if not trade_date:
        trade_date = time.strftime("%Y-%m-%d", time.localtime(time.time() + 8 * 3600))
    data = _datacenter(
        "RPT_DAILYBILLBOARD_DETAILSNEW",
        f"(TRADE_DATE>='{trade_date}')(TRADE_DATE<='{trade_date}')",
        page_size=500, sort_columns="BILLBOARD_NET_AMT", sort_types="-1",
    )
    stocks = []
    for row in data:
        if min_net_buy_wan and (row.get("BILLBOARD_NET_AMT") or 0) / 10000 < min_net_buy_wan:
            continue
        stocks.append({
            "code": row.get("SECURITY_CODE") or "",
            "name": row.get("SECURITY_NAME_ABBR") or "",
            "reason": row.get("EXPLAIN") or row.get("EXPLANATION") or "",
            "close": row.get("CLOSE_PRICE") or 0,
            "change_pct": round(float(row.get("CHANGE_RATE") or 0), 2),
            "net_buy_wan": round(float(row.get("BILLBOARD_NET_AMT") or 0) / 10000, 1),
            "turnover_pct": round(float(row.get("TURNOVERRATE") or 0), 2),
        })
    return {"date": trade_date, "total_records": len(stocks), "stocks": stocks}


def get_lockup_calendar(code: str, forward_days: int = 90) -> dict:
    """限售解禁日历（datacenter RPT_LIFT_STAGE）"""
    c = extract_code(code)
    trade_date = time.strftime("%Y-%m-%d", time.localtime(time.time() + 8 * 3600))
    end = time.strftime("%Y-%m-%d", time.localtime(time.time() + 8 * 3600 + forward_days * 86400))
    history = _datacenter(
        "RPT_LIFT_STAGE", f'(SECURITY_CODE="{c}")',
        page_size=15, sort_columns="FREE_DATE", sort_types="-1",
    )
    upcoming = _datacenter(
        "RPT_LIFT_STAGE", f'(SECURITY_CODE="{c}")(FREE_DATE>=\'{trade_date}\')(FREE_DATE<=\'{end}\')',
        page_size=20, sort_columns="FREE_DATE", sort_types="1",
    )
    fmt = lambda rows: [{
        "date": str(r.get("FREE_DATE") or "")[:10],
        "type": r.get("LIMITED_STOCK_TYPE") or "",
        "shares": r.get("FREE_SHARES_NUM") or 0,
        "ratio": r.get("FREE_RATIO") or 0,
    } for r in rows]
    return {"code": code, "history": fmt(history), "upcoming": fmt(upcoming)}


def get_research_reports(code: str, pages: int = 1) -> dict:
    """个股研报列表（datacenter RPT_RESEARCH_REPORT）"""
    c = extract_code(code)
    secu = f"{c}.SH" if c[0] in "69" else f"{c}.SZ"
    data = _datacenter(
        "RPT_RESEARCH_REPORT", f'(SECURITY_CODE="{c}")',
        page_size=min(pages * 20, 100), sort_columns="NOTICE_DATE", sort_types="-1",
    )
    reports = [{
        "title": r.get("TITLE") or "",
        "publish_date": str(r.get("NOTICE_DATE") or "")[:10],
        "org": r.get("ORG_NAME") or "",
        "rating": r.get("EM_RATING_NAME") or r.get("RATING") or "",
    } for r in data]
    return {"code": code, "total": len(reports), "reports": reports[:30]}


def get_announcements(code: str, page_size: int = 30) -> dict:
    """巨潮公告（cninfo POST，本地 200 ✅）"""
    c = extract_code(code)
    try:
        raw = _http_post(
            "https://www.cninfo.com.cn/new/hisAnnouncement/query",
            {"pageNum": "1", "pageSize": str(page_size), "column": "szse",
             "tabName": "fulltext", "plate": "", "stock": "", "searchkey": "",
             "secid": "", "category": "", "trade": "", "seDate": ""},
            referer="https://www.cninfo.com.cn/",
        )
        data = json.loads(raw)
        announcements = data.get("announcements") or []
        items = [{
            "title": a.get("announcementTitle") or "",
            "date": str(a.get("announcementTime") or "")[:10],
            "url": f"https://static.cninfo.com.cn/{a.get('adjunctUrl') or ''}" if a.get("adjunctUrl") else "",
        } for a in announcements[:page_size]]
        return {"code": code, "total": len(items), "announcements": items}
    except Exception as e:
        return {"code": code, "error": str(e), "announcements": []}


def get_stock_boards(code: str) -> dict:
    """个股所属板块（东财 push2，本地可能 502 → 返回空但带提示）"""
    c = extract_code(code)
    prefix = 1 if c[0] in "69" else 0
    url = f"https://push2.eastmoney.com/api/qt/stock/get?secid={prefix}.{c}&fields=f57,f58,f127,f128,f136"
    try:
        raw = _http_get(url, referer="https://quote.eastmoney.com/")
        data = json.loads(raw)
        d = data.get("data") or {}
        return {
            "code": c,
            "name": d.get("f58") or "",
            "industry": d.get("f127") or "",
            "concept": d.get("f128") or "",
            "region": d.get("f136") or "",
            "source": "eastmoney_push2",
        }
    except Exception as e:
        return {"code": c, "error": f"push2 受限: {e}", "source": "eastmoney_push2"}


def get_industry_rank_tv(top_n: int = 20) -> dict:
    """TV REST 行业排名（push2 替代源，本地 200 ✅）"""
    try:
        payload = json.dumps({
            "filter": [{"left": "market_cap_basic", "operation": "nempty"}],
            "options": {"lang": "zh"},
            "markets": ["sse", "szse"],
            "symbols": {"query": {"types": []}, "tickers": []},
            "columns": ["name", "description", "close", "change", "change_abs", "sector", "industry", "market_cap_basic"],
            "sort": {"sortBy": "market_cap_basic", "sortOrder": "desc"},
            "range": [0, 300],
        }).encode()
        req = urllib.request.Request("https://scanner.tradingview.com/china/scan", data=payload, headers={
            "User-Agent": UA, "Content-Type": "application/json", "Accept": "application/json",
        })
        with urllib.request.urlopen(req, timeout=12) as resp:
            data = json.loads(resp.read().decode())
        agg = {}
        for row in (data.get("data") or []):
            v = row.get("d") or []
            if len(v) < 7:
                continue
            industry = v[6] or v[5] or "其他"
            change_pct = float(v[3] or 0)
            a = agg.setdefault(industry, {"count": 0, "sum": 0.0, "up": 0, "down": 0})
            a["count"] += 1
            a["sum"] += change_pct
            if change_pct > 0:
                a["up"] += 1
            elif change_pct < 0:
                a["down"] += 1
        industries = [{
            "industry": k,
            "avg_change_pct": round(v["sum"] / v["count"], 2) if v["count"] else 0,
            "count": v["count"], "up_count": v["up"], "down_count": v["down"],
        } for k, v in agg.items()]
        industries.sort(key=lambda x: -x["avg_change_pct"])
        return {"source": "tradingview_rest", "total": len(industries), "top": industries[:top_n]}
    except Exception as e:
        return {"source": "tradingview_rest", "error": str(e), "top": []}


def get_tv_market_list(top_n: int = 100) -> dict:
    """TV REST 大盘股列表"""
    try:
        payload = json.dumps({
            "filter": [{"left": "market_cap_basic", "operation": "nempty"}],
            "options": {"lang": "zh"},
            "markets": ["sse", "szse"],
            "symbols": {"query": {"types": []}, "tickers": []},
            "columns": ["name", "description", "close", "change", "change_abs", "sector", "industry", "market_cap_basic"],
            "sort": {"sortBy": "market_cap_basic", "sortOrder": "desc"},
            "range": [0, top_n],
        }).encode()
        req = urllib.request.Request("https://scanner.tradingview.com/china/scan", data=payload, headers={
            "User-Agent": UA, "Content-Type": "application/json", "Accept": "application/json",
        })
        with urllib.request.urlopen(req, timeout=12) as resp:
            data = json.loads(resp.read().decode())
        stocks = []
        for row in (data.get("data") or []):
            v = row.get("d") or []
            if len(v) < 8:
                continue
            stocks.append({
                "code": str(v[0] or ""), "name": str(v[1] or ""),
                "close": float(v[2] or 0), "change_pct": float(v[3] or 0),
                "industry": str(v[6] or ""), "market_cap": float(v[7] or 0),
            })
        return {"source": "tradingview_rest", "stocks": stocks}
    except Exception as e:
        return {"source": "tradingview_rest", "error": str(e), "stocks": []}


def get_tv_quote(code: str) -> dict:
    """TV REST 个股行情"""
    c = extract_code(code)
    exchange = "SSE" if c[0] in "69" else "SZSE"
    try:
        payload = json.dumps({
            "filter": [{"left": "market_cap_basic", "operation": "nempty"}],
            "options": {"lang": "zh"},
            "markets": ["sse", "szse"],
            "symbols": {"query": {"types": []}, "tickers": [f"{exchange}:{c}"]},
            "columns": ["name", "description", "close", "change", "change_abs", "sector", "industry", "market_cap_basic"],
            "sort": {"sortBy": "market_cap_basic", "sortOrder": "desc"},
            "range": [0, 5],
        }).encode()
        req = urllib.request.Request("https://scanner.tradingview.com/china/scan", data=payload, headers={
            "User-Agent": UA, "Content-Type": "application/json", "Accept": "application/json",
        })
        with urllib.request.urlopen(req, timeout=12) as resp:
            data = json.loads(resp.read().decode())
        rows = data.get("data") or []
        if not rows:
            return {"source": "tradingview_rest", "error": f"未找到代码 {code}", "code": code}
        v = rows[0].get("d") or []
        return {
            "source": "tradingview_rest", "code": str(v[0] or c), "name": str(v[1] or ""),
            "close": float(v[2] or 0), "change_pct": float(v[3] or 0),
            "industry": str(v[6] or ""), "market_cap": float(v[7] or 0),
        }
    except Exception as e:
        return {"source": "tradingview_rest", "error": str(e), "code": code}


def get_market_hot_stocks(date_str: str = "") -> dict:
    """同花顺热点强势股（本地 200 ✅，GBK 编码，返回纯JSON）"""
    if not date_str:
        date_str = time.strftime("%Y%m%d", time.localtime(time.time() + 8 * 3600))
    try:
        url = f"http://zx.10jqka.com.cn/event/api/getharden/date/{date_str}/orderby/date/orderway/desc/charset/GBK/"
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=12) as resp:
            raw = resp.read()
        text = raw.decode("gbk", "replace")
        # 返回纯 JSON（偶发带 JSONP 包装 data = {...}）
        import re
        m = re.search(r"data\s*=\s*(\{.*?\})\s*;?\s*$", text, re.S)
        if m:
            data = json.loads(m.group(1))
        else:
            data = json.loads(text)
        items = data.get("data") or []
        if isinstance(items, dict):
            items = items.get("list") or items.get("data") or []
        stocks = []
        for it in items:
            stocks.append({
                "code": str(it.get("code") or ""),
                "name": it.get("name") or "",
                "reason": it.get("reason") or it.get("hot_reason") or "",
                "change_pct": it.get("zhangfu") or it.get("zdf") or it.get("change_pct") or "",
                "turnover_rate": it.get("huanshou") or "",
            })
        return {"date": date_str, "total": len(stocks), "stocks": stocks[:50]}
    except Exception as e:
        return {"date": date_str, "error": str(e), "stocks": []}


def get_convertible_bonds(page_size: int = 20) -> dict:
    """可转债列表（东财 datacenter，本地 200 ✅）"""
    data = _datacenter(
        "RPT_BOND_CB_LIST", "",
        page_size=min(page_size, 100), sort_columns="", sort_types="",
    )
    bonds = [{
        "code": r.get("SECURITY_CODE") or r.get("BOND_CODE") or "",
        "name": r.get("SECURITY_NAME_ABBR") or r.get("BOND_ABBR") or "",
        "price": r.get("LATEST_PRICE") or r.get("CLOSE_PRICE") or 0,
        "premium_rate": r.get("CONVERT_PREMIUM_RATIO") or r.get("PREMIUM_RATE") or 0,
    } for r in data]
    return {"total": len(bonds), "bonds": bonds[:page_size]}
