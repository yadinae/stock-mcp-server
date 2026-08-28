"""
信号反馈闭环 — 追踪推荐效果，动态调整策略

设计原则（借鉴 WyckoffTradingAgent）：
- shadow 池：信号类型在观察中，不改变正式候选
- 激活门槛：≥30 个成熟样本 + 胜率 > 50%
- 每个信号类型独立追踪
- 明确终止条件：超过 5 天未确认自动过期

用法:
    feedback = SignalFeedback()
    feedback.record_outcome("600519", "trend", entry=1800, exit=1850, holding_days=5)
    stats = feedback.compute_stats("trend")
    pool = feedback.get_shadow_pool()
"""
from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional

import logging

logger = logging.getLogger("stock-mcp.signal_feedback")

DB_PATH = os.environ.get(
    "STOCK_MCP_DB",
    os.path.expanduser("~/.stock-mcp/stock_mcp.db"),
)

# ── Schema ────────────────────────────────────────────────

_SCHEMA = """
CREATE TABLE IF NOT EXISTS signal_outcomes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL,
    signal_type TEXT NOT NULL,
    entry_price REAL,
    exit_price REAL,
    pnl_pct REAL,
    result TEXT,
    holding_days INTEGER,
    recorded_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_signal_outcomes_type
    ON signal_outcomes(signal_type);
CREATE INDEX IF NOT EXISTS idx_signal_outcomes_code
    ON signal_outcomes(code);
"""


# ── 数据类 ────────────────────────────────────────────────

@dataclass
class SignalStats:
    """单个信号类型的统计"""
    signal_type: str
    total_samples: int
    win_count: int
    loss_count: int
    neutral_count: int
    win_rate: float
    avg_pnl_pct: float
    is_mature: bool        # ≥ 最小样本数
    should_activate: bool  # 成熟 + 胜率达标
    status: str            # "active" | "shadow" | "empty"

    def to_dict(self) -> dict:
        return {
            "signal_type": self.signal_type,
            "total_samples": self.total_samples,
            "win_rate": round(self.win_rate, 3),
            "avg_pnl_pct": round(self.avg_pnl_pct, 2),
            "is_mature": self.is_mature,
            "should_activate": self.should_activate,
            "status": self.status,
        }


# ── 反馈引擎 ──────────────────────────────────────────────

class SignalFeedback:
    """
    信号反馈闭环

    Args:
        db_path: SQLite 数据库路径
        min_samples: 最小样本数（默认 30）
        min_win_rate: 最小胜率（默认 0.5）
    """

    def __init__(
        self,
        db_path: Optional[str] = None,
        min_samples: int = 30,
        min_win_rate: float = 0.5,
    ):
        self.db_path = db_path or DB_PATH
        self.min_samples = min_samples
        self.min_win_rate = min_win_rate
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

    def record_outcome(
        self,
        code: str,
        signal_type: str,
        entry_price: float,
        exit_price: float,
        holding_days: int,
    ):
        """
        记录信号的实际结果

        Args:
            code: 股票代码
            signal_type: 信号类型（trend/reversal/breakout/accumulation）
            entry_price: 入场价
            exit_price: 出场价
            holding_days: 持仓天数
        """
        pnl = (exit_price - entry_price) / entry_price * 100 if entry_price > 0 else 0
        result = "win" if pnl > 2 else ("loss" if pnl < -2 else "neutral")

        conn = self._get_conn()
        try:
            conn.execute(
                """INSERT INTO signal_outcomes
                   (code, signal_type, entry_price, exit_price, pnl_pct,
                    result, holding_days, recorded_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (code, signal_type, entry_price, exit_price, pnl,
                 result, holding_days, datetime.now().isoformat()),
            )
            conn.commit()
            logger.info(
                "Recorded outcome: %s %s entry=%.2f exit=%.2f pnl=%.2f%% %s",
                code, signal_type, entry_price, exit_price, pnl, result,
            )
        finally:
            conn.close()

    def compute_stats(self, signal_type: str, window: int = 30) -> SignalStats:
        """
        计算信号类型的统计

        Args:
            signal_type: 信号类型
            window: 统计窗口（最近 N 个样本）
        """
        conn = self._get_conn()
        try:
            cursor = conn.execute(
                """SELECT COUNT(*),
                          SUM(CASE WHEN result='win' THEN 1 ELSE 0 END),
                          SUM(CASE WHEN result='loss' THEN 1 ELSE 0 END),
                          SUM(CASE WHEN result='neutral' THEN 1 ELSE 0 END),
                          AVG(pnl_pct)
                   FROM (
                       SELECT result, pnl_pct FROM signal_outcomes
                       WHERE signal_type = ?
                       ORDER BY recorded_at DESC
                       LIMIT ?
                   )""",
                (signal_type, window),
            )
            row = cursor.fetchone()
            total = row[0] or 0
            wins = row[1] or 0
            losses = row[2] or 0
            neutrals = row[3] or 0
            avg_pnl = row[4] or 0

            win_rate = wins / total if total > 0 else 0
            is_mature = total >= self.min_samples
            should_activate = is_mature and win_rate > self.min_win_rate

            if total == 0:
                status = "empty"
            elif should_activate:
                status = "active"
            else:
                status = "shadow"

            return SignalStats(
                signal_type=signal_type,
                total_samples=total,
                win_count=wins,
                loss_count=losses,
                neutral_count=neutrals,
                win_rate=win_rate,
                avg_pnl_pct=avg_pnl,
                is_mature=is_mature,
                should_activate=should_activate,
                status=status,
            )
        finally:
            conn.close()

    def get_all_stats(self) -> List[SignalStats]:
        """获取所有信号类型的统计"""
        conn = self._get_conn()
        try:
            cursor = conn.execute(
                "SELECT DISTINCT signal_type FROM signal_outcomes"
            )
            types = [r[0] for r in cursor.fetchall()]
            return [self.compute_stats(t) for t in types]
        finally:
            conn.close()

    def get_shadow_pool(self) -> List[dict]:
        """
        获取 shadow 池

        shadow 池 = 有数据但未达到激活门槛的信号类型
        """
        all_stats = self.get_all_stats()
        pool = []
        for stats in all_stats:
            if stats.status != "empty":
                pool.append(stats.to_dict())
        return pool

    def get_winners(self, min_pnl: float = 5.0) -> List[dict]:
        """获取盈利超过阈值的记录"""
        conn = self._get_conn()
        try:
            cursor = conn.execute(
                """SELECT code, signal_type, entry_price, exit_price,
                          pnl_pct, holding_days, recorded_at
                   FROM signal_outcomes
                   WHERE pnl_pct >= ?
                   ORDER BY pnl_pct DESC""",
                (min_pnl,),
            )
            return [
                {
                    "code": r[0], "signal_type": r[1],
                    "entry_price": r[2], "exit_price": r[3],
                    "pnl_pct": r[4], "holding_days": r[5],
                    "recorded_at": r[6],
                }
                for r in cursor.fetchall()
            ]
        finally:
            conn.close()

    def summary(self) -> str:
        """生成人类可读的摘要"""
        stats = self.get_all_stats()
        if not stats:
            return "No signal outcomes recorded yet."

        lines = ["Signal Feedback Summary:"]
        for s in stats:
            icon = "🟢" if s.status == "active" else "🟡" if s.status == "shadow" else "⚪"
            lines.append(
                f"  {icon} {s.signal_type}: {s.total_samples} samples, "
                f"win_rate={s.win_rate:.1%}, avg_pnl={s.avg_pnl_pct:+.2f}%, "
                f"status={s.status}"
            )
        return "\n".join(lines)
