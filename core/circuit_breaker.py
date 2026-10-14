"""
Circuit Breaker — 熔断器

借鉴 stock-mcp-gateway/src/circuit_breaker.ts 的 Python 实现。
状态机: CLOSED → OPEN → HALF_OPEN → CLOSED

用于保护下游数据源（tencent/yahoo/mootdx 等），
当连续失败超过阈值时自动熔断，避免级联超时和资源耗尽。

环境变量:
  STOCK_MCP_CB_TENCENT_FAILURE_THRESHOLD   默认 5
  STOCK_MCP_CB_TENCENT_COOLDOWN            默认 30 (秒)
  STOCK_MCP_CB_YAHOO_FAILURE_THRESHOLD     默认 3
  STOCK_MCP_CB_YAHOO_COOLDOWN              默认 60
  STOCK_MCP_CB_MOOTDX_FAILURE_THRESHOLD    默认 5
  STOCK_MCP_CB_MOOTDX_COOLDOWN             默认 30
  STOCK_MCP_CB_DEFAULT_FAILURE_THRESHOLD   默认 5
  STOCK_MCP_CB_DEFAULT_COOLDOWN            默认 30
"""
from __future__ import annotations

import enum
import logging
import threading
import time
from typing import Any, Callable, Optional, TypeVar, Protocol

logger = logging.getLogger("stock-mcp.circuit_breaker")

T = TypeVar("T")


class CBState(enum.Enum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


class CircuitBreakerError(Exception):
    """熔断器处于 OPEN 状态，请求被拦截"""
    def __init__(self, name: str, state: CBState, last_failure_at: float):
        self.name = name
        self.state = state
        self.last_failure_at = last_failure_at
        super().__init__(f"Circuit breaker '{name}' is {state.value} (last failure {last_failure_at:.1f}s ago)")


class CircuitBreakerConfig:
    """熔断器配置"""
    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        cooldown_sec: float = 30.0,
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.cooldown_sec = cooldown_sec


class CircuitBreaker:
    """单个熔断器实例"""

    def __init__(self, config: CircuitBreakerConfig):
        self.config = config
        self._lock = threading.Lock()
        self._state = CBState.CLOSED
        self._failure_count = 0
        self._last_failure_at: float = 0.0
        self._success_count_in_half_open = 0
        self._half_open_success_target = 3  # HALF_OPEN 需连续成功 3 次才能关闭

    @property
    def state(self) -> CBState:
        with self._lock:
            return self._state

    @property
    def failure_count(self) -> int:
        with self._lock:
            return self._failure_count

    def allow_request(self) -> bool:
        """检查是否允许请求通过"""
        with self._lock:
            if self._state == CBState.CLOSED:
                return True
            if self._state == CBState.OPEN:
                elapsed = time.time() - self._last_failure_at
                if elapsed >= self.config.cooldown_sec:
                    self._state = CBState.HALF_OPEN
                    logger.info(f"[CB] {self.config.name}: OPEN → HALF_OPEN (cooldown {self.config.cooldown_sec}s elapsed)")
                    return True
                return False
            # HALF_OPEN: allow a limited test request
            if self._state == CBState.HALF_OPEN:
                return True
            return False

    def record_success(self) -> None:
        """记录成功 — CLOSED 重置计数，HALF_OPEN 计数达标后关闭"""
        with self._lock:
            if self._state == CBState.HALF_OPEN:
                self._success_count_in_half_open += 1
                if self._success_count_in_half_open >= self._half_open_success_target:
                    self._state = CBState.CLOSED
                    self._failure_count = 0
                    self._success_count_in_half_open = 0
                    logger.info(f"[CB] {self.config.name}: HALF_OPEN → CLOSED (recovered)")
            elif self._state == CBState.CLOSED:
                self._failure_count = 0

    def record_failure(self) -> None:
        """记录失败 — CLOSED 累加计数超限后打开，HALF_OPEN 失败立即重新打开"""
        with self._lock:
            if self._state == CBState.HALF_OPEN:
                # 任何失败都回到 OPEN
                self._state = CBState.OPEN
                self._failure_count = self.config.failure_threshold
                self._success_count_in_half_open = 0
                self._last_failure_at = time.time()
                logger.warning(f"[CB] {self.config.name}: HALF_OPEN → OPEN (failure during recovery)")
            else:
                self._failure_count += 1
                self._last_failure_at = time.time()
                if self._failure_count >= self.config.failure_threshold:
                    self._state = CBState.OPEN
                    logger.warning(
                        f"[CB] {self.config.name}: CLOSED → OPEN "
                        f"(failures={self._failure_count} >= threshold={self.config.failure_threshold})"
                    )

    def get_report(self) -> dict[str, Any]:
        """获取熔断器状态报告"""
        with self._lock:
            return {
                "name": self.config.name,
                "state": self._state.value,
                "failure_count": self._failure_count,
                "failure_threshold": self.config.failure_threshold,
                "cooldown_sec": self.config.cooldown_sec,
                "last_failure_at": self._last_failure_at,
                "time_since_last_failure_s": round(time.time() - self._last_failure_at, 1),
            }


def _cb_config_for(name: str, default_threshold: int = 5, default_cooldown: float = 30.0) -> CircuitBreakerConfig:
    """从环境变量读取指定数据源的熔断器配置"""
    prefix = f"STOCK_MCP_CB_{name.upper()}"
    try:
        threshold = int(os.environ.get(f"{prefix}_FAILURE_THRESHOLD", str(default_threshold)))
        cooldown = float(os.environ.get(f"{prefix}_COOLDOWN", str(default_cooldown)))
    except (ValueError, TypeError):
        threshold = default_threshold
        cooldown = default_cooldown
    return CircuitBreakerConfig(name=name, failure_threshold=max(1, threshold), cooldown_sec=max(1.0, cooldown))


import os  # 放在顶层但确保只在需要时用


# ── Registry ────────────────────────────────────────────────────────────────

class CircuitBreakerRegistry:
    """熔断器注册表，管理多个数据源的熔断器"""

    def __init__(self):
        self._breakers: dict[str, CircuitBreaker] = {}
        self._lock = threading.Lock()

        # 预创建常用数据源的熔断器
        self._default_threshold = int(os.environ.get("STOCK_MCP_CB_DEFAULT_FAILURE_THRESHOLD", "5"))
        self._default_cooldown = float(os.environ.get("STOCK_MCP_CB_DEFAULT_COOLDOWN", "30"))
        for source_name in ["tencent", "yahoo", "mootdx", "eastmoney", "sina"]:
            self.get(source_name)

    def get(self, name: str) -> CircuitBreaker:
        """获取或创建熔断器"""
        with self._lock:
            if name not in self._breakers:
                config = _cb_config_for(name, self._default_threshold, self._default_cooldown)
                self._breakers[name] = CircuitBreaker(config)
            return self._breakers[name]

    def allow(self, name: str) -> bool:
        """检查是否允许请求通过"""
        return self.get(name).allow_request()

    def record_success(self, name: str) -> None:
        """记录成功"""
        self.get(name).record_success()

    def record_failure(self, name: str) -> None:
        """记录失败"""
        self.get(name).record_failure()

    def get_report(self, name: Optional[str] = None) -> list[dict[str, Any]]:
        """获取所有或单个熔断器报告"""
        if name:
            return [self.get(name).get_report()]
        with self._lock:
            return [b.get_report() for b in self._breakers.values()]

    def reset(self, name: str) -> None:
        """手动重置熔断器（管理员操作）"""
        with self._lock:
            if name in self._breakers:
                config = self._breakers[name].config
                self._breakers[name] = CircuitBreaker(config)
                logger.info(f"[CB] {name}: manually reset")


# ── 全局实例 ────────────────────────────────────────────────────────────────

_default_registry: Optional[CircuitBreakerRegistry] = None
_registry_lock = threading.Lock()


def get_registry() -> CircuitBreakerRegistry:
    """获取全局熔断器注册表（单例）"""
    global _default_registry
    with _registry_lock:
        if _default_registry is None:
            _default_registry = CircuitBreakerRegistry()
        return _default_registry


def cb_allow(name: str) -> bool:
    """便捷函数：检查熔断器是否允许请求"""
    return get_registry().allow(name)


def cb_record_success(name: str) -> None:
    """便捷函数：记录成功"""
    get_registry().record_success(name)


def cb_record_failure(name: str) -> None:
    """便捷函数：记录失败"""
    get_registry().record_failure(name)


def cb_report(name: Optional[str] = None) -> list[dict[str, Any]]:
    """便捷函数：获取熔断器报告"""
    return get_registry().get_report(name)


def cb_reset(name: str) -> None:
    """便捷函数：手动重置熔断器"""
    get_registry().reset(name)


# ── 装饰器 ──────────────────────────────────────────────────────────────────

def with_circuit_breaker(
    source_name: str,
    fallback: Optional[Callable[[], T]] = None,
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """
    装饰器：为函数添加熔断器保护。

    用法:
        @with_circuit_breaker("tencent")
        async def fetch_quotes(codes: list[str]) -> dict:
            ...  # 熔断时自动返回 fallback 或抛出 CircuitBreakerError
    """
    def decorator(fn: Callable[..., T]) -> Callable[..., T]:
        def wrapper(*args, **kwargs) -> T:
            if not cb_allow(source_name):
                if fallback:
                    return fallback()
                raise CircuitBreakerError(
                    source_name,
                    get_registry().get(source_name).state,
                    get_registry().get(source_name)._last_failure_at,
                )
            try:
                result = fn(*args, **kwargs)
                cb_record_success(source_name)
                return result
            except (KeyError, ValueError, TypeError, AttributeError):
                cb_record_failure(source_name)
                raise
        wrapper.__name__ = fn.__name__
        wrapper.__doc__ = fn.__doc__
        return wrapper
    return decorator
