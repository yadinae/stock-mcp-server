"""
Baostock 内存缓存 — 首次加载后常驻内存

设计:
- 懒加载: 首次访问时从 SQLite 全量加载到内存
- 模块级单例: 进程生命周期内只加载一次
- 线程安全: threading.Lock 保护加载过程
- 字典结构: {symbol: DataFrame}，DataFrame 按 date 降序排列
- 内存占用: ~15MB（441 只股票 × 250 天 × 8 列）
"""
from __future__ import annotations

import logging
import sqlite3
import threading
from pathlib import Path
from typing import Dict, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger("stock-mcp.baostock_cache")

_BAOSTOCK_DB = Path(__file__).parent.parent / "data" / "baostock_cache.db"


class BaostockMemoryCache:
    """
    Baostock 数据内存缓存

    用法:
        cache = BaostockMemoryCache.instance()
        df = cache.get("000001")  # 返回 DataFrame (date, open, high, low, close, volume)，按 date 降序
        all_symbols = cache.symbols()
    """

    _instance: Optional["BaostockMemoryCache"] = None
    _lock = threading.Lock()

    def __init__(self):
        self._data: Dict[str, pd.DataFrame] = {}
        self._loaded = False
        self._load_lock = threading.Lock()

    @classmethod
    def instance(cls) -> "BaostockMemoryCache":
        """获取全局单例（线程安全）"""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def _ensure_loaded(self):
        """懒加载：首次访问时从 SQLite 全量加载"""
        if self._loaded:
            return

        with self._load_lock:
            if self._loaded:
                return

            if not _BAOSTOCK_DB.exists():
                logger.warning("Baostock DB not found: %s", _BAOSTOCK_DB)
                self._loaded = True
                return

            import time
            t0 = time.time()

            conn = sqlite3.connect(str(_BAOSTOCK_DB))
            try:
                df = pd.read_sql_query(
                    "SELECT symbol, date, open, high, low, close, volume "
                    "FROM stock_daily ORDER BY symbol, date DESC",
                    conn,
                )
            finally:
                conn.close()

            # 数值列转换
            for col in ["open", "high", "low", "close", "volume"]:
                df[col] = pd.to_numeric(df[col], errors="coerce")

            # 按 symbol 分组，建立字典
            self._data = {
                sym: grp.reset_index(drop=True)
                for sym, grp in df.groupby("symbol")
            }

            self._loaded = True
            elapsed = (time.time() - t0) * 1000
            logger.info(
                "Baostock memory cache loaded: %d symbols, %d rows, %.1fMB, %.0fms",
                len(self._data),
                len(df),
                df.memory_usage(deep=True).sum() / 1024 / 1024,
                elapsed,
            )

    def get(self, symbol: str) -> Optional[pd.DataFrame]:
        """
        获取单只股票的 K 线数据

        返回: DataFrame with columns [date, open, high, low, close, volume]
              按 date 降序排列（最新在前），或 None if not found
        """
        self._ensure_loaded()
        return self._data.get(symbol)

    def get_batch(self, symbols: list[str]) -> Dict[str, pd.DataFrame]:
        """
        批量获取多只股票的 K 线数据

        返回: {symbol: DataFrame}，只包含存在的 symbol
        """
        self._ensure_loaded()
        return {s: self._data[s] for s in symbols if s in self._data}

    def symbols(self) -> list[str]:
        """返回所有可用的 symbol 列表"""
        self._ensure_loaded()
        return list(self._data.keys())

    def symbol_count(self) -> int:
        """返回股票数量"""
        self._ensure_loaded()
        return len(self._data)

    def row_count(self) -> int:
        """返回总行数"""
        self._ensure_loaded()
        return sum(len(df) for df in self._data.values())

    def stats(self) -> dict:
        """返回缓存统计信息"""
        self._ensure_loaded()
        total_rows = self.row_count()
        total_mem = sum(df.memory_usage(deep=True).sum() for df in self._data.values())
        return {
            "symbols": self.symbol_count(),
            "total_rows": total_rows,
            "memory_mb": round(total_mem / 1024 / 1024, 1),
            "loaded": self._loaded,
        }

    def reload(self):
        """强制重新加载（用于数据更新后）"""
        with self._load_lock:
            self._data.clear()
            self._loaded = False
        self._ensure_loaded()
