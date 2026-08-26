"""baostock 数据源 — 免费、无需注册、无限流的 A 股 K 线数据。

用途：
1. 作为 tencent/东财反爬限流时的后备数据源
2. 提供后复权日 K 线数据（适合策略回测）
3. 获取全市场 A 股代码列表
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

logger = logging.getLogger("stock-mcp.baostock")

# ── 缓存配置 ───────────────────────────────────────────
_DB_DIR = Path(__file__).parent.parent / "data"
_DB_PATH = _DB_DIR / "baostock_cache.db"
_cache_conn: sqlite3.Connection | None = None


def _get_conn() -> sqlite3.Connection:
    """获取/创建 SQLite 缓存连接"""
    global _cache_conn
    if _cache_conn is None:
        _DB_DIR.mkdir(parents=True, exist_ok=True)
        _cache_conn = sqlite3.connect(str(_DB_PATH), timeout=5)
        _cache_conn.execute("""
            CREATE TABLE IF NOT EXISTS stock_daily (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                date TEXT NOT NULL,
                open REAL, high REAL, low REAL, close REAL,
                volume REAL, turnover REAL,
                UNIQUE(symbol, date)
            )
        """)
        _cache_conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_symbol_date ON stock_daily (symbol, date)"
        )
        _cache_conn.commit()
    return _cache_conn


def _to_bs_code(symbol: str) -> str:
    """纯数字代码 → baostock 格式：6/9 开头 → sh，其余 → sz"""
    prefix = "sh" if symbol.startswith(("6", "9")) else "sz"
    return f"{prefix}.{symbol}"


def get_kline(symbol: str, days: int = 120, adjust: str = "1") -> dict[str, Any]:
    """通过 baostock 获取 A 股日 K 线数据。

    Args:
        symbol: 纯数字股票代码（如 600519）
        days: 获取最近多少个交易日
        adjust: 复权方式 "1"=后复权, "2"=前复权, "3"=不复权

    Returns:
        {"records": [...], "source": "baostock", "count": N}
    """
    import baostock as bs

    today_str = date.today().strftime("%Y-%m-%d")
    start_str = (date.today() - timedelta(days=days * 2)).strftime("%Y-%m-%d")

    # 先检查本地缓存
    conn = _get_conn()
    cached = pd.read_sql(
        "SELECT date, open, high, low, close, volume, turnover "
        "FROM stock_daily WHERE symbol = ? AND date >= ? ORDER BY date",
        conn, params=(symbol, start_str),
    )

    if len(cached) >= days:
        # 缓存够用，直接返回
        records = cached.tail(days).to_dict("records")
        for r in records:
            for k in ("open", "high", "low", "close", "volume", "turnover"):
                if k in r and pd.notna(r[k]):
                    r[k] = float(r[k])
        return {"records": records, "source": "baostock_cache", "count": len(records)}

    # 缓存不够，从 baostock 拉取
    lg = bs.login()
    if lg.error_code != "0":
        logger.error(f"baostock 登录失败: {lg.error_msg}")
        return {"records": [], "source": "baostock", "error": lg.error_msg}

    try:
        bs_code = _to_bs_code(symbol)
        rs = bs.query_history_k_data_plus(
            bs_code,
            "date,open,high,low,close,volume,amount",
            start_date=start_str,
            end_date=today_str,
            frequency="d",
            adjustflag=adjust,
        )
        if rs.error_code != "0":
            return {"records": [], "source": "baostock", "error": rs.error_msg}

        rows = []
        while rs.next():
            rows.append(rs.get_row_data())

        if not rows:
            return {"records": [], "source": "baostock", "count": 0}

        df = pd.DataFrame(rows, columns=["date", "open", "high", "low", "close", "volume", "turnover"])
        for col in ["open", "high", "low", "close", "volume", "turnover"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df["symbol"] = symbol
        df = df.dropna(subset=["close"])
        df = df[df["volume"] > 0]

        # 写入缓存
        try:
            with sqlite3.connect(str(_DB_PATH), timeout=5) as wconn:
                df.to_sql("stock_daily", wconn, if_exists="append", index=False,
                          method="multi", chunksize=500)
        except sqlite3.IntegrityError:
            pass  # 已存在则跳过

        records = df.tail(days).to_dict("records")
        for r in records:
            for k in ("open", "high", "low", "close", "volume", "turnover"):
                if k in r and pd.notna(r[k]):
                    r[k] = float(r[k])
        return {"records": records, "source": "baostock", "count": len(records)}
    finally:
        bs.logout()


def get_all_a_symbols() -> list[str]:
    """通过 baostock 获取全市场 A 股代码列表"""
    import baostock as bs

    lg = bs.login()
    if lg.error_code != "0":
        logger.error(f"baostock 登录失败: {lg.error_msg}")
        return []

    try:
        rs = bs.query_stock_basic(code_name="", code="")
        symbols = []
        while rs.next():
            row = rs.get_row_data()
            code = row[0]  # "sh.600000"
            status = row[4]  # "1" = 上市
            stock_type = row[5]  # "1" = 股票
            if status == "1" and stock_type == "1":
                symbols.append(code.split(".")[1])
        return symbols
    except Exception as e:
        logger.error(f"获取股票列表失败: {e}")
        return []
    finally:
        bs.logout()


def backfill_symbol(symbol: str, start_date: str = "2024-01-01") -> int:
    """回填单只股票的历史数据（后复权），返回写入行数"""
    import baostock as bs

    today_str = date.today().strftime("%Y-%m-%d")
    conn = _get_conn()
    row = conn.execute(
        "SELECT MAX(date) FROM stock_daily WHERE symbol = ?", (symbol,)
    ).fetchone()
    last_date = row[0] if row and row[0] else None
    if last_date and last_date >= today_str:
        return 0

    effective_start = last_date or start_date

    lg = bs.login()
    if lg.error_code != "0":
        return 0

    try:
        bs_code = _to_bs_code(symbol)
        rs = bs.query_history_k_data_plus(
            bs_code,
            "date,open,high,low,close,volume,amount",
            start_date=effective_start,
            end_date=today_str,
            frequency="d",
            adjustflag="1",
        )
        if rs.error_code != "0":
            return 0

        rows = []
        while rs.next():
            rows.append(rs.get_row_data())

        if not rows:
            return 0

        df = pd.DataFrame(rows, columns=["date", "open", "high", "low", "close", "volume", "turnover"])
        for col in ["open", "high", "low", "close", "volume", "turnover"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df["symbol"] = symbol
        df = df.dropna(subset=["close"])
        df = df[df["volume"] > 0]

        if df.empty:
            return 0

        # 先删除已有日期的数据，再插入（避免 UNIQUE 约束冲突）
        wconn = sqlite3.connect(str(_DB_PATH), timeout=5)
        try:
            dates = df["date"].unique().tolist()
            placeholders = ",".join(["?"] * len(dates))
            wconn.execute(
                f"DELETE FROM stock_daily WHERE symbol = ? AND date IN ({placeholders})",
                [symbol] + dates,
            )
            df.to_sql("stock_daily", wconn, if_exists="append", index=False,
                      method="multi", chunksize=500)
            wconn.commit()
        finally:
            wconn.close()
        return len(df)
    except Exception as e:
        logger.warning(f"[{symbol}] backfill 失败: {e}")
        return 0
    finally:
        bs.logout()


def backfill_batch(symbols: list[str], start_date: str = "2024-01-01") -> dict:
    """批量回填（单次 login，快速遍历）"""
    import baostock as bs

    today_str = date.today().strftime("%Y-%m-%d")
    lg = bs.login()
    if lg.error_code != "0":
        return {"error": lg.error_msg}

    success = 0
    skipped = 0
    failed = 0
    total_rows = 0

    try:
        for symbol in symbols:
            # 检查是否已是最新
            conn = _get_conn()
            row = conn.execute(
                "SELECT MAX(date) FROM stock_daily WHERE symbol = ?", (symbol,)
            ).fetchone()
            last_date = row[0] if row and row[0] else None
            if last_date and last_date >= today_str:
                skipped += 1
                continue

            effective_start = last_date or start_date
            bs_code = _to_bs_code(symbol)
            rs = bs.query_history_k_data_plus(
                bs_code,
                "date,open,high,low,close,volume,amount",
                start_date=effective_start,
                end_date=today_str,
                frequency="d",
                adjustflag="1",
            )
            if rs.error_code != "0":
                failed += 1
                continue

            rows = []
            while rs.next():
                rows.append(rs.get_row_data())

            if not rows:
                skipped += 1
                continue

            df = pd.DataFrame(rows, columns=["date", "open", "high", "low", "close", "volume", "turnover"])
            for col in ["open", "high", "low", "close", "volume", "turnover"]:
                df[col] = pd.to_numeric(df[col], errors="coerce")
            df["symbol"] = symbol
            df = df.dropna(subset=["close"])
            df = df[df["volume"] > 0]

            if df.empty:
                skipped += 1
                continue

            wconn = sqlite3.connect(str(_DB_PATH), timeout=5)
            try:
                dates = df["date"].unique().tolist()
                placeholders = ",".join(["?"] * len(dates))
                wconn.execute(
                    f"DELETE FROM stock_daily WHERE symbol = ? AND date IN ({placeholders})",
                    [symbol] + dates,
                )
                df.to_sql("stock_daily", wconn, if_exists="append", index=False,
                          method="multi", chunksize=500)
                wconn.commit()
            finally:
                wconn.close()

            success += 1
            total_rows += len(df)
    finally:
        bs.logout()

    return {
        "success": success,
        "skipped": skipped,
        "failed": failed,
        "total_rows": total_rows,
        "symbols_count": len(symbols),
    }
