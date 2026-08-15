#!/usr/bin/env python3
"""加密货币数据源 — Kraken Public API（移植自 Gateway sources/binance.ts）

注意: Gateway 的 binance.ts 实际走 Kraken（Binance 从 CF 被屏蔽 403，本地也需验证）。
Kraken 公开 API 无需 key，本地实测 200 ✅。
"""
import json
import urllib.request
import urllib.parse

KRAKEN_BASE = "https://api.kraken.com"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"

# 用户友好名 → Kraken pair
SYMBOL_MAP = {
    "BTC": "XBT", "BTCUSDT": "XBTUSD", "BTCUSD": "XBTUSD", "BTC-USDT": "XBTUSD", "BTC-USD": "XBTUSD",
    "ETH": "ETH", "ETHUSDT": "ETHUSD", "ETHUSD": "ETHUSD", "ETH-USDT": "ETHUSD", "ETH-USD": "ETHUSD",
    "SOL": "SOL", "SOLUSDT": "SOLUSD", "SOLUSD": "SOLUSD", "SOL-USDT": "SOLUSD", "SOL-USD": "SOLUSD",
    "XRP": "XRP", "XRPUSDT": "XRPUSD", "XRPUSD": "XRPUSD",
    "ADA": "ADA", "ADAUSDT": "ADAUSD", "ADAUSD": "ADAUSD",
    "DOT": "DOT", "DOTUSDT": "DOTUSD", "DOTUSD": "DOTUSD",
    "LINK": "LINK", "LINKUSDT": "LINKUSD", "LINKUSD": "LINKUSD",
    "AVAX": "AVAX", "AVAXUSDT": "AVAXUSD", "AVAXUSD": "AVAXUSD",
    "DOGE": "XDG", "DOGEUSDT": "XDGUSD", "DOGEUSD": "XDGUSD", "DOGE-USD": "XDGUSD",
    "LTC": "LTC", "LTCUSDT": "LTCUSD", "LTCUSD": "LTCUSD",
    "UNI": "UNI", "UNIUSDT": "UNIUSD", "UNIUSD": "UNIUSD",
}


def _norm(symbol: str) -> str:
    """归一化 symbol → Kraken pair"""
    s = (symbol or "").strip().upper().replace("/", "-").replace(" ", "")
    if s in SYMBOL_MAP:
        return SYMBOL_MAP[s]
    # 直接 Kraken 格式
    return s


def _kraken_get(path: str, timeout: float = 12.0):
    req = urllib.request.Request(f"{KRAKEN_BASE}{path}", headers={
        "User-Agent": UA, "Accept": "application/json",
    })
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def get_crypto_quote(symbol: str) -> dict:
    """加密币实时行情"""
    pair = _norm(symbol)
    try:
        d = _kraken_get(f"/0/public/Ticker?pair={pair}")
        if d.get("error"):
            return {"symbol": symbol, "error": "; ".join(d["error"])}
        result = d.get("result") or {}
        if not result:
            return {"symbol": symbol, "error": f"未找到 {pair}"}
        # 取第一个 pair 数据
        info = next(iter(result.values()))
        price = float(info.get("c", ["0"])[0])
        open24 = float(info.get("o", "0"))
        prev_close = float(info.get("p", ["0"])[0])
        change_pct = round((price - open24) / open24 * 100, 2) if open24 else 0
        return {
            "symbol": symbol,
            "pair": pair,
            "price": price,
            "change_pct": change_pct,
            "high": float(info.get("h", ["0"])[0]),
            "low": float(info.get("l", ["0"])[0]),
            "volume": float(info.get("v", ["0"])[0]),
            "source": "kraken",
        }
    except Exception as e:
        return {"symbol": symbol, "error": f"Kraken 接口异常: {e}"}


def get_crypto_quotes(symbols: str) -> dict:
    """批量加密币行情（逗号分隔）"""
    syms = [s.strip() for s in (symbols or "").split(",") if s.strip()]
    if not syms:
        return {"error": "symbols 不能为空", "quotes": []}
    quotes = []
    for s in syms[:10]:
        q = get_crypto_quote(s)
        if not q.get("error"):
            quotes.append(q)
    return {"quotes": quotes, "count": len(quotes)}


def get_crypto_kline(symbol: str, interval: str = "1d", limit: int = 60) -> dict:
    """加密币K线（Kraken OHLC）"""
    pair = _norm(symbol)
    # Kraken interval 分钟
    iv_map = {"1m": 1, "5m": 5, "15m": 15, "30m": 30, "1h": 60, "4h": 240, "1d": 1440, "1w": 10080}
    iv = iv_map.get(interval, 1440)
    try:
        d = _kraken_get(f"/0/public/OHLC?pair={pair}&interval={iv}")
        if d.get("error"):
            return {"symbol": symbol, "error": "; ".join(d["error"])}
        result = d.get("result") or {}
        if not result:
            return {"symbol": symbol, "error": f"未找到 {pair}"}
        rows = next(iter(result.values()))  # [time, open, high, low, close, vwap, volume, count]
        records = []
        for r in rows[-limit:]:
            records.append({
                "time": r[0],
                "date": __import__("datetime").datetime.utcfromtimestamp(r[0]).strftime("%Y-%m-%d %H:%M"),
                "open": float(r[1]),
                "high": float(r[2]),
                "low": float(r[3]),
                "close": float(r[4]),
                "volume": float(r[6]),
            })
        return {"symbol": symbol, "pair": pair, "interval": interval, "count": len(records), "records": records}
    except Exception as e:
        return {"symbol": symbol, "error": f"Kraken 接口异常: {e}"}


def get_top_crypto(sort_by: str = "volume", limit: int = 10) -> dict:
    """热门加密币排行（Kraken 主流币）"""
    majors = ["XBTUSD", "ETHUSD", "SOLUSD", "XRPUSD", "ADAUSD", "DOTUSD",
              "LINKUSD", "AVAXUSD", "XDGUSD", "LTCUSD", "UNIUSD", "BCHUSD"]
    quotes = []
    for pair in majors[:max(limit, 10)]:
        try:
            d = _kraken_get(f"/0/public/Ticker?pair={pair}")
            result = d.get("result") or {}
            if not result:
                continue
            info = next(iter(result.values()))
            price = float(info.get("c", ["0"])[0])
            open24 = float(info.get("o", "0"))
            vol = float(info.get("v", ["0"])[1])  # 24h volume
            change_pct = round((price - open24) / open24 * 100, 2) if open24 else 0
            quotes.append({
                "symbol": pair.replace("XBT", "BTC").replace("XDG", "DOGE").replace("USD", "USDT"),
                "price": price,
                "change_pct": change_pct,
                "volume_24h": vol,
                "source": "kraken",
            })
        except Exception:
            continue
    if sort_by == "volume":
        quotes.sort(key=lambda x: -x.get("volume_24h", 0))
    else:
        quotes.sort(key=lambda x: -x.get("change_pct", 0))
    return {"quotes": quotes[:limit], "count": len(quotes[:limit])}
