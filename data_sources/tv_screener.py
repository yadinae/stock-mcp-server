"""
TradingView Screener 数据源 — 基于 tradingview-screener 库

优势：
- 一步到位拿到 A 股 + 技术指标（RSI/MACD/MA/ADX 等）
- SQL-like 服务端过滤，无需拉全量再本地算
- 支持多周期（1m/5m/1d/1w 等）

参考：https://github.com/shner-elmo/TradingView-Screener (MIT)
"""
from __future__ import annotations

import logging
from typing import List, Optional

logger = logging.getLogger("stock-mcp.tv_screener")

# 延迟导入，避免未安装时阻塞启动
_ts = None


def _get_ts():
    global _ts
    if _ts is None:
        try:
            from tradingview_screener import Query, col, stocks
            _ts = {"Query": Query, "col": col, "stocks": stocks}
        except ImportError:
            logger.warning("tradingview-screener not installed, pip install tradingview-screener")
            return None
    return _ts


def fetch_a_shares(
    limit: int = 5500,
    min_market_cap: float = 0,
    min_volume: float = 0,
    include_indicators: bool = True,
) -> List[dict]:
    """
    从 TradingView Screener 获取 A 股列表（带技术指标）

    Args:
        limit: 最大返回数量
        min_market_cap: 最小市值过滤（0=不过滤）
        min_volume: 最小成交量过滤
        include_indicators: 是否包含技术指标（RSI/MACD/MA 等）

    Returns:
        [{code, name, price, change_pct, volume, market_cap,
          rsi, macd, macd_signal, ma50, ma200, adx, atr,
          volume_ratio, source}]
    """
    ts = _get_ts()
    if ts is None:
        return []

    Query = ts["Query"]
    col = ts["col"]
    stocks_fn = ts["stocks"]

    try:
        # 构建查询
        q = stocks_fn("china")

        # 选择字段
        fields = [
            "name", "close", "change", "change_abs",
            "volume", "market_cap_basic",
        ]

        if include_indicators:
            fields.extend([
                "RSI", "RSI[1]",           # RSI 当前 + 前值
                "MACD.macd", "MACD.signal", # MACD 线 + 信号线
                "ADX", "ADX DI+", "ADX DI-", # 趋势强度
                "ATR",                       # 真实波幅
                "OBV",                       # 能量潮
                "close|5", "close|15", "close|60",  # 多周期收盘价
                "Volatility.D",             # 日波动率
                "relative_volume_10d_calc", # 相对成交量
            ])

        q = q.select(*fields)

        # 过滤条件
        if min_market_cap > 0:
            q = q.where(col("market_cap_basic") > min_market_cap)
        if min_volume > 0:
            q = q.where(col("volume") > min_volume)

        # 排序 + 限制
        q = q.order_by("volume", ascending=False).limit(limit)

        # 执行查询
        total, df = q.get_scanner_data()

        if df is None or df.empty:
            logger.warning("TV Screener returned empty result")
            return []

        # 转换为标准格式
        stocks = []
        for _, row in df.iterrows():
            ticker = row.get("ticker", "")
            # 提取纯代码: "SSE:600519" → "600519"
            code = ticker.split(":")[-1] if ":" in str(ticker) else str(ticker)

            stock = {
                "code": code,
                "name": str(row.get("name", "")),
                "price": _safe_float(row.get("close")),
                "change_pct": _safe_float(row.get("change")),
                "change_amount": _safe_float(row.get("change_abs")),
                "volume": _safe_float(row.get("volume")),
                "amount": _calc_amount(row),
                "market_cap": _safe_float(row.get("market_cap_basic")),
                "source": "tv_screener",
            }

            if include_indicators:
                stock.update({
                    "rsi": _safe_float(row.get("RSI")),
                    "rsi_prev": _safe_float(row.get("RSI[1]")),
                    "macd": _safe_float(row.get("MACD.macd")),
                    "macd_signal": _safe_float(row.get("MACD.signal")),
                    "adx": _safe_float(row.get("ADX")),
                    "adx_di_plus": _safe_float(row.get("ADX DI+")),
                    "adx_di_minus": _safe_float(row.get("ADX DI-")),
                    "atr": _safe_float(row.get("ATR")),
                    "obv": _safe_float(row.get("OBV")),
                    "close_5m": _safe_float(row.get("close|5")),
                    "close_15m": _safe_float(row.get("close|15")),
                    "close_1h": _safe_float(row.get("close|60")),
                    "volatility_d": _safe_float(row.get("Volatility.D")),
                    "relative_volume": _safe_float(row.get("relative_volume_10d_calc")),
                })

            stocks.append(stock)

        logger.info(
            "Fetched %d A-shares via TV Screener (total in market: %d, indicators: %s)",
            len(stocks), total, "on" if include_indicators else "off",
        )
        return stocks

    except Exception as e:
        logger.warning("TV Screener failed: %s", e)
        return []


