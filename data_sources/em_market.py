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
    """个股所属板块（emweb F10 CoreConception，替代 push2 — 本地 200 ✅）

    东财 push2 对数据中心 IP 限流 502，emweb.securities.eastmoney.com 不受限。
    """
    c = extract_code(code)
    prefix = "SH" if c[0] in "69" else ("BJ" if c[0] in "48" else "SZ")
    url = f"https://emweb.securities.eastmoney.com/PC_HSF10/CoreConception/PageAjax?code={prefix}{c}"
    try:
        raw = _http_get(url, referer="https://emweb.securities.eastmoney.com/")
        data = json.loads(raw)
        ssbk = data.get("ssbk") or []
        # 区分行业/概念/地域（按板块名特征）
        industries, concepts, regions = [], [], []
        for b in ssbk:
            name = b.get("BOARD_NAME") or ""
            item = {"name": name, "code": b.get("BOARD_CODE") or "", "rank": b.get("BOARD_RANK") or 0}
            if name.endswith(("Ⅱ", "Ⅲ", "Ⅰ")):
                industries.append(item)
            elif name.endswith("板块"):
                regions.append(item)
            else:
                concepts.append(item)
        return {
            "code": c,
            "name": ssbk[0].get("SECURITY_NAME_ABBR") if ssbk else "",
            "industry": industries[0]["name"] if industries else "",
            "concepts": concepts[:20],
            "regions": regions[:10],
            "total": len(ssbk),
            "source": "emweb_f10",
        }
    except Exception as e:
        return {"code": c, "error": f"emweb 板块获取失败: {e}", "source": "emweb_f10"}


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


