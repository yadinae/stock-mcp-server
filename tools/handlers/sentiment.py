#!/usr/bin/env python3
"""Sentiment tool handlers — 情绪存储、趋势查询、异常检测。"""
from __future__ import annotations

import json

from core.sentiment import (
    store_daily_sentiment,
    get_daily_sentiment,
    get_sentiment_trend,
    detect_sentiment_anomaly,
    store_stock_sentiment,
    get_stock_sentiment,
)


def register(mcp) -> None:
    @mcp.tool(name="sentiment_store")
    def tool_sentiment_store(
        limit_up: int = 0,
        limit_down: int = 0,
        streak_high: int = 0,
        up_ratio: int = 0,
        down_ratio: int = 0,
        total_amount: float = 0,
        breadth: float = 0,
        date: str = "",
        extra: str = "",
    ) -> str:
        """存储每日市场情绪快照

        Args:
            limit_up: 涨停数
            limit_down: 跌停数
            streak_high: 连板最高高度
            up_ratio: 上涨家数
            down_ratio: 下跌家数
            total_amount: 总成交额（亿）
            breadth: 市场宽度（0~1）
            date: 日期 YYYY-MM-DD（默认今天）
            extra: 额外指标 JSON（可选）
        """
        kwargs = {}
        if limit_up: kwargs["limit_up"] = limit_up
        if limit_down: kwargs["limit_down"] = limit_down
        if streak_high: kwargs["streak_high"] = streak_high
        if up_ratio: kwargs["up_ratio"] = up_ratio
        if down_ratio: kwargs["down_ratio"] = down_ratio
        if total_amount: kwargs["total_amount"] = total_amount
        if breadth: kwargs["breadth"] = breadth
        if extra:
            try:
                kwargs.update(json.loads(extra))
            except Exception:
                pass
        result = store_daily_sentiment(date=date or None, **kwargs)
        return json.dumps(result, ensure_ascii=False)

    @mcp.tool(name="sentiment_get")
    def tool_sentiment_get(date: str = "") -> str:
        """获取指定日期的情绪快照

        Args:
            date: 日期 YYYY-MM-DD（默认今天）
        """
        result = get_daily_sentiment(date=date or None)
        return json.dumps(result, ensure_ascii=False, default=str)

    @mcp.tool(name="sentiment_trend")
    def tool_sentiment_trend(days: int = 7) -> str:
        """情绪趋势分析 — 最近 N 天指标变化方向

        Args:
            days: 回溯天数（默认7）
        """
        result = get_sentiment_trend(days=days)
        return json.dumps(result, ensure_ascii=False, default=str)

    @mcp.tool(name="sentiment_anomaly")
    def tool_sentiment_anomaly(threshold_pct: float = 50.0) -> str:
        """情绪异常检测 — 当日指标突变告警

        Args:
            threshold_pct: 异常阈值百分比（默认50%）
        """
        result = detect_sentiment_anomaly(threshold_pct=threshold_pct)
        return json.dumps(result, ensure_ascii=False, default=str)

    @mcp.tool(name="sentiment_stock_store")
    def tool_sentiment_stock_store(date: str, code: str, data: str = "{}") -> str:
        """存储个股情绪数据

        Args:
            date: 日期 YYYY-MM-DD
            code: 股票代码
            data: 情绪数据 JSON（如 {"limit_up": true, "board_type": "首板"}）
        """
        try:
            d = json.loads(data) if isinstance(data, str) else data
        except Exception:
            d = {}
        result = store_stock_sentiment(date, code, **d)
        return json.dumps(result, ensure_ascii=False)

    @mcp.tool(name="sentiment_stock_get")
    def tool_sentiment_stock_get(code: str, days: int = 5) -> str:
        """获取个股最近 N 天的情绪数据

        Args:
            code: 股票代码
            days: 天数
        """
        result = get_stock_sentiment(code, days=days)
        return json.dumps(result, ensure_ascii=False, default=str)
