"""并行执行工具 — P0 优化核心

提供 run_parallel() 函数，同时执行多个独立任务，
显著减少 analyze_stock_ai / get_stock_context 的响应时间。
"""

from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable

logger = logging.getLogger("stock-mcp.parallel")

# 全局线程池（最多4个worker，避免API限流）
_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="stock-mcp")


def run_parallel(tasks: dict[str, Callable[[], Any]],
                 timeout: float = 30) -> dict[str, Any]:
    """并行执行多个任务

    Args:
        tasks: {名称: 可调用函数} 字典
        timeout: 每个任务的超时秒数

    Returns:
        {名称: 结果或错误信息}
    """
    results: dict[str, Any] = {}
    locks: dict[str, threading.Lock] = {}

    def safe_run(name: str, fn: Callable) -> None:
        try:
            result = fn()
            with locks.get(name, threading.Lock()):
                results[name] = result
        except Exception as e:
            logger.warning("并行任务 %s 失败: %s", name, e)
            with locks.get(name, threading.Lock()):
                results[name] = {"error": str(e)}

    futures = {}
    for name, fn in tasks.items():
        locks[name] = threading.Lock()
        futures[_executor.submit(safe_run, name, fn)] = name

    for future in as_completed(futures, timeout=timeout * 2):
        pass  # safe_run 已经写了 results

    # 超时强制取消未完成的任务
    for future in futures:
        if not future.done():
            future.cancel()

    return results


def parallel_map(fn: Callable, items: list, max_workers: int = 4) -> list:
    """对列表每个元素并行执行函数

    用于批量并行获取多个股票行情。
    """
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        return list(pool.map(fn, items))
