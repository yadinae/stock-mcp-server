/**
 * ST Risk Detection — ported from tools/st_risk.py
 *
 * Checks: ST/*ST status, face-value delisting risk (< 1 RMB),
 * abnormal volume + price drop.
 */

import { getCache, setCache, invalidateCache, makeCacheKey, TTL_ST_RISK } from "../cache";
import type { RiskReport, RiskSignal } from "../types";

const RISK_LEVELS: Record<number, string> = {
  0: "正常", 1: "关注", 2: "警告", 3: "高风险",
};

function checkStStatus(name: string): string | null {
  const upper = name.toUpperCase();
  if (upper.includes("退市")) return "退市";
  if (upper.startsWith("*ST")) return "*ST";
  if (upper.startsWith("ST")) return "ST";
  if (upper.includes("ST")) return "ST";
  return null;
}

function checkPriceRisk(price: number | null | undefined): RiskSignal | null {
  if (price == null || price <= 0) return null;
  if (price < 1) {
    const level = price < 0.5 ? 3 : 2;
    return {
      dimension: "面值退市风险",
      level,
      level_name: RISK_LEVELS[level],
      detail: `当前股价 ${price} 元${price < 0.5 ? '，低于 0.5 元面临面值退市' : '，低于 1 元触发面值退市警戒线'}`,
      suggestion: "密切监控股价走势，低于 1 元连续 20 个交易日将触发退市",
    };
  }
  return null;
}

function checkVolumeRisk(volumeRatio: number | null | undefined, changePct: number | null | undefined): RiskSignal | null {
  if (volumeRatio != null && changePct != null) {
    if (volumeRatio > 3 && changePct < -5) {
      return {
        dimension: "放量下跌",
        level: 3,
        level_name: "高风险",
        detail: `量比 ${volumeRatio}，跌幅 ${changePct}%，放量下跌可能是主力出货`,
        suggestion: "警惕主力出货，建议减仓回避",
      };
    }
    if (volumeRatio > 2 && changePct < -3) {
      return {
        dimension: "放量下跌",
        level: 2,
        level_name: "警告",
        detail: `量比 ${volumeRatio}，跌幅 ${changePct}%，成交量异常放大`,
        suggestion: "关注是否有重大利空消息",
      };
    }
  }
  return null;
}

export function assessRisk(
  code: string,
  name: string,
  price?: number | null,
  changePct?: number | null,
  volumeRatio?: number | null,
): RiskReport {
  const signals: RiskSignal[] = [];

  // 1. ST status
  const stStatus = checkStStatus(name);
  if (stStatus) {
    signals.push({
      dimension: "ST/退市状态",
      level: 3,
      level_name: "高风险",
      detail: `股票当前状态为「${stStatus}」`,
      suggestion: `${stStatus}股票风险极高，建议回避。如需交易请确认风险揭示书已签署`,
    });
  }

  // 2. Face-value risk
  const priceSignal = checkPriceRisk(price);
  if (priceSignal) signals.push(priceSignal);

  // 3. Volume anomaly
  const volSignal = checkVolumeRisk(volumeRatio, changePct);
  if (volSignal) signals.push(volSignal);

  // 4. Default: no risk
  if (signals.length === 0) {
    signals.push({
      dimension: "综合评估",
      level: 0,
      level_name: "正常",
      detail: `${name}(${code}) 当前无明显ST/退市风险信号`,
      suggestion: "正常交易，建议定期关注公司财报和公告",
    });
  }

  const maxLevel = Math.max(...signals.map(s => s.level), 0);
  return {
    code,
    name,
    max_level: maxLevel,
    level_name: RISK_LEVELS[maxLevel] || "未知",
    is_st: name ? name.toUpperCase().includes("ST") : false,
    signals,
    signal_count: signals.length,
    source: "公开数据（简版）",
  };
}

export async function getStRisk(code: string, realtimeData: Record<string, any>): Promise<RiskReport> {
  
  const stKey = makeCacheKey("st_risk", code);
  const cached = await getCache(stKey);
  if (cached) return cached;

  const result = assessRisk(
    code,
    realtimeData.name ?? "",
    realtimeData.price,
    realtimeData.change_pct,
    realtimeData.volume_ratio,
  );

  await setCache(stKey, result, TTL_ST_RISK);
  return result;
}
