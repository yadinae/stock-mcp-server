#!/usr/bin/env python3
"""聚合工具模块（移植自 Gateway tools_registry 的聚合 handler）

包含: cache_warmup / market_overview / market_regime / sector_rotation / stock_finder
这些工具组合多个数据源，一次性返回综合结果。
"""
import json
import sys
import os
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from data_sources import tencent, yahoo, em_market


def cache_warmup(codes: list = None) -> dict:
    """缓存预热 — 预取热门股票数据到内存缓存"""
    pool = codes if isinstance(codes, list) and codes else [
        "600519", "000858", "300750", "601318", "000333",
        "159949", "512010", "512660", "510200", "510050",
        "AAPL", "MSFT", "NVDA", "TSLA",
    ]
    results = []
    for code in pool:
        try:
            c = code.strip()
            if c.isdigit() and len(c) == 6:
                tencent.get_realtime_quote(c)
                tencent.get_kline(c, 30)
            else:
                yahoo.get_realtime_quote(c)
                yahoo.get_kline(c, 30)
            results.append({"code": c, "status": "cached"})
        except Exception as e:
            results.append({"code": c, "status": "error", "error": str(e)[:80]})
    return {
        "total": len(pool),
        "succeeded": len([r for r in results if r["status"] == "cached"]),
        "failed": len([r for r in results if r["status"] != "cached"]),
        "results": results,
    }


def market_overview() -> dict:
    """全市场总览 — A股主要指数 + 行业板块强弱 + 美股三大指数"""
    results = {"generated_at": datetime.now().isoformat()}

    # A股指数
    indices = []
    for code, name in [("sh000001", "上证指数"), ("sz399001", "深证成指"),
                       ("sz399006", "创业板指"), ("sh000300", "沪深300")]:
        try:
            q = tencent.get_realtime_quote(code)
            indices.append({"name": q.get("name") or name, "code": code,
                            "price": q.get("price"), "change_pct": q.get("change_pct")})
        except Exception:
            pass
    results["indices"] = indices

    # 行业板块（TV REST 替代 push2）
    try:
        rank = em_market.get_industry_rank_tv(10)
        top = rank.get("top") or []
        results["sectors"] = {
            "top5": [{"name": r["industry"], "change_pct": r["avg_change_pct"]} for r in top[:5]],
            "bottom5": [{"name": r["industry"], "change_pct": r["avg_change_pct"]} for r in top[-5:]][::-1] if len(top) >= 5 else [],
        }
    except Exception:
        results["sectors"] = {}

    # 美股三大指数
    us_indices = []
    for code in ("DJI", "IXIC", "INX"):
        try:
            q = yahoo.get_realtime_quote(code)
            us_indices.append({"name": q.get("name") or code, "code": code,
                               "price": q.get("price"), "change_pct": q.get("change_pct")})
        except Exception:
            pass
    results["us_indices"] = us_indices
    return results


