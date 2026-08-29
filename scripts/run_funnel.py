#!/usr/bin/env python3
"""
漏斗执行入口 — 每日运行一次全市场 A 股漏斗

MVP 数据源策略:
  - 东财 push2 优先（全市场 ~5000 只）
  - 降级到 baostock 缓存（仅 ~50 只测试股）
  - 腾讯行情补充实时价格

用法:
    cd /home/admin/projects/stock-mcp-server
    python scripts/run_funnel.py
"""
from __future__ import annotations

import json
import logging
import sqlite3
import sys
import time
from pathlib import Path
from typing import List, Optional

# 确保项目根目录在 path 中
_root = Path(__file__).parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from core.orchestrator import Pipeline, PipelineResult
from core.funnel import (
    enrich_with_baostock,
    stage_basic_filter,
    stage_technical_multi_channel,
    stage_ranking,
)
from core.signal_state import SignalTracker, SignalState

# LLM 审计支持
try:
    from core.llm_agnes import create_auditor_with_llm
    HAS_LLM = True
except ImportError:
    HAS_LLM = False

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("run_funnel")

_BAOSTOCK_DB = _root / "data" / "baostock_cache.db"


def _fetch_from_eastmoney() -> List[dict]:
    """尝试从东财获取全市场 A 股"""
    import httpx

    url = "https://push2.eastmoney.com/api/qt/clist/get"
    params = {
        "pn": 1, "pz": 5000, "po": 1, "np": 1,
        "fltt": 2, "invt": 2, "fid": "f6",
        "fs": "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23",
        "fields": "f2,f3,f4,f5,f6,f7,f12,f14,f15,f16,f17,f18",
    }
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://data.eastmoney.com/",
    }
    try:
        resp = httpx.get(url, params=params, headers=headers, timeout=15)
        if resp.status_code != 200:
            logger.warning("Eastmoney API returned status %d", resp.status_code)
            return []
        data = resp.json().get("data", {})
    except Exception as e:
        logger.warning("Eastmoney API error: %s", e)
        return []

    stocks = []
    for item in data.get("diff", []):
        code = item.get("f12", "")
        if not code:
            continue
        stocks.append({
            "code": code,
            "name": item.get("f14", ""),
            "price": item.get("f2"),
            "change_pct": round(item["f3"] / 100, 2) if item.get("f3") is not None else None,
            "volume": item.get("f5"),
            "amount": item.get("f6"),
            "amplitude": round(item["f7"] / 100, 2) if item.get("f7") is not None else None,
            "high": item.get("f15"),
            "low": item.get("f16"),
            "open": item.get("f17"),
            "pre_close": item.get("f18"),
            "source": "eastmoney",
        })
    return stocks


