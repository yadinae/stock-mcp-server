#!/usr/bin/env python3
"""加密货币数据源 — Binance 公开 API（VPS 实测 2026-08-15: 全部 200 ✅）

对比: CF Workers 出口被 Binance 风控 403；阿里云 VPS IP 未被拉黑。
因此加密工具改走 Binance（USDT计价/币种全/热门榜完整），Kraken 保留为兜底。

接口:
- GET /api/v3/ticker/price?symbol=BTCUSDT          实时价
- GET /api/v3/klines?symbol=BTCUSDT&interval=1d     K线
- GET /api/v3/ticker/24hr?symbol=                  24h行情(含涨跌幅/高低/量)
- GET /api/v3/ticker/24hr                          全市场热门榜
"""
import json
import urllib.request

BINANCE_API = "https://api.binance.com"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"


def _binance_get(path: str, timeout: float = 12.0):
    req = urllib.request.Request(f"{BINANCE_API}{path}", headers={
        "User-Agent": UA, "Accept": "application/json",
    })
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def norm_symbol(symbol: str) -> str:
    """归一化币种代码 → Binance 格式"""
    s = (symbol or "").strip().upper().replace("/", "").replace("-", "").replace(" ", "")
    if s.endswith("USDT") or s.endswith("USD") or s in ("BTC", "ETH", "SOL", "BNB", "XRP", "ADA", "DOGE"):
        if s == "BTC":
            return "BTCUSDT"
        if s == "ETH":
            return "ETHUSDT"
        if s == "SOL":
            return "SOLUSDT"
        if s == "BNB":
            return "BNBUSDT"
        if s == "XRP":
            return "XRPUSDT"
        if s == "ADA":
            return "ADAUSDT"
        if s == "DOGE":
            return "DOGEUSDT"
        if s.endswith("USD") and not s.endswith("USDT"):
            return s + "T"
        return s
    return s + "USDT" if s and not s.endswith("USDT") else s


def get_crypto_quote(symbol: str) -> dict:
    """加密币实时行情（Binance 主源）"""
    s = norm_symbol(symbol)
    try:
        d = _binance_get(f"/api/v3/ticker/24hr?symbol={s}")
        return {
            "symbol": symbol,
            "pair": s,
            "price": float(d.get("lastPrice") or 0),
            "change_pct": round(float(d.get("priceChangePercent") or 0), 2),
            "high": float(d.get("highPrice") or 0),
            "low": float(d.get("lowPrice") or 0),
            "volume": float(d.get("volume") or 0),
            "quote_volume": float(d.get("quoteVolume") or 0),
            "source": "binance",
        }
    except Exception as e:
        # Binance 失败 → Kraken 兜底
        try:
            from data_sources import kraken
            return kraken.get_crypto_quote(symbol)
        except Exception:
            return {"symbol": symbol, "error": f"Binance/Kraken 均失败: {e}"}


def get_crypto_quotes(symbols: str) -> dict:
    """批量加密币行情（逗号分隔，最多10个）"""
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
    """加密币K线（Binance klines）"""
    s = norm_symbol(symbol)
    iv_map = {"1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m", "1h": "1h", "4h": "4h",
              "1d": "1d", "1w": "1w", "1M": "1M"}
    iv = iv_map.get(interval, "1d")
    try:
        rows = _binance_get(f"/api/v3/klines?symbol={s}&interval={iv}&limit={min(limit, 500)}")
        import datetime
        records = [{
            "time": r[0],
            "date": datetime.datetime.utcfromtimestamp(r[0] / 1000).strftime("%Y-%m-%d %H:%M"),
            "open": float(r[1]),
            "high": float(r[2]),
            "low": float(r[3]),
            "close": float(r[4]),
            "volume": float(r[5]),
        } for r in rows]
        return {"symbol": symbol, "pair": s, "interval": iv, "count": len(records), "records": records, "source": "binance"}
    except Exception as e:
        try:
            from data_sources import kraken
            return kraken.get_crypto_kline(symbol, interval, limit)
        except Exception:
            return {"symbol": symbol, "error": f"Binance/Kraken 均失败: {e}"}


def get_top_crypto(sort_by: str = "volume", limit: int = 10) -> dict:
    """热门加密币排行（Binance 24hr 全市场，按成交量）"""
    try:
        rows = _binance_get("/api/v3/ticker/24hr")
        # 过滤稳定币和衍生对
        stable = ("USDC", "USDP", "TUSD", "FDUSD", "BUSD", "DAI", "EUR", "GBP", "JPY", "BRL", "TRY")
        filtered = []
        for r in rows:
            sym = r.get("symbol", "")
            if not sym.endswith("USDT"):
                continue
            base = sym[:-4]
            if base in stable or "USD" == base:
                continue
            filtered.append(r)
        quotes = [{
            "symbol": r.get("symbol", ""),
            "price": float(r.get("lastPrice") or 0),
            "change_pct": round(float(r.get("priceChangePercent") or 0), 2),
            "volume_24h": float(r.get("quoteVolume") or 0),
            "source": "binance",
        } for r in filtered]
        if sort_by == "volume":
            quotes.sort(key=lambda x: -x.get("volume_24h", 0))
        else:
            quotes.sort(key=lambda x: -x.get("change_pct", 0))
        return {"quotes": quotes[:limit], "count": len(quotes[:limit]), "source": "binance"}
    except Exception as e:
        try:
            from data_sources import kraken
            return kraken.get_top_crypto(sort_by, limit)
        except Exception:
            return {"error": f"Binance/Kraken 均失败: {e}", "quotes": []}
