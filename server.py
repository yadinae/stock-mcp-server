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
from data_sources import em_f10
from data_sources import em_market
from data_sources import danjuan_csindex
from data_sources import kraken
from data_sources import binance as binance_source
from core import store as local_store
from tools import portfolio as portfolio_tools
from tools import aggregate as aggregate_tools
from tools.technical import analyze as analyze_technical
from tools.news import search_news
from tools.analyzer import analyze_stock as ai_analyze
from tools.st_risk import get_st_risk
from tools.backtest import run_backtest, list_backtest_strategies
from tools import advanced as advanced_tools
from tools import advanced2_dcf
from tools import advanced2_lhb
from tools import advanced2_unit
from tools import advanced2_hot
from data_sources import em_fundflow
from data_sources import sina_financial
from data_sources import intel as intel_tools

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


# ── 通达信 F10 数据增强（mootdx TCP 协议）──────────────
# 通过通达信 TCP 直连获取 F10 级公司资料、财务数据
# Workers 版本通过东财 HTTP 实现等价功能


@mcp.tool(name="get_tdx_company_info")
def get_tdx_company_info(code: str) -> str:
    """通达信 F10 公司资料（东财 emweb 通道）— 公司简介、股本结构、注册地址、法人代表

    Args:
        code: 股票代码。A股示例：600519, 000001
    """
    return json.dumps(em_f10.get_company_profile(code), ensure_ascii=False, default=str)


@mcp.tool(name="get_tdx_finance_info")
def get_tdx_finance_info(code: str) -> str:
    """通达信 F10 财务信息（东财 datacenter 通道）— EPS、营收、净利润、ROE、毛利率

    Args:
        code: 股票代码。A股示例：600519, 000001
    """
    return json.dumps(em_f10.get_company_financials(code), ensure_ascii=False, default=str)


@mcp.tool(name="get_tdx_xdxr_info")
def get_tdx_xdxr_info(code: str) -> str:
    """通达信除权除息信息（东财通道）— 分红、送转股历史

    Args:
        code: 股票代码。A股示例：600519, 000001
    """
    return json.dumps(em_f10.get_xdxr_info(code), ensure_ascii=False, default=str)


@mcp.tool(name="get_company_profile")
def get_company_profile(code: str) -> str:
    """🆕 获取公司详细资料（F10）— 名称、全称、成立日期、上市日期、注册地址、主营业务、行业分类、员工数、法人代表、总股本等。仅支持 A 股。

    Args:
        code: 股票代码，如 600519
    """
    return json.dumps(em_f10.get_company_profile(code), ensure_ascii=False, default=str)


@mcp.tool(name="get_company_financials")
def get_company_financials(code: str) -> str:
    """🆕 获取公司财务核心指标（F10）— 近8期EPS/营收/净利润/毛利率/ROE/资产负债率/BVPS/CFPS。仅支持 A 股。

    Args:
        code: 股票代码，如 600519
    """
    return json.dumps(em_f10.get_company_financials(code), ensure_ascii=False, default=str)


@mcp.tool(name="get_top_shareholders")
def get_top_shareholders(code: str) -> str:
    """🆕 获取十大股东 — 股东名称、持股数量、持股比例、变动情况。仅支持 A 股。

    Args:
        code: 股票代码，如 600519
    """
    return json.dumps(em_f10.get_top_shareholders(code), ensure_ascii=False, default=str)


@mcp.tool(name="get_management_team")
def get_management_team(code: str) -> str:
    """🆕 获取管理层信息 — 董事长/总经理/董秘/独董等核心岗位。仅支持 A 股。

    Args:
        code: 股票代码，如 600519
    """
    return json.dumps(em_f10.get_management_team(code), ensure_ascii=False, default=str)


# ═══════════════════════════════════════════════════════════════
# 东财市场数据系列（移植自 Gateway em_market_lhb/em_fundflow/em_blocks/em_reports/cninfo/em_limitup/ths_hot）
# ═══════════════════════════════════════════════════════════════


@mcp.tool(name="get_market_lhb")
def get_market_lhb(date: str = "", min_net_buy: float = 0) -> str:
    """全市场龙虎榜 — 当日所有上榜股票，含上榜原因、净买入、换手率。

    Args:
        date: 日期 YYYY-MM-DD（默认今天）
        min_net_buy: 净买入下限(万元)，可选
    """
    return json.dumps(em_market.get_market_lhb(date, min_net_buy), ensure_ascii=False, default=str)


@mcp.tool(name="get_lockup_calendar")
def get_lockup_calendar(code: str) -> str:
    """个股限售解禁日历 — 历史解禁 + 未来90天待解禁。

    Args:
        code: 股票代码
    """
    return json.dumps(em_market.get_lockup_calendar(code), ensure_ascii=False, default=str)


@mcp.tool(name="get_research_reports")
def get_research_reports(code: str, pages: int = 1) -> str:
    """个股研报列表 — 研报标题、机构、评级。

    Args:
        code: 股票代码
        pages: 页数（每页20条）
    """
    return json.dumps(em_market.get_research_reports(code, pages), ensure_ascii=False, default=str)


@mcp.tool(name="get_announcements")
def get_announcements(code: str, page_size: int = 30) -> str:
    """个股公告全文检索（巨潮）。

    Args:
        code: 股票代码
        page_size: 返回条数
    """
    return json.dumps(em_market.get_announcements(code, page_size), ensure_ascii=False, default=str)


