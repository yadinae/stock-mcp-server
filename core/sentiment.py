#!/usr/bin/env python3
"""Sentiment Store — 每日市场情绪指标存储 + 跨日趋势对比

纯代码，零 LLM 成本。本地 SQLite 持久化。

核心功能：
1. 每日情绪快照：涨停数/跌停数/连板高度/涨跌比/成交量
2. 历史趋势：N 日均值、动量方向
3. 异常检测：情绪指标突变告警
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
from datetime import datetime, timedelta
from typing import Optional


# ─── 数据库路径 ────────────────────────────────────────────────
_DB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
_DB_PATH = os.path.join(_DB_DIR, "sentiment.db")


def _get_conn() -> sqlite3.Connection:
    """获取数据库连接（自动创建表）"""
    os.makedirs(_DB_DIR, exist_ok=True)
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sentiment_daily (
            date TEXT PRIMARY KEY,
            data TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS stock_sentiment (
            date TEXT NOT NULL,
            code TEXT NOT NULL,
            data TEXT NOT NULL,
            PRIMARY KEY (date, code)
        )
    """)
    conn.commit()
    return conn


def _today_str() -> str:
    """返回当天日期字符串 YYYY-MM-DD"""
    return datetime.now().strftime("%Y-%m-%d")


def store_daily_sentiment(date: Optional[str] = None, **kwargs) -> dict:
    """存储每日市场情绪快照

    Args:
        date: 日期（默认今天）
        **kwargs: 情绪指标，如:
            limit_up: 涨停数
            limit_down: 跌停数
            streak_high: 连板最高高度
            up_ratio: 上涨家数
            down_ratio: 下跌家数
            flat_ratio: 平盘家数
            total_volume: 总成交量
            total_amount: 总成交额
            breadth: 市场宽度（上涨家数/总数）
            custom: 自定义指标 dict

    Returns:
        {"date": ..., "stored": True}
    """
    date = date or _today_str()
    data = {k: v for k, v in kwargs.items() if v is not None}
    data["updated_at"] = datetime.now().isoformat()

    conn = _get_conn()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO sentiment_daily (date, data) VALUES (?, ?)",
            (date, json.dumps(data, ensure_ascii=False, default=str)),
        )
        conn.commit()
    finally:
        conn.close()

    return {"date": date, "stored": True, "fields": list(data.keys())}


def get_daily_sentiment(date: Optional[str] = None) -> dict:
    """获取指定日期的情绪快照

    Returns:
        {"date": ..., "data": {...}} or {"date": ..., "data": None, "error": "not found"}
    """
    date = date or _today_str()
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT data FROM sentiment_daily WHERE date = ?", (date,)
        ).fetchone()
        if row:
            return {"date": date, "data": json.loads(row["data"])}
        return {"date": date, "data": None, "error": f"{date} 无情绪数据"}
    finally:
        conn.close()


def get_sentiment_trend(days: int = 7, end_date: Optional[str] = None) -> dict:
    """获取情绪趋势 — 最近 N 天的指标变化

    Args:
        days: 回溯天数（默认7）
        end_date: 截止日期（默认今天）

    Returns:
        {
            dates: [str],
            limit_up: [int, ...],
            limit_down: [int, ...],
            up_ratio: [int, ...],
            breadth: [float, ...],
            trend: {字段: {direction, change_pct, avg}},
        }
    """
    end = end_date or _today_str()
    start_dt = datetime.strptime(end, "%Y-%m-%d") - timedelta(days=days + 3)  # 多取几天防空
    start = start_dt.strftime("%Y-%m-%d")

    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT date, data FROM sentiment_daily WHERE date >= ? AND date <= ? ORDER BY date",
            (start, end),
        ).fetchall()
    finally:
        conn.close()

    if not rows:
        return {"dates": [], "data": {}, "trend": {}, "error": "无历史情绪数据"}

    # 取最近 N 个交易日
    records = []
    for row in rows[-days:]:
        d = json.loads(row["data"])
        d["_date"] = row["date"]
        records.append(d)

    dates = [r["_date"] for r in records]
    metric_keys = [
        "limit_up", "limit_down", "streak_high", "up_ratio", "down_ratio",
        "total_volume", "total_amount", "breadth",
    ]

    series = {}
    for key in metric_keys:
        values = [r.get(key) for r in records if r.get(key) is not None]
        if values:
            series[key] = values

    # 趋势分析
    trend = {}
    for key, values in series.items():
        if len(values) < 2:
            continue
        avg = sum(values) / len(values)
        recent = values[-1]
        prev = values[-2]
        change_pct = round((recent - prev) / abs(prev) * 100, 1) if prev != 0 else 0

        if recent > avg * 1.1:
            direction = "上升"
        elif recent < avg * 0.9:
            direction = "下降"
        else:
            direction = "平稳"

        trend[key] = {
            "direction": direction,
            "latest": recent,
            "previous": prev,
            "change_pct": change_pct,
            "avg": round(avg, 2),
            "min": min(values),
            "max": max(values),
        }

    return {"dates": dates, "data": series, "trend": trend, "count": len(records)}


def detect_sentiment_anomaly(
    threshold_pct: float = 50.0,
    end_date: Optional[str] = None,
) -> dict:
    """检测情绪异常 — 当日指标相对 N 日均值的突变

    Args:
        threshold_pct: 异常阈值（百分比，默认50%）
        end_date: 截止日期

    Returns:
        {
            anomalies: [{field, value, avg, change_pct, severity}],
            risk_level: low|medium|high,
        }
    """
    trend = get_sentiment_trend(days=5, end_date=end_date)
    if not trend.get("trend"):
        return {"anomalies": [], "risk_level": "low", "note": "数据不足"}

    anomalies = []
    for field, info in trend["trend"].items():
        change_pct = abs(info.get("change_pct", 0))
        if change_pct >= threshold_pct:
            severity = "high" if change_pct >= 100 else ("medium" if change_pct >= 70 else "low")
            anomalies.append({
                "field": field,
                "value": info["latest"],
                "avg": info["avg"],
                "change_pct": info["change_pct"],
                "severity": severity,
            })

    risk_level = "high" if any(a["severity"] == "high" for a in anomalies) else (
        "medium" if any(a["severity"] == "medium" for a in anomalies) else "low"
    )

    return {"anomalies": anomalies, "risk_level": risk_level}


def store_stock_sentiment(date: str, code: str, **kwargs) -> dict:
    """存储个股情绪数据（龙虎榜/涨停/跌停标记等）"""
    date = date or _today_str()
    data = {k: v for k, v in kwargs.items() if v is not None}
    data["updated_at"] = datetime.now().isoformat()

    conn = _get_conn()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO stock_sentiment (date, code, data) VALUES (?, ?, ?)",
            (date, code, json.dumps(data, ensure_ascii=False, default=str)),
        )
        conn.commit()
    finally:
        conn.close()
    return {"date": date, "code": code, "stored": True}


def get_stock_sentiment(code: str, days: int = 5) -> list:
    """获取个股最近 N 天的情绪数据"""
    end = _today_str()
    start_dt = datetime.strptime(end, "%Y-%m-%d") - timedelta(days=days + 3)
    start = start_dt.strftime("%Y-%m-%d")

    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT date, data FROM stock_sentiment WHERE code = ? AND date >= ? AND date <= ? ORDER BY date",
            (code, start, end),
        ).fetchall()
    finally:
        conn.close()

    return [
        {"date": row["date"], **json.loads(row["data"])}
        for row in rows[-days:]
    ]
