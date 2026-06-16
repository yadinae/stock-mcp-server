/**
 * audit_log.ts — 请求日志/审计追踪（P1 生产加固）
 * 
 * 每次 tools/call 记录一条日志到 KV：
 *   audit:{YYYYMMDD}:{timestamp_ms}:{random4}
 *   7 天 TTL 自动清理
 * 
 * 查询端点：GET /logs?limit=50&prefix=audit:20260616
 */

export interface AuditEntry {
  timestamp: string;          // ISO 8601
  apiKey: string;             // API key prefix (first 8 chars)
  tool: string;               // called tool name
  args: Record<string, any>;  // arguments (sanitized)
  status: 'ok' | 'error';
  durationMs: number;
  errorMessage?: string;
}

export interface AuditQuery {
  date?: string;     // YYYYMMDD, default today
  limit?: number;    // max entries (default 50, max 200)
  cursor?: string;   // pagination cursor
}

export interface AuditResult {
  entries: AuditEntry[];
  cursor?: string;   // next page cursor (null = no more)
  count: number;
}

/**
 * Record an audit log entry to KV.
 */
export async function recordAudit(
  kv: KVNamespace,
  entry: Omit<AuditEntry, 'timestamp'> & { timestamp?: string },
): Promise<void> {
  const ts = entry.timestamp || new Date().toISOString();
  const dateKey = ts.slice(0, 10).replace(/-/g, ''); // YYYYMMDD
  const ms = Date.now();
  const rand = Math.floor(Math.random() * 10000).toString().padStart(4, '0');
  const kvKey = `audit:${dateKey}:${ms}:${rand}`;
  
  const logEntry: AuditEntry = {
    ...entry,
    timestamp: ts,
    apiKey: entry.apiKey.slice(0, 8) + '...',
  };

  // TTL: 7 days (604800 seconds)
  await kv.put(kvKey, JSON.stringify(logEntry), { expirationTtl: 604800 });
}

/**
 * Query audit logs by date prefix.
 */
export async function queryAuditLogs(
  kv: KVNamespace,
  query: AuditQuery = {},
): Promise<AuditResult> {
  const date = query.date || new Date().toISOString().slice(0, 10).replace(/-/g, '');
  const limit = Math.min(query.limit || 50, 200);
  
  const result = await kv.list({
    prefix: `audit:${date}:`,
    limit: limit + 1,  // +1 to check if there's a next page
    cursor: query.cursor,
  });

  const entries: AuditEntry[] = [];
  for (const key of result.keys) {
    if (entries.length >= limit) break;
    const val = await kv.get(key.name);
    if (val) {
      try {
        entries.push(JSON.parse(val));
      } catch {
        // skip corrupted entries
      }
    }
  }

  return {
    entries,
    cursor: (result as any).cursor || undefined,
    count: entries.length,
  };
}
