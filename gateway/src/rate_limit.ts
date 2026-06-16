/**
 * rate_limit.ts — Per-API-Key 请求频率限制（P0 生产加固）
 * 
 * 使用 Workers KV 存储计数器：
 * - 分钟级限制：ratelimit:{key}:min:{YYYYMMDDHHMM}  (60s TTL)
 * - 日级限制：  ratelimit:{key}:day:{YYYYMMDD}       (86400s TTL)
 * 
 * KV 是最终一致性，对于频率限制做 P0 防护够用。
 * 后续可升级为 D1 事务计数器实现精确计数。
 */

export interface RateLimitConfig {
  /** 每分钟最大请求数（默认 60） */
  maxPerMinute: number;
  /** 每日最大请求数（默认 5000） */
  maxPerDay: number;
  /** 高成本工具每分钟限制（如 AI 分析，默认 20） */
  maxPerMinuteExpensive: number;
  /** 高成本工具每日限制（默认 500） */
  maxPerDayExpensive: number;
}

export interface RateLimitResult {
  allowed: boolean;
  remainingMinute: number;
  remainingDay: number;
  resetMinute: number;  // seconds until minute window resets
  error?: string;
}

const DEFAULT_CONFIG: RateLimitConfig = {
  maxPerMinute: 60,
  maxPerDay: 5000,
  maxPerMinuteExpensive: 20,
  maxPerDayExpensive: 500,
};

const EXPENSIVE_TOOLS = new Set([
  'analyze_stock_ai',
  'check_backtest',
]);

// ───── Helper: pad number to 2 digits ─────
function pad(n: number): string {
  return n < 10 ? '0' + n : '' + n;
}

// ───── Helper: get minute window key ─────
function getMinuteWindow(date: Date): string {
  return `${date.getFullYear()}${pad(date.getMonth() + 1)}${pad(date.getDate())}${pad(date.getHours())}${pad(date.getMinutes())}`;
}

// ───── Helper: get day window key ─────
function getDayWindow(date: Date): string {
  return `${date.getFullYear()}${pad(date.getMonth() + 1)}${pad(date.getDate())}`;
}

/**
 * Check and increment rate limit for a given API key.
 * Returns whether the request is allowed and remaining quota.
 */
export async function checkRateLimit(
  kv: KVNamespace,
  apiKey: string,
  toolName: string,
  config: RateLimitConfig = DEFAULT_CONFIG,
): Promise<RateLimitResult> {
  const now = new Date();
  const minWin = getMinuteWindow(now);
  const dayWin = getDayWindow(now);
  const isExpensive = EXPENSIVE_TOOLS.has(toolName);

  const maxMin = isExpensive ? config.maxPerMinuteExpensive : config.maxPerMinute;
  const maxDay = isExpensive ? config.maxPerDayExpensive : config.maxPerDay;

  const minKey = `ratelimit:${apiKey}:min:${minWin}`;
  const dayKey = `ratelimit:${apiKey}:day:${dayWin}`;

  // Seconds until next minute boundary (for reset info)
  const resetMinute = 60 - now.getSeconds();

  try {
    // Read current counters
    const [minRaw, dayRaw] = await Promise.all([
      kv.get(minKey),
      kv.get(dayKey),
    ]);

    const minCount = minRaw ? parseInt(minRaw, 10) : 0;
    const dayCount = dayRaw ? parseInt(dayRaw, 10) : 0;

    // Check limits
    if (minCount >= maxMin) {
      return {
        allowed: false,
        remainingMinute: 0,
        remainingDay: maxDay - dayCount,
        resetMinute,
        error: `Rate limit exceeded: ${toolName} allows ${maxMin} req/min. Try again in ${resetMinute}s.`,
      };
    }
    if (dayCount >= maxDay) {
      return {
        allowed: false,
        remainingMinute: maxMin - minCount,
        remainingDay: 0,
        resetMinute,
        error: `Daily rate limit exceeded: ${toolName} allows ${maxDay} req/day. Resets at midnight UTC.`,
      };
    }

    // Increment counters
    // Use TTL to auto-clean: minute counter = 120s, day counter = 86400s
    await Promise.all([
      kv.put(minKey, String(minCount + 1), { expirationTtl: 120 }),
      kv.put(dayKey, String(dayCount + 1), { expirationTtl: 86400 }),
    ]);

    return {
      allowed: true,
      remainingMinute: maxMin - minCount - 1,
      remainingDay: maxDay - dayCount - 1,
      resetMinute,
    };
  } catch (e) {
    // KV error — allow through (fail open) but log
    console.error(`[RateLimit] KV error for key ${apiKey}:`, e);
    return {
      allowed: true,
      remainingMinute: -1,
      remainingDay: -1,
      resetMinute,
    };
  }
}

/**
 * Get current usage stats for a given API key.
 */
export async function getUsageStats(
  kv: KVNamespace,
  apiKey: string,
): Promise<{ currentMinute: number; currentDay: number }> {
  const now = new Date();
  const minWin = getMinuteWindow(now);
  const dayWin = getDayWindow(now);

  const [minRaw, dayRaw] = await Promise.all([
    kv.get(`ratelimit:${apiKey}:min:${minWin}`),
    kv.get(`ratelimit:${apiKey}:day:${dayWin}`),
  ]);

  return {
    currentMinute: minRaw ? parseInt(minRaw, 10) : 0,
    currentDay: dayRaw ? parseInt(dayRaw, 10) : 0,
  };
}
