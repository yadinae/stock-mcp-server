"""策略基类 — 所有选股策略的抽象接口。

移植自 Sequoia-X base.py，适配 MCP server 的数据层。
"""
from __future__ import annotations

import logging
import sqlite3
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

logger = logging.getLogger("stock-mcp.strategy")

# 缓存数据库路径（与 baostock_source 共享）
_DB_PATH = Path(__file__).parent.parent.parent / "data" / "baostock_cache.db"


@dataclass
class StrategyResult:
    """策略扫描结果"""
    strategy_name: str
    selected: list[dict[str, Any]]
    scan_count: int  # 扫描股票总数
    select_count: int  # 选中数量
    source: str = "baostock_cache"
    error: str = ""
    details: dict[str, Any] = field(default_factory=dict)


class BaseStrategy(ABC):
    """选股策略抽象基类。

    子类必须实现 run() 方法，返回 StrategyResult。
    """

    name: str = "base"
    description: str = ""
    min_bars: int = 60  # 最少需要的 K 线数量

    def __init__(self) -> None:
        self._db_path = _DB_PATH

    def _get_all_symbols(self) -> list[str]:
        """从本地缓存获取所有有数据的股票代码"""
        if not self._db_path.exists():
            return []
        conn = sqlite3.connect(str(self._db_path))
        try:
            rows = conn.execute(
                "SELECT symbol, COUNT(*) as cnt FROM stock_daily "
                "GROUP BY symbol HAVING cnt >= ? ORDER BY symbol",
                (self.min_bars,),
            ).fetchall()
            return [r[0] for r in rows]
        finally:
            conn.close()

    def _get_kline_df(self, symbol: str) -> pd.DataFrame:
        """获取单只股票的 K 线 DataFrame（从缓存）"""
        if not self._db_path.exists():
            return pd.DataFrame()
        conn = sqlite3.connect(str(self._db_path))
        try:
            df = pd.read_sql(
                "SELECT date, open, high, low, close, volume, turnover "
                "FROM stock_daily WHERE symbol = ? ORDER BY date",
                conn, params=(symbol,),
            )
            for col in ["open", "high", "low", "close", "volume", "turnover"]:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors="coerce")
            return df
        finally:
            conn.close()

    def _get_all_klines_bulk(self) -> dict[str, pd.DataFrame]:
        """批量获取所有股票的 K 线（一次性读取，避免 N+1 查询）"""
        if not self._db_path.exists():
            return {}
        conn = sqlite3.connect(str(self._db_path))
        try:
            df = pd.read_sql(
                "SELECT symbol, date, open, high, low, close, volume, turnover "
                "FROM stock_daily ORDER BY symbol, date",
                conn,
            )
            for col in ["open", "high", "low", "close", "volume", "turnover"]:
                df[col] = pd.to_numeric(df[col], errors="coerce")

            result = {}
            for sym, grp in df.groupby("symbol"):
                if len(grp) >= self.min_bars:
                    result[sym] = grp.reset_index(drop=True)
            return result
        finally:
            conn.close()

    @abstractmethod
    def run(self) -> StrategyResult:
        """执行选股逻辑，返回 StrategyResult。

        Returns:
            StrategyResult 包含选中的股票代码和详细信息
        """
        ...