@mcp.tool(name="get_stock_boards")
def get_stock_boards(code: str) -> str:
    """个股所属板块 — 行业/概念/地域。

    Args:
        code: 股票代码
    """
    return json.dumps(em_market.get_stock_boards(code), ensure_ascii=False, default=str)


@mcp.tool(name="get_industry_rank")
def get_industry_rank(top_n: int = 20) -> str:
    """全行业涨跌幅排名（TV REST 数据源，东财 push2 对数据中心IP限流时的替代）。

    Args:
        top_n: 返回前N名
    """
    # 输出 Gateway 兼容结构 {total, top:[{name,change_pct,...}], bottom:[...]} —
    # 2026-08-16 迁移: 雪球 collect_industry/collect_market_data 依赖 name/change_pct 字段
    r = em_market.get_industry_rank_tv(top_n)
    if isinstance(r, dict) and r.get("top") and r.get("total"):
        rows = [{"name": x.get("industry", ""), "change_pct": x.get("avg_change_pct", 0),
                 "count": x.get("count", 0), "up_count": x.get("up_count", 0),
                 "down_count": x.get("down_count", 0)} for x in r["top"]]
        n = min(max(int(top_n or 20), 1), len(rows))
        return json.dumps({"source": r.get("source"), "total": len(rows),
                           "top": rows[:n], "bottom": rows[-n:]},
                          ensure_ascii=False, default=str)
    return json.dumps(r, ensure_ascii=False, default=str)


@mcp.tool(name="get_tv_industry_rank")
def get_tv_industry_rank(top_n: int = 20) -> str:
    """TV REST 行业涨跌排名（英文GICS分类）。

    Args:
        top_n: 返回前N名
    """
    return json.dumps(em_market.get_industry_rank_tv(top_n), ensure_ascii=False, default=str)


@mcp.tool(name="get_tv_market_list")
def get_tv_market_list(top_n: int = 100) -> str:
    """TV REST 大盘股列表（按市值排序）。

    Args:
        top_n: 返回前N名
    """
    return json.dumps(em_market.get_tv_market_list(top_n), ensure_ascii=False, default=str)


@mcp.tool(name="get_tv_quote")
def get_tv_quote(code: str) -> str:
    """TV REST 个股行情（A股）。

    Args:
        code: 6位A股代码
    """
    return json.dumps(em_market.get_tv_quote(code), ensure_ascii=False, default=str)


@mcp.tool(name="get_market_hot_stocks")
def get_market_hot_stocks(date: str = "") -> str:
    """当日强势股清单及题材归因（同花顺热点）。

    Args:
        date: 日期 YYYYMMDD（默认今天）
    """
    return json.dumps(em_market.get_market_hot_stocks(date), ensure_ascii=False, default=str)


@mcp.tool(name="get_convertible_bonds")
def get_convertible_bonds(page_size: int = 20) -> str:
    """可转债列表 — 代码/名称/价格/溢价率。

    Args:
        page_size: 返回条数
    """
    return json.dumps(em_market.get_convertible_bonds(page_size), ensure_ascii=False, default=str)


@mcp.tool(name="analyze_limitup_tiers")
def analyze_limitup_tiers() -> str:
    """涨停梯队分析 — 首板/二连板/三连板及以上/炸板分类 + 市场统计（涨停总数/炸板率/最高连板）。

    数据源: 东财 datacenter 涨停股 + 腾讯K线连板判断（本地 200 ✅）
    """
    return json.dumps(em_market.get_limitup_tiers(), ensure_ascii=False, default=str)


@mcp.tool(name="get_wallstreetcn_news")
def get_wallstreetcn_news(limit: int = 10, mode: str = "all") -> str:
    """华尔街见闻快讯 — 7x24 快讯 + 热门文章 + 最新文章摘要。

    Args:
        limit: 每类返回条数（默认10，最大30）
        mode: all | live | hot | articles
    """
    return json.dumps(em_market.get_wallstreetcn_news(limit, mode), ensure_ascii=False, default=str)


@mcp.tool(name="get_industry_fund_flow")
def get_industry_fund_flow(top_n: int = 20) -> str:
    """行业板块资金流向排名（主力净流入，东财 push2 502 时用腾讯板块接口替代）。

    Args:
        top_n: 返回前N个行业（默认20，最大50）
    """
    return json.dumps(em_market.get_industry_fund_flow(top_n), ensure_ascii=False, default=str)


# ═══════════════════════════════════════════════════════════════
# 基金（蛋卷）+ 指数（中证）系列（移植自 Gateway danjuan_fund.ts / csindex.ts）
# ═══════════════════════════════════════════════════════════════


@mcp.tool(name="get_fund_info")
def get_fund_info(code: str) -> str:
    """基金基础信息 — 名称/类型/规模/经理/风险等级/状态。

    Args:
        code: 基金代码（6位数字）
    """
    return json.dumps(danjuan_csindex.fund_info(code), ensure_ascii=False, default=str)


@mcp.tool(name="get_fund_detail")
def get_fund_detail(code: str) -> str:
    """基金详情 — 公司介绍+持仓(前10)+费率+经理列表。

    Args:
        code: 基金代码（6位数字）
    """
    return json.dumps(danjuan_csindex.fund_detail(code), ensure_ascii=False, default=str)


