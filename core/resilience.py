"""
Resilience Layer — 借鉴 tradingview-mcp (https://github.com/atilaahmettaner/tradingview-mcp) screener_provider.py

功能:
1. 带 jitter 的指数退避重试
2. TTL 缓存（60s 新鲜 + 6h 过期）
3. Socket 级超时保护
4. 失败冷却（避免连续轰炸上游）

环境变量:
  STOCK_MCP_SOCKET_TIMEOUT   默认 15s
  STOCK_MCP_RETRY_DELAYS     默认 "1.0,3.0"
  STOCK_MCP_RETRY_JITTER     默认 0.2 (±20%)
  STOCK_MCP_CACHE_TTL        默认 60s
  STOCK_MCP_STALE_TTL        默认 21600s (6h)
  STOCK_MCP_FAILURE_COOLDOWN 默认 10s
"""
from __future__ import annotations

import hashlib
import json
import os
import random
import socket
import threading
import time
from typing import Any, Callable, Optional, TypeVar

T = TypeVar("T")

# ── Socket Timeout ─────────────────────────────────────────────────────────

def _socket_timeout_s() -> float:
    try:
        return max(1.0, float(os.environ.get("STOCK_MCP_SOCKET_TIMEOUT", "15")))
    except Exception:
        return 15.0

_socket_applied = False

def ensure_socket_timeout():
    """Apply socket default timeout once per process."""
    global _socket_applied
    if _socket_applied:
        return
    t = _socket_timeout_s()
    try:
        socket.setdefaulttimeout(t)
        _socket_applied = True
    except Exception:
        pass

# Apply at import time
ensure_socket_timeout()


# ── Retry ──────────────────────────────────────────────────────────────────

def _retry_delays() -> tuple[float, ...]:
    raw = os.environ.get("STOCK_MCP_RETRY_DELAYS", "1.0,3.0")
    try:
        return tuple(float(x) for x in raw.split(",") if x.strip())
    except Exception:
        return (1.0, 3.0)


def _retry_jitter() -> float:
    try:
        return max(0.0, min(1.0, float(os.environ.get("STOCK_MCP_RETRY_JITTER", "0.2"))))
    except Exception:
        return 0.2


def _jittered(delay: float) -> float:
    j = _retry_jitter()
    if j <= 0 or delay <= 0:
        return delay
    return max(0.0, delay * (1.0 + random.uniform(-j, j)))


def retry_with_backoff(
    fn: Callable[..., T],
    *args,
    max_retries: int = 2,
    retryable_check: Optional[Callable[[Exception], bool]] = None,
    **kwargs,
) -> T:
    """
    带指数退避 + jitter 的重试包装。

    Args:
        fn: 要执行的函数
        max_retries: 最大重试次数
        retryable_check: 自定义判断异常是否可重试（默认所有异常都重试）

    Returns:
        fn 的返回值

    Raises:
        最后一次重试的异常
    """
    delays = _retry_delays()
    last_exc = None

    for attempt in range(max_retries + 1):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            last_exc = e

            # 检查是否可重试
            if retryable_check and not retryable_check(e):
                raise

            if attempt < max_retries:
                delay = _jittered(delays[min(attempt, len(delays) - 1)])
                time.sleep(delay)

    raise last_exc  # type: ignore[misc]


# ── Cache ──────────────────────────────────────────────────────────────────

def _cache_ttl_s() -> float:
    try:
        return float(os.environ.get("STOCK_MCP_CACHE_TTL", "60"))
    except Exception:
        return 60.0


def _stale_ttl_s() -> float:
    try:
        return max(0.0, float(os.environ.get("STOCK_MCP_STALE_TTL", "21600")))
    except Exception:
        return 21600.0


class TTLCache:
    """带 stale-while-error 降级的 TTL 缓存。"""

    def __init__(self):
        self._lock = threading.RLock()
        self._store: dict[str, tuple[float, Any]] = {}

    def get(self, key: str) -> Optional[Any]:
        """获取新鲜缓存。"""
        ttl = _cache_ttl_s()
        if ttl <= 0:
            return None
        with self._lock:
            entry = self._store.get(key)
            if not entry:
                return None
            ts, payload = entry
            if time.time() - ts > ttl:
                return None
            return payload

    def get_stale(self, key: str) -> Optional[tuple[float, Any]]:
        """获取过期但可用的缓存。返回 (age_seconds, payload) 或 None。"""
        stale_ttl = _stale_ttl_s()
        if stale_ttl <= 0:
            return None
        with self._lock:
            entry = self._store.get(key)
            if not entry:
                return None
            ts, payload = entry
            age = time.time() - ts
            if age > stale_ttl:
                self._store.pop(key, None)
                return None
            return (age, payload)

    def set(self, key: str, payload: Any):
        """写入缓存。"""
        with self._lock:
            self._store[key] = (time.time(), payload)

    def make_key(self, *parts) -> str:
        """从多个部分生成缓存 key。"""
        raw = json.dumps(parts, sort_keys=True, default=str)
        return hashlib.md5(raw.encode()).hexdigest()


# ── Failure Cooldown ───────────────────────────────────────────────────────

_failure_lock = threading.Lock()
_last_failure_ts: float = 0.0


def _failure_cooldown_s() -> float:
    try:
        return max(0.0, float(os.environ.get("STOCK_MCP_FAILURE_COOLDOWN", "10")))
    except Exception:
        return 10.0


def record_failure():
    global _last_failure_ts
    with _failure_lock:
        _last_failure_ts = time.time()


def wait_for_cooldown():
    """如果上次失败在冷却期内，等待。"""
    cooldown = _failure_cooldown_s()
    if cooldown <= 0:
        return
    with _failure_lock:
        elapsed = time.time() - _last_failure_ts
        if elapsed < cooldown:
            time.sleep(cooldown - elapsed)


# ── Resilient Request Helper ───────────────────────────────────────────────

# Shared cache instance
cache = TTLCache()


def resilient_request(
    fn: Callable[..., Any],
    *args,
    cache_key: Optional[str] = None,
    source: str = "",
    max_retries: int = 2,
    **kwargs,
) -> Any:
    """
    带弹性层的请求包装：
    1. 检查缓存
    2. 等待冷却
    3. 重试 + 退避
    4. 失败时返回 stale 缓存
    5. 记录失败

    Returns:
        成功返回 fn 的结果，全部失败返回 stale 缓存或 raise
    """
    # 1. 检查新鲜缓存
    if cache_key:
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

    # 2. 等待冷却
    wait_for_cooldown()

    # 3. 重试
    last_exc = None
    for attempt in range(max_retries + 1):
        try:
            result = fn(*args, **kwargs)
            # 成功 → 缓存
            if cache_key:
                cache.set(cache_key, result)
            return result
        except Exception as e:
            last_exc = e
            if attempt < max_retries:
                delays = _retry_delays()
                delay = _jittered(delays[min(attempt, len(delays) - 1)])
                time.sleep(delay)

    # 4. 全部失败 → 尝试 stale 缓存
    if cache_key:
        stale = cache.get_stale(cache_key)
        if stale:
            return stale[1]

    # 5. 记录失败并抛出
    record_failure()
    raise last_exc  # type: ignore[misc]
