"""Cryptocurrency tools (Binance + Kraken + TradingView WS)."""
from __future__ import annotations

import json

from data_sources import binance as binance_source


def register(mcp):
    """Register crypto tools."""

    @mcp.tool(name="get_crypto_quote")
    def get_crypto_quote(symbol: str) -> str:
        """数字货币实时行情（Binance 公开 API；失败自动降级 TradingView WS）。

        Args:
            symbol: 币种代码，如 BTCUSDT / ETHUSDT / SOLUSDT
        """
        result = binance_source.get_crypto_quote(symbol)
        if result.get("error"):
            try:
                from data_sources.tv_ws import get_crypto_quote as tv_quote
                tv_result = tv_quote(symbol)
                if not tv_result.get("error"):
                    return json.dumps(tv_result, ensure_ascii=False, default=str)
            except Exception:
                pass
        return json.dumps(result, ensure_ascii=False, default=str)

    @mcp.tool(name="get_crypto_quotes")
    def get_crypto_quotes(symbols: str) -> str:
        """批量数字货币实时行情（逗号分隔，最多10个）。

        Args:
            symbols: 逗号分隔的币种代码
        """
        return json.dumps(binance_source.get_crypto_quotes(symbols), ensure_ascii=False, default=str)

    @mcp.tool(name="get_crypto_kline")
    def get_crypto_kline(symbol: str, interval: str = "1d", limit: int = 60) -> str:
        """数字货币 K 线（Binance klines；失败自动降级 TradingView WS）。

        Args:
            symbol: 币种代码
            interval: 1m/5m/15m/30m/1h/4h/1d/1w/1M
            limit: 返回条数
        """
        result = binance_source.get_crypto_kline(symbol, interval, limit)
        if result.get("error"):
            try:
                from data_sources.tv_ws import get_crypto_kline as tv_kline
                tv_result = tv_kline(symbol, timeframe=interval, count=limit)
                if not tv_result.get("error"):
                    return json.dumps(tv_result, ensure_ascii=False, default=str)
            except Exception:
                pass
        return json.dumps(result, ensure_ascii=False, default=str)

    @mcp.tool(name="get_top_crypto")
    def get_top_crypto(sort_by: str = "volume", limit: int = 10) -> str:
        """热门数字货币排行（Binance 24hr 全市场）。

        Args:
            sort_by: volume(成交量) / change(涨跌幅)
            limit: 返回条数
        """
        return json.dumps(binance_source.get_top_crypto(sort_by, limit), ensure_ascii=False, default=str)

    @mcp.tool(name="get_tv_crypto_kline")
    def get_tv_crypto_kline(symbol: str, timeframe: str = "1D", count: int = 100) -> str:
        """TradingView WebSocket 加密货币 K 线（实时推送数据）。

        Args:
            symbol: 交易对，如 BTCUSDT / ETHUSDT
            timeframe: 1m/5m/15m/1h/4h/1D/1W/1M
            count: K 线数量
        """
        from data_sources.tv_ws import get_crypto_kline
        return json.dumps(get_crypto_kline(symbol, timeframe, count), ensure_ascii=False, default=str)

    @mcp.tool(name="tv_ws_status")
    def tv_ws_status() -> str:
        """TradingView WebSocket 连接状态检查。"""
        from data_sources.tv_ws import tv_ws_status
        return json.dumps(tv_ws_status(), ensure_ascii=False, default=str)
