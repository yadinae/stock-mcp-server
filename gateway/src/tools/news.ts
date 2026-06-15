/**
 * News Search — ported from tools/news.py
 *
 * Free sources: Sina Finance + Baidu News HTML scraping.
 * No API key required.
 */

import { getCache, makeCacheKey, TTL_NEWS } from "../cache";
import type { NewsResult, NewsItem } from "../types";

const HTTP_HEADERS = {
  "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
  Accept: "text/html,application/xhtml+xml",
};

async function searchSina(query: string): Promise<NewsItem[]> {
  try {
    const url = `https://search.sina.com.cn/stock/?q=${encodeURIComponent(query)}&range=title&c=news&sort=time`;
    const resp = await fetch(url, { headers: HTTP_HEADERS });
    const text = await resp.text();

    const items: NewsItem[] = [];
    // Match <h2>...<a href="...">title</a>...</h2>
    const h2Regex = /<h2[^>]*>\s*<a[^>]*href="([^"]*)"[^>]*>(.*?)<\/a>\s*<\/h2>/gi;
    let m: RegExpExecArray | null;
    while ((m = h2Regex.exec(text)) !== null) {
      const urlFound = m[1].startsWith("http") ? m[1] : `https:${m[1]}`;
      const title = m[2].replace(/<[^>]+>/g, "").trim();
      if (title && title.length > 5) {
        items.push({ title: title.replace(/\s+/g, " "), url: urlFound, source: "新浪财经" });
      }
    }

    if (items.length === 0) {
      // Fallback: match <a href="https://finance.sina.com.cn/...">title</a>
      const aRegex = /<a[^>]*href="(https?:\/\/finance\.sina\.com\.cn[^"]*)"[^>]*>(.*?)<\/a>/gi;
      while ((m = aRegex.exec(text)) !== null) {
        const title = m[2].replace(/<[^>]+>/g, "").trim();
        if (title && title.length > 5 && !title.slice(0, 10).includes("股票")) {
          items.push({ title: title.replace(/\s+/g, " "), url: m[1], source: "新浪财经" });
        }
      }
    }

    return items;
  } catch {
    return [];
  }
}

async function searchBaidu(query: string): Promise<NewsItem[]> {
  try {
    const url = `https://news.baidu.com/s?tn=news&word=${encodeURIComponent(query)}&pn=0&rn=10&cl=2&ct=1`;
    const resp = await fetch(url, { headers: HTTP_HEADERS });
    const text = await resp.text();

    const items: NewsItem[] = [];
    const h3Regex = /<h3[^>]*>.*?<a[^>]*href="([^"]*)"[^>]*>(.*?)<\/a>/gi;
    let m: RegExpExecArray | null;
    while ((m = h3Regex.exec(text)) !== null) {
      const urlFound = m[1].startsWith("http") ? m[1] : `https://news.baidu.com${m[1]}`;
      const title = m[2].replace(/<[^>]+>/g, "").trim();
      if (title && title.length > 5) {
        items.push({ title: title.replace(/\s+/g, " "), url: urlFound, source: "百度新闻" });
      }
    }
    return items;
  } catch {
    return [];
  }
}

export async function searchNews(stockCode: string, stockName = ""): Promise<NewsResult> {
  const cache = getCache();
  const key = makeCacheKey("news", stockCode, stockName || stockCode);
  const cached = cache.get(key);
  if (cached) return cached;

  const queries = [stockCode];
  if (stockName) queries.push(stockName);

  const allItems: NewsItem[] = [];
  for (const q of queries) {
    allItems.push(...await searchSina(q));
  }
  for (const q of queries) {
    allItems.push(...await searchBaidu(q));
  }

  // Dedup
  const seen = new Set<string>();
  const unique: NewsItem[] = [];
  for (const item of allItems) {
    const key = item.title.slice(0, 30);
    if (!seen.has(key)) {
      seen.add(key);
      unique.push(item);
    }
  }

  const cnTime = new Date().toLocaleString("zh-CN", {
    timeZone: "Asia/Shanghai",
    hour12: false,
  });

  const result: NewsResult = {
    stock_code: stockCode,
    stock_name: stockName || stockCode,
    news: unique.slice(0, 10),
    count: Math.min(unique.length, 10),
    time: cnTime,
  };

  cache.set(key, result, TTL_NEWS);
  return result;
}
