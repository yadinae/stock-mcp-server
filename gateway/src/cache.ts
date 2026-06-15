/**
 * Dual-layer cache: in-memory (L1) + Workers KV (L2)
 *
 * L1: in-memory Map — fast, intra-request dedup
 * L2: Workers KV — persistent across requests and Worker restarts
 *
 * KV values are stored as: { value: any, expireAt: number }
 * with a keyspace prefix "cache:".
 *
 * The KV binding must be provided at the start of each request
 * via initCache(env). Falls back to pure in-memory if no KV.
 */

// ── TTL Constants (in seconds) ──
export const TTL_REALTIME = 30;       // 实时行情：30秒
export const TTL_KLINE = 300;         // K线：5分钟
export const TTL_STOCK_INFO = 3600;   // 股票信息：1小时
export const TTL_TECHNICAL = 300;     // 技术分析：5分钟
export const TTL_NEWS = 600;          // 新闻：10分钟
export const TTL_AI_ANALYSIS = 0;     // AI分析：不缓存
export const TTL_ST_RISK = 600;       // ST风险：10分钟
export const TTL_HOURLY = 3600;       // 通用小时级：1小时

const KV_PREFIX = "cache:";

// ── L1: In-Memory Store ──

interface L1Entry {
  expireAt: number;
  value: any;
}

class L1Store {
  private store = new Map<string, L1Entry>();
  hits = 0;
  misses = 0;

  get(key: string): any | null {
    const entry = this.store.get(key);
    if (!entry) { this.misses++; return null; }
    if (Date.now() > entry.expireAt) {
      this.store.delete(key);
      this.misses++;
      return null;
    }
    this.hits++;
    return entry.value;
  }

  set(key: string, value: any, ttlSec: number): void {
    this.store.set(key, { expireAt: Date.now() + ttlSec * 1000, value });
  }

  invalidate(key: string): void { this.store.delete(key); }
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
      ratio: total > 0 ? +(this.hits / total).toFixed(3) : 0,
      size: this.store.size,
      l1: true,
    };
  }
}

// ── Singleton ──

const l1 = new L1Store();
let kvBinding: KVNamespace | null = null;

/**
 * Initialize cache with the KV binding (call at start of each request).
 * If env has GATEWAY_KV, KV caching is enabled; otherwise pure memory.
 */
export function initCache(env?: { GATEWAY_KV?: KVNamespace }): void {
  kvBinding = env?.GATEWAY_KV ?? null;
}

/**
 * Get a cached value. Checks L1 (memory) first, then L2 (KV).
 */
export async function getCache(key: string): Promise<any | null> {
  // L1: memory
  const memVal = l1.get(key);
  if (memVal !== null) return memVal;

  // L2: KV
  if (kvBinding) {
    try {
      const raw = await kvBinding.get(KV_PREFIX + key);
      if (raw) {
        const entry = JSON.parse(raw);
        if (entry.expireAt > Date.now()) {
          // Promote to L1 (use shorter TTL for L1 since KV handles persistence)
          l1.set(key, entry.value, 60);
          return entry.value;
        }
        // Expired — delete from KV
        await kvBinding.delete(KV_PREFIX + key).catch(() => {});
      }
    } catch { /* KV read failed, fall back to L1 miss */ }
  }

  return null;
}

/**
 * Set a cached value with TTL in seconds.
 * Writes to both L1 (memory) and L2 (KV, fire-and-forget).
 */
export async function setCache(
  key: string,
  value: any,
  ttlSec: number = 60,
): Promise<void> {
  // L1: memory
  l1.set(key, value, ttlSec);

  // L2: KV (fire-and-forget — don't block the request)
  if (kvBinding) {
    const payload = JSON.stringify({ value, expireAt: Date.now() + ttlSec * 1000 });
    kvBinding.put(KV_PREFIX + key, payload, {
      expirationTtl: ttlSec,
    }).catch(() => {}); // Fire and forget
  }
}

/**
 * Invalidate a cache key.
 */
export async function invalidateCache(key: string): Promise<void> {
  l1.invalidate(key);
  if (kvBinding) {
    await kvBinding.delete(KV_PREFIX + key).catch(() => {});
  }
}

/**
 * Clear all cache (L1 only — KV clear is not supported per-key without listing).
 */
export function clearCache(): void {
  l1.clear();
}

/**
 * Cache stats.
 */
export function getCacheStats(): { hits: number; misses: number; ratio: number; size: number; l1: boolean } {
  return l1.stats;
}

/**
 * Build a cache key from prefix and args.
 */
export function makeCacheKey(prefix: string, ...args: string[]): string {
  return [prefix, ...args].join(":");
}