def get_limitup_tiers() -> dict:
    """涨停梯队分析（移植自 Gateway em_limitup.ts，东财 datacenter + 腾讯K线连板判断）
    输出结构与 Gateway 一致: market_summary + tiers(首板/二连板/三连板及以上/炸板)
    """
    def _is_limit_up(chg: float) -> bool:
        return chg >= 9.8  # 保守阈值覆盖所有板块

    def _twitter_code(code: str) -> str:
        c = extract_code(code)
        return f"sh{c}" if c.startswith("6") else f"sz{c}"

    def _check_consecutive(code: str, current_chg: float):
        """腾讯K线判断连板天数 + 封板质量"""
        sec = _twitter_code(code)
        url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={sec},day,,,20,qfq"
        try:
            raw = _http_get(url, referer="https://gu.qq.com/", timeout=10)
            data = json.loads(raw)
            node = (data.get("data") or {}).get(sec, {})
            kl = node.get("day") or node.get("qfqday") or []
            if not kl or len(kl) < 2:
                return 1, True
            klines = sorted(kl, key=lambda r: str(r[0]), reverse=True)  # 新→旧
            threshold = 19.5 if (code.startswith("3") or code.startswith("688")) else 9.8
            today_high = float(klines[0][3] or 0)
            today_close = float(klines[0][2] or 0)
            is_board = today_high > 0 and today_close > 0 and \
                ((today_high - today_close) / today_high) < 0.02 and \
                current_chg >= threshold * 0.8
            days = 1
            for i in range(len(klines) - 1):
                tc = float(klines[i][2] or 0)
                pc = float(klines[i + 1][2] or 0)
                if pc <= 0:
                    break
                chg = ((tc - pc) / pc) * 100
                if chg >= threshold:
                    days += 1
                else:
                    break
            return days, is_board
        except Exception:
            return 1, True

    # 1. 当日涨停股（东财 datacenter）
    params = {
        "reportName": "RPT_DMSK_TS_STOCKNEW", "columns": "ALL",
        "pageNumber": "1", "pageSize": "200",
        "sortColumns": "CHANGE_RATE", "sortTypes": "-1",
        "filter": "(CHANGE_RATE>=9.8)", "source": "WEB", "client": "WEB",
    }
    url = f"{DATACENTER_API}?{urllib.parse.urlencode(params)}"
    try:
        raw = _http_get(url, referer="https://data.eastmoney.com/", timeout=15)
        data = json.loads(raw)
        rows = (data.get("result") or {}).get("data") or []
    except Exception as e:
        return {"success": False, "error": f"涨停采集失败: {e}", "tiers": {}, "market_summary": {}}

    if not rows:
        return {"success": True, "date": time.strftime("%Y-%m-%d"), "total_limit_up": 0,
                "message": "今日无涨停股票（可能是非交易日）", "tiers": {}, "market_summary": {}}

    stocks = [{
        "code": r.get("SECURITY_CODE", ""),
        "name": r.get("SECURITY_NAME_ABBR", ""),
        "price": r.get("CLOSE_PRICE", 0) or 0,
        "changePct": r.get("CHANGE_RATE", 0) or 0,
        "turnoverRate": r.get("TURNOVERRATE", 0) or 0,
        "totalScore": r.get("TOTALSCORE", 0) or 0,
        "consecutiveDays": 0, "isBoard": True,
    } for r in rows]

    # 2. 前 30 只做连板分析（太多会超时）
    detailed, remaining = stocks[:30], stocks[30:]
    for s in detailed:
        s["consecutiveDays"], s["isBoard"] = _check_consecutive(s["code"], s["changePct"])
        time.sleep(0.05)  # 腾讯K线轻限流
    for s in remaining:
        s["consecutiveDays"] = 1

    # 3. 分类
    tiers = {"first_boards": [], "second_boards": [], "multiple_boards": [], "broken_boards": []}
    for s in stocks:
        if not s["isBoard"]:
            tiers["broken_boards"].append(s)
        elif s["consecutiveDays"] >= 3:
            tiers["multiple_boards"].append(s)
        elif s["consecutiveDays"] == 2:
            tiers["second_boards"].append(s)
        else:
            tiers["first_boards"].append(s)

    # 4. 市场统计
    board_count = len(tiers["first_boards"]) + len(tiers["second_boards"]) + len(tiers["multiple_boards"])
    total = board_count + len(tiers["broken_boards"])
    ratio = (board_count / total * 100) if total > 0 else 0
    avg_days = sum(s["consecutiveDays"] for s in stocks) / len(stocks) if stocks else 0
    market_summary = {
        "total_limit_up": len(stocks),
        "first_board": len(tiers["first_boards"]),
        "second_board": len(tiers["second_boards"]),
        "multiple_board": len(tiers["multiple_boards"]),
        "broken_board": len(tiers["broken_boards"]),
        "board_success_rate": f"{ratio:.1f}%",
        "avg_consecutive": f"{avg_days:.2f}",
        "max_consecutive": max(s["consecutiveDays"] for s in stocks) if stocks else 0,
    }

    def fmt(s):
        return {
            "code": s["code"], "name": s["name"], "price": s["price"],
            "change_pct": f"{s['changePct']:.2f}", "turnover_rate": f"{s['turnoverRate']:.2f}",
            "total_score": f"{s['totalScore']:.1f}", "consecutive_days": s["consecutiveDays"],
            "is_board": s["isBoard"],
        }

    return {
        "success": True, "date": time.strftime("%Y-%m-%d"),
        "market_summary": market_summary,
        "tiers": {
            "首板": {"count": len(tiers["first_boards"]), "stocks": [fmt(s) for s in tiers["first_boards"][:15]]},
            "二连板": {"count": len(tiers["second_boards"]), "stocks": [fmt(s) for s in tiers["second_boards"][:15]]},
            "三连板及以上": {"count": len(tiers["multiple_boards"]), "stocks": [fmt(s) for s in tiers["multiple_boards"][:20]]},
            "炸板": {"count": len(tiers["broken_boards"]), "stocks": [fmt(s) for s in tiers["broken_boards"][:15]]},
        },
    }


