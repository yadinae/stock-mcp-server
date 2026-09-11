from __future__ import annotations
import json
import copy

from core.helpers import (
    _validate_code, _error_response,
    _get_realtime_quote, _get_kline, _get_stock_info,
)
from core.parallel import run_parallel
from tools.technical import analyze as analyze_technical
from tools.news import search_news
from tools.analyzer import analyze_stock as ai_analyze
from tools.st_risk import get_st_risk
from tools.backtest import run_backtest, list_backtest_strategies
from tools import advanced2_dcf
from tools import advanced2_unit


def register(mcp):
    @mcp.tool(name="analyze_stock_ai")
    def analyze_stock_ai_tool(code: str, name: str = "") -> str:
        """AI 智能分析股票，生成决策仪表盘（含评分、买卖建议、技术面、消息面）
        Args:
            code: 股票代码。A股示例：600519, 000001  美股示例：AAPL, MSFT  港股示例：HK00700
            name: 股票名称（可选）

        并行获取实时行情 + K 线 + 新闻数据，然后调用 LLM 分析。
        """
        err = _validate_code(code)
        if err:
            return _error_response(code, err)

        stock_name = name or _get_stock_info(code).get("name", "")

        tasks = {
            "realtime": lambda: _get_realtime_quote(code),
            "kline": lambda: _get_kline(code, days=120),
            "news": lambda: search_news(code, stock_name or code),
        }
        parallel_results = run_parallel(tasks, timeout=25)

        realtime = parallel_results.get("realtime", {"error": "获取失败"})
        kline = parallel_results.get("kline", {"error": "获取失败"})
        news_data = parallel_results.get("news", {"error": "获取失败"})

        technical = {}
        records = kline.get("records", []) if isinstance(kline, dict) else []
        if records:
            try:
                technical = analyze_technical(records, code)
            except Exception as e:
                technical = {"error": str(e)}

        result = ai_analyze(
            stock_code=code, stock_name=stock_name or code,
            realtime_data=realtime, kline_data=kline,
            technical_data=technical, news_data=news_data,
        )
        return json.dumps(result, ensure_ascii=False, default=str)

    @mcp.tool(name="check_backtest")
    def check_backtest_tool(
        code: str,
        strategy: str = "ma_crossover",
        days: int = 365,
        capital: float = 100000.0,
        slippage_model: str = "",
        slippage_rate: float = 0.0,
    ) -> str:
        """策略回测 — 基于历史K线模拟交易，评估策略表现（含S/A/B/C/D评级）
        Args:
            code: 股票代码。A股示例：600519, 000001  美股示例：AAPL, MSFT
            strategy: 策略ID (ma_crossover=MA金叉/死叉, macd=MACD, rsi=RSI均值回归,
                      bollinger=布林带反弹, combined=组合信号)
            days: 回测天数（默认365，最大730）
            capital: 初始资金（默认100,000）
            slippage_model: 滑点模型 (percentage=百分比, flat=固定金额, volume=成交量感知, 空=默认)
            slippage_rate: 滑点参数（percentage模型=比例如0.001, flat模型=元/股如0.05）

        输出：交易记录、绩效指标（总收益率/年化/最大回撤/夏普/Sortino/Calmar/波动率/胜率）、
              S/A/B/C/D 数据评级（六维加权+一票否决）、权益曲线
        注意：回测仅作研究参考，不代表未来收益
        """
        err = _validate_code(code)
        if err:
            return _error_response(code, err)

        strategies = list_backtest_strategies()
        valid_ids = [s["id"] for s in strategies]
        if strategy not in valid_ids:
            return _error_response(code, f"未知策略: {strategy}，可用策略: {', '.join(valid_ids)}")

        backtest_days = min(max(days, 60), 730)
        kline = _get_kline(code, days=backtest_days)
        records = kline.get("records", [])
        if not records:
            return _error_response(code, kline.get("error", "无K线数据"), "data_error")

        # 构建滑点参数
        sm_params = {}
        if slippage_model and slippage_rate > 0:
            if slippage_model == "percentage":
                sm_params["rate"] = slippage_rate
            elif slippage_model == "flat":
                sm_params["amount"] = slippage_rate
            elif slippage_model == "volume":
                sm_params["impact_factor"] = slippage_rate

        result = run_backtest(
            code=code, records=records, strategy=strategy,
            days=backtest_days, capital=capital,
            slippage_model=slippage_model or None,
            slippage_params=sm_params or None,
        )
        return json.dumps(result, ensure_ascii=False, default=str)

    @mcp.tool(name="run_alert_check")
    def run_alert_check_tool(dry_run: bool = False, channel: str = "auto") -> str:
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

    @mcp.tool(name="check_st_risk")
    def check_st_risk_tool(code: str) -> str:
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

    @mcp.tool(name="dcf_valuation")
    def dcf_valuation_tool(code: str) -> str:
        """DCF 估值模型 — 两阶段自由现金流折现 + 5×5 敏感性表。
        Args:
            code: 股票代码
        基于最新财报数据，输出内在价值、安全边际、敏感性分析。
        """
        result = advanced2_dcf.dcf_valuation(code)
        return json.dumps(result, ensure_ascii=False, default=str)

    @mcp.tool(name="ic_memo")
    def ic_memo_tool(code: str) -> str:
        """投委会备忘录 — 质量评分 × DCF估值 → P0-P4 级别买入/观望/回避建议。
        Args:
            code=股票代码
        综合财务质量、估值安全边际、技术面、风险信号，输出投委会级别建议。
        """
        result = advanced2_dcf.ic_memo(code)
        return json.dumps(result, ensure_ascii=False, default=str)

    @mcp.tool(name="unit_economics")
    def unit_economics_tool(code: str) -> str:
        """单元经济分析 — SaaS: ARPU/LTV/CAC/回本周期 | 非SaaS: 毛利瀑布分解。
        Args:
            code: 股票代码
        根据公司类型自动选择分析模型。
        """
        result = advanced2_unit.unit_economics(code)
        return json.dumps(result, ensure_ascii=False, default=str)

    @mcp.tool(name="value_creation_plan")
    def value_creation_plan_tool(code: str) -> str:
        """价值创造计划 — 5年EBITDA Bridge: 营收增长/交叉销售/定价优化/供应链/营运资本。
        Args:
            code: 股票代码
        基于财务数据生成5年价值创造路径。
        """
        result = advanced2_unit.value_creation_plan(code)
        return json.dumps(result, ensure_ascii=False, default=str)

    @mcp.tool(name="stock_score")
    def stock_score(code: str) -> str:
        """个股综合评分 — 整合技术面、资金流向、市场表现等多维度，输出 0-100 评分及分项明细。
        Args: code=股票代码"""
        from tools.advanced import stock_score as _stock_score
        return json.dumps(_stock_score(code), ensure_ascii=False, default=str)

    @mcp.tool(name="stock_signals")
    def stock_signals(code: str) -> str:
        """个股多因子信号聚合 — 技术 + 资金 + 量价综合判断。
        Args: code=股票代码"""
        from tools.advanced import stock_signals as _stock_signals
        return json.dumps(_stock_signals(code), ensure_ascii=False, default=str)

    @mcp.tool(name="strategy_scan")
    def strategy_scan(strategy: str) -> str:
        """A股特色策略扫描 — 基于涨停梯队/热点题材/技术指标执行选股策略。
        Args: strategy=策略ID(limit_up_ladder/momentum/broken_board_reversal/volume_price_rise/oversold_rebound/ma_bullish/all)"""
        from tools.advanced import strategy_scan as _strategy_scan
        return json.dumps(_strategy_scan(strategy), ensure_ascii=False, default=str)
