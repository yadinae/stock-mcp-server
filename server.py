#!/usr/bin/env python3
"""
Stock Analysis MCP Server
=========================
提供 A股（腾讯行情 + mootdx 通达信 TCP）+ 美股/港股（Yahoo Finance）实时数据。
12 个工具，集成 TTL 缓存 + 并行执行 + 数据源健康追踪 + 策略回测。

Phase 1:  缓存 + 并行化 + Vibe-Trading 整合（mootdx fallback + Ichimoku + K线形态）
Phase 2:  ST 风险检测 + 数据源健康监控 + 缓存统计
Phase 3:  输入校验 + 统一错误格式 + 数据源健康全覆盖
Phase 4:  轻量级策略回测（5策略 + 交易模拟 + 绩效指标）
"""

from __future__ import annotations

import json
import logging
import re
import sys
from datetime import datetime, timedelta
from typing import Any

# ── MCP SDK ──────────────────────────────────────────────────
try:
    from mcp.server.fastmcp import FastMCP
except ImportError:
    print("ERROR: MCP SDK not installed. Run: pip install mcp", file=sys.stderr)
    sys.exit(1)

# ── 内部模块 ──────────────────────────────────────────────────
from core.cache import get_cache
from core.parallel import run_parallel, parallel_map
from data_sources import tencent, yahoo
from tools.technical import analyze as analyze_technical
from tools.news import search_news
from tools.analyzer import analyze_stock as ai_analyze
from tools.st_risk import get_st_risk
from tools.backtest import run_backtest, list_backtest_strategies

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("stock-mcp")

mcp = FastMCP("stock-mcp")

# ── 代码分类辅助函数 ──────────────────────────────────────────


def _code_type(code: str) -> str:
    """Detect market: a=沪/深, us=美股, hk=港股"""
    return tencent.code_type(code)


def _get_realtime_quote(code: str) -> dict[str, Any]:
    """通用实时行情（自动判断市场）"""
    ctype = _code_type(code)
    if ctype == "a":
        return tencent.get_realtime_quote(code)
    if ctype in ("us", "hk"):
        result = yahoo.get_realtime_quote(code)
        return result or {"code": code, "error": f"无法获取{'美股' if ctype == 'us' else '港股'}行情"}
    return {"code": code, "error": f"无法识别股票代码: {code}"}


def _get_kline(code: str, days: int = 60) -> dict[str, Any]:
    """通用 K 线数据（自动判断市场）"""
    ctype = _code_type(code)
    if ctype == "a":
        return tencent.get_kline(code, days)
    if ctype in ("us", "hk"):
        return yahoo.get_kline(code, days)
    return {"code": code, "error": f"不支持的市场类型: {ctype}"}


def _get_stock_info(code: str) -> dict[str, Any]:
    """通用股票信息（自动判断市场）"""
    ctype = _code_type(code)
    result = {"code": code, "type": ctype}
    if ctype == "a":
        result.update(tencent.get_stock_info(code))
    elif ctype in ("us", "hk"):
        result.update(yahoo.get_stock_info(code))
    return result


# ── 输入校验 ──────────────────────────────────────────────

_STOCK_CODE_RE = re.compile(r"^[A-Za-z0-9]{2,10}$")


def _validate_code(code: str) -> str | None:
    """验证股票代码格式，返回错误信息或 None"""
    if not code or not code.strip():
        return "股票代码不能为空"
    c = code.strip()
    if not _STOCK_CODE_RE.match(c):
        return f"股票代码格式异常: {code}"
    return None


def _validate_days(days: int) -> str | None:
    """验证天数参数"""
    if not isinstance(days, int) or days < 1:
        return "天数必须 >= 1"
    if days > 730:
        return "天数不能超过 730（2年）"
    return None


def _error_response(code: str, message: str, error_type: str = "validation_error") -> str:
    """生成统一格式的错误响应"""
    return json.dumps({
        "code": code,
        "error": message,
        "error_type": error_type,
        "success": False,
    }, ensure_ascii=False)


# ── MCP 工具定义 ─────────────────────────────────────────────