@mcp.tool(name="get_fund_nav_history")
def get_fund_nav_history(code: str, page: int = 1, size: int = 30) -> str:
    """基金净值历史 — 每日净值+涨跌幅。

    Args:
        code: 基金代码（6位数字）
        page: 页码
        size: 每页条数
    """
    return json.dumps(danjuan_csindex.fund_nav_history(code, page, size), ensure_ascii=False, default=str)


@mcp.tool(name="get_fund_growth")
def get_fund_growth(code: str, day: str = "ty") -> str:
    """基金阶段涨幅 — day: ty(今年)/1y/3y/5y。

    Args:
        code: 基金代码（6位数字）
        day: 区间（默认ty=今年以来）
    """
    return json.dumps(danjuan_csindex.fund_growth(code, day), ensure_ascii=False, default=str)


@mcp.tool(name="get_fund_asset")
def get_fund_asset(code: str) -> str:
    """基金资产配置 — 股票/债券/现金比例+重仓股(前10)。

    Args:
        code: 基金代码（6位数字）
    """
    return json.dumps(danjuan_csindex.fund_asset(code), ensure_ascii=False, default=str)


@mcp.tool(name="get_fund_manager")
def get_fund_manager(code: str) -> str:
    """基金经理 — 任期/年限/业绩。

    Args:
        code: 基金代码（6位数字）
    """
    return json.dumps(danjuan_csindex.fund_manager(code), ensure_ascii=False, default=str)


@mcp.tool(name="get_index_info")
def get_index_info(code: str) -> str:
    """指数基本信息 — 全名/简称/基日/基点/发布日期/编制说明。

    Args:
        code: 指数代码（6位数字，如 000300）
    """
    return json.dumps(danjuan_csindex.index_basic_info(code), ensure_ascii=False, default=str)


@mcp.tool(name="get_index_details")
def get_index_details(code: str) -> str:
    """指数详情文件清单 — 编制方案PDF/样本权重xls等直链。

    Args:
        code: 指数代码（6位数字）
    """
    return json.dumps(danjuan_csindex.index_details(code), ensure_ascii=False, default=str)


@mcp.tool(name="get_index_perf")
def get_index_perf(code: str, days: int = 30) -> str:
    """指数区间表现 — 每日开高低收/涨跌幅。

    Args:
        code: 指数代码（6位数字）
        days: 返回天数
    """
    return json.dumps(danjuan_csindex.index_perf(code, days), ensure_ascii=False, default=str)


# ═══════════════════════════════════════════════════════════════
# 加密货币（Binance 主源 + Kraken 兜底，VPS 实测 Binance 200 ✅）
# ═══════════════════════════════════════════════════════════════


@mcp.tool(name="get_crypto_quote")
def get_crypto_quote(symbol: str) -> str:
    """数字货币实时行情（Binance 公开 API，无需 Key；失败自动降级 Kraken）。

    Args:
        symbol: 币种代码，如 BTCUSDT / ETHUSDT / SOLUSDT
    """
    return json.dumps(binance_source.get_crypto_quote(symbol), ensure_ascii=False, default=str)


@mcp.tool(name="get_crypto_quotes")
def get_crypto_quotes(symbols: str) -> str:
    """批量数字货币实时行情（逗号分隔，最多10个）。

    Args:
        symbols: 逗号分隔的币种代码
    """
    return json.dumps(binance_source.get_crypto_quotes(symbols), ensure_ascii=False, default=str)


@mcp.tool(name="get_crypto_kline")
def get_crypto_kline(symbol: str, interval: str = "1d", limit: int = 60) -> str:
    """数字货币 K 线（Binance klines）。

    Args:
        symbol: 币种代码
        interval: 1m/5m/15m/30m/1h/4h/1d/1w/1M
        limit: 返回条数
    """
    return json.dumps(binance_source.get_crypto_kline(symbol, interval, limit), ensure_ascii=False, default=str)


@mcp.tool(name="get_top_crypto")
def get_top_crypto(sort_by: str = "volume", limit: int = 10) -> str:
    """热门数字货币排行（Binance 24hr 全市场）。

    Args:
        sort_by: volume(成交量) / change(涨跌幅)
        limit: 返回条数
    """
    return json.dumps(binance_source.get_top_crypto(sort_by, limit), ensure_ascii=False, default=str)


# ═══════════════════════════════════════════════════════════════
# 组合诊断（移植自 Gateway tools/portfolio.ts）
# ═══════════════════════════════════════════════════════════════


@mcp.tool(name="portfolio_risk_diagnosis")
def portfolio_risk_diagnosis(holdings=None) -> str:
    """组合风险诊断 — 持仓集中度、行业暴露、跨市场分布、浮动盈亏。

    Args:
        holdings: 持仓 JSON 字符串或数组，如 [{"code":"600519","shares":100,"cost_price":1500}]
    """
    try:
        h = json.loads(holdings) if isinstance(holdings, str) else holdings
    except Exception:
        return json.dumps({"error": "holdings 必须是合法 JSON"}, ensure_ascii=False)
    return json.dumps(portfolio_tools.portfolio_risk_diagnosis(h), ensure_ascii=False, default=str)


@mcp.tool(name="portfolio_correlation")
def portfolio_correlation(codes: str, days: int = 60) -> str:
    """持仓相关性矩阵 — 计算组合内各持仓两两 Pearson 相关系数。

    Args:
        codes: JSON数组或逗号分隔字符串，如 ["600519","000001"] 或 "600519,000001"
        days: 分析天数
    """
    try:
        c = json.loads(codes) if isinstance(codes, str) and codes.strip().startswith("[") else [x.strip() for x in codes.replace("，", ",").split(",") if x.strip()]
    except Exception:
        c = [x.strip() for x in codes.replace("，", ",").split(",") if x.strip()]
    return json.dumps(portfolio_tools.portfolio_correlation(c, days), ensure_ascii=False, default=str)


