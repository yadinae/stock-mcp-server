"""TTL 内存缓存 — P0 优化核心

线程安全（threading.Lock），支持：
- 设置/获取缓存条目，带 TTL 过期
- 装饰器模式：@cached(ttl_seconds)
- 批量操作：get_or_compute
- 缓存统计：命中率
"""

from __future__ import annotations

import logging
import threading
import time
from functools import wraps
from typing import Any, Callable, Optional

logger = logging.getLogger("stock-mcp.cache")

# ── 默认 TTL 常量 ───────────────────────────────────────
TTL_REALTIME = 30       # 实时行情：30秒（盘中变化快）
TTL_KLINE = 300         # K 线：5分钟
TTL_STOCK_INFO = 300    # 股票信息：5分钟
TTL_TECHNICAL = 300     # 技术分析：5分钟（基于K线，变化慢）
TTL_NEWS = 600          # 新闻：10分钟
TTL_AI_ANALYSIS = 0     # AI 分析：不缓存（每次可能不同）


class TTLCache:
    """线程安全的 TTL 缓存"""

    def __init__(self, default_ttl: int = 60):
        self._default_ttl = default_ttl
        self._store: dict[str, tuple[float, Any]] = {}
        self._lock = threading.Lock()
        self._hits = 0
        self._misses = 0

    def get(self, key: str) -> Optional[Any]:
        """获取缓存值，过期返回 None"""
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                self._misses += 1
                return None
            expire_at, value = entry
            if time.monotonic() > expire_at:
                del self._store[key]
                self._misses += 1
                return None
            self._hits += 1
            return value

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        """设置缓存"""
        expire_at = time.monotonic() + (ttl if ttl is not None else self._default_ttl)
        with self._lock:
            self._store[key] = (expire_at, value)

    def get_or_compute(self, key: str, compute: Callable[[], Any],
                       ttl: Optional[int] = None) -> Any:
        """获取或计算并缓存"""
        cached = self.get(key)
        if cached is not None:
            return cached
        value = compute()
        self.set(key, value, ttl)
        return value

    def invalidate(self, key: str) -> None:
        """主动失效缓存"""
        with self._lock:
            self._store.pop(key, None)

    def clear(self) -> None:
        """清空全部缓存"""
        with self._lock:
            self._store.clear()
            self._hits = 0
            self._misses = 0

    @property
    def stats(self) -> dict:
        """缓存命中统计"""
        total = self._hits + self._misses
        return {
            "hits": self._hits,
            "misses": self._misses,
            "ratio": round(self._hits / total, 3) if total else 0,
            "size": len(self._store),
        }

    def __len__(self) -> int:
        return len(self._store)


# ── 全局单例 ────────────────────────────────────────────
_cache = TTLCache()


def get_cache() -> TTLCache:
    return _cache


def make_cache_key(prefix: str, *args: str) -> str:
    """生成标准化缓存键：prefix:arg1:arg2:..."""
    return f"{prefix}:" + ":".join(str(a) for a in args)