@mcp.tool(name="get_realtime_quote")
def get_realtime_quote(code: str) -> str:
    """获取股票实时行情（价格、涨跌幅、成交量等）
    Args:
        code: 股票代码。A股示例：600519, 000001, sh600519
              美股示例：AAPL, MSFT, TSLA
              港股示例：HK00700, hk00700
    """
    err = _validate_code(code)
    if err:
        return _error_response(code, err)
    result = _get_realtime_quote(code)
    return json.dumps(result, ensure_ascii=False, default=str)


@mcp.tool(name="get_kline")
def get_kline(code: str, days: int = 60) -> str:
    """获取股票历史K线数据
    Args:
        code: 股票代码
        days: 最近多少天（默认60）
    """
    err = _validate_code(code)
    if err:
        return _error_response(code, err)
    err = _validate_days(days)
    if err:
        return _error_response(code, err)
    result = _get_kline(code, min(days, 365))
    return json.dumps(result, ensure_ascii=False, default=str)


@mcp.tool(name="get_stock_info")
def get_stock_info(code: str) -> str:
    """获取股票基本信息（名称、现价、涨跌幅、成交量）
    Args:
        code: 股票代码
    """
    err = _validate_code(code)
    if err:
        return _error_response(code, err)
    result = _get_stock_info(code)
    return json.dumps(result, ensure_ascii=False, default=str)


@mcp.tool(name="analyze_stocks")
def analyze_stocks(stock_list: str) -> str:
    """批量分析多只股票的行情摘要
    Args:
        stock_list: 逗号分隔的股票代码，如 "600519,000001,AAPL,HK00700"
    """
    codes = [c.strip() for c in stock_list.split(",") if c.strip()]
    if not codes:
        return _error_response("", "请提供至少一个股票代码")
    # 验证每个代码
    for c in codes:
        err = _validate_code(c)
        if err:
            return _error_response(c, err)
    # 按市场分组
    a_codes = [c for c in codes if _code_type(c) == "a"]
    us_codes = [c for c in codes if _code_type(c) in ("us", "hk")]

    # A 股批量查询（单次 API 调用）
    a_results = tencent.batch_realtime(a_codes) if a_codes else []

    # 美股/港股并行查询
    us_results = []
    if us_codes:
        us_results = parallel_map(yahoo.get_realtime_quote, us_codes, max_workers=4)

    results = a_results + [r for r in us_results if r is not None]

    return json.dumps({
        "stocks": results,
        "count": len(results),
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }, ensure_ascii=False, default=str)


@mcp.tool(name="get_technical_analysis")
def get_technical_analysis(code: str) -> str:
    """获取股票技术分析（MA/MACD/RSI/布林带/趋势判断/量价分析）
    Args:
        code: 股票代码。A股示例：600519, 000001  美股示例：AAPL, MSFT  港股示例：HK00700
    """
    err = _validate_code(code)
    if err:
        return _error_response(code, err)
    kline = _get_kline(code, days=120)
    records = kline.get("records", [])
    if not records:
        return _error_response(code, kline.get("error", "无K线数据"), "data_error")

    result = analyze_technical(records, code)
    result["code"] = code
    return json.dumps(result, ensure_ascii=False, default=str)


@mcp.tool(name="search_stock_news")
def search_stock_news(code: str, name: str = "") -> str:
    """搜索股票相关新闻
    Args:
        code: 股票代码
        name: 股票名称（可选，提供后可提高搜索准确度）
    """
    err = _validate_code(code)
    if err:
        return _error_response(code, err)
    stock_name = name or _get_stock_info(code).get("name", "")
    result = search_news(code, stock_name)
    return json.dumps(result, ensure_ascii=False, default=str)