def _fetch_from_tradingview() -> List[dict]:
    """从 TradingView REST 获取全市场 A 股（东财 502 时的兜底）"""
    import json
    import urllib.request

    payload = json.dumps({
        "filter": [{"left": "market_cap_basic", "operation": "nempty"}],
        "options": {"lang": "zh"},
        "markets": ["sse", "szse"],
        "symbols": {"query": {"types": []}, "tickers": []},
        "columns": ["name", "description", "close", "change", "volume",
                    "sector", "industry", "market_cap_basic"],
        "sort": {"sortBy": "market_cap_basic", "sortOrder": "desc"},
        "range": [0, 5000],
    }).encode()

    req = urllib.request.Request(
        "https://scanner.tradingview.com/china/scan",
        data=payload,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
    except Exception as e:
        logger.warning("TradingView API error: %s", e)
        return []

    stocks = []
    for row in (data.get("data") or []):
        v = row.get("d") or []
        if len(v) < 8:
            continue
        code = str(v[0] or "")
        name = str(v[1] or "")
        close = float(v[2] or 0)
        change_pct = float(v[3] or 0)
        volume = float(v[4] or 0)
        industry = str(v[7] or "")
        market_cap = float(v[8] or 0) if len(v) > 8 else 0

        if not code:
            continue
        stocks.append({
            "code": code,
            "name": name,
            "price": close if close else None,
            "change_pct": round(change_pct, 2),
            "volume": volume,
            # TV 无成交额字段，用 成交量×收盘价 近似
            "amount": round(volume * close, 2) if close else None,
            "industry": industry,
            "market_cap": market_cap,
            "source": "tradingview",
        })

    logger.info("Fetched %d A-shares from TradingView REST", len(stocks))
    return stocks


def _fetch_from_baostock_cache() -> List[dict]:
    """从 baostock 本地缓存获取股票列表 + 最新行情"""
    if not _BAOSTOCK_DB.exists():
        return []

    conn = sqlite3.connect(str(_BAOSTOCK_DB))
    try:
        rows = conn.execute("""
            SELECT symbol, COUNT(*) as cnt,
                   MAX(date) as latest_date
            FROM stock_daily
            GROUP BY symbol
            HAVING cnt >= 60
        """).fetchall()

        stocks = []
        for symbol, cnt, latest_date in rows:
            # 获取最新一天的数据
            latest = conn.execute(
                "SELECT open, high, low, close, volume, turnover "
                "FROM stock_daily WHERE symbol = ? ORDER BY date DESC LIMIT 1",
                (symbol,),
            ).fetchone()

            if not latest:
                continue

            open_p, high, low, close, volume, turnover = latest
            # baostock 价格单位是 分(fen)，需要除以 100 转为 元(yuan)
            divisor = 100 if close and close > 10000 else 1

            stocks.append({
                "code": symbol,
                "name": symbol,
                "price": close / divisor if close else None,
                "open": open_p / divisor if open_p else None,
                "high": high / divisor if high else None,
                "low": low / divisor if low else None,
                "change_pct": None,
                "volume": volume,
                "amount": turnover,  # turnover 就是成交额
                "source": "baostock_cache",
                "_raw_close": close,
            })

        return stocks
    finally:
        conn.close()


def run_funnel(context: dict = None) -> PipelineResult:
    """执行完整漏斗"""

    ctx = context or {}
    t0 = time.time()

    # 1. 获取全市场 A 股（东财优先 → TradingView → baostock 降级）
    logger.info("Step 1: Fetching A-share universe...")
    universe = _fetch_from_eastmoney()
    source = "eastmoney"

    if not universe:
        logger.warning("Eastmoney API unavailable, trying TradingView REST...")
        universe = _fetch_from_tradingview()
        source = "tradingview"

    if not universe:
        logger.warning("TradingView API unavailable, falling back to baostock cache")
        universe = _fetch_from_baostock_cache()
        source = "baostock_cache"

    if not universe:
        logger.error("No data source available, aborting")
        return PipelineResult()

    logger.info("Got %d stocks from %s", len(universe), source)

    # 2. 用 baostock 补充均线/量能数据（东财/TradingView 源需要补齐技术指标）
    if source in ("eastmoney", "tradingview"):
        logger.info("Step 2: Enriching with baostock data...")
        universe = enrich_with_baostock(universe)
    else:
        # baostock 缓存源已自带历史数据，直接计算技术指标
        logger.info("Step 2: Computing indicators from baostock cache...")
        _enrich_baostock_direct(universe)

    # 3. 构建 Pipeline
    pipe = Pipeline()
    pipe.add_stage("basic_filter", stage_basic_filter)
    pipe.add_stage("technical_multi_channel", stage_technical_multi_channel)
    pipe.add_stage("ranking", stage_ranking)

    # 4. 执行
    logger.info("Step 3: Running funnel pipeline...")
    result = pipe.run(universe, ctx)

    # 5. AI 审计（可选）
    from core.ai_auditor import AIAuditor
    use_llm = ctx.get("use_llm", False)

    if use_llm and HAS_LLM:
        logger.info("Step 5: Running AI audit with Agnes LLM...")
        from core.llm_agnes import create_auditor_with_llm
        auditor = create_auditor_with_llm()
    else:
        logger.info("Step 5: Running AI audit (no LLM mode)...")
        auditor = AIAuditor(llm_fn=None)

    audit_result = auditor.audit(result.candidates)
    logger.info("Audit: %s", audit_result.summary())

    # 过滤被 VETO 的候选
    vetoed_codes = set(audit_result.vetoed_codes())
    result.candidates = [c for c in result.candidates if c["code"] not in vetoed_codes]

    # 6. 记录信号到状态机
    logger.info("Step 4: Recording signals...")
    tracker = SignalTracker()
    tracker.expire_stale()

    for candidate in result.candidates:
        for ch in candidate.get("channels", []):
            tracker.record(
                code=candidate["code"],
                signal_type=ch,
                state=SignalState.DETECTED,
                key_level=candidate.get("price"),
                context={
                    "channels": candidate.get("channels"),
                    "funnel_score": candidate.get("funnel_score"),
                },
            )

    # 6. 输出报告
    print(result.report())
    print(f"\n信号统计: {tracker.get_stats()}")

    return result


def _enrich_baostock_direct(stocks: List[dict]):
    """直接从 baostock 缓存计算技术指标"""
    if not _BAOSTOCK_DB.exists():
        return

    conn = sqlite3.connect(str(_BAOSTOCK_DB))
    try:
        for s in stocks:
            code = s.get("code", "")
            rows = conn.execute(
                "SELECT date, open, high, low, close, volume "
                "FROM stock_daily WHERE symbol = ? ORDER BY date DESC LIMIT 250",
                (code,),
            ).fetchall()

            if len(rows) < 60:
                continue

            closes = [r[4] for r in rows if r[4]]
            volumes = [r[5] for r in rows if r[5]]

            # 均线
            if len(closes) >= 50:
                s["ma50"] = sum(closes[:50]) / 50
            if len(closes) >= 200:
                s["ma200"] = sum(closes[:200]) / 200

            # 量比
            if len(volumes) >= 20:
                avg_vol_20 = sum(volumes[:20]) / 20
                s["volume_avg_20"] = avg_vol_20
                today_vol = volumes[0] if volumes else 0
                s["volume_ratio"] = round(today_vol / avg_vol_20, 2) if avg_vol_20 > 0 else 0

            # 距年低
            year_lows = [r[3] for r in rows[:250] if r[3]]
            if year_lows:
                min_low = min(year_lows)
                current = s.get("price") or (closes[0] if closes else 0)
                if min_low > 0 and current > 0:
                    s["dist_from_year_low_pct"] = round(
                        (current - min_low) / min_low * 100, 1
                    )

            # 20 日涨跌幅
            if len(closes) >= 20:
                s["change_pct_20d"] = round(
                    (closes[0] - closes[19]) / closes[19] * 100, 2
                ) if closes[19] else 0

            # 120 日涨幅
            if len(closes) >= 120:
                s["return_120d"] = round(
                    (closes[0] - closes[119]) / closes[119] * 100, 2
                ) if closes[119] else 0
    finally:
        conn.close()


def format_candidates_json(result: PipelineResult) -> str:
    """格式化候选列表为 JSON"""
    candidates = []
    for s in result.candidates:
        candidates.append({
            "code": s.get("code"),
            "name": s.get("name"),
            "price": s.get("price"),
            "change_pct": s.get("change_pct"),
            "channels": s.get("channels", []),
            "funnel_score": s.get("funnel_score", 0),
            "amount": s.get("amount"),
        })
    return json.dumps(candidates, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    result = run_funnel()

    if result.candidates:
        print(f"\n{'='*60}")
        print(f"候选列表 ({len(result.candidates)} 只):")
        print(f"{'='*60}")
        print(format_candidates_json(result))
    else:
        print("\n本轮漏斗无候选输出")
