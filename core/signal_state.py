"""
信号状态机 — 跟踪信号从 DETECTED 到 EXPIRED 的生命周期

状态流转:
  DETECTED → SURVIVED → CONFIRMED → (持有中)
  DETECTED → EXPIRED（超时未确认）
  DETECTED → REJECTED（被 AI 审计否决）

数据存储: SQLite（与 core/store.py 共享 DB_PATH）
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger("stock-mcp.signal_state")

DB_PATH = os.environ.get(
    "STOCK_MCP_DB",
    os.path.expanduser("~/.stock-mcp/stock_mcp.db"),
)

# ── 状态定义 ──────────────────────────────────────────────

class SignalState(Enum):
    DETECTED = "detected"       # 技术面信号刚触发
    SURVIVED = "survived"       # 跨日存活，信号未失效
    CONFIRMED = "confirmed"     # 出现量价确认
    EXPIRED = "expired"         # 信号失效（超时/跌破关键位）
    REJECTED = "rejected"       # 被 AI 审计否决


# ── Schema ────────────────────────────────────────────────

_SCHEMA = """
CREATE TABLE IF NOT EXISTS signal_states (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL,
    signal_type TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'detected',
    detected_at TEXT NOT NULL,
    confirmed_at TEXT,
    expired_at TEXT,
    key_level REAL,
    context TEXT,
    UNIQUE(code, signal_type, detected_at)
);

CREATE INDEX IF NOT EXISTS idx_signal_states_code
    ON signal_states(code);
CREATE INDEX IF NOT EXISTS idx_signal_states_state
    ON signal_states(state);
CREATE INDEX IF NOT EXISTS idx_signal_states_type
    ON signal_states(signal_type);
"""


# ── Tracker ───────────────────────────────────────────────

class SignalTracker:
    """
    信号状态机

    用法:
        tracker = SignalTracker()
        tracker.record("600519", "trend", SignalState.DETECTED, key_level=1800)
        # 次日确认
        tracker.record("600519", "trend", SignalState.CONFIRMED)
        # 检查存活
        alive = tracker.check_survival("600519", current_price=1810)
    """

    MAX_AGE_DAYS = 5  # 超过 5 天未确认自动过期

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or DB_PATH
        self._ensure_db()

    def _ensure_db(self):
        """确保数据库表存在"""
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(_SCHEMA)
        conn.commit()
        conn.close()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def record(
        self,
        code: str,
        signal_type: str,
        state: SignalState,
        key_level: Optional[float] = None,
        context: Optional[dict] = None,
    ):
        """记录信号状态"""
        now = datetime.now().isoformat()
        conn = self._get_conn()

        try:
            if state == SignalState.CONFIRMED:
                conn.execute(
                    """UPDATE signal_states
                       SET state = ?, confirmed_at = ?
                       WHERE code = ? AND signal_type = ?
                         AND state IN ('detected', 'survived')""",
                    (state.value, now, code, signal_type),
                )
            elif state in (SignalState.EXPIRED, SignalState.REJECTED):
                conn.execute(
                    """UPDATE signal_states
                       SET state = ?, expired_at = ?
                       WHERE code = ? AND signal_type = ?
                         AND state != 'expired'""",
                    (state.value, now, code, signal_type),
                )
            else:
                conn.execute(
                    """INSERT OR IGNORE INTO signal_states
                       (code, signal_type, state, detected_at, key_level, context)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (code, signal_type, state.value, now, key_level,
                     json.dumps(context or {})),
                )
            conn.commit()
        finally:
            conn.close()

    def get_active_signals(self) -> List[dict]:
        """获取所有活跃信号（非 EXPIRED/REJECTED）"""
        conn = self._get_conn()
        try:
            cursor = conn.execute(
                """SELECT id, code, signal_type, state, detected_at, key_level
                   FROM signal_states
                   WHERE state NOT IN ('expired', 'rejected')
                   ORDER BY detected_at DESC"""
            )
            return [
                {
                    "id": r[0],
                    "code": r[1],
                    "signal_type": r[2],
                    "state": r[3],
                    "detected_at": r[4],
                    "key_level": r[5],
                }
                for r in cursor.fetchall()
            ]
        finally:
            conn.close()

    def get_signals_by_code(self, code: str) -> List[dict]:
        """获取某只股票的所有信号"""
        conn = self._get_conn()
        try:
            cursor = conn.execute(
                """SELECT id, signal_type, state, detected_at, confirmed_at,
                          expired_at, key_level
                   FROM signal_states
                   WHERE code = ?
                   ORDER BY detected_at DESC""",
                (code,),
            )
            return [
                {
                    "id": r[0],
                    "signal_type": r[1],
                    "state": r[2],
                    "detected_at": r[3],
                    "confirmed_at": r[4],
                    "expired_at": r[5],
                    "key_level": r[6],
                }
                for r in cursor.fetchall()
            ]
        finally:
            conn.close()

    def check_survival(self, code: str, current_price: float) -> bool:
        """
        检查信号是否存活（价格未跌破关键位）

        规则：当前价低于 key_level × 0.97 → 信号失效
        """
        conn = self._get_conn()
        try:
            cursor = conn.execute(
                """SELECT key_level FROM signal_states
                   WHERE code = ? AND state IN ('detected', 'survived')""",
                (code,),
            )
            for row in cursor.fetchall():
                if row[0] and current_price < row[0] * 0.97:
                    return False
            return True
        finally:
            conn.close()

    def expire_stale(self, max_age_days: Optional[int] = None):
        """
        过期陈旧信号

        超过 max_age_days 天未确认的信号自动过期
        """
        days = max_age_days or self.MAX_AGE_DAYS
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        now = datetime.now().isoformat()

        conn = self._get_conn()
        try:
            cursor = conn.execute(
                """UPDATE signal_states
                   SET state = 'expired', expired_at = ?
                   WHERE state IN ('detected', 'survived')
                     AND detected_at < ?""",
                (now, cutoff),
            )
            affected = cursor.rowcount
            conn.commit()
            if affected > 0:
                logger.info("Expired %d stale signals (older than %d days)", affected, days)
            return affected
        finally:
            conn.close()

    def get_stats(self) -> dict:
        """获取信号统计"""
        conn = self._get_conn()
        try:
            cursor = conn.execute(
                """SELECT state, COUNT(*) FROM signal_states GROUP BY state"""
            )
            state_counts = {r[0]: r[1] for r in cursor.fetchall()}

            cursor = conn.execute(
                """SELECT signal_type, COUNT(*) FROM signal_states
                   WHERE state NOT IN ('expired', 'rejected')
                   GROUP BY signal_type"""
            )
            active_by_type = {r[0]: r[1] for r in cursor.fetchall()}

            return {
                "total": sum(state_counts.values()),
                "by_state": state_counts,
                "active_by_type": active_by_type,
            }
        finally:
            conn.close()

    def cleanup(self, keep_days: int = 30):
        """清理过期信号（保留最近 N 天）"""
        cutoff = (datetime.now() - timedelta(days=keep_days)).isoformat()
        conn = self._get_conn()
        try:
            cursor = conn.execute(
                "DELETE FROM signal_states WHERE state = 'expired' AND expired_at < ?",
                (cutoff,),
            )
            affected = cursor.rowcount
            conn.commit()
            if affected > 0:
                logger.info("Cleaned up %d expired signals (older than %d days)", affected, keep_days)
            return affected
        finally:
            conn.close()