@mcp.tool(name="portfolio_full_report")
def portfolio_full_report(holdings=None, days: int = 60) -> str:
    """综合组合报告 — 行情摘要 + 集中度 + 行业暴露 + 相关性矩阵。

    Args:
        holdings: 持仓 JSON 字符串或数组
        days: 分析天数
    """
    try:
        h = json.loads(holdings) if isinstance(holdings, str) else holdings
    except Exception:
        return json.dumps({"error": "holdings 必须是合法 JSON"}, ensure_ascii=False)
    return json.dumps(portfolio_tools.portfolio_full_report(h, days), ensure_ascii=False, default=str)


@mcp.tool(name="portfolio_rebalance")
def portfolio_rebalance(holdings=None, max_single_weight: float = 40) -> str:
    """组合调仓建议 — 仓位调整 + 行业分散优化。

    Args:
        holdings: 持仓 JSON 字符串或数组
        max_single_weight: 单标的权重上限(%)
    """
    try:
        h = json.loads(holdings) if isinstance(holdings, str) else holdings
    except Exception:
        return json.dumps({"error": "holdings 必须是合法 JSON"}, ensure_ascii=False)
    return json.dumps(portfolio_tools.portfolio_rebalance(h, max_single_weight), ensure_ascii=False, default=str)


@mcp.tool(name="portfolio_signal")
def portfolio_signal(holdings=None) -> str:
    """组合调仓信号 — urgency(high/medium/low) + 建议。

    Args:
        holdings: 持仓 JSON 字符串或数组
    """
    try:
        h = json.loads(holdings) if isinstance(holdings, str) else holdings
    except Exception:
        return json.dumps({"error": "holdings 必须是合法 JSON"}, ensure_ascii=False)
    return json.dumps(portfolio_tools.portfolio_signal(h), ensure_ascii=False, default=str)


# ═══════════════════════════════════════════════════════════════
# 交易日志（本地 SQLite 存储）
# ═══════════════════════════════════════════════════════════════


@mcp.tool(name="trade_journal_open")
def trade_journal_open(symbol: str, shares: float, entry_price: float, strategy: str = "",
                       rationale: str = "", side: str = "long", name: str = "") -> str:
    """开仓 — 记录一笔交易。

    Args:
        symbol: 代码
        shares: 股数
        entry_price: 成交价
        strategy: 策略标签
        rationale: 理由
        side: long/short
        name: 名称
    """
    return json.dumps(local_store.trade_open(symbol, shares, entry_price, strategy, rationale, side, name), ensure_ascii=False, default=str)


@mcp.tool(name="trade_journal_close")
def trade_journal_close(id: int, exit_price: float, notes: str = "") -> str:
    """平仓 — 关闭一笔持仓并计算盈亏。

    Args:
        id: 交易ID
        exit_price: 卖出价
        notes: 备注
    """
    return json.dumps(local_store.trade_close(id, exit_price, notes), ensure_ascii=False, default=str)


@mcp.tool(name="trade_journal_list")
def trade_journal_list(status: str = "", strategy: str = "", symbol: str = "") -> str:
    """交易查询 — 按状态/策略/标的筛选。

    Args:
        status: open/closed
        strategy: 策略
        symbol: 代码
    """
    return json.dumps(local_store.trade_list(status, strategy, symbol), ensure_ascii=False, default=str)


@mcp.tool(name="trade_journal_stats")
def trade_journal_stats() -> str:
    """交易统计 — 胜率、总盈亏、按策略聚合。"""
    return json.dumps(local_store.trade_stats(), ensure_ascii=False, default=str)


@mcp.tool(name="trade_journal_update")
def trade_journal_update(id: int, notes: str = "", strategy: str = "", rationale: str = "", entry_price: float = 0) -> str:
    """交易更新 — 修改备注/策略/理由。

    Args:
        id: 交易ID
        notes/strategy/rationale/entry_price: 可更新字段
    """
    return json.dumps(local_store.trade_update(id, notes, strategy, rationale, entry_price), ensure_ascii=False, default=str)


# ═══════════════════════════════════════════════════════════════
# 观察清单（本地 SQLite 存储）
# ═══════════════════════════════════════════════════════════════


@mcp.tool(name="watchlist_create")
def watchlist_create(name: str, description: str = "") -> str:
    """创建观察清单。

    Args:
        name: 清单名称
        description: 描述
    """
    return json.dumps(local_store.watchlist_create(name, description), ensure_ascii=False, default=str)


@mcp.tool(name="watchlist_add")
def watchlist_add(watchlist_id: int, symbols: str) -> str:
    """添加标的到观察清单。

    Args:
        watchlist_id: 清单ID
        symbols: 代码，逗号分隔或JSON数组
    """
    try:
        s = json.loads(symbols) if isinstance(symbols, str) and symbols.strip().startswith("[") else symbols
    except Exception:
        s = symbols
    return json.dumps(local_store.watchlist_add(watchlist_id, s), ensure_ascii=False, default=str)


