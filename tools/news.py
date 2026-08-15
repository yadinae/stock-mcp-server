"""新闻搜索模块（免费源）— 带缓存

从新浪财经聚合、百度 RSS 兜底
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone, timedelta
from typing import Any

import httpx

from core.cache import get_cache, make_cache_key, TTL_NEWS

logger = logging.getLogger("stock-mcp.news")

HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "text/html,application/xhtml+xml",
}


def _search_sina(query: str, results: list):
    """搜索新浪财经新闻"""
    try:
        url = f"https://search.sina.com.cn/stock/?q={query}&range=title&c=news&sort=time"
        resp = httpx.get(url, headers=HTTP_HEADERS, timeout=15, follow_redirects=True)

        items = re.findall(
            r'<h2[^>]*>\s*<a[^>]*href="([^"]*)"[^>]*>(.*?)</a>\s*</h2>',
            resp.text, re.DOTALL
        )
        for url_found, title_html in items[:5]:
            title = re.sub(r'<[^>]+>', '', title_html).strip()
            if title and len(title) > 5:
                results.append({
                    "title": re.sub(r'\s+', ' ', title),
                    "url": url_found if url_found.startswith("http") else f"https:{url_found}",
                    "source": "新浪财经",
                })

        if not items:
            items = re.findall(
                r'<a[^>]*href="(https?://finance\.sina\.com\.cn[^"]*)"[^>]*>(.*?)</a>',
                resp.text, re.DOTALL
            )
            for url_found, title_html in items[:5]:
                title = re.sub(r'<[^>]+>', '', title_html).strip()
                if title and len(title) > 5 and '股票' not in title[:10]:
                    results.append({
                        "title": re.sub(r'\s+', ' ', title),
                        "url": url_found,
                        "source": "新浪财经",
                    })
    except Exception as e:
        logger.debug("Sina news search failed: %s", e)


def _search_baidu_news(query: str, results: list):
    """搜索百度新闻"""
    try:
        url = f"https://news.baidu.com/s?tn=news&word={query}&pn=0&rn=10&cl=2&ct=1"
        resp = httpx.get(url, headers=HTTP_HEADERS, timeout=15, follow_redirects=True)

        items = re.findall(
            r'<h3[^>]*>.*?<a[^>]*href="([^"]*)"[^>]*>(.*?)</a>',
            resp.text, re.DOTALL
        )
        for url_found, title_html in items[:5]:
            title = re.sub(r'<[^>]+>', '', title_html).strip()
            if title and len(title) > 5:
                results.append({
                    "title": title,
                    "url": url_found if url_found.startswith("http") else f"https://news.baidu.com{url_found}",
                    "source": "百度新闻",
                })
    except Exception as e:
        logger.debug("Baidu news search failed: %s", e)


def search_news(stock_code: str, stock_name: str = "") -> dict[str, Any]:
    """搜索股票相关新闻（带缓存）

    使用新浪财经 + 百度 RSS，无需 API key。
    """
    cache = get_cache()
    key = make_cache_key("news", stock_code, stock_name or stock_code)
    cached = cache.get(key)
    if cached is not None:
        return cached

    queries = [stock_code]
    if stock_name:
        queries.append(stock_name)

    results = []
    for query in queries:
        _search_sina(query, results)
    for query in queries:
        _search_baidu_news(query, results)

    # 去重
    seen = set()
    unique = []
    for r in results:
        k = r["title"][:30]
        if k not in seen:
            seen.add(k)
            unique.append(r)

    result = {
        "stock_code": stock_code,
        "stock_name": stock_name or stock_code,
        "news": unique[:10],
        "count": len(unique[:10]),
        "time": datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S"),
    }

    cache.set(key, result, TTL_NEWS)
    return result
