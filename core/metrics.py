"""
Tool call metrics — SQLite-persisted call statistics.

Tracks per-tool call count, latency, error rate.
Inspired by go-stock (https://github.com/ArvinLovegood/go-stock) D1 usage_daily pattern.
"""
from __future__ import annotations

import logging
import sqlite3
import threading
import time
from pathlib import Path

logger = logging.getLogger("stock-mcp.metrics")

DB_PATH = Path.home() / ".stock-mcp" / "metrics.db"


class ToolMetrics:
    """SQLite-backed tool call statistics."""

    def __init__(self, db_path: str | Path | None = None):
        self._db_path = str(db_path or DB_PATH)
        self._lock = threading.Lock()
        self._ensure_db()

    def _ensure_db(self):
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS tool_calls (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tool_name TEXT NOT NULL,
                    latency_ms INTEGER DEFAULT 0,
                    success INTEGER DEFAULT 1,
                    error_msg TEXT DEFAULT '',
                    called_at TEXT DEFAULT (datetime('now', 'localtime'))
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_tool_name ON tool_calls(tool_name)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_called_at ON tool_calls(called_at)
            """)

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._db_path, timeout=5)

    def record(self, tool_name: str, latency_ms: int = 0, success: bool = True, error: str = ""):
        """Record a tool call event."""
        with self._lock:
            try:
                with self._connect() as conn:
                    conn.execute(
                        "INSERT INTO tool_calls (tool_name, latency_ms, success, error_msg) VALUES (?, ?, ?, ?)",
                        (tool_name, latency_ms, 1 if success else 0, error[:200]),
                    )
            except Exception as e:
                logger.warning("Failed to record metrics: %s", e)

    def summary(self, hours: int = 24) -> dict:
        """Get tool usage summary for the last N hours."""
        with self._lock:
            try:
                with self._connect() as conn:
                    # Total calls
                    row = conn.execute(
                        "SELECT COUNT(*), SUM(success), AVG(latency_ms) FROM tool_calls WHERE called_at >= datetime('now', '-' || ? || ' hours', 'localtime')",
                        (hours,),
                    ).fetchone()
                    total = row[0] or 0
                    success_count = row[1] or 0
                    avg_latency = round(row[2] or 0, 1)

                    # Top tools
                    rows = conn.execute(
                        """SELECT tool_name, COUNT(*) as cnt, SUM(success) as ok, AVG(latency_ms) as avg_ms
                           FROM tool_calls WHERE called_at >= datetime('now', '-' || ? || ' hours', 'localtime')
                           GROUP BY tool_name ORDER BY cnt DESC LIMIT 20""",
                        (hours,),
                    ).fetchall()

                    top_tools = []
                    for r in rows:
                        top_tools.append({
                            "tool": r[0],
                            "calls": r[1],
                            "success_rate": round((r[2] or 0) / r[1] * 100, 1) if r[1] else 100,
                            "avg_latency_ms": round(r[3] or 0, 1),
                        })

                    return {
                        "period_hours": hours,
                        "total_calls": total,
                        "success_rate": round((success_count or 0) / total * 100, 1) if total else 100,
                        "avg_latency_ms": avg_latency,
                        "top_tools": top_tools,
                    }
            except Exception as e:
                logger.warning("Failed to get metrics summary: %s", e)
                return {"error": str(e)}

    def cleanup(self, days: int = 30):
        """Delete metrics older than N days."""
        with self._lock:
            try:
                with self._connect() as conn:
                    deleted = conn.execute(
                        "DELETE FROM tool_calls WHERE called_at < datetime('now', '-' || ? || ' days', 'localtime')",
                        (days,),
                    ).rowcount
                    return {"deleted": deleted}
            except Exception as e:
                return {"error": str(e)}


# ── Global singleton ────────────────────────────────────
_metrics: ToolMetrics | None = None


def get_metrics() -> ToolMetrics:
    global _metrics
    if _metrics is None:
        _metrics = ToolMetrics()
    return _metrics
