import { RealtimeQuote } from '../types';

/**
 * Tencent stock API: https://qt.gtimg.cn/q=sh600519
 * Returns a pipe-delimited text response.
 */
export async function getRealtimeQuote(code: string): Promise<RealtimeQuote> {
  const secCode = normalizeCode(code);
  const url = `https://qt.gtimg.cn/q=${secCode}`;

  const res = await fetch(url, {
    headers: { 'User-Agent': 'Mozilla/5.0' },
    cf: { cacheTtl: 15, cacheEverything: true },  // Edge cache 15s
  });

  const text = await res.text();
  return parseTencentResponse(text, code);
}

/**
 * Tencent K-line API
 * https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=sh600519,day,,,60
 */
export async function getKline(code: string, days = 60): Promise<{ code: string; records: any[] }> {
  const secCode = normalizeCode(code);
  const url = `https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=${secCode},day,,,${days},qfq`;

  const res = await fetch(url, {
    headers: { 'User-Agent': 'Mozilla/5.0' },
    cf: { cacheTtl: 120, cacheEverything: true },  // Edge cache 2min
  });

  const data: any = await res.json();

  // Parse Tencent's nested response structure
  const records: any[] = [];

  // Response is nested: data[secCode][day] or data[secCode][qfqday]
  const dataBlock = data?.data || {};
  const codeBlock = dataBlock[secCode] || {};
  const klineData = codeBlock?.day || [];
  const qfqData = codeBlock?.qfqday || [];

  // Use day data first, fall back to qfq (forward-adjusted)
  const sourceData = klineData.length > 0 ? klineData : qfqData;

  for (const item of sourceData) {
    if (Array.isArray(item) && item.length >= 6) {
      records.push({
        date: item[0],
        open: Number(item[1]),
        close: Number(item[2]),
        high: Number(item[3]),
        low: Number(item[4]),
        volume: Number(item[5]),
        amount: item[6] ? Number(item[6]) : 0,
      });
    }
  }

  return { code, records };
}

export async function getStockInfo(code: string): Promise<{ code: string; name?: string; type: string }> {
  const quote = await getRealtimeQuote(code);
  return {
    code,
    name: quote.name || '',
    type: quote.code?.startsWith('6') ? 'a' : 'a',
  };
}

// ───── Helpers ─────

function normalizeCode(code: string): string {
  code = code.toUpperCase();
  if (code.startsWith('SH') || code.startsWith('SZ')) return code.toLowerCase();
  if (code.startsWith('6') || code.startsWith('5')) return `sh${code}`;
  if (code.startsWith('0') || code.startsWith('3')) return `sz${code}`;
  return code;  // Keep as-is for non-A-stock
}

function parseTencentResponse(text: string, code: string): RealtimeQuote {
  const result: RealtimeQuote = { code };

  // Format: v_sh600519="1=name,2=code,3=price,4=change,..."
  try {
    const match = text.match(/v_[^=]+="([^"]+)"/);
    if (!match) return { code, error: 'parse failed' };

    const parts = match[1].split('~');
    if (parts.length < 40) return { code, error: `unexpected format: ${parts.length} fields` };

    result.name = parts[1];
    result.code = parts[2];
    result.price = parseFloat(parts[3]) || 0;
    result.change = parseFloat(parts[31]) || 0;
    result.change_pct = parseFloat(parts[32]) || 0;
    result.volume = parseInt(parts[6]) || 0;
    result.amount = parseFloat(parts[37]) || 0;
    result.open = parseFloat(parts[5]) || 0;
    result.high = parseFloat(parts[33]) || 0;
    result.low = parseFloat(parts[34]) || 0;
    result.pre_close = parseFloat(parts[4]) || 0;
    result.pe_ratio = parseFloat(parts[39]) || 0;
    result.turnover_rate = parseFloat(parts[38]) || 0;
    result.market_cap = parseFloat(parts[45]) || 0;
    result.amp = parseFloat(parts[43]) || 0;  // Amplitude
  } catch (err: any) {
    return { code, error: err.message };
  }

  return result;
}