@mcp.tool(name="get_stock_context")
def get_stock_context(code: str) -> str:
    """获取股票综合数据（一次调用返回所有可用数据）
    Args:
        code: 股票代码。A股示例：600519, 000001  美股示例：AAPL, MSFT  港股示例：HK00700

    使用并行执行同时获取实时行情 + K 线数据，显著减少响应时间。
    """
    err = _validate_code(code)
    if err:
        return _error_response(code, err)
    tasks = {
        "realtime": lambda: _get_realtime_quote(code),
        "kline": lambda: _get_kline(code, days=120),
    }
    parallel_results = run_parallel(tasks, timeout=20)

    result = {
        "code": code,
        "realtime": parallel_results.get("realtime", {"error": "获取失败"}),
        "kline": parallel_results.get("kline", {"error": "获取失败"}),
        "technical": None,
        "news": None,
    }

    # 技术分析（基于并行获取的 K 线）
    kline_data = result["kline"]
    records = kline_data.get("records", []) if isinstance(kline_data, dict) else []
    if records:
        try:
            result["technical"] = analyze_technical(records, code)
        except Exception as e:
            result["technical"] = {"error": str(e)}

    # 新闻（单任务，直接调用不走并行开销）
    try:
        stock_name = _get_stock_info(code).get("name", "")
        result["news"] = search_news(code, stock_name)
    except Exception as e:
        result["news"] = {"error": str(e)}

    result["time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return json.dumps(result, ensure_ascii=False, default=str)


@mcp.tool(name="analyze_stock_ai")
def analyze_stock_ai(code: str, name: str = "") -> str:
    """AI 智能分析股票，生成决策仪表盘（含评分、买卖建议、技术面、消息面）
    Args:
        code: 股票代码。A股示例：600519, 000001  美股示例：AAPL, MSFT  港股示例：HK00700
        name: 股票名称（可选）

    并行获取实时行情 + K 线 + 新闻数据，然后调用 LLM 分析。
    """
    err = _validate_code(code)
    if err:
        return _error_response(code, err)
    import copy

    stock_name = name or _get_stock_info(code).get("name", "")

    # 并行获取独立数据
    tasks = {
        "realtime": lambda: _get_realtime_quote(code),
        "kline": lambda: _get_kline(code, days=120),
        "news": lambda: search_news(code, stock_name or code),
    }
    parallel_results = run_parallel(tasks, timeout=25)

    realtime = parallel_results.get("realtime", {"error": "获取失败"})
    kline = parallel_results.get("kline", {"error": "获取失败"})
    news_data = parallel_results.get("news", {"error": "获取失败"})

    # 技术分析（基于 K 线，非并行可省略—K 线已经并行获取）
    technical = {}
    records = kline.get("records", []) if isinstance(kline, dict) else []
    if records:
        try:
            technical = analyze_technical(records, code)
        except Exception as e:
            technical = {"error": str(e)}

    # 调用 AI 分析
    result = ai_analyze(
        stock_code=code,
        stock_name=stock_name or code,
        realtime_data=realtime,
        kline_data=kline,
        technical_data=technical,
        news_data=news_data,
    )
    return json.dumps(result, ensure_ascii=False, default=str)


# ── Phase 2 新工具 ───────────────────────────────────────


@mcp.tool(name="check_st_risk")
def check_st_risk(code: str) -> str:
    """检测股票的 ST/退市/异常风险（基于公开数据）
    Args:
        code: 股票代码。A股示例：600519, 000001  美股示例：AAPL, MSFT

    检测维度：
    - ST/*ST/退市状态 (基于股票名称)
    - 面值退市风险（股价 < 1元）
    - 量能异常（放量下跌等）
    - 风险等级: 正常 / 关注 / 警告 / 高风险
    """
    err = _validate_code(code)
    if err:
        return _error_response(code, err)
    realtime = _get_realtime_quote(code)
    if "error" in realtime and not realtime.get("price"):
        risk_result = get_st_risk(code, {"name": realtime.get("name", "")})
    else:
        risk_result = get_st_risk(code, realtime)
    return json.dumps(risk_result, ensure_ascii=False, default=str)


@mcp.tool(name="get_cache_stats")
def get_cache_stats() -> str:
    """获取缓存统计（命中率、条目数、各TTL分布）

    用于监控缓存效率和诊断性能问题。
    """
    cache = get_cache()
    stats = cache.stats
    stats["tool_name"] = "get_cache_stats"
    stats["note"] = "缓存命中率 > 60% 为健康，< 40% 需调整 TTL"
    return json.dumps(stats, ensure_ascii=False, default=str)


@mcp.tool(name="get_data_source_health")
def get_data_source_health() -> str:
    """获取数据源健康状态（腾讯、mootdx、Yahoo 的可用性和成功率）

    用于监控各数据源运行状态，及时发现腾讯 API 失效等故障。
    """
    from core.health import get_health_tracker
    report = get_health_tracker().get_report()
    result = {
        "sources": report,
        "count": len(report),
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "tool_name": "get_data_source_health",
    }
    return json.dumps(result, ensure_ascii=False, default=str)


# ── Phase 4: 回测集成 ────────────────────────────────────


@mcp.tool(name="check_backtest")
def check_backtest(code: str, strategy: str = "ma_crossover", days: int = 365,
                   capital: float = 100000.0) -> str:
    """策略回测 — 基于历史K线模拟交易，评估策略表现
    Args:
        code: 股票代码。A股示例：600519, 000001  美股示例：AAPL, MSFT
        strategy: 策略ID (ma_crossover=MA金叉/死叉, macd=MACD, rsi=RSI均值回归,
                  bollinger=布林带反弹, combined=组合信号)
        days: 回测天数（默认365，最大730）
        capital: 初始资金（默认100,000）

    输出：交易记录、绩效指标（总收益率/年化/最大回撤/夏普比率/胜率）、权益曲线
    注意：回测仅作研究参考，不代表未来收益
    """
    err = _validate_code(code)
    if err:
        return _error_response(code, err)

    # 验证策略ID
    strategies = list_backtest_strategies()
    valid_ids = [s["id"] for s in strategies]
    if strategy not in valid_ids:
        return _error_response(code, f"未知策略: {strategy}，可用策略: {', '.join(valid_ids)}")

    # 获取K线数据
    backtest_days = min(max(days, 60), 730)
    kline = _get_kline(code, days=backtest_days)
    records = kline.get("records", [])
    if not records:
        return _error_response(code, kline.get("error", "无K线数据"), "data_error")

    # 运行回测
    result = run_backtest(
        code=code,
        records=records,
        strategy=strategy,
        days=backtest_days,
        capital=capital,
    )

    return json.dumps(result, ensure_ascii=False, default=str)


# ── Webhook 告警 ─────────────────────────────────────────


@mcp.tool(name="run_alert_check")
def run_alert_check(dry_run: bool = False, channel: str = "auto") -> str:
    """运行告警检查：检查持仓预警、ST异动、ETF信号，推送飞书/TG通知

    Args:
        dry_run: True=仅检查不发送通知，False=检查并发送
        channel: 发送渠道 (auto, feishu, telegram, all)

    检查维度:
    - 价格跌幅（阈值: -3%/-5%/-8%）
    - 放量下跌（量比>3 + 跌幅>3%）
    - ST 风险（风险等级 >= 警告）
    - MACD 金叉/死叉
    - RSI 超买/超卖
    - ETF 技术评分 >= 70
    """
    try:
        from webhook.config import load_rules, load_notifier_config
        from webhook.alerter import run_alert_check as _run_check

        rules = load_rules()
        result = _run_check(rules=rules, dry_run=dry_run, channel=channel)
        return json.dumps(result, ensure_ascii=False, default=str)
    except ImportError as e:
        return json.dumps({
            "status": "error",
            "error": f"Webhook 模块加载失败: {e}",
            "note": "请确保 webhook/ 模块完整（config.py, alerter.py, rules.py, notifier.py）",
        }, ensure_ascii=False)
    except Exception as e:
        return json.dumps({
            "status": "error",
            "error": str(e),
        }, ensure_ascii=False)


# ── 美股港股增强数据工具 ──────────────────────────────────
# 整合自 simonlin1212/global-stock-data 项目
# 覆盖：行情/K线/基本面(中文三表+关键指标)/Yahoo统计/机构持仓/
#       资金流/期权/SEC Filing/XBRL/搜索/市场排名


@mcp.tool(name="get_global_quote")
def get_global_quote(code: str, source: str = "auto") -> str:
    """获取美股/港股实时行情（增强版，多数据源）

    Args:
        code: 美股字母代码如 AAPL, TSLA / 港股5位数字如 00700, 09988
        source: auto(自动选最优) / sina / tencent / eastmoney

    字段含中文名、PE、PB、市值、52周高低等，比Yahoo基础版更丰富。
    """
    from data_sources.global_stock import (
        global_quote, us_quote_sina, us_quote_tencent,
        hk_quote_tencent, hk_quote_sina, quote_eastmoney,
    )
    try:
        code = code.strip().upper()
        if source == "sina":
            if code.isalpha():
                result = us_quote_sina(code)
            else:
                result = hk_quote_sina(code)
        elif source == "tencent":
            if code.isalpha():
                result = us_quote_tencent(code)
            else:
                result = hk_quote_tencent(code)
        elif source == "eastmoney":
            secid = _code_to_secid(code)
            result = quote_eastmoney(secid) if secid else {"error": f"无法映射secid: {code}"}
        else:
            result = global_quote(code)
        result["code"] = code
        return json.dumps(result, ensure_ascii=False, default=str)
    except Exception as e:
        return json.dumps({"error": str(e), "code": code}, ensure_ascii=False)


@mcp.tool(name="get_global_kline")
def get_global_kline(code: str, days: int = 120, interval: str = "1d") -> str:
    """获取美股/港股历史K线数据

    Args:
        code: AAPL(美股) / 0700.HK(港股)
        days: 天数（默认120，新浪美股可回溯至1984年）
        interval: 周期 1d(日) / 1wk(周) / 1mo(月)

    美股优先用新浪（回溯更久），港股用 Yahoo。Yahoo 支持多周期。
    """
    from data_sources.global_stock import us_kline_sina, kline_yahoo
    try:
        code_clean = code.strip().upper()
        records = []

        if code_clean.isalpha() and len(code_clean) <= 5:
            # 美股 → 新浪
            records = us_kline_sina(code_clean, num=days)
            if not records:
                # Fallback 到 Yahoo
                range_map = {60: "3mo", 120: "6mo", 250: "1y", 750: "5y"}
                range_ = "6mo"
                for d, r in sorted(range_map.items()):
                    if days <= d:
                        range_ = r
                        break
                records = kline_yahoo(code_clean, interval=interval, range_=range_)
        else:
            # 港股 → Yahoo
            if not code_clean.endswith(".HK"):
                code_clean = f"{code_clean}.HK"
            range_map = {60: "3mo", 120: "6mo", 250: "1y", 750: "5y"}
            range_ = "6mo"
            for d, r in sorted(range_map.items()):
                if days <= d:
                    range_ = r
                    break
            records = kline_yahoo(code_clean, interval=interval, range_=range_)

        return json.dumps({
            "code": code.strip(),
            "records": records,
            "count": len(records),
        }, ensure_ascii=False, default=str)
    except Exception as e:
        return json.dumps({"error": str(e), "code": code}, ensure_ascii=False)


@mcp.tool(name="get_us_financials")
def get_us_financials(code: str, statement: str = "income", market: str = "us") -> str:
    """获取美股/港股财务报表（中文科目名）

    Args:
        code: AAPL(美股) / 00700(港股)
        statement: balance(资产负债表) / income(利润表) / cashflow(现金流量表)
        market: us(美股) / hk(港股)

    通过东财 datacenter 获取，中文字段名，按科目行展开。
    """
    from data_sources.global_stock import financial_statements, get_secucode
    try:
        secucode = get_secucode(code.strip().upper(), market)
        data = financial_statements(secucode, statement=statement)
        return json.dumps({
            "code": code.strip(),
            "secucode": secucode,
            "statement": statement,
            "records": data[:100],
            "count": len(data[:100]),
        }, ensure_ascii=False, default=str)
    except Exception as e:
        return json.dumps({"error": str(e), "code": code}, ensure_ascii=False)


@mcp.tool(name="get_us_key_indicators")
def get_us_key_indicators(code: str, market: str = "us") -> str:
    """获取美股/港股关键财务指标（中文版）

    Args:
        code: AAPL(美股) / 00700(港股)
        market: us(美股) / hk(港股)

    通过东财 GMAININDICATOR 获取，含 ROE/ROA/EPS/毛利率/资产负债率 等。
    """
    from data_sources.global_stock import key_indicators, get_secucode
    try:
        secucode = get_secucode(code.strip().upper(), market)
        data = key_indicators(secucode)
        return json.dumps({
            "code": code.strip(),
            "secucode": secucode,
            "records": data,
            "count": len(data),
        }, ensure_ascii=False, default=str)
    except Exception as e:
        return json.dumps({"error": str(e), "code": code}, ensure_ascii=False)


@mcp.tool(name="get_yahoo_statistics")
def get_yahoo_statistics(symbol: str) -> str:
    """获取美股/港股关键财务指标（英文版，Yahoo）

    Args:
        symbol: AAPL(美股) / 0700.HK(港股)

    返回 PE/PB/EV/利润率/ROE/目标价/Beta/股息率/机构数据等。
    """
    from data_sources.global_stock import yahoo_key_statistics
    try:
        result = yahoo_key_statistics(symbol.strip().upper())
        return json.dumps(result, ensure_ascii=False, default=str)
    except Exception as e:
        return json.dumps({"error": str(e), "symbol": symbol}, ensure_ascii=False)


@mcp.tool(name="get_institutional_holders")
def get_institutional_holders(symbol: str) -> str:
    """获取美股/港股机构持仓（Yahoo）

    Args:
        symbol: AAPL(美股) / 0700.HK(港股)

    返回机构持股比例、前10大机构持仓明细。
    """
    from data_sources.global_stock import yahoo_institutional_holders
    try:
        result = yahoo_institutional_holders(symbol.strip().upper())
        return json.dumps(result, ensure_ascii=False, default=str)
    except Exception as e:
        return json.dumps({"error": str(e), "symbol": symbol}, ensure_ascii=False)


@mcp.tool(name="get_us_fund_flow")
def get_us_fund_flow(code: str, days: int = 30, secid_prefix: int = 0) -> str:
    """获取美股/港股日级资金流向

    Args:
        code: AAPL(美股) / 00700(港股)
        days: 返回天数（默认30）
        secid_prefix: 105=NASDAQ, 106=NYSE, 116=港股（0=自动检测）

    返回主力/大单/中单/小单净流入历史。
    """
    from data_sources.global_stock import fund_flow_daily
    try:
        code_clean = code.strip().upper()
        if secid_prefix == 0:
            secid_prefix = _detect_secid_prefix(code_clean)
        secid = f"{secid_prefix}.{code_clean}"
        data = fund_flow_daily(secid, limit=days)
        return json.dumps({
            "code": code_clean,
            "secid": secid,
            "records": data,
            "count": len(data),
        }, ensure_ascii=False, default=str)
    except Exception as e:
        return json.dumps({"error": str(e), "code": code}, ensure_ascii=False)


@mcp.tool(name="get_options_chain")
def get_options_chain(symbol: str) -> str:
    """获取美股期权链（Yahoo，仅美股）

    Args:
        symbol: AAPL, TSLA 等美股 ticker（港股不支持）

    返回 calls + puts，含行权价/最新价/隐含波动率/Greeks。
    """
    from data_sources.global_stock import options_chain
    try:
        result = options_chain(symbol.strip().upper())
        return json.dumps(result, ensure_ascii=False, default=str)
    except Exception as e:
        return json.dumps({"error": str(e), "symbol": symbol}, ensure_ascii=False)


@mcp.tool(name="get_sec_filings")
def get_sec_filings(ticker: str, form_type: str = "") -> str:
    """获取 SEC EDGAR 文件列表（仅美股）

    Args:
        ticker: AAPL, TSLA 等美股 ticker
        form_type: 筛选 10-K(年报) / 10-Q(季报) / 8-K(重大事件)，不传则返回全部

    返回 Filing 列表含 SEC 官方链接。
    """
    from data_sources.global_stock import ticker_to_cik, sec_filings
    try:
        tk = ticker.strip().upper()
        cik_info = ticker_to_cik(tk)
        if "error" in cik_info:
            return json.dumps(cik_info, ensure_ascii=False)
        filings = sec_filings(cik_info["cik"], form_type=form_type)
        filings["ticker"] = tk
        return json.dumps(filings, ensure_ascii=False, default=str)
    except Exception as e:
        return json.dumps({"error": str(e), "ticker": ticker}, ensure_ascii=False)


@mcp.tool(name="get_sec_xbrl")
def get_sec_xbrl(ticker: str, metrics: str = "") -> str:
    """获取 SEC XBRL 结构化财务数据（仅美股，503个GAAP指标）

    Args:
        ticker: AAPL, TSLA 等美股 ticker
        metrics: 逗号分隔的指标名，如 "RevenueFromContractWithCustomerExcludingAssessedTax,NetIncomeLoss"
                 不传则返回所有可用指标列表

    常用指标: RevenueFromContractWithCustomerExcludingAssessedTax(营收),
              NetIncomeLoss(净利), EarningsPerShareDiluted(稀释EPS),
              Assets(总资产), Liabilities(总负债)
    """
    from data_sources.global_stock import ticker_to_cik, sec_xbrl_facts
    try:
        tk = ticker.strip().upper()
        cik_info = ticker_to_cik(tk)
        if "error" in cik_info:
            return json.dumps(cik_info, ensure_ascii=False)
        metrics_list = [m.strip() for m in metrics.split(",") if m.strip()] if metrics else None
        result = sec_xbrl_facts(cik_info["cik"], metrics=metrics_list)
        return json.dumps(result, ensure_ascii=False, default=str)
    except Exception as e:
        return json.dumps({"error": str(e), "ticker": ticker}, ensure_ascii=False)


@mcp.tool(name="search_global_stock")
def search_global_stock(keyword: str) -> str:
    """搜索全球股票（东财，支持中英文）

    Args:
        keyword: AAPL / 苹果 / Tencent / 00700 / 特斯拉

    返回代码、中文名、市场(NASDAQ/NYSE/HK)及 secid 前缀。
    """
    from data_sources.global_stock import stock_search
    try:
        results = stock_search(keyword)
        return json.dumps({
            "keyword": keyword,
            "results": results,
            "count": len(results),
        }, ensure_ascii=False, default=str)
    except Exception as e:
        return json.dumps({"error": str(e), "keyword": keyword}, ensure_ascii=False)


@mcp.tool(name="get_us_market_ranking")
def get_us_market_ranking(market: str = "us_nasdaq", sort_by: str = "change_pct",
                          ascending: bool = False, page: int = 1) -> str:
    """获取美股/港股全市场涨跌幅排名

    Args:
        market: us_nasdaq(NASDAQ) / us_nyse(NYSE) / us_etf(美股ETF) / hk(港股)
        sort_by: change_pct(涨跌幅) / volume(成交量) / amount(成交额)
        ascending: False=降序(涨幅榜) True=升序(跌幅榜)

    返回股票代码、中文名、最新价、涨跌幅、成交量、成交额等。
    """
    from data_sources.global_stock import market_stock_list
    try:
        sort_field_map = {
            "change_pct": "f3", "volume": "f5", "amount": "f6",
        }
        sf = sort_field_map.get(sort_by, "f3")
        data = market_stock_list(
            market=market, sort_field=sf,
            sort_desc=not ascending, page=page,
        )
        return json.dumps({
            "market": market,
            "sort_by": sort_by,
            "total": data["total"],
            "stocks": data["stocks"],
            "page": page,
        }, ensure_ascii=False, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


# ── 辅助函数 ──────────────────────────────────────────────


def _code_to_secid(code: str) -> str:
    """将代码转为东财 secid 格式"""
    c = code.strip().upper()
    if c.isalpha() and len(c) <= 5:
        return f"105.{c}"  # 默认 NASDAQ
    if c.isdigit() and len(c) == 5:
        return f"116.{c}"  # 港股
    return ""


def _detect_secid_prefix(code: str) -> int:
    """自动检测 secid 前缀"""
    c = code.strip().upper()
    if c.isalpha() and len(c) <= 5:
        return 105  # NASDAQ
    if c.isdigit() and len(c) == 5:
        return 116  # 港股
    return 105


if __name__ == "__main__":
    mcp.run()