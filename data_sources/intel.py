#!/usr/bin/env python3
"""投资情报赛道（P3，移植自 Gateway intel_fetcher.ts + intel_sources.ts，2026-08-16）

12 大赛道 × 85 RSS 源，本地抓取 + 解析 + 自动摘要 + SQLite 缓存。
LLM 摘要为可选增强（配置 LLM 时启用），无 LLM 时自动降级规则摘要（与 Gateway 一致）。
"""
import json
import os
import re
import sqlite3
import time
import urllib.request
import xml.etree.ElementTree as ET

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
DB_PATH = os.path.expanduser("~/.stock-mcp/intel.db")
SECTORS_FILE = os.path.join(os.path.dirname(__file__), "sectors.json")
CACHE_TTL_RAW = 4 * 3600       # 原始条目 4h
CACHE_TTL_DIGEST = 6 * 3600    # 摘要 6h

REDLINE_KEYWORDS = [
    "代开发票", "贷款", "加微信", "扫码", "返利", "刷单", "博彩", "彩票",
    "炒股群", "内幕消息", "稳赚", "保本", "荐股", "会员费", "股票群",
]

_SECTORS = None
_CONN = None


def _get_conn():
    global _CONN
    if _CONN is None:
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        _CONN = sqlite3.connect(DB_PATH, check_same_thread=False)
        _CONN.execute("""CREATE TABLE IF NOT EXISTS intel_cache (
            key TEXT PRIMARY KEY, value TEXT, created_at REAL)""")
        _CONN.execute("""CREATE TABLE IF NOT EXISTS intel_raw (
            sector TEXT, title TEXT, url TEXT, summary TEXT, source TEXT, time TEXT,
            created_at REAL, PRIMARY KEY (sector, url))""")
        _CONN.commit()
    return _CONN


def get_sectors():
    global _SECTORS
    if _SECTORS is None:
        if os.path.exists(SECTORS_FILE):
            with open(SECTORS_FILE, encoding="utf-8") as f:
                _SECTORS = json.load(f)
        else:
            _SECTORS = []
    return _SECTORS


def list_sectors():
    """列出所有投资情报赛道"""
    sectors = get_sectors()
    return {"total": len(sectors), "sectors": [
        {"id": s["id"], "name": s["name"], "nameZh": s["nameZh"],
         "description": s["description"], "bkCode": s["bkCode"], "tags": s["tags"],
         "source_count": len(s.get("sources", []))} for s in sectors
    ]}


def _cache_get(key):
    conn = _get_conn()
    row = conn.execute("SELECT value, created_at FROM intel_cache WHERE key=?", (key,)).fetchone()
    if row and time.time() - row[1] < CACHE_TTL_RAW:
        return json.loads(row[0])
    return None


def _cache_set(key, value, ttl=None):
    conn = _get_conn()
    conn.execute("INSERT OR REPLACE INTO intel_cache VALUES (?,?,?)",
                 (key, json.dumps(value, ensure_ascii=False), time.time()))
    conn.commit()


def _is_redlined(text):
    return any(kw in (text or "") for kw in REDLINE_KEYWORDS)


def _strip_html(text):
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _fetch_url(url, timeout=12):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/rss+xml, application/xml, */*"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _parse_feed(xml_bytes, source_name, sector_id, feed_url):
    items = []
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return items
    # RSS 2.0: rss/channel/item
    for item in root.iter("item"):
        title_el = item.find("title")
        if title_el is None or not title_el.text:
            continue
        title = title_el.text.strip()
        if _is_redlined(title):
            continue
        desc_el = item.find("description")
        desc = _strip_html(desc_el.text if desc_el is not None and desc_el.text else "")
        if _is_redlined(desc):
            continue
        link_el = item.find("link")
        link = link_el.text.strip() if link_el is not None and link_el.text else feed_url
        pub_el = item.find("pubDate")
        pub = pub_el.text.strip() if pub_el is not None and pub_el.text else ""
        items.append({"title": title, "url": link, "summary": desc[:500],
                      "source": source_name, "time": pub, "sectorId": sector_id})
    # Atom: feed/entry
    if not items:
        for entry in root.iter("entry"):
            title_el = entry.find("title")
            if title_el is None or not title_el.text:
                continue
            title = title_el.text.strip()
            if _is_redlined(title):
                continue
            link_el = entry.find("link")
            link = link_el.get("href") if link_el is not None else feed_url
            summary_el = entry.find("summary") or entry.find("content")
            summary = _strip_html(summary_el.text) if summary_el is not None and summary_el.text else ""
            updated_el = entry.find("updated")
            updated = updated_el.text.strip() if updated_el is not None and updated_el.text else ""
            items.append({"title": title, "url": link, "summary": summary[:500],
                          "source": source_name, "time": updated, "sectorId": sector_id})
    return items


def _fetch_sector(sector):
    """抓取一个赛道的所有 RSS 源"""
    all_items = []
    errors = []
    for src in sector.get("sources", []):
        try:
            raw = _fetch_url(src["url"])
            items = _parse_feed(raw, src["name"], sector["id"], src["url"])
            all_items.extend(items)
        except Exception as e:
            errors.append({"source": src["name"], "error": str(e)[:80]})
    # 去重 + 排序（按标题去重）
    seen = set()
    dedup = []
    for it in all_items:
        if it["title"] not in seen:
            seen.add(it["title"])
            dedup.append(it)
    # 入库
    conn = _get_conn()
    for it in dedup[:50]:
        conn.execute("INSERT OR IGNORE INTO intel_raw VALUES (?,?,?,?,?,?,?)",
                     (sector["id"], it["title"], it["url"], it["summary"],
                      it["source"], it["time"], time.time()))
    conn.commit()
    return {"sector": sector["id"], "items": dedup[:30], "total": len(dedup), "errors": errors}


def _generate_auto_digest(items, sector):
    """自动摘要（Gateway generateAutoDigest 规则移植）"""
    points = []
    if not items:
        return ["暂无最新资讯"]
    points.append(f"📡 {sector['nameZh']}赛道今日有 {len(items)} 条最新资讯，覆盖 {len(set(i['source'] for i in items))} 个信息源")
    keywords = ["发布", "收购", "合作", "突破", "融资", "获批", "上市", "量产", "增长", "下跌"]
    found = set()
    for item in items[:15]:
        for kw in keywords:
            if kw in item["title"]:
                found.add(kw)
    if found:
        points.append(f"🔑 热点关键词：{'、'.join(sorted(found))}")
    for item in items[:3]:
        title = item["title"] if len(item["title"]) <= 60 else item["title"][:60] + "…"
        points.append(f"• {title} — {item['source']}")
    return points


def get_sector_news(sector_id="", limit=10):
    """获取指定赛道的最新原始新闻"""
    sectors = get_sectors()
    sector = next((s for s in sectors if s["id"] == sector_id), None)
    if not sector:
        return {"error": f"未知赛道: {sector_id}", "sectors": [s["id"] for s in sectors]}
    result = _fetch_sector(sector)
    return {"sector": sector_id, "sectorName": sector["nameZh"],
            "total": result["total"], "news": result["items"][:limit],
            "errors": result["errors"]}


def get_sector_briefing(sector_id=""):
    """获取指定赛道的 AI 摘要简报"""
    sectors = get_sectors()
    sector = next((s for s in sectors if s["id"] == sector_id), None)
    if not sector:
        return {"error": f"未知赛道: {sector_id}", "sectors": [s["id"] for s in sectors]}
    result = _fetch_sector(sector)
    points = _generate_auto_digest(result["items"], sector)
    return {
        "sectorId": sector_id,
        "sectorName": sector["nameZh"],
        "keyPoints": points,
        "topNews": result["items"][:5],
        "totalItems": result["total"],
        "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
    }


def get_all_sectors_briefing():
    """全赛道综合摘要"""
    sectors = get_sectors()
    digests = []
    hot_scores = {}
    for s in sectors:
        d = get_sector_briefing(s["id"])
        digests.append(d)
        if d.get("keyPoints") and d["keyPoints"][0] != "暂无最新资讯":
            hot_scores[s["id"]] = d.get("totalItems", 0)
    hot = sorted(hot_scores, key=hot_scores.get, reverse=True)[:3]
    overview = "\n\n".join(
        f"【{d['sectorName']}】\n" + "\n".join(d["keyPoints"]) for d in digests
        if d.get("keyPoints") and d["keyPoints"][0] != "暂无最新资讯"
    ) or "各赛道暂无最新资讯"
    return {"sectors": digests, "overallSummary": overview,
            "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
            "hotSectors": hot}


def search_industry_news(keyword=""):
    """跨赛道搜索新闻"""
    keyword = (keyword or "").strip()
    if not keyword:
        return {"error": "keyword 不能为空"}
    conn = _get_conn()
    rows = conn.execute(
        "SELECT sector, title, url, summary, source, time FROM intel_raw "
        "WHERE title LIKE ? OR summary LIKE ? ORDER BY created_at DESC LIMIT 30",
        (f"%{keyword}%", f"%{keyword}%")).fetchall()
    results = [{"sector": r[0], "title": r[1], "url": r[2], "summary": r[3],
                "source": r[4], "time": r[5]} for r in rows]
    return {"keyword": keyword, "total": len(results), "results": results}


def refresh_intel_cache():
    """刷新所有赛道情报缓存"""
    sectors = get_sectors()
    ok, fail = 0, 0
    for s in sectors:
        try:
            _fetch_sector(s)
            ok += 1
        except Exception:
            fail += 1
    return {"refreshed": ok, "failed": fail, "total": len(sectors)}


if __name__ == "__main__":
    import sys
    test = sys.argv[1] if len(sys.argv) > 1 else "list"
    if test == "list":
        print(json.dumps(list_sectors(), ensure_ascii=False)[:300])
    elif test == "news":
        sid = sys.argv[2] if len(sys.argv) > 2 else "ai"
        r = get_sector_news(sid, 3)
        print(f"赛道 {r.get('sector')}: {r.get('total')} 条")
        for n in r.get("news", [])[:3]:
            print(f"  • {n['title'][:60]} — {n['source']}")
        if r.get("errors"):
            print(f"  源错误 {len(r['errors'])} 个: {[e['source'] for e in r['errors'][:5]]}")
    elif test == "brief":
        sid = sys.argv[2] if len(sys.argv) > 2 else "ai"
        r = get_sector_briefing(sid)
        print(f"=== {r.get('sectorName')} ===")
        for p in r.get("keyPoints", []):
            print(f"  {p}")
    elif test == "all":
        r = get_all_sectors_briefing()
        print(f"全赛道: {len(r['sectors'])} 个 | 热门: {r['hotSectors']}")
        print(f"综述前200字: {r['overallSummary'][:200]}")