@mcp.tool(name="watchlist_remove")
def watchlist_remove(watchlist_id: int, symbol: str) -> str:
    """从观察清单移除标的。

    Args:
        watchlist_id: 清单ID
        symbol: 代码
    """
    return json.dumps(local_store.watchlist_remove(watchlist_id, symbol), ensure_ascii=False, default=str)


@mcp.tool(name="watchlist_list")
def watchlist_list() -> str:
    """查看所有观察清单。"""
    return json.dumps(local_store.watchlist_list(), ensure_ascii=False, default=str)


@mcp.tool(name="watchlist_brief")
def watchlist_brief(watchlist_id: int) -> str:
    """生成观察清单实时简报。

    Args:
        watchlist_id: 清单ID
    """
    symbols = local_store.watchlist_get_items(watchlist_id)
    if not symbols:
        return json.dumps({"error": f"观察清单 {watchlist_id} 无标的"}, ensure_ascii=False)
    quotes = []
    up = down = 0
    for s in symbols:
        q = _safe_quote(s)
        quotes.append(q)
        if q.get("change_pct", 0) > 0:
            up += 1
        elif q.get("change_pct", 0) < 0:
            down += 1
    quotes.sort(key=lambda x: x.get("change_pct", 0), reverse=True)
    return json.dumps({
        "watchlist_id": watchlist_id,
        "total": len(quotes),
        "up_count": up, "down_count": down,
        "top_gainer": quotes[0] if quotes else None,
        "top_loser": quotes[-1] if quotes else None,
        "quotes": quotes,
    }, ensure_ascii=False, default=str)


# ═══════════════════════════════════════════════════════════════
# 聚合工具（cache_warmup / market_overview / market_regime / sector_rotation / stock_finder）
# ═══════════════════════════════════════════════════════════════


@mcp.tool(name="cache_warmup")
def cache_warmup(codes: str = "") -> str:
    """缓存预热 — 预取热门股票数据到缓存，减少首次查询延迟。

    Args:
        codes: 可选，JSON数组自定义股票代码列表，如 ["600519","AAPL"]
    """
    pool = None
    if codes and codes.strip():
        try:
            pool = json.loads(codes) if codes.strip().startswith("[") else [c.strip() for c in codes.replace("，", ",").split(",") if c.strip()]
        except Exception:
            pool = None
    return json.dumps(aggregate_tools.cache_warmup(pool), ensure_ascii=False, default=str)


@mcp.tool(name="market_overview")
def market_overview() -> str:
    """全市场总览 — A股主要指数行情 + 行业板块强弱排名 + 美股三大指数。"""
    return json.dumps(aggregate_tools.market_overview(), ensure_ascii=False, default=str)


@mcp.tool(name="market_regime")
def market_regime() -> str:
    """市场状态判断 — 指数趋势(MA20/MA60) + 成交量 + 行业宽度 → bull/bear/oscillate。"""
    return json.dumps(aggregate_tools.market_regime(), ensure_ascii=False, default=str)


@mcp.tool(name="sector_rotation")
def sector_rotation() -> str:
    """板块轮动追踪 — 全行业涨跌排名及动量变化。"""
    return json.dumps(aggregate_tools.sector_rotation(), ensure_ascii=False, default=str)


@mcp.tool(name="stock_finder")
def stock_finder(strategy: str = "etf", max_results: int = 5, risk_tolerance: str = "medium",
                 holdings: str = "") -> str:
    """股票/ETF 推荐 — 策略选股 + 本地行情评分。

    Args:
        strategy: value(低估)/momentum(动量)/etf(ETF)/reversal(反转)
        max_results: 最大返回数量
        risk_tolerance: low/medium/high
        holdings: 当前持仓（JSON数组，可选，用于排除）
    """
    h = None
    if holdings and holdings.strip():
        try:
            h = json.loads(holdings) if holdings.strip().startswith("[") else [x.strip() for x in holdings.replace("，", ",").split(",") if x.strip()]
        except Exception:
            h = None
    return json.dumps(aggregate_tools.stock_finder(strategy, max_results, risk_tolerance, h), ensure_ascii=False, default=str)


# ══════════════════════════════════════════════════════════════
# P2 补全工具（2026-08-16，移植自 Gateway 15 个缺口）
# ══════════════════════════════════════════════════════════════

@mcp.tool(name="get_fund_flow_120d")
def tool_get_fund_flow_120d(code: str, days: int = 120) -> str:
    """获取个股120日资金流向（日级主力/大单/中单/小单净流入）。
    Args: code=股票代码, days=最近多少天(默认120，最大120)
    用途：判断中长期资金趋势"""
    return json.dumps(em_fundflow.get_fund_flow_120d(code, days), ensure_ascii=False, default=str)


@mcp.tool(name="get_fund_flow_minute")
def tool_get_fund_flow_minute(code: str) -> str:
    """获取个股当日盘中分钟级资金流向（主力/大单/中单/小单/超大单净流入）。
    Args: code=股票代码
    用途：盘中实时判断资金偏好"""
    return json.dumps(em_fundflow.get_fund_flow_minute(code), ensure_ascii=False, default=str)


@mcp.tool(name="get_concept_fund_flow")
def tool_get_concept_fund_flow(top_n: int = 20, sort_by: str = "net_inflow") -> str:
    """获取概念板块资金流向排名（主力净流入/流出）。
    Args: top_n=返回条数(默认20), sort_by=net_inflow/net_outflow
    无需股票代码参数，纯市场数据。用途：判断概念级别的资金偏好，捕捉热点题材。"""
    return json.dumps(em_fundflow.get_concept_fund_flow(top_n, sort_by), ensure_ascii=False, default=str)