def scan_with_filter(
    filters: Optional[dict] = None,
    limit: int = 100,
) -> List[dict]:
    """
    高级筛选：直接在 TV 服务端做过滤

    Args:
        filters: 筛选条件字典，支持:
            - min_rsi / max_rsi: RSI 范围
            - min_adx: ADX 最小值（趋势强度）
            - macd_cross_up: MACD 金叉（macd > signal）
            - min_volume_ratio: 相对成交量最小值
            - min_market_cap: 最小市值
        limit: 最大返回数

    Returns:
        筛选后的股票列表
    """
    ts = _get_ts()
    if ts is None:
        return []

    Query = ts["Query"]
    col = ts["col"]
    stocks_fn = ts["stocks"]

    try:
        q = stocks_fn("china").select(
            "name", "close", "change", "volume", "market_cap_basic",
            "RSI", "MACD.macd", "MACD.signal", "ADX",
            "relative_volume_10d_calc",
        )

        if filters:
            if "min_rsi" in filters:
                q = q.where(col("RSI") > filters["min_rsi"])
            if "max_rsi" in filters:
                q = q.where(col("RSI") < filters["max_rsi"])
            if "min_adx" in filters:
                q = q.where(col("ADX") > filters["min_adx"])
            if "macd_cross_up":
                q = q.where(col("MACD.macd") > col("MACD.signal"))
            if "min_volume_ratio" in filters:
                q = q.where(col("relative_volume_10d_calc") > filters["min_volume_ratio"])
            if "min_market_cap" in filters:
                q = q.where(col("market_cap_basic") > filters["min_market_cap"])

        q = q.order_by("volume", ascending=False).limit(limit)
        total, df = q.get_scanner_data()

        if df is None or df.empty:
            return []

        stocks = []
        for _, row in df.iterrows():
            ticker = row.get("ticker", "")
            code = ticker.split(":")[-1] if ":" in str(ticker) else str(ticker)
            stocks.append({
                "code": code,
                "name": str(row.get("name", "")),
                "price": _safe_float(row.get("close")),
                "change_pct": _safe_float(row.get("change")),
                "volume": _safe_float(row.get("volume")),
                "market_cap": _safe_float(row.get("market_cap_basic")),
                "rsi": _safe_float(row.get("RSI")),
                "macd": _safe_float(row.get("MACD.macd")),
                "macd_signal": _safe_float(row.get("MACD.signal")),
                "adx": _safe_float(row.get("ADX")),
                "relative_volume": _safe_float(row.get("relative_volume_10d_calc")),
                "source": "tv_screener_scan",
            })

        logger.info("TV Screener scan: %d results (total: %d)", len(stocks), total)
        return stocks

    except Exception as e:
        logger.warning("TV Screener scan failed: %s", e)
        return []


# ── Helpers ──

def _safe_float(val) -> Optional[float]:
    """安全转换为 float，NaN/None → None"""
    if val is None:
        return None
    try:
        import math
        f = float(val)
        return None if math.isnan(f) else f
    except (ValueError, TypeError):
        return None


def _calc_amount(row) -> float:
    """估算成交额 = 收盘价 × 成交量"""
    price = _safe_float(row.get("close"))
    volume = _safe_float(row.get("volume"))
    if price and volume:
        return price * volume
    return 0