def get_wallstreetcn_news(limit: int = 10, mode: str = "all") -> dict:
    """华尔街见闻快讯（移植自 Gateway wallstreetcn.ts，本地 200 ✅）
    mode: all | live | hot | articles
    """
    api_base = "https://api-one.wallstcn.com"
    ch_map = {"global": "global-channel", "cn": "cn-stock", "us": "us-stock", "hk": "hk-stock",
              "forex": "forex-channel", "bond": "bond-channel", "commodity": "commodity-channel",
              "fund": "fund-channel", "macro": "macro-channel"}
    n = min(limit or 10, 30)

    def _wscn(path):
        url = api_base + path
        req = urllib.request.Request(url, headers={
            "User-Agent": UA, "Referer": "https://wallstreetcn.com/",
            "Origin": "https://wallstreetcn.com", "Accept": "application/json",
        })
        with urllib.request.urlopen(req, timeout=12) as resp:
            return json.loads(resp.read().decode("utf-8", "replace"))

    result = {"success": True, "source": "华尔街见闻", "fetch_time": time.strftime("%Y-%m-%dT%H:%M:%S")}
    try:
        if mode in ("all", "live"):
            try:
                d = _wscn(f"/apiv1/content/lives?channel=global-channel&limit={n}")
                if d.get("code") == 20000:
                    items = (d.get("data") or {}).get("items") or []
                    result["live_news"] = {"channel": "global", "count": len(items), "items": [
                        {"time": time.strftime("%H:%M", time.localtime(it.get("display_time") or 0)),
                         "content": it.get("content_text") or "", "author": (it.get("author") or {}).get("display_name", ""),
                         "url": f"https:{it['uri']}" if it.get("uri") else None}
                        for it in items]}
            except Exception:
                pass
        if mode in ("all", "hot"):
            try:
                d = _wscn(f"/apiv1/content/articles/hot?period=all&limit={n}")
                if d.get("code") == 20000:
                    items = (d.get("data") or {}).get("day_items") or []
                    result["hot_articles"] = {"count": len(items), "items": [
                        {"title": it.get("title", ""), "date": time.strftime("%Y-%m-%d", time.localtime(it.get("display_time") or 0)),
                         "views": it.get("pageviews") or 0, "url": it.get("uri", "")}
                        for it in items]}
            except Exception:
                pass
        if mode in ("all", "articles"):
            try:
                d = _wscn(f"/apiv1/content/articles?limit={n}")
                if d.get("code") == 20000:
                    items = (d.get("data") or {}).get("items") or []
                    result["latest_articles"] = {"count": len(items), "items": [
                        {"title": it.get("title", ""), "summary": it.get("content_short", ""),
                         "author": (it.get("author") or {}).get("display_name", ""),
                         "date": time.strftime("%Y-%m-%d", time.localtime(it.get("display_time") or 0)),
                         "url": it.get("uri", "")}
                        for it in items]}
            except Exception:
                pass
        result["summary"] = {
            "total_items": len(result.get("live_news", {}).get("items", [])) +
                            len(result.get("hot_articles", {}).get("items", [])) +
                            len(result.get("latest_articles", {}).get("items", [])),
            "live_count": len(result.get("live_news", {}).get("items", [])),
            "hot_count": len(result.get("hot_articles", {}).get("items", [])),
            "article_count": len(result.get("latest_articles", {}).get("items", [])),
        }
    except Exception as e:
        return {"success": False, "source": "华尔街见闻", "error": f"获取失败: {e}", "fetch_time": result["fetch_time"]}
    return result


def get_industry_fund_flow(top_n: int = 20) -> dict:
    """行业板块资金流向（腾讯板块接口 zljlr 主力净流入，本地 200 ✅ — 替代 push2 502）
    输出结构与 Gateway em_bk_fundflow 一致: {type, records:[{code,name,net_inflow}], count, sorted_by}
    """
    n = min(max(int(top_n or 20), 1), 50)
    url = ("https://proxy.finance.qq.com/cgi/cgi-bin/rank/pt/getRank"
           f"?board_type=hy&sort_type=price&direct=down&offset=0&count={n}")
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": UA, "Referer": "https://gu.qq.com/", "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=12) as resp:
            d = json.loads(resp.read().decode("utf-8", "replace"))
        rows = (d.get("data") or {}).get("rank_list") or []
        records = [{
            "code": r.get("code", ""), "name": r.get("name", ""),
            "net_inflow": float(r.get("zljlr") or 0),  # 主力净流入（万元）
        } for r in rows]
        records.sort(key=lambda x: x["net_inflow"], reverse=True)
        return {"type": "industry", "records": records[:n], "count": len(records), "sorted_by": "net_inflow"}
    except Exception as e:
        return {"type": "industry", "records": [], "count": 0, "sorted_by": "net_inflow",
                "error": f"板块资金流接口异常: {e}"}