@mcp.tool(name="get_margin_trading")
def tool_get_margin_trading(code: str, days: int = 30) -> str:
    """获取个股融资融券明细（日级）。含融资余额、融资买入/偿还、融券余额等。
    Args: code=股票代码, days=天数(默认30，最大120)
    用途：两融数据跟踪，判断杠杆资金动向"""
    return json.dumps({"code": code, "records": em_market.get_margin_trading(code, days)}, ensure_ascii=False, default=str)


@mcp.tool(name="get_block_trade")
def tool_get_block_trade(code: str) -> str:
    """获取个股大宗交易记录。含成交价、溢价率、买卖方营业部。
    Args: code=股票代码
    用途：跟踪大宗交易动向，判断机构/大资金行为"""
    return json.dumps({"code": code, "records": em_market.get_block_trade(code)}, ensure_ascii=False, default=str)


@mcp.tool(name="get_holder_change")
def tool_get_holder_change(code: str) -> str:
    """获取股东户数变化（季度级）。含股东户数、环比变化、户均持股。
    Args: code=股票代码
    用途：筹码集中度分析，股东户数持续减少=主力吸筹信号"""
    return json.dumps({"code": code, "records": em_market.get_holder_change(code)}, ensure_ascii=False, default=str)


@mcp.tool(name="get_dividend_history")
def tool_get_dividend_history(code: str) -> str:
    """获取分红送转历史。含每股派息、每10股转增/送股比例。
    Args: code=股票代码
    用途：分红能力评估"""
    return json.dumps({"code": code, "records": em_market.get_dividend_history(code)}, ensure_ascii=False, default=str)


@mcp.tool(name="fetch_financials")
def tool_fetch_financials(code: str) -> str:
    """获取股票财务报表核心数据 — 营收、利润、EPS、FCF、负债、流通股本等。
    Args: code=股票代码
    数据源：东方财富 F10 主要财务指标，自动覆盖近5期"""
    return json.dumps(em_market.fetch_financials(code), ensure_ascii=False, default=str)


@mcp.tool(name="get_financial_reports")
def tool_get_financial_reports(code: str, type: str = "lrb", periods: int = 8) -> str:
    """获取新浪财报三表数据（资产负债表/利润表/现金流量表）。
    Args: code=股票代码, type=报表类型(lrb利润表/fzb资产负债表/llb现金流量表,默认lrb), periods=期数(默认8，最大20)
    用途：详细的财务科目分析"""
    return json.dumps(sina_financial.get_sina_financial_report(code, type, periods), ensure_ascii=False, default=str)


@mcp.tool(name="search_tradingview_market")
def tool_search_tradingview_market(query: str, filter: str = "") -> str:
    """搜索 TV 行情代码。
    Args: query=关键词, filter=类型(可选)
    用途：查找 TV 代码（SSE/SZSE 格式）"""
    return json.dumps(advanced_tools.search_tradingview_market(query, filter), ensure_ascii=False, default=str)


@mcp.tool(name="technical_batch_scan")
def tool_technical_batch_scan(codes: str, days: int = 90, filter: str = "") -> str:
    """批量技术指标扫描 — 一次计算多只股票的技术指标并可按条件筛选。
    Args: codes=股票代码列表(逗号分隔,最多30只), days=K线天数(默认90), filter=筛选条件
    filter可选: macd=golden/dead(金叉/死叉), rsi=oversold/overbought(超卖/超买),
    boll=upper/lower(布林突破), min_score=最小评分(0-100), min_volume_ratio=最小量比, limit=返回条数"""
    return json.dumps(advanced_tools.technical_batch_scan(codes, days, filter), ensure_ascii=False, default=str)


@mcp.tool(name="strategy_scan")
def tool_strategy_scan(strategy: str) -> str:
    """A股特色策略扫描 — 基于涨停梯队/热点题材/技术指标执行选股策略。
    Args: strategy=策略ID(必填), 可选 all=跑全部
    策略: limit_up_ladder(连板梯队) / limit_up_momentum(涨停动量) / broken_board_reversal(断板反包) /
    volume_price_rise(量价齐升) / oversold_rebound(超跌反弹) / ma_bullish(均线多头)
    用途: 盘前/盘中快速选股"""
    return json.dumps(advanced_tools.strategy_scan(strategy), ensure_ascii=False, default=str)


@mcp.tool(name="stock_score")
def tool_stock_score(code: str) -> str:
    """个股综合评分 — 整合技术面、资金流向、市场表现等多维度，输出 0-100 评分及分项明细。
    Args: code=股票代码
    一次调用替代多次独立查询"""
    return json.dumps(advanced_tools.stock_score(code), ensure_ascii=False, default=str)


@mcp.tool(name="stock_signals")
def tool_stock_signals(code: str) -> str:
    """个股多因子信号聚合 — 技术 + 资金 + 量价综合判断。
    Args: code=股票代码
    返回多头/空头信号列表与综合结论"""
    return json.dumps(advanced_tools.stock_signals(code), ensure_ascii=False, default=str)


@mcp.tool(name="tdx_test")
def tool_tdx_test() -> str:
    """TDX 协议连通性测试 — mootdx TCP 直连 + 腾讯行情兜底。
    用途：验证行情链路可用性"""
    return json.dumps(advanced_tools.tdx_test(), ensure_ascii=False, default=str)


