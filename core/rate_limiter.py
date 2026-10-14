"""
Rate Limiter — 令牌桶限流器

基于滑动窗口 + 令牌桶混合模型，保护下游 API 不受突发流量冲击。

设计原则:
- 每数据源独立限流（不同 API 有不同的速率限制）
- 内存计数器 + SQLite 持久化（进程重启不丢失计数）
- 支持 tier 概念（free/pro/enterprise 不同配额）
- 与 CircuitBreaker 互补：熔断器管"健康度"，限流管"频率"

环境变量:
  STOCK_MCP_RATE_TENCENT_MAX_PER_MIN    默认 60
  STOCK_MCP_RATE_YAHOO_MAX_PER_MIN      默认 30
  STOCK_MCP_RATE_MOOTDX_MAX_PER_MIN     默认 10
  STOCK_MCP_RATE_EASTMONEY_MAX_PER_MIN  默认 30
  STOCK_MCP_RATE_DEFAULT_MAX_PER_MIN    默认 60
  STOCK_MCP_RATE_PERSISTENCE_DB         默认 ~/.stock-mcp/rate_limit.db
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import time
from typing import Any, Optional, Callable

logger = logging.getLogger("stock-mcp.rate_limiter")

# ── 默认配额 ────────────────────────────────────────────────────────────────

DEFAULT_TIERS = {
    "free":  {"max_per_min": 60,  "max_per_day": 10_000},
    "pro":   {"max_per_min": 120, "max_per_day": 50_000},
    "enterprise": {"max_per_min": 300, "max_per_day": 200_000},
}

# 昂贵工具额外限制（调用 LLM 或复杂计算的）
EXPENSIVE_TOOLS = frozenset({
    "analyze_stock_ai", "check_backtest", "analyze_stock_agent",
    "ic_memo", "dcf_valuation", "portfolio_full_report",
})


class RateLimiter:
    """
    基于滑动窗口的单数据源限流器。
    维护最近 60s 内的请求计数，超限则拒绝。
    """

    def __init__(
        self,
        source: str,
        max_per_min: int = 60,
        max_per_day: int = 10_000,
    ):
        self.source = source
        self.max_per_min = max_per_min
        self.max_per_day = max_per_day
        self._lock = threading.Lock()
        # 滑动窗口: list of timestamps
        self._requests: list[float] = []
        self._day_count: int = 0
        self._day_start: float = time.time()

    def _evict_old(self) -> None:
        """清理超过 60s 的旧请求"""
        cutoff = time.time() - 60.0
        while self._requests and self._requests[0] < cutoff:
            self._requests.pop(0)

    def _reset_day_if_needed(self) -> None:
        """每日重置计数器"""
        if time.time() - self._day_start >= 86400:
            self._day_count = 0
            self._day_start = time.time()

    def allow(self, cost: int = 1) -> tuple[bool, float]:
        """
        检查请求是否允许。
        Returns: (allowed: bool, wait_seconds: float)
        """
        with self._lock:
            self._evict_old()
            self._reset_day_if_needed()

            current_minute = len(self._requests)
            if current_minute + cost > self.max_per_min:
                # 计算需要等待的时间
                if self._requests:
                    wait = self._requests[0] + 60.0 - time.time()
                    return False, max(0.1, wait)
                return False, 1.0

            if self._day_count + cost > self.max_per_day:
                logger.warning(f"[RL] {self.source}: daily limit reached ({self._day_count}/{self.max_per_day})")
                return False, 60.0

            self._requests.extend([time.time()] * cost)
            self._day_count += cost
            return True, 0.0

    def get_stats(self) -> dict:
        with self._lock:
            self._evict_old()
            return {
                "source": self.source,
                "minute_count": len(self._requests),
                "minute_max": self.max_per_min,
                "day_count": self._day_count,
                "day_max": self.max_per_day,
                "utilization_pct": round(len(self._requests) / max(1, self.max_per_min) * 100, 1),
            }


class RateLimiterRegistry:
    """限流器注册表"""

    def __init__(self, persist_db: Optional[str] = None):
        self._limiters: dict[str, RateLimiter] = {}
        self._lock = threading.Lock()
        self._persist_db = persist_db or os.environ.get(
            "STOCK_MCP_RATE_PERSISTENCE_DB",
            os.path.expanduser("~/.stock-mcp/rate_limit.db"),
        )
        self._load_from_db()

        # 预创建常用数据源的限流器
        for source in ["tencent", "yahoo", "mootdx", "eastmoney", "sina", "tradingview", "kraken"]:
            self.get(source)

    def _load_from_db(self) -> None:
        """从 SQLite 加载计数状态"""
        try:
            conn = sqlite3.connect(self._persist_db)
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT source, minute_count, day_count FROM rate_states").fetchall()
            for row in rows:
                self._limiters[row["source"]] = RateLimiter(
                    source=row["source"],
                    max_per_min=self._default_max_for(row["source"]),
                )
                # 恢复状态
                with self._limiters[row["source"]]._lock:
                    self._limiters[row["source"]]._day_count = row["day_count"] or 0
            conn.close()
        except Exception:
            pass  # 首次运行或 DB 不存在，从空状态开始

    def _save_to_db(self) -> None:
        """持久化到 SQLite"""
        try:
            os.makedirs(os.path.dirname(self._persist_db), exist_ok=True)
            conn = sqlite3.connect(self._persist_db)
            for name, limiter in self._limiters.items():
                with limiter._lock:
                    conn.execute(
                        "INSERT OR REPLACE INTO rate_states (source, minute_count, day_count) VALUES (?, ?, ?)",
                        (name, limiter._day_count, len(limiter._requests)),
                    )
            conn.commit()
            conn.close()
        except Exception:
            pass  # 持久化失败不影响功能

    def _default_max_for(self, source: str) -> int:
        """根据环境变量获取默认限流配额"""
        prefix = f"STOCK_MCP_RATE_{source.upper()}"
        env_key = f"{prefix}_MAX_PER_MIN"
        try:
            return int(os.environ.get(env_key, "60"))
        except (ValueError, TypeError):
            return 60

    def get(self, source: str) -> RateLimiter:
        with self._lock:
            if source not in self._limiters:
                max_per_min = self._default_max_for(source)
                max_per_day = int(os.environ.get(f"STOCK_MCP_RATE_{source.upper()}_MAX_PER_DAY", "10000"))
                self._limiters[source] = RateLimiter(source=source, max_per_min=max_per_min, max_per_day=max_per_day)
            return self._limiters[source]

    def allow(self, source: str, cost: int = 1) -> tuple[bool, float]:
        return self.get(source).allow(cost)

    def get_stats(self, source: Optional[str] = None) -> list[dict]:
        if source:
            return [self.get(source).get_stats()]
        with self._lock:
            return [l.get_stats() for l in self._limiters.values()]

    def periodic_save(self) -> None:
        """定期保存状态（由外层 cron 或定时器调用）"""
        self._save_to_db()


# ── 全局实例 ────────────────────────────────────────────────────────────────

_default_rl_registry: Optional[RateLimiterRegistry] = None
_rl_registry_lock = threading.Lock()


def get_rl_registry() -> RateLimiterRegistry:
    global _default_rl_registry
    with _rl_registry_lock:
        if _default_rl_registry is None:
            _default_rl_registry = RateLimiterRegistry()
        return _default_rl_registry


def rl_allow(source: str, cost: int = 1) -> tuple[bool, float]:
    return get_rl_registry().allow(source, cost)


def rl_stats(source: Optional[str] = None) -> list[dict]:
    return get_rl_registry().get_stats(source)


def rl_periodic_save() -> None:
    get_rl_registry().periodic_save()


# ── 工具级限流装饰器 ────────────────────────────────────────────────────────

def with_rate_limit(
    tool_name: str,
    tier: str = "free",
    source: Optional[str] = None,
) -> Callable:
    """
    为 MCP 工具添加限流保护。

    用法:
        @with_rate_limit("get_realtime_quote", tier="free", source="tencent")
        async def get_realtime_quote(code: str) -> dict:
            ...
    """
    tier_config = DEFAULT_TIERS.get(tier, DEFAULT_TIERS["free"])
    rate_source = source or tool_name
    rate_per_min = tier_config["max_per_min"]

    # 昂贵工具降配额
    if tool_name in EXPENSIVE_TOOLS:
        rate_per_min = max(1, rate_per_min // 4)

    def decorator(fn):
        def wrapper(*args, **kwargs):
            allowed, wait = rl_allow(rate_source)
            if not allowed:
                raise RateLimitExceeded(
                    tool_name=tool_name,
                    source=rate_source,
                    wait_seconds=wait,
                    tier=tier,
                )
            return fn(*args, **kwargs)
        wrapper.__name__ = fn.__name__
        wrapper.__doc__ = fn.__doc__
        return wrapper
    return decorator


class RateLimitExceeded(Exception):
    """限流超出异常"""
    def __init__(self, tool_name: str, source: str, wait_seconds: float, tier: str):
        self.tool_name = tool_name
        self.source = source
        self.wait_seconds = wait_seconds
        self.tier = tier
        super().__init__(
            f"Rate limit exceeded for '{tool_name}' (source={source}, tier={tier}, "
            f"retry in {wait_seconds:.1f}s)"
        )