def get_convertible_bonds(page_size: int = 20) -> dict:
    """可转债列表（东财 datacenter RPT_BOND_CB_LIST，按上市日期倒序 — 本地 200 ✅）

    Gateway 同款: sortColumns=PUBLIC_START_DATE&sortTypes=-1 + quoteColumns 实时价
    """
    size = min(max(int(page_size or 20), 1), 100)
    quote_cols = ("f2~01~CONVERT_STOCK_CODE~CONVERT_STOCK_PRICE,"
                  "f235~10~SECURITY_CODE~TRANSFER_PRICE,"
                  "f236~10~SECURITY_CODE~TRANSFER_VALUE,"
                  "f2~10~SECURITY_CODE~CURRENT_BOND_PRICE,"
                  "f237~10~SECURITY_CODE~TRANSFER_PREMIUM_RATIO,"
                  "f239~10~SECURITY_CODE~RESALE_TRIG_PRICE,"
                  "f240~10~SECURITY_CODE~REDEEM_TRIG_PRICE,"
                  "f23~01~CONVERT_STOCK_CODE~PBV_RATIO")
    params = {
        "pageSize": str(size), "pageNumber": "1",
        "sortColumns": "PUBLIC_START_DATE", "sortTypes": "-1",
        "reportName": "RPT_BOND_CB_LIST", "columns": "ALL",
        "quoteColumns": quote_cols,
        "source": "WEB", "client": "WEB",
    }
    try:
        url = DATACENTER_API + "?" + urllib.parse.urlencode(params)
        raw = _http_get(url, referer="https://data.eastmoney.com/")
        data = json.loads(raw)
        rows = (data.get("result") or {}).get("data") or []
        bonds = [{
            "bond_code": r.get("SECURITY_CODE") or "",
            "bond_abbr": r.get("SECURITY_NAME_ABBR") or "",
            "stock_code": r.get("CONVERT_STOCK_CODE") or "",
            "convert_price": r.get("TRANSFER_PRICE") or 0,
            "convert_value": r.get("TRANSFER_VALUE") or 0,
            "bond_price": r.get("CURRENT_BOND_PRICE") or 0,
            "premium_rate": r.get("TRANSFER_PREMIUM_RATIO") or 0,
            "resale_trig_price": r.get("RESALE_TRIG_PRICE") or 0,
            "redeem_trig_price": r.get("REDEEM_TRIG_PRICE") or 0,
            "pbv": r.get("PBV_RATIO") or 0,
            "list_date": r.get("PUBLIC_START_DATE") or "",
        } for r in rows[:size]]
        return {"total": len(bonds), "bonds": bonds}
    except Exception as e:
        return {"error": f"可转债接口异常: {e}", "bonds": []}


# ══════════════════════════════════════════════════════════════
# 东财 datacenter 系列（2026-08-16 P2 补全，移植自 Gateway em_market_lhb.ts / financials.ts）
# ══════════════════════════════════════════════════════════════

def get_margin_trading(code: str, days: int = 30) -> list:
    """个股融资融券明细（datacenter RPTA_WEB_RZRQ_GGMX，本地 200 ✅）"""
    c = extract_code(code)
    data = _datacenter(
        "RPTA_WEB_RZRQ_GGMX", f'(SCODE="{c}")',
        page_size=max(1, min(int(days or 30), 120)),
        sort_columns="DATE", sort_types="-1",
    )
    return [{
        "date": str(r.get("DATE") or "")[:10],
        "rzye": r.get("RZYE") or 0,
        "rzmre": r.get("RZMRE") or 0,
        "rzche": r.get("RZCHE") or 0,
        "rqye": r.get("RQYE") or 0,
        "rqmcl": r.get("RQMCL") or 0,
        "rqchl": r.get("RQCHL") or 0,
        "rzrqye": r.get("RZRQYE") or 0,
    } for r in data]


def get_block_trade(code: str, page_size: int = 20) -> list:
    """个股大宗交易记录（datacenter RPT_DATA_BLOCKTRADE，本地 200 ✅）"""
    c = extract_code(code)
    data = _datacenter(
        "RPT_DATA_BLOCKTRADE", f'(SECURITY_CODE="{c}")',
        page_size=max(1, min(int(page_size or 20), 50)),
        sort_columns="TRADE_DATE", sort_types="-1",
    )
    records = []
    for r in data:
        deal_price = float(r.get("DEAL_PRICE") or 0)
        close_price = float(r.get("CLOSE_PRICE") or 0)
        premium = (deal_price / close_price - 1) * 100 if close_price else 0
        records.append({
            "date": str(r.get("TRADE_DATE") or "")[:10],
            "price": deal_price,
            "close": close_price,
            "premium_pct": round(premium, 2),
            "vol": r.get("DEAL_VOLUME") or 0,
            "amount": r.get("DEAL_AMT") or 0,
            "buyer": r.get("BUYER_NAME") or "",
            "seller": r.get("SELLER_NAME") or "",
        })
    return records