# ══════════════════════════════════════════════════════════════
# P3 情报赛道工具（2026-08-16，移植自 Gateway intelligence.ts / intel_fetcher.ts）
# ══════════════════════════════════════════════════════════════

@mcp.tool(name="list_sectors")
def tool_list_sectors() -> str:
    """列出所有投资情报赛道。
    返回 12 大赛道（AI/半导体/机器人/汽车/新能源/医药/航天/网安/科技/消费/宏观/科学），
    含 A 股板块代码(BK)与标签。用途：了解可订阅的情报范围。"""
    return json.dumps(intel_tools.list_sectors(), ensure_ascii=False, default=str)


@mcp.tool(name="get_sector_briefing")
def tool_get_sector_briefing(sector_id: str = "ai") -> str:
    """获取指定赛道的 AI 摘要简报。
    Args: sector_id=赛道ID（ai/semi/robot/auto/energy/bio/space/security/tech/consumer/macro/science）
    返回该赛道今日要点 + 最新新闻。用途：快速了解某赛道最新动态。"""
    return json.dumps(intel_tools.get_sector_briefing(sector_id), ensure_ascii=False, default=str)


@mcp.tool(name="get_sector_news")
def tool_get_sector_news(sector_id: str = "ai", limit: int = 10) -> str:
    """获取指定赛道的最新原始新闻。
    Args: sector_id=赛道ID, limit=返回条数(默认10)
    用途：查看赛道原始新闻标题/来源/摘要。"""
    return json.dumps(intel_tools.get_sector_news(sector_id, limit), ensure_ascii=False, default=str)


@mcp.tool(name="get_all_sectors_briefing")
def tool_get_all_sectors_briefing() -> str:
    """全赛道综合摘要 — 一次获取 12 大赛道的 AI 摘要 + 跨赛道综述 + 当前热门赛道。
    用途：开盘前快速了解全市场情报。"""
    return json.dumps(intel_tools.get_all_sectors_briefing(), ensure_ascii=False, default=str)


@mcp.tool(name="search_industry_news")
def tool_search_industry_news(keyword: str) -> str:
    """跨赛道搜索新闻。
    Args: keyword=搜索关键词
    用途：在所有赛道的缓存新闻中搜索特定主题。"""
    return json.dumps(intel_tools.search_industry_news(keyword), ensure_ascii=False, default=str)


@mcp.tool(name="refresh_intel_cache")
def tool_refresh_intel_cache() -> str:
    """刷新所有赛道情报缓存（重新抓取 RSS）。
    用途：缓存过期后手动刷新。"""
    return json.dumps(intel_tools.refresh_intel_cache(), ensure_ascii=False, default=str)


# ══════════════════════════════════════════════════════════════
# P2 复合分析工具（2026-08-16，移植自 Gateway analyze_policy/analyze_hot_money/lhb/icmemo/dcf/dd_checklist/trap/unit_econ/value_plan）
# ══════════════════════════════════════════════════════════════

@mcp.tool(name="dcf_valuation")
def tool_dcf_valuation(code: str) -> str:
    """DCF 估值模型 — 两阶段自由现金流折现 + 5×5 敏感性表。
    Args: code=股票代码
    基于最新财报 FCF，输出内在价值/安全边际/WACC/敏感性网格。用途：价值投资估值。"""
    return json.dumps(advanced2_dcf.dcf_valuation(code), ensure_ascii=False, default=str)


@mcp.tool(name="ic_memo")
def tool_ic_memo(code: str) -> str:
    """投委会备忘录 — 质量评分 × DCF估值 → P0-P4 级别买入/观望/回避建议。
    Args: code=股票代码
    整合财务质量分 + 估值安全边际 + 情景分析 + 风险清单。用途：投资决策支持。"""
    return json.dumps(advanced2_dcf.ic_memo(code), ensure_ascii=False, default=str)


@mcp.tool(name="unit_economics")
def tool_unit_economics(code: str) -> str:
    """单元经济分析 — SaaS: ARPU/LTV/CAC/回本周期 | 非SaaS: 毛利瀑布分解。
    Args: code=股票代码
    基于财报估算单位经济模型。用途：商业模式质量评估。"""
    return json.dumps(advanced2_unit.unit_economics(code), ensure_ascii=False, default=str)


@mcp.tool(name="value_creation_plan")
def tool_value_creation_plan(code: str) -> str:
    """价值创造计划 — 5年EBITDA Bridge: 营收增长/交叉销售/定价优化/供应链/营运资本。
    Args: code=股票代码
    输出当前→逐杠杆影响→目标EBITDA + 百日优先行动。用途：管理层价值提升路线图。"""
    return json.dumps(advanced2_unit.value_creation_plan(code), ensure_ascii=False, default=str)


@mcp.tool(name="check_trap_risk")
def tool_check_trap_risk(code: str) -> str:
    """杀猪盘检测 — 从K线 + 新闻检测推广/拉盘/出货等杀猪盘特征信号。
    Args: code=股票代码
    检测: 短期暴涨/中期暴涨/放量下跌/连续涨停/新闻推广。用途：避雷。"""
    return json.dumps(advanced2_lhb.check_trap_risk(code), ensure_ascii=False, default=str)


