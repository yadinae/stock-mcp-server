"""
数据源健康状态追踪

记录每个数据源的请求成功/失败次数，用于：
1. 透明展示当前各数据源可用性
2. 长期趋势分析（哪些源不稳定）
3. 调试辅助（快速定位问题源）

线程安全：使用 threading.Lock 保护计数器。
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

logger = logging.getLogger("stock-mcp.health")

# ── 健康记录 ──────────────────────────────────────────────
# 结构：{
#     "tencent": {
#         "total": 100, "success": 95, "failures": 5,
#         "last_failure": "13:30:45", "last_error": "Timeout",
#         "failures_1h": 2,
#     },
#     "mootdx": {...},
#     "yahoo": {...},
# }


class DataSourceHealth:
    """数据源健康状态追踪器"""

    def __init__(self):
        self._lock = threading.Lock()
        self._sources: dict[str, dict[str, Any]] = {}

    def _ensure_source(self, name: str) -> dict[str, Any]:
        if name not in self._sources:
            self._sources[name] = {
                "name": name,
                "total": 0,
                "success": 0,
                "failures": 0,
                "last_failure": "",
                "last_error": "",
                "last_success": "",
                "failures_1h": 0,
                "_hour_bucket": int(time.time()) // 3600,
            }
        return self._sources[name]

    def record_success(self, source: str) -> None:
        """记录一次成功请求"""
        with self._lock:
            s = self._ensure_source(source)
            s["total"] += 1
            s["success"] += 1
            s["last_success"] = time.strftime("%H:%M:%S")

    def record_failure(self, source: str, error: str = "") -> None:
        """记录一次失败请求"""
        with self._lock:
            s = self._ensure_source(source)
            s["total"] += 1
            s["failures"] += 1
            s["last_failure"] = time.strftime("%H:%M:%S")
            s["last_error"] = str(error)[:100]

            # 1小时滚动计数
            current_hour = int(time.time()) // 3600
            if current_hour == s["_hour_bucket"]:
                s["failures_1h"] += 1
            else:
                s["_hour_bucket"] = current_hour
                s["failures_1h"] = 1

    def get_report(self) -> list[dict[str, Any]]:
        """获取所有数据源的健康报告"""
        with self._lock:
            now = time.strftime("%H:%M:%S")
            report = []
            for name, s in sorted(self._sources.items()):
                success_rate = (
                    round(s["success"] / s["total"] * 100, 1)
                    if s["total"] > 0
                    else 100.0
                )
                status = "healthy"
                if s["total"] > 0 and success_rate < 80:
                    status = "degraded"
                if s["failures_1h"] >= 5:
                    status = "unstable"
                if s["total"] > 0 and success_rate < 50:
                    status = "failing"

                report.append({
                    "name": name,
                    "status": status,
                    "total_requests": s["total"],
                    "success": s["success"],
                    "failures": s["failures"],
                    "success_rate": success_rate,
                    "last_success": s["last_success"],
                    "last_failure": s["last_failure"],
                    "last_error": s["last_error"],
                    "failures_last_hour": s["failures_1h"],
                    "checked_at": now,
                })
            return report

    def get_source_stats(self, name: str) -> dict[str, Any]:
        """获取单个数据源的统计"""
        with self._lock:
            s = self._ensure_source(name)
            total = s["total"]
            success_rate = round(s["success"] / total * 100, 1) if total else 100.0
            return {
                "name": name,
                "total_requests": total,
                "success": s["success"],
                "failures": s["failures"],
                "success_rate": success_rate,
                "last_error": s["last_error"],
                "failures_last_hour": s["failures_1h"],
            }


# ── 全局单例 ────────────────────────────────────────────
_health = DataSourceHealth()


def get_health_tracker() -> DataSourceHealth:
    return _health
