/**
 * Data source health tracker — ported from core/health.py
 *
 * Records success/failure per data source (tencent, yahoo).
 * mootdx is excluded — it's a Python-only TCP fallback not available on Workers.
 */

interface SourceStats {
  name: string;
  total: number;
  success: number;
  failures: number;
  lastFailure: string;
  lastError: string;
  lastSuccess: string;
  failures1h: number;
  hourBucket: number;
}

class DataSourceHealth {
  private sources: Map<string, SourceStats> = new Map();

  private ensure(name: string): SourceStats {
    let s = this.sources.get(name);
    if (!s) {
      s = {
        name,
        total: 0,
        success: 0,
        failures: 0,
        lastFailure: "",
        lastError: "",
        lastSuccess: "",
        failures1h: 0,
        hourBucket: Math.floor(Date.now() / 3600000),
      };
      this.sources.set(name, s);
    }
    return s;
  }

  recordSuccess(source: string): void {
    const s = this.ensure(source);
    s.total++;
    s.success++;
    s.lastSuccess = new Date().toLocaleTimeString("zh-CN", { hour12: false });
  }

  recordFailure(source: string, error = ""): void {
    const s = this.ensure(source);
    s.total++;
    s.failures++;
    s.lastFailure = new Date().toLocaleTimeString("zh-CN", { hour12: false });
    s.lastError = error.slice(0, 100);

    const currentHour = Math.floor(Date.now() / 3600000);
    if (currentHour === s.hourBucket) {
      s.failures1h++;
    } else {
      s.hourBucket = currentHour;
      s.failures1h = 1;
    }
  }

  getReport(): Record<string, any>[] {
    const now = new Date().toLocaleTimeString("zh-CN", { hour12: false });
    const report: Record<string, any>[] = [];
    for (const s of this.sources.values()) {
      const successRate = s.total > 0
        ? Math.round((s.success / s.total) * 1000) / 10
        : 100.0;
      let status = "healthy";
      if (s.total > 0 && successRate < 80) status = "degraded";
      if (s.failures1h >= 5) status = "unstable";
      if (s.total > 0 && successRate < 50) status = "failing";

      report.push({
        name: s.name,
        status,
        total_requests: s.total,
        success: s.success,
        failures: s.failures,
        success_rate: successRate,
        last_success: s.lastSuccess,
        last_failure: s.lastFailure,
        last_error: s.lastError,
        failures_last_hour: s.failures1h,
        checked_at: now,
      });
    }
    return report;
  }

  getSourceStats(name: string): Record<string, any> {
    const s = this.ensure(name);
    const successRate = s.total > 0
      ? Math.round((s.success / s.total) * 1000) / 10
      : 100.0;
    return {
      name: s.name,
      total_requests: s.total,
      success: s.success,
      failures: s.failures,
      success_rate: successRate,
      last_error: s.lastError,
      failures_last_hour: s.failures1h,
    };
  }
}

const _health = new DataSourceHealth();
export function getHealthTracker(): DataSourceHealth {
  return _health;
}
