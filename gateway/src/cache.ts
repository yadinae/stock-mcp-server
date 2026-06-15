/**
 * In-memory TTL cache — ported from core/cache.py
 *
 * Worker isolates are short-lived but within a single request's lifetime
 * we cache repeatedly fetched data (K-line, technical analysis, etc.).
 * For cross-request caching, CF edge cache is used on fetch() calls.
 */

// ── TTL Constants ──
export const TTL_REALTIME = 30;       // 实时行情：30秒
export const TTL_KLINE = 300;         // K线：5分钟
export const TTL_STOCK_INFO = 3600;    // 股票信息：1小时
export const TTL_TECHNICAL = 300;     // 技术分析：5分钟
export const TTL_NEWS = 600;          // 新闻：10分钟
export const TTL_AI_ANALYSIS = 0;     // AI分析：不缓存
export const TTL_ST_RISK = 600;       // ST风险：10分钟
export const TTL_HOURLY = 3600;       // 通用小时级：1小时

class TTLCache {
  private store: Map<string, { expireAt: number; value: any }> = new Map();
  private hits = 0;
  private misses = 0;

  get(key: string): any | null {
    const entry = this.store.get(key);
    if (!entry) {
      this.misses++;
      return null;
    }
    if (Date.now() > entry.expireAt) {
      this.store.delete(key);
      this.misses++;
      return null;
    }
    this.hits++;
    return entry.value;
  }

  set(key: string, value: any, ttl?: number): void {
    const expireAt = Date.now() + (ttl ?? 60) * 1000;
    this.store.set(key, { expireAt, value });
  }

  invalidate(key: string): void {
    this.store.delete(key);
  }

  clear(): void {
    this.store.clear();
    this.hits = 0;
    this.misses = 0;
  }

  get stats() {
    const total = this.hits + this.misses;
    return {
      hits: this.hits,
      misses: this.misses,
      ratio: total > 0 ? Math.round((this.hits / total) * 1000) / 1000 : 0,
      size: this.store.size,
    };
  }
}

// Global singleton
const _cache = new TTLCache();
export function getCache(): TTLCache {
  return _cache;
}

export function makeCacheKey(prefix: string, ...args: string[]): string {
  return [prefix, ...args].join(":");
}