def market_regime() -> dict:
    """市场状态判断 — 指数趋势(MA20/MA60) + 成交量 + 行业宽度 → bull/bear/oscillate"""
    results = {"generated_at": datetime.now().isoformat()}
    index_codes = ["sh000001", "sz399001", "sz399006", "sh000300"]
    ma_data = []

    for code in index_codes:
        try:
            quote = tencent.get_realtime_quote(code)
            kline = tencent.get_kline(code, 60)
            records = kline.get("records") or []
            if len(records) < 20:
                continue
            closes = [r.get("close") for r in records]
            ma20 = sum(closes[-20:]) / 20
            ma60 = sum(closes[-60:]) / min(60, len(closes))
            current = quote.get("price") or closes[-1]
            vol20 = sum(r.get("volume") or 0 for r in records[-20:]) / 20
            today_vol = records[-1].get("volume") or 0
            ma_data.append({
                "code": code, "name": quote.get("name") or code,
                "price": current, "ma20": round(ma20, 2), "ma60": round(ma60, 2),
                "above_ma20": current > ma20, "above_ma60": current > ma60,
                "vol_ratio": round(today_vol / vol20, 2) if vol20 else 1,
            })
        except Exception:
            continue
    results["indices"] = ma_data

    bull_score, bear_score = 0, 0
    above_ma20 = len([d for d in ma_data if d["above_ma20"]])
    above_ma60 = len([d for d in ma_data if d["above_ma60"]])
    if above_ma20 >= 3:
        bull_score += 30
    elif above_ma20 <= 1:
        bear_score += 30
    if above_ma60 >= 3:
        bull_score += 25
    elif above_ma60 <= 1:
        bear_score += 25
    avg_vol = sum(d.get("vol_ratio", 1) for d in ma_data) / max(1, len(ma_data))
    if avg_vol > 1.2:
        bull_score += 15
    elif avg_vol < 0.7:
        bear_score += 15

    try:
        ir = em_market.get_industry_rank_tv(10)
        top = ir.get("top") or []
        top_avg = sum(r.get("avg_change_pct", 0) for r in top[:5]) / 5 if top else 0
        bot_avg = sum(r.get("avg_change_pct", 0) for r in top[-5:]) / 5 if len(top) >= 5 else 0
        results["industry_breadth"] = {"top5_avg": round(top_avg, 2), "bottom5_avg": round(bot_avg, 2)}
        if top_avg > 2:
            bull_score += 10
        if bot_avg < -2:
            bear_score += 10
    except Exception:
        results["industry_breadth"] = None

    total = bull_score + bear_score
    bull_conf = round(bull_score / total * 100) if total > 0 else 50
    regime = ("bull" if bull_conf >= 65 else
              "oscillate_up" if bull_conf >= 55 else
              "oscillate" if bull_conf >= 45 else
              "oscillate_down" if bull_conf >= 35 else "bear")
    results["regime"] = regime
    results["bull_confidence"] = bull_conf
    results["bull_score"] = bull_score
    results["bear_score"] = bear_score
    return results


def sector_rotation() -> dict:
    """板块轮动追踪 — 全行业 N 日涨跌排名及动量变化"""
    try:
        rank = em_market.get_industry_rank_tv(10)
        top = rank.get("top") or []
        return {
            "generated_at": datetime.now().isoformat(),
            "total_industries": len(top),
            "top_gainers": [{"name": r["industry"], "change_pct": r["avg_change_pct"]} for r in top[:5]],
            "top_losers": [{"name": r["industry"], "change_pct": r["avg_change_pct"]} for r in top[-5:]][::-1] if len(top) >= 5 else [],
        }
    except Exception as e:
        return {"error": f"获取板块数据失败: {e}"}


def stock_finder(strategy: str = "etf", max_results: int = 5, risk_tolerance: str = "medium",
                 holdings: list = None) -> dict:
    """股票/ETF 推荐 — 策略选股 + 本地行情评分"""
    strategy = (strategy or "etf").strip()
    max_results = max(1, min(int(max_results or 5), 10))
    existing = set()
    if holdings:
        for h in holdings:
            if isinstance(h, str):
                existing.add(h.strip())
            elif isinstance(h, dict):
                existing.add(str(h.get("code") or "").strip())

    strategy_pools = {
        "value": [("600519", "贵州茅台"), ("000858", "五粮液"), ("601318", "中国平安"),
                  ("600036", "招商银行"), ("000333", "美的集团")],
        "momentum": [("300750", "宁德时代"), ("002594", "比亚迪"), ("300308", "中际旭创"),
                     ("601127", "赛力斯"), ("688981", "中芯国际")],
        "etf": [("513100", "纳斯达克ETF"), ("518880", "黄金ETF"), ("159915", "创业板ETF"),
                ("159949", "创业板50ETF"), ("512880", "证券ETF")],
        "reversal": [("600030", "中信证券"), ("000651", "格力电器"), ("601888", "中国中免"),
                     ("600809", "山西汾酒"), ("002415", "海康威视")],
    }
    pool = strategy_pools.get(strategy, strategy_pools["etf"])
    results = []
    for code, name in pool:
        if code in existing:
            continue
        try:
            q = tencent.get_realtime_quote(code)
            price = q.get("price") or 0
            change = q.get("change_pct") or 0
            # 简单评分: 基准50 + 涨跌幅加权（动量偏好正收益）
            score = 50 + min(change * 2, 20) + (10 if change > 0 else -5)
            score = max(20, min(95, round(score)))
            results.append({"code": code, "name": q.get("name") or name,
                            "price": price, "change_rate": change, "total_score": score})
        except Exception:
            continue
    results.sort(key=lambda x: -x.get("total_score", 0))
    return {
        "strategy": strategy,
        "max_results": max_results,
        "results": results[:max_results],
        "total": len(results[:max_results]),
    }
