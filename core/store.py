#!/usr/bin/env python3
"""本地 SQLite 存储 — 交易日志 + 观察清单（替代 Gateway D1）

数据库: ~/.stock-mcp/stock_mcp.db（自动创建）
"""
import os
import sqlite3
import json
from datetime import datetime

DB_PATH = os.environ.get("STOCK_MCP_DB", os.path.expanduser("~/.stock-mcp/stock_mcp.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS trade_journal (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  symbol TEXT NOT NULL,
  name TEXT,
  side TEXT NOT NULL DEFAULT 'long',
  entry_price REAL NOT NULL,
  shares REAL NOT NULL,
  entry_date TEXT NOT NULL,
  exit_price REAL,
  exit_date TEXT,
  strategy TEXT,
  rationale TEXT,
  notes TEXT,
  pnl REAL,
  pnl_pct REAL,
  status TEXT NOT NULL DEFAULT 'open',
  tags TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS watchlists (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL UNIQUE,
  description TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS watchlist_items (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  watchlist_id INTEGER NOT NULL,
  symbol TEXT NOT NULL,
  name TEXT,
  added_at TEXT NOT NULL DEFAULT (datetime('now')),
  FOREIGN KEY (watchlist_id) REFERENCES watchlists(id) ON DELETE CASCADE,
  UNIQUE(watchlist_id, symbol)
);
"""

_conn = None


def _get_conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        _conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.executescript(SCHEMA)
        _conn.commit()
    return _conn


def now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def today() -> str:
    return now()[:10]


# ═══════════════ 交易日志 ═══════════════

def trade_open(symbol: str, shares: float, entry_price: float, strategy: str = "",
               rationale: str = "", side: str = "long", name: str = "") -> dict:
    db = _get_conn()
    symbol = symbol.strip().upper()
    if not symbol:
        return {"error": "symbol 不能为空"}
    if not shares or shares <= 0:
        return {"error": "shares 必须为正数"}
    if not entry_price or entry_price <= 0:
        return {"error": "entry_price 必须为正数"}
    cur = db.execute(
        """INSERT INTO trade_journal (symbol, name, side, entry_price, shares, entry_date, strategy, rationale, status)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'open')""",
        (symbol, name or "", side or "long", entry_price, shares, today(), strategy or "", rationale or ""),
    )
    db.commit()
    return {"id": cur.lastrowid, "symbol": symbol, "status": "open", "message": "开仓成功"}


def trade_close(trade_id: int, exit_price: float, notes: str = "") -> dict:
    db = _get_conn()
    row = db.execute("SELECT * FROM trade_journal WHERE id = ? AND status = 'open'", (trade_id,)).fetchone()
    if not row:
        return {"error": f"未找到开仓中的交易 id={trade_id}"}
    if not exit_price or exit_price <= 0:
        return {"error": "exit_price 必须为正数"}
    pnl = (exit_price - row["entry_price"]) * row["shares"]
    pnl_pct = (exit_price - row["entry_price"]) / row["entry_price"] * 100 if row["entry_price"] else 0
    db.execute(
        """UPDATE trade_journal SET exit_price=?, exit_date=?, notes=?, pnl=?, pnl_pct=?, status='closed', updated_at=?
           WHERE id=?""",
        (exit_price, today(), notes or "", round(pnl, 2), round(pnl_pct, 2), now(), trade_id),
    )
    db.commit()
    return {"id": trade_id, "status": "closed", "pnl": round(pnl, 2), "pnl_pct": round(pnl_pct, 2), "message": "平仓成功"}


def trade_update(trade_id: int, notes: str = "", strategy: str = "", rationale: str = "",
                 entry_price: float = 0) -> dict:
    db = _get_conn()
    row = db.execute("SELECT id FROM trade_journal WHERE id = ?", (trade_id,)).fetchone()
    if not row:
        return {"error": f"未找到交易 id={trade_id}"}
    sets, vals = [], []
    if notes:
        sets.append("notes=?"); vals.append(notes)
    if strategy:
        sets.append("strategy=?"); vals.append(strategy)
    if rationale:
        sets.append("rationale=?"); vals.append(rationale)
    if entry_price and entry_price > 0:
        sets.append("entry_price=?"); vals.append(entry_price)
    if not sets:
        return {"error": "没有可更新的字段"}
    sets.append("updated_at=?")
    vals.append(now())
    vals.append(trade_id)
    db.execute(f"UPDATE trade_journal SET {', '.join(sets)} WHERE id=?", vals)
    db.commit()
    return {"id": trade_id, "message": "更新成功"}


def trade_list(status: str = "", strategy: str = "", symbol: str = "") -> dict:
    db = _get_conn()
    sql = "SELECT * FROM trade_journal WHERE 1=1"
    params = []
    if status:
        sql += " AND status=?"; params.append(status)
    if strategy:
        sql += " AND strategy=?"; params.append(strategy)
    if symbol:
        sql += " AND symbol=?"; params.append(symbol.strip().upper())
    sql += " ORDER BY id DESC"
    rows = db.execute(sql, params).fetchall()
    trades = [dict(r) for r in rows]
    return {"total": len(trades), "trades": trades}


def trade_stats() -> dict:
    db = _get_conn()
    closed = db.execute("SELECT * FROM trade_journal WHERE status='closed'").fetchall()
    open_rows = db.execute("SELECT COUNT(*) c FROM trade_journal WHERE status='open'").fetchone()
    wins = [t for t in closed if (t["pnl"] or 0) > 0]
    total_pnl = sum(t["pnl"] or 0 for t in closed)
    # 按策略聚合
    by_strategy = {}
    for t in closed:
        s = t["strategy"] or "未标记"
        a = by_strategy.setdefault(s, {"count": 0, "wins": 0, "pnl": 0.0})
        a["count"] += 1
        if (t["pnl"] or 0) > 0:
            a["wins"] += 1
        a["pnl"] += t["pnl"] or 0
    return {
        "summary": {
            "total_closed": len(closed),
            "open_positions": open_rows["c"] if open_rows else 0,
            "win_count": len(wins),
            "win_rate_pct": round(len(wins) / len(closed) * 100, 1) if closed else 0,
            "total_pnl": round(total_pnl, 2),
        },
        "by_strategy": by_strategy,
    }


# ═══════════════ 观察清单 ═══════════════

def watchlist_create(name: str, description: str = "") -> dict:
    db = _get_conn()
    name = (name or "").strip()
    if not name:
        return {"error": "name 不能为空"}
    try:
        cur = db.execute("INSERT INTO watchlists (name, description) VALUES (?, ?)", (name, description or ""))
        db.commit()
        return {"id": cur.lastrowid, "name": name, "message": "创建成功"}
    except sqlite3.IntegrityError:
        return {"error": f"观察清单已存在: {name}"}


def watchlist_add(watchlist_id: int, symbols) -> dict:
    db = _get_conn()
    wl = db.execute("SELECT * FROM watchlists WHERE id = ?", (watchlist_id,)).fetchone()
    if not wl:
        return {"error": f"未找到观察清单 id={watchlist_id}"}
    if isinstance(symbols, str):
        symbols = [s.strip() for s in symbols.replace("，", ",").split(",") if s.strip()]
    added, dup = [], []
    for s in symbols:
        s = s.strip().upper()
        if not s:
            continue
        try:
            cur = db.execute("INSERT INTO watchlist_items (watchlist_id, symbol) VALUES (?, ?)", (watchlist_id, s))
            added.append(s)
        except sqlite3.IntegrityError:
            dup.append(s)
    db.commit()
    return {"watchlist_id": watchlist_id, "added": added, "duplicates": dup, "message": f"添加 {len(added)} 个标的"}


def watchlist_remove(watchlist_id: int, symbol: str) -> dict:
    db = _get_conn()
    symbol = (symbol or "").strip().upper()
    if not symbol:
        return {"error": "symbol 不能为空"}
    cur = db.execute("DELETE FROM watchlist_items WHERE watchlist_id=? AND symbol=?", (watchlist_id, symbol))
    db.commit()
    return {"removed": cur.rowcount > 0, "symbol": symbol, "watchlist_id": watchlist_id}


def watchlist_list() -> dict:
    db = _get_conn()
    rows = db.execute("SELECT * FROM watchlists ORDER BY id").fetchall()
    watchlists = []
    for wl in rows:
        items = db.execute("SELECT symbol, name FROM watchlist_items WHERE watchlist_id=? ORDER BY added_at", (wl["id"],)).fetchall()
        watchlists.append({
            "id": wl["id"], "name": wl["name"], "description": wl["description"] or "",
            "created_at": wl["created_at"],
            "symbols": [{"symbol": i["symbol"], "name": i["name"] or ""} for i in items],
        })
    return {"total": len(watchlists), "watchlists": watchlists}


def watchlist_get_items(watchlist_id: int) -> list:
    db = _get_conn()
    rows = db.execute("SELECT symbol FROM watchlist_items WHERE watchlist_id=?", (watchlist_id,)).fetchall()
    return [r["symbol"] for r in rows]
