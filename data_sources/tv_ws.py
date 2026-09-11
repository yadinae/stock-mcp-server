"""
TradingView WebSocket 数据源 — Crypto 实时行情

通过 wss://data.tradingview.com/socket.io/websocket 获取:
- 实时报价 (quote_create_session)
- K 线数据 (chart_create_session + create_series)

关键协议知识:
- 格式: ~m~{len}~m~{json}
- 一次 recv 可能返回多条拼接消息
- chart_create_session + resolve_symbol + create_series 需一起发送
"""
from __future__ import annotations

import json
import logging
import random
import string
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger("stock-mcp.tv_ws")

WS_URL = "wss://data.tradingview.com/socket.io/websocket"
WS_HEADERS = {"Origin": "https://data.tradingview.com"}


def _gen_session(prefix: str = "cs") -> str:
    rnd = "".join(random.choices(string.ascii_lowercase, k=12))
    return f"{prefix}_{rnd}"


def _parse_tv_messages(raw: str) -> list[dict]:
    """解析 TV WS 协议：一次 recv 可能返回多条拼接消息。"""
    msgs = []
    i = 0
    while i < len(raw):
        idx = raw.find("~m~", i)
        if idx == -1:
            break
        start = idx + 3
        end = raw.find("~m~", start)
        if end == -1:
            payload = raw[start:]
            i = len(raw)
        else:
            payload = raw[start:end]
            i = end
        parts = payload.split("~m~", 1)
        json_str = parts[-1]
        try:
            d = json.loads(json_str)
            if isinstance(d, dict):
                msgs.append(d)
        except Exception:
            pass
    return msgs


def _make_msg(method: str, params: list) -> str:
    msg = json.dumps({"m": method, "p": params}, separators=(",", ":"))
    return f"~m~{len(msg)}~m~{msg}"


def _ws_connect():
    """创建 TV WS 连接并完成 auth。返回 (ws, drain_fn)。"""
    from websocket import create_connection
    ws = create_connection(
        WS_URL, header=WS_HEADERS, timeout=8, sslopt={"cert_reqs": 0},
    )
    # Auth
    for method, params in [
        ("set_auth_token", ["unauthorized_user_token"]),
        ("set_locale", ["en", "US"]),
    ]:
        ws.send(_make_msg(method, params))
    # Drain auth responses
    ws.settimeout(2)
    for _ in range(3):
        try:
            ws.recv()
        except Exception:
            break
    return ws


def _ws_recv_all(ws, timeout: float = 8, max_rounds: int = 10) -> list[dict]:
    """接收所有 TV WS 消息。连续2次超时则认为数据已收完。"""
    all_msgs = []
    consecutive_timeouts = 0
    ws.settimeout(3)  # 每轮最多等 3s
    for _ in range(max_rounds):
        try:
            raw = ws.recv()
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8", errors="replace")
            parsed = _parse_tv_messages(raw)
            if parsed:
                all_msgs.extend(parsed)
                consecutive_timeouts = 0
            else:
                consecutive_timeouts += 1
        except Exception:
            consecutive_timeouts += 1
        if consecutive_timeouts >= 1:
            break
    return all_msgs


# ── Public API ─────────────────────────────────────────────────────────────

def get_crypto_quote(symbol: str) -> dict[str, Any]:
    """获取加密货币实时报价。"""
    sym = symbol.upper().replace("/", "").replace("-", "").replace(" ", "")
    if not any(sym.endswith(s) for s in ("USDT", "USD", "BUSD", "USDC")):
        sym = sym + "USDT"
    tv_symbol = f"BINANCE:{sym}"

    try:
        ws = _ws_connect()
        qs = _gen_session("qs")
        ws.send(_make_msg("quote_create_session", [qs]))
        sym_json = json.dumps({"symbol": tv_symbol, "adjustment": "splits"})
        ws.send(_make_msg("quote_add_symbols", [qs, "=" + sym_json]))

        msgs = _ws_recv_all(ws, timeout=8)
        ws.close()

        for m in msgs:
            if m.get("m") == "qsd":
                p = m.get("p", [])
                data = p[1] if len(p) > 1 and isinstance(p[1], dict) else {}
                v = data.get("v", {})
                if v.get("close"):
                    return {
                        "symbol": sym,
                        "price": v.get("close"),
                        "change_24h": v.get("change_percent", 0),
                        "volume": v.get("volume", 0),
                        "high": v.get("high", 0),
                        "low": v.get("low", 0),
                        "source": "tradingview_ws",
                        "exchange": "binance",
                    }

        return {"symbol": sym, "error": "未获取到报价", "source": "tradingview_ws"}

    except Exception as e:
        return {"symbol": sym, "error": str(e), "source": "tradingview_ws"}


def get_crypto_kline(
    symbol: str,
    timeframe: str = "1D",
    count: int = 100,
) -> dict[str, Any]:
    """获取加密货币 K 线数据。"""
    sym = symbol.upper().replace("/", "").replace("-", "").replace(" ", "")
    if not any(sym.endswith(s) for s in ("USDT", "USD", "BUSD", "USDC")):
        sym = sym + "USDT"
    tv_symbol = f"BINANCE:{sym}"

    tf_map = {
        "1m": "1", "5m": "5", "15m": "15", "30m": "30",
        "1h": "60", "4h": "240", "1D": "1D", "1W": "1W", "1M": "1M",
    }
    tv_tf = tf_map.get(timeframe, timeframe)

    try:
        ws = _ws_connect()
        cs = _gen_session("cs")

        # 一次性发送所有请求
        ws.send(_make_msg("chart_create_session", [cs, ""]))
        sym_json = json.dumps({"symbol": tv_symbol, "adjustment": "splits"})
        ws.send(_make_msg("resolve_symbol", [cs, "sds_sym_1", "=" + sym_json]))
        ws.send(_make_msg("create_series", [cs, "sds_1", "s1", "sds_sym_1", tv_tf, count, ""]))

        # 接收数据
        all_msgs = _ws_recv_all(ws, timeout=8)
        ws.close()

        # 提取 K 线
        candles = []
        for m in all_msgs:
            mt = m.get("m", "")
            if mt in ("timescale_update", "du"):
                p = m.get("p", [])
                for item in (p[1:] if len(p) > 1 else p):
                    if isinstance(item, dict):
                        for k, v in item.items():
                            if isinstance(v, dict) and "s" in v:
                                for bar in v["s"]:
                                    vals = bar.get("v", [])
                                    if len(vals) >= 6:
                                        ts = vals[0]
                                        candles.append({
                                            "date": datetime.fromtimestamp(
                                                ts, tz=timezone.utc
                                            ).strftime("%Y-%m-%d %H:%M"),
                                            "open": vals[1],
                                            "high": vals[2],
                                            "low": vals[3],
                                            "close": vals[4],
                                            "volume": vals[5],
                                        })

        if candles:
            return {
                "symbol": sym,
                "records": candles,
                "count": len(candles),
                "timeframe": timeframe,
                "source": "tradingview_ws",
            }
        return {"symbol": sym, "error": "未获取到 K 线数据", "source": "tradingview_ws"}

    except Exception as e:
        return {"symbol": sym, "error": str(e), "source": "tradingview_ws"}


def tv_ws_status() -> dict[str, Any]:
    """TV WebSocket 连接状态检查。"""
    try:
        ws = _ws_connect()
        ws.close()
        return {"status": "ok", "source": "tradingview_ws"}
    except Exception as e:
        return {"status": "error", "error": str(e), "source": "tradingview_ws"}
