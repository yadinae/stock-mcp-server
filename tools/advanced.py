#!/usr/bin/env python3
"""高级组合工具（2026-08-16 P2 补全，移植自 Gateway tools/technical_batch.ts / strategy_screener.ts / analyzer.ts / tdx_test.ts / tv_rest.ts）

全部基于本地已有能力组合，零新数据源：
- technical_batch_scan: 本地 get_kline + analyze_technical
- strategy_scan: 涨停梯队 + 热点题材 + 技术指标
- stock_score: 行情 + 技术 + 资金流多维评分
- stock_signals: 多因子信号聚合
- search_tradingview_market: TV REST + 东财 suggest 兜底
- tdx_test: mootdx TCP 连通测试
"""
import json
import time
import urllib.request
import urllib.parse

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"

# ─── search_tradingview_market: TV 代码搜索 ───

def search_tradingview_market(query: str = "", filter_type: str = ""):
    """搜索 TV 行情代码。TV REST scanner + 东财 suggest 兜底。"""
    query = (query or "").strip()
    if not query:
        return {"error": "query 不能为空"}

    # 主源: TV REST scanner 搜索
    try:
        payload = json.dumps({
            "filter": [{"left": "name", "operation": "match", "right": query}],
            "options": {"lang": "zh", "limit": 10},
            "markets": ["china"], "symbols": {"query": {"types": []}},
            "columns": ["name", "description", "close", "change", "change_abs", "market_cap_basic"],
        }).encode()
        req = urllib.request.Request("https://scanner.tradingview.com/china/scan",
                                     data=payload, headers={"User-Agent": UA, "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            d = json.loads(resp.read().decode("utf-8", "replace"))
        items = []
        for row in (d or {}).get("data") or []:
            s = row.get("s", "")
            vals = row.get("d") or []
            items.append({
                "symbol": s,  # e.g. SSE:600519
                "name": vals[0] if len(vals) > 0 else "",
                "description": vals[1] if len(vals) > 1 else "",
                "close": vals[2] if len(vals) > 2 else None,
                "change_pct": vals[3] if len(vals) > 3 else None,
            })
        if items:
            return {"query": query, "total": len(items), "results": items}
    except Exception:
        pass

    # 兜底: 东财 suggest
    try:
        url = ("https://searchapi.eastmoney.com/api/suggest/get?input="
               f"{urllib.parse.quote(query)}&type=14&token=D43BF722C8E33BDC906FB84D85E326E8&count=10")
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=10) as resp:
            d = json.loads(resp.read().decode("utf-8", "replace"))
        rows = (d or {}).get("QuotationCodeTable", {}).get("Data") or []
        items = [{
            "symbol": f"{r.get('Code', '')}", "name": r.get("Name", ""),
            "description": r.get("Classify", ""), "close": None, "change_pct": None,
        } for r in rows]
        return {"query": query, "total": len(items), "results": items, "source": "eastmoney_suggest"}
    except Exception as e:
        return {"query": query, "total": 0, "results": [], "error": str(e)[:120]}


# ─── technical_batch_scan: 批量技术指标扫描 ───

def technical_batch_scan(codes: str = "", days: int = 90, filter_str: str = ""):
    """批量技术指标扫描。codes 逗号分隔 ≤30 只。"""
    codes = [c.strip() for c in (codes or "").split(",") if c.strip()][:30]
    if not codes:
        return {"error": "codes 不能为空"}
    days = max(10, min(int(days or 90), 365))

    from data_sources import tencent
    from tools.technical import analyze as analyze_technical

    results = []
    for code in codes:
        try:
            kline = tencent.get_kline(code, days=days)
            records = kline.get("records", [])
            if not records:
                results.append({"code": code, "name": code, "error": kline.get("error", "无K线")})
                continue
            tech = analyze_technical(records, code)
            name = tech.get("name") or code
            results.append({
                "code": code, "name": name,
                "score": tech.get("score", 0),
                "trend": tech.get("trend", {}).get("status", ""),
                "macd": tech.get("macd", {}).get("signal", ""),
                "rsi": tech.get("rsi", {}).get("value", None),
                "boll": tech.get("bollinger", {}).get("position", ""),
                "volume_ratio": tech.get("volume", {}).get("volume_ratio", 0),
                "suggestion": tech.get("suggestion", ""),
                "close": tech.get("close", None),
            })
        except Exception as e:
            results.append({"code": code, "name": code, "error": str(e)[:100]})

    # 筛选
    if filter_str:
        try:
            parts = dict(p.split("=", 1) for p in filter_str.split(",") if "=" in p)
            filtered = []
            for r in results:
                if "error" in r:
                    continue
                ok = True
                if "macd" in parts and parts["macd"] in ("golden", "dead") and r["macd"] != parts["macd"]:
                    ok = False
                if "rsi" in parts:
                    v = r.get("rsi")
                    if v is None:
                        ok = False
                    elif parts["rsi"] == "oversold" and not (v < 30):
                        ok = False
                    elif parts["rsi"] == "overbought" and not (v > 70):
                        ok = False
                if "boll" in parts:
                    pos = r.get("boll", "")
                    if parts["boll"] == "upper" and "上轨" not in pos and "超买" not in pos:
                        ok = False
                    elif parts["boll"] == "lower" and "下轨" not in pos and "超卖" not in pos:
                        ok = False
                if "min_score" in parts and (r.get("score") or 0) < float(parts["min_score"]):
                    ok = False
                if "min_volume_ratio" in parts and (r.get("volume_ratio") or 0) < float(parts["min_volume_ratio"]):
                    ok = False
                if ok:
                    filtered.append(r)
            results = filtered
        except Exception as e:
            return {"error": f"筛选参数解析失败: {e}", "results": results}

    if "limit" in filter_str:
        try:
            n = int(filter_str.split("limit=")[1].split(",")[0])
            results = results[:n]
        except Exception:
            pass

    return {"total": len(results), "results": results}


# ─── strategy_scan: A股特色策略 ───

def strategy_scan(strategy: str = ""):
    """A股特色策略扫描。strategy: limit_up_ladder / limit_up_momentum / broken_board_reversal /
    volume_price_rise / oversold_rebound / ma_bullish / all"""
    strategy = (strategy or "").strip()
    if not strategy:
        return {"error": "strategy 不能为空"}

    # 数据提供者：涨停梯队 + 热点 + 技术指标
    from data_sources import em_market, tencent
    from tools.technical import analyze as analyze_technical

    tiers = []
    try:
        tier_data = em_market.get_limitup_tiers()
        # 结构: tiers = {首板: {count, stocks:[{code,name,consecutive_days,...}]}, 二连板: {...}, ...}
        tier_groups = tier_data.get("tiers") or {}
        for group_name, group in tier_groups.items():
            for t in group.get("stocks") or []:
                tiers.append({
                    "code": t.get("code", ""),
                    "name": t.get("name", ""),
                    "type": group_name,
                    "consecutive_days": t.get("consecutive_days") or 1,
                    "change_pct": t.get("change_pct", 0),
                    "turnover": t.get("turnover", 0),
                    "volume_ratio": t.get("volume_ratio", 0),
                })
    except Exception:
        tiers = []
    hot = []
    try:
        hot_data = em_market.get_market_hot_stocks()
        hot = hot_data.get("stocks") or []
    except Exception:
        hot = []
    tier_names = {t.get("code", ""): t.get("name", "") for t in tiers}

    def run(id_: str):
        out = []
        if id_ == "limit_up_ladder":
            for t in tiers:
                if (t.get("consecutive_days") or 0) >= 2:
                    out.append({"code": t.get("code"), "name": t.get("name"),
                                "consecutive_days": t.get("consecutive_days"),
                                "change_pct": t.get("change_pct"), "turnover": t.get("turnover")})
            out.sort(key=lambda x: x.get("consecutive_days") or 0, reverse=True)
        elif id_ == "limit_up_momentum":
            for t in tiers:
                if (t.get("consecutive_days") or 0) >= 2 and (t.get("turnover") or 0) > 8:
                    out.append({"code": t.get("code"), "name": t.get("name"),
                                "consecutive_days": t.get("consecutive_days"),
                                "change_pct": t.get("change_pct"), "turnover": t.get("turnover")})
        elif id_ == "broken_board_reversal":
            hot_codes = {str(h.get("code")) for h in hot}
            for t in tiers:
                if t.get("type") == "炸板" and str(t.get("code")) in hot_codes:
                    out.append({"code": t.get("code"), "name": t.get("name"),
                                "reason": "炸板+热点题材"})
        elif id_ == "volume_price_rise":
            for t in tiers:
                if (t.get("volume_ratio") or 0) >= 1.5 and (t.get("change_pct") or 0) >= 3:
                    out.append({"code": t.get("code"), "name": t.get("name"),
                                "volume_ratio": t.get("volume_ratio"), "change_pct": t.get("change_pct")})
        elif id_ == "oversold_rebound":
            for t in tiers[:15]:
                try:
                    kline = tencent.get_kline(t.get("code", ""), days=60)
                    tech = analyze_technical(kline.get("records", []), t.get("code", ""))
                    rsi = tech.get("rsi", {}).get("value")
                    if rsi is not None and rsi < 30:
                        out.append({"code": t.get("code"), "name": t.get("name"), "rsi": rsi})
                except Exception:
                    continue
        elif id_ == "ma_bullish":
            for t in tiers[:15]:
                try:
                    kline = tencent.get_kline(t.get("code", ""), days=60)
                    tech = analyze_technical(kline.get("records", []), t.get("code", ""))
                    status = tech.get("trend", {}).get("status", "")
                    if "多头" in status:
                        out.append({"code": t.get("code"), "name": t.get("name"),
                                    "trend": status, "score": tech.get("score")})
                except Exception:
                    continue
        # 名称补全
        for x in out:
            if not x.get("name") and x.get("code") in tier_names:
                x["name"] = tier_names[x["code"]]
        return out

    if strategy == "all":
        result = {}
        for s in ["limit_up_ladder", "limit_up_momentum", "broken_board_reversal",
                  "volume_price_rise", "oversold_rebound", "ma_bullish"]:
            result[s] = run(s)
        return {"strategy": "all", "results": result}
    else:
        if strategy not in ["limit_up_ladder", "limit_up_momentum", "broken_board_reversal",
                            "volume_price_rise", "oversold_rebound", "ma_bullish"]:
            return {"error": f"未知策略: {strategy}"}
        out = run(strategy)
        return {"strategy": strategy, "total": len(out), "results": out}


# ─── stock_score: 个股综合评分 ───

def stock_score(code: str):
    """个股综合评分 — 估值 + 技术面 + 资金流多维评分 0-100"""
    code = code.strip()
    if not code:
        return {"error": "股票代码不能为空"}

    from data_sources import tencent, em_market
    from tools.technical import analyze as analyze_technical

    result = {"code": code, "score": 0, "dimensions": {}, "suggestion": ""}
    try:
        quote = tencent.get_realtime_quote(code)
    except Exception as e:
        return {"code": code, "error": f"行情获取失败: {e}", "score": 0}
    if not quote:
        return {"code": code, "error": "无行情数据", "score": 0}

    result["name"] = quote.get("name", code)
    result["price"] = quote.get("price", 0)
    result["change_pct"] = quote.get("change_pct", 0)

    # 技术面 0-40
    tech_score = 20
    try:
        kline = tencent.get_kline(code, days=120)
        tech = analyze_technical(kline.get("records", []), code)
        if tech.get("trend", {}).get("status") in ("强势多头", "多头排列"):
            tech_score += 12
        elif tech.get("trend", {}).get("status") == "弱势多头":
            tech_score += 6
        rsi = tech.get("rsi", {}).get("value")
        if rsi is not None:
            if 40 <= rsi <= 70:
                tech_score += 5
            elif rsi < 30:
                tech_score += 3  # 超卖反弹潜力
        if tech.get("macd", {}).get("signal") == "golden":
            tech_score += 3
        result["dimensions"]["technical"] = {"score": min(tech_score, 40), "trend": tech.get("trend", {}).get("status"),
                                             "rsi": rsi, "macd": tech.get("macd", {}).get("signal")}
    except Exception:
        result["dimensions"]["technical"] = {"score": tech_score, "trend": "N/A"}

    # 资金面 0-30
    fund_score = 15
    try:
        from data_sources.em_fundflow import get_fund_flow_120d
        ff = get_fund_flow_120d(code, days=20)
        flow = ff.get("flow") or []
        if flow:
            recent5 = sum(f.get("main_net") or 0 for f in flow[:5])
            if recent5 > 0:
                fund_score += 10
            elif recent5 < 0:
                fund_score -= 5
            ratio = flow[0].get("ratioamount") or 0
            if ratio > 0.1:
                fund_score += 5
        result["dimensions"]["fund_flow"] = {"score": max(0, min(fund_score, 30)),
                                              "total_main_net_yi": ff.get("total_main_net_yi")}
    except Exception:
        result["dimensions"]["fund_flow"] = {"score": fund_score}

    # 估值/价格位置 0-30
    val_score = 15
    try:
        quote_pct = quote.get("change_pct") or 0
        if quote_pct > 0:
            val_score += 5
        if quote_pct > 3:
            val_score += 5
        result["dimensions"]["market"] = {"score": val_score, "change_pct": quote_pct}
    except Exception:
        result["dimensions"]["market"] = {"score": val_score}

    total = sum(d["score"] for d in result["dimensions"].values())
    result["score"] = min(total, 100)
    result["suggestion"] = (
        "强势，可关注" if result["score"] >= 70 else
        "中性，观望" if result["score"] >= 45 else "弱势，谨慎"
    )
    return result


# ─── stock_signals: 多因子信号聚合 ───

def stock_signals(code: str):
    """个股多因子信号聚合 — 技术 + 资金 + 量价综合判断"""
    code = code.strip()
    if not code:
        return {"error": "股票代码不能为空"}

    from data_sources import tencent, em_market
    from tools.technical import analyze as analyze_technical

    signals = []
    result = {"code": code, "signals": signals, "summary": "中性", "bullish_count": 0, "bearish_count": 0}
    try:
        quote = tencent.get_realtime_quote(code)
    except Exception:
        quote = {}
    result["name"] = quote.get("name", code)

    # 技术信号
    try:
        kline = tencent.get_kline(code, days=120)
        tech = analyze_technical(kline.get("records", []), code)
        trend = tech.get("trend", {}).get("status", "")
        if "多头" in trend:
            signals.append({"factor": "trend", "signal": "bullish", "detail": trend})
        elif "空头" in trend:
            signals.append({"factor": "trend", "signal": "bearish", "detail": trend})
        macd = tech.get("macd", {}).get("signal")
        if macd == "golden":
            signals.append({"factor": "macd", "signal": "bullish", "detail": "MACD金叉"})
        elif macd == "dead":
            signals.append({"factor": "macd", "signal": "bearish", "detail": "MACD死叉"})
        rsi = tech.get("rsi", {}).get("value")
        if rsi is not None:
            if rsi < 30:
                signals.append({"factor": "rsi", "signal": "bullish", "detail": f"RSI={rsi:.1f} 超卖"})
            elif rsi > 70:
                signals.append({"factor": "rsi", "signal": "bearish", "detail": f"RSI={rsi:.1f} 超买"})
    except Exception:
        pass

    # 资金信号
    try:
        from data_sources.em_fundflow import get_fund_flow_120d
        ff = get_fund_flow_120d(code, days=10)
        flow = ff.get("flow") or []
        if flow:
            main_net = flow[0].get("main_net") or 0
            if main_net > 0:
                signals.append({"factor": "fund_flow", "signal": "bullish",
                                "detail": f"主力净流入{main_net/1e8:.2f}亿"})
            else:
                signals.append({"factor": "fund_flow", "signal": "bearish",
                                "detail": f"主力净流出{abs(main_net)/1e8:.2f}亿"})
    except Exception:
        pass

    # 量价信号
    try:
        quote_pct = quote.get("change_pct") or 0
        volume_ratio = quote.get("volume_ratio") or 0
        if quote_pct > 3 and volume_ratio > 1.5:
            signals.append({"factor": "volume_price", "signal": "bullish",
                            "detail": f"放量上涨 +{quote_pct:.1f}% 量比{volume_ratio:.1f}"})
        elif quote_pct < -3 and volume_ratio > 1.5:
            signals.append({"factor": "volume_price", "signal": "bearish",
                            "detail": f"放量下跌 {quote_pct:.1f}% 量比{volume_ratio:.1f}"})
    except Exception:
        pass

    bull = sum(1 for s in signals if s["signal"] == "bullish")
    bear = sum(1 for s in signals if s["signal"] == "bearish")
    result["bullish_count"] = bull
    result["bearish_count"] = bear
    result["summary"] = (
        "强烈看多" if bull >= 3 and bear == 0 else
        "看多" if bull > bear else
        "看空" if bear > bull else "中性"
    )
    return result


# ─── tdx_test: TDX 连通测试 ───

def tdx_test():
    """TDX 协议连通性测试 — mootdx TCP 直连 + 腾讯行情兜底"""
    result = {"source": "mootdx_tcp", "ok": False, "tests": []}
    try:
        from mootdx.quotes import Quotes
        client = Quotes.factory(market="std", timeout=5)
        df = client.quotes(symbol=["600519"], market=[1])
        ok = df is not None and not df.empty
        result["tests"].append({"name": "mootdx quotes(600519)", "ok": ok,
                                "rows": len(df) if df is not None else 0})
        if ok:
            result["last_price"] = float(df.iloc[0].get("price", 0))
        try:
            client.close()
        except Exception:
            pass
    except Exception as e:
        result["tests"].append({"name": "mootdx", "ok": False, "error": str(e)[:150]})

    # 腾讯行情兜底（数据中心 IP 下 TDX TCP 常被拒，腾讯 API 是可靠替代）
    try:
        from data_sources import tencent
        q = tencent.get_realtime_quote("600519")
        if q:
            result["tests"].append({"name": "tencent_fallback(600519)", "ok": True,
                                    "price": q.get("price"), "name": q.get("name")})
            result["ok"] = result["ok"] or True
    except Exception as e:
        result["tests"].append({"name": "tencent_fallback", "ok": False, "error": str(e)[:150]})

    # 汇总
    any_ok = any(t.get("ok") for t in result["tests"])
    result["ok"] = any_ok
    if any_ok:
        result["note"] = "TDX TCP 不可达时自动降级腾讯行情，行情能力可用"
    return result


if __name__ == "__main__":
    import sys
    test = sys.argv[1] if len(sys.argv) > 1 else "score"
    code = sys.argv[2] if len(sys.argv) > 2 else "600519"
    if test == "score":
        print(json.dumps(stock_score(code), ensure_ascii=False)[:500])
    elif test == "signals":
        print(json.dumps(stock_signals(code), ensure_ascii=False)[:500])
    elif test == "tech":
        print(json.dumps(technical_batch_scan(f"{code},000001", 60), ensure_ascii=False)[:600])
    elif test == "strategy":
        print(json.dumps(strategy_scan("limit_up_ladder"), ensure_ascii=False)[:500])
    elif test == "search":
        print(json.dumps(search_tradingview_market("茅台"), ensure_ascii=False)[:400])
    elif test == "tdx":
        print(json.dumps(tdx_test(), ensure_ascii=False)[:400])