@mcp.tool(name="dd_checklist")
def tool_dd_checklist(code: str) -> str:
    """尽调清单 — 5大工作流（财务/商业/法律/运营/市场）自动尽调。
    Args: code=股票代码
    基于已有数据自动标记完成项，输出完成率 + 需人工核查项。用途：投资尽调框架。"""
    return json.dumps(advanced2_lhb.dd_checklist(code), ensure_ascii=False, default=str)


@mcp.tool(name="analyze_lhb")
def tool_analyze_lhb(code: str) -> str:
    """龙虎榜深度分析 — 个股近30日龙虎榜数据、游资席位识别、机构vs游资博弈。
    Args: code=股票代码（仅A股）
    匹配 22 位知名游资席位库，输出席位买卖/机构拆分/操作建议。用途：跟庄/避雷。"""
    return json.dumps(advanced2_lhb.analyze_lhb(code), ensure_ascii=False, default=str)


@mcp.tool(name="analyze_hot_money")
def tool_analyze_hot_money(code: str) -> str:
    """游资深度分析 — 综合龙虎榜+资金流向+板块资金+概念热度，输出游资博弈全景图。
    Args: code=股票代码
    输出: 龙虎榜摘要/席位分析/资金流趋势/概念热度/风险等级。用途：判断资金博弈格局。"""
    return json.dumps(advanced2_hot.analyze_hot_money(code), ensure_ascii=False, default=str)


@mcp.tool(name="analyze_policy")
def tool_analyze_policy(code: str = "", sector: str = "") -> str:
    """政策影响分析 — 宏观/行业/公司三层政策动态 + 影响评估。
    Args: code=股票代码(可选), sector=行业(可选)
    基于华尔街见闻快讯分类，检测宽松/收紧信号。用途：政策面风险与机会扫描。"""
    return json.dumps(advanced2_hot.analyze_policy(code, sector), ensure_ascii=False, default=str)


@mcp.tool(name="analyze_stock_agent")
def tool_analyze_stock_agent(code: str) -> str:
    """Agent 模式综合股票分析 — PlanExecute 编排多工具深度分析。
    Args: code=股票代码
    按顺序执行: 行情→财务→技术→资金→风险→综合结论。用途：一站式个股体检。"""
    from tools.advanced2_hot import analyze_hot_money
    from tools.advanced2_dcf import dcf_valuation
    from tools.advanced2_lhb import check_trap_risk, analyze_lhb
    from data_sources import tencent, em_market
    result = {"code": code, "steps": []}
    try:
        q = tencent.get_realtime_quote(code)
        result["steps"].append({"step": "行情", "name": q.get("name", code), "price": q.get("price"),
                                "change_pct": q.get("change_pct")})
    except Exception as e:
        result["steps"].append({"step": "行情", "error": str(e)[:80]})
    try:
        fin = em_market.fetch_financials(code)
        result["steps"].append({"step": "财务", "revenue_yi": round((fin.get("revenue") or 0)/1e8, 1),
                                "net_profit_yi": round((fin.get("net_profit") or 0)/1e8, 1),
                                "net_margin": fin.get("net_margin")})
    except Exception as e:
        result["steps"].append({"step": "财务", "error": str(e)[:80]})
    try:
        d = dcf_valuation(code)
        result["steps"].append({"step": "估值", "intrinsic": d.get("intrinsic_per_share"),
                                "safety_margin_pct": d.get("safety_margin_pct")})
    except Exception as e:
        result["steps"].append({"step": "估值", "error": str(e)[:80]})
    try:
        t = check_trap_risk(code)
        result["steps"].append({"step": "风险", "risk_level": t.get("risk_level"),
                                "signals": len(t.get("signals") or [])})
    except Exception as e:
        result["steps"].append({"step": "风险", "error": str(e)[:80]})
    try:
        hm = analyze_hot_money(code)
        result["steps"].append({"step": "资金博弈", "risk_level": hm.get("risk_level"),
                                "lhb_trend": hm.get("lhb_summary", {}).get("trend")})
    except Exception as e:
        result["steps"].append({"step": "资金博弈", "error": str(e)[:80]})
    # 综合结论
    risks = [s.get("risk_level") for s in result["steps"] if s.get("risk_level") == "高"]
    result["conclusion"] = "⚠️ 存在高风险信号，建议谨慎" if risks else "基本面+资金面综合评估正常"
    return json.dumps(result, ensure_ascii=False, default=str)


# ── 辅助函数 ──────────────────────────────────────────────


def _safe_quote(code: str) -> dict:
    """安全获取行情（供 watchlist_brief 使用），失败返回最小结构"""
    try:
        q = tencent.get_realtime_quote(code)
        return {
            "code": code,
            "name": q.get("name") or code,
            "price": q.get("price") or 0,
            "change_pct": q.get("change_pct") or 0,
            "source": q.get("source") or "",
        }
    except Exception:
        return {"code": code, "name": code, "price": 0, "change_pct": 0}


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
    import os
    mode = os.environ.get("STOCK_MCP_MODE", "stdio")
    port = int(os.environ.get("STOCK_MCP_PORT", "8902"))
    if mode == "http":
        # streamable HTTP 模式（供 cron 脚本 / Hermes 远程调用）
        import uvicorn
        from mcp.server.fastmcp import FastMCP
        mcp.settings.host = "127.0.0.1"
        mcp.settings.port = port
        uvicorn.run(mcp.streamable_http_app(), host="127.0.0.1", port=port, log_level="warning")
    else:
        mcp.run()