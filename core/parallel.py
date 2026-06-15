"""并行执行工具 — P0 优化核心

提供 run_parallel() 函数，同时执行多个独立任务，
显著减少 analyze_stock_ai / get_stock_context 的响应时间。
"""

from __future__ import annotations

import atexit
import logging
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError, as_completed
from typing import Any, Callable

logger = logging.getLogger("stock-mcp.parallel")

# 全局线程池（最多4个worker，避免API限流）
_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="stock-mcp")
atexit.register(lambda: _executor.shutdown(wait=False))


def run_parallel(tasks: dict[str, Callable[[], Any]],
                 timeout: float = 30) -> dict[str, Any]:
    """并行执行多个任务

    Args:
        tasks: {名称: 可调用函数} 字典
        timeout: 每个任务的超时秒数

    Returns:
        {名称: 结果或错误信息}
    """
    if not tasks:
        return {}

    # 单任务：提交到线程池由全局 timeout 保护，避免无超时阻塞
    if len(tasks) == 1:
        name, fn = next(iter(tasks.items()))
        fut = _executor.submit(fn)
        try:
            return {name: fut.result(timeout=timeout)}
        except Exception as e:
            fut.cancel()
            return {name: {"error": str(e) if not isinstance(e, TimeoutError) else f"超时（>{timeout}s）"}}

    results: dict[str, Any] = {}
    futures = {}

    def safe_run(name: str, fn: Callable) -> tuple[str, Any]:
        try:
            return name, fn()
        except Exception as e:
            logger.warning("并行任务 %s 失败: %s", name, e)
            return name, {"error": str(e)}

    for name, fn in tasks.items():
        futures[_executor.submit(safe_run, name, fn)] = name

    deadline = time.monotonic() + timeout
    for future in as_completed(futures, timeout=timeout):
        name = futures[future]
        try:
            _, result = future.result()
            results[name] = result
        except Exception as e:
            results[name] = {"error": str(e)}

        if len(results) == len(tasks):
            break
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break

    # 超时强制取消未完成的任务
    for future in futures:
        if not future.done():
            future.cancel()

    # 补充未返回的任务为超时
    for name in tasks:
        if name not in results:
            results[name] = {"error": f"超时（>{timeout}s）"}

    return results


def parallel_map(fn: Callable, items: list, max_workers: int = 4) -> list:
    """对列表每个元素并行执行函数（复用全局线程池）"""
    if not items:
        return []
    if len(items) == 1:
        return [fn(items[0])]

    futures = [_executor.submit(fn, item) for item in items]
    results = []
    for f in futures:
        try:
            results.append(f.result())
        except Exception as e:
            results.append({"error": str(e)})
    return results