def get_holder_change(code: str, page_size: int = 10) -> list:
    """股东户数变化（datacenter RPT_HOLDERNUMLATEST，本地 200 ✅）"""
    c = extract_code(code)
    data = _datacenter(
        "RPT_HOLDERNUMLATEST", f'(SECURITY_CODE="{c}")',
        page_size=max(1, min(int(page_size or 10), 30)),
        sort_columns="END_DATE", sort_types="-1",
    )
    return [{
        "date": str(r.get("END_DATE") or "")[:10],
        "holder_num": r.get("HOLDER_NUM") or 0,
        "change_num": r.get("HOLDER_NUM_CHANGE") or 0,
        "change_ratio": r.get("HOLDER_NUM_RATIO") or 0,
        "avg_shares": r.get("AVG_FREE_SHARES") or 0,
    } for r in data]


def get_dividend_history(code: str, page_size: int = 20) -> list:
    """分红送转历史（datacenter RPT_SHAREBONUS_DET，本地 200 ✅）"""
    c = extract_code(code)
    data = _datacenter(
        "RPT_SHAREBONUS_DET", f'(SECURITY_CODE="{c}")',
        page_size=max(1, min(int(page_size or 20), 50)),
        sort_columns="EX_DIVIDEND_DATE", sort_types="-1",
    )
    return [{
        "date": str(r.get("EX_DIVIDEND_DATE") or "")[:10],
        "bonus_rmb": r.get("PRETAX_BONUS_RMB") or 0,
        "transfer_ratio": r.get("TRANSFER_RATIO") or 0,
        "bonus_ratio": r.get("BONUS_RATIO") or 0,
        "plan": r.get("ASSIGN_PROGRESS") or "",
    } for r in data]


def fetch_financials(code: str) -> dict:
    """财务报表核心数据（datacenter RPT_F10_FINANCE_MAINFINADATA，本地 200 ✅）
    营收/利润/EPS/FCF/负债/流通股本，近5期历史"""
    c = extract_code(code)
    data = _datacenter(
        "RPT_F10_FINANCE_MAINFINADATA", f'(SECURITY_CODE="{c}")',
        page_size=5, sort_columns="REPORT_DATE", sort_types="-1",
    )
    if not data:
        # 兜底：带市场后缀
        secu = f"{c}.SH" if c.startswith("6") else f"{c}.SZ"
        data = _datacenter(
            "RPT_F10_FINANCE_MAINFINADATA", f'(SECUCODE="{secu}")',
            page_size=5, sort_columns="REPORT_DATE", sort_types="-1",
        )
    if not data:
        return {"code": c, "error": f"未获取到 {c} 的财务数据"}

    latest = data[0]
    annual = next((r for r in data if "-12-" in str(r.get("REPORT_DATE") or "")), None)
    base = annual or latest
    is_annual = annual is not None

    revenue = float(base.get("OPERATE_INCOME_PK") or 0)
    net_profit = float(base.get("PARENTNETPROFIT") or 0)
    net_margin = round(net_profit / revenue * 100, 2) if revenue else 0

    result = {
        "code": c,
        "name": base.get("SECURITY_NAME_ABBR") or c,
        "report_date": str(base.get("REPORT_DATE") or "")[:10],
        "report_type": "年报" if is_annual else "季报",
        "notice_date": str(base.get("NOTICE_DATE") or "")[:10],
        "revenue": revenue,
        "operating_profit": base.get("OPERATE_PROFIT_PK") or 0,
        "net_profit": net_profit,
        "net_margin": net_margin,
        "eps": base.get("EPSJB") or 0,
        "bps": base.get("BPS") or 0,
        "operating_cashflow": base.get("NETCASH_OPERATE_PK") or 0,
        "fcff_back": base.get("FCFF_BACK") or 0,
        "fcff_forward": base.get("FCFF_FORWARD") or 0,
        "cashflow_per_share": base.get("MGJYXJJE") or 0,
        "total_liabilities": base.get("LIABILITY") or 0,
        "shares_outstanding": base.get("A_FREE_SHARE") or 0,
        "revenue_history": [], "profit_history": [], "eps_history": [], "dates": [],
    }
    for r in reversed(data):
        result["revenue_history"].append(r.get("OPERATE_INCOME_PK") or 0)
        result["profit_history"].append(r.get("PARENTNETPROFIT") or 0)
        result["eps_history"].append(r.get("EPSJB") or 0)
        result["dates"].append(str(r.get("REPORT_DATE") or "")[:7])
    return result
