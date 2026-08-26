"""策略扫描工具注册 — 提供 4 个技术面选股策略 + baostock 数据回填。

工具列表：
1. strategy_scan_turtle  — 海龟突破
2. strategy_scan_ma_vol  — 均线金叉放量
3. strategy_scan_flag    — 高窄旗形整理
4. strategy_scan_rps     — RPS 突破
5. strategy_scan_all     — 全策略扫描
6. baostock_backfill     — 回填历史数据
"""
from __future__ import annotations

import json
import logging
import time

logger = logging.getLogger("stock-mcp.strategy_scan")


def register(mcp):
    """Register strategy scan tools with the MCP server."""

    # ── 单策略扫描 ──
    @mcp.tool(name="strategy_scan_turtle")
    def strategy_scan_turtle() -> str:
        """海龟交易策略扫描 — 20日新高突破+成交额过亿+阳线防诱多。
        扫描全市场A股，返回满足海龟突破条件的股票列表。
        需要先运行 baostock_backfill 回填历史数据。
        """
        from tools.strategies import TurtleTradeStrategy
        t0 = time.time()
        strategy = TurtleTradeStrategy()
        result = strategy.run()
        result.details["elapsed_s"] = round(time.time() - t0, 1)
        return _format_result(result)

    @mcp.tool(name="strategy_scan_ma_vol")
    def strategy_scan_ma_vol() -> str:
        """均线金叉放量策略扫描 — MA5上穿MA20+成交量放大1.5倍。
        扫描全市场A股，返回满足均线金叉放量条件的股票列表。
        需要先运行 baostock_backfill 回填历史数据。
        """
        from tools.strategies import MaVolumeStrategy
        t0 = time.time()
        strategy = MaVolumeStrategy()
        result = strategy.run()
        result.details["elapsed_s"] = round(time.time() - t0, 1)
        return _format_result(result)

    @mcp.tool(name="strategy_scan_flag")
    def strategy_scan_flag() -> str:
        """高窄旗形整理策略扫描 — 强动量后极度收敛+缩量。
        扫描全市场A股，返回满足高窄旗形整理条件的股票列表。
        需要先运行 baostock_backfill 回填历史数据。
        """
        from tools.strategies import HighTightFlagStrategy
        t0 = time.time()
        strategy = HighTightFlagStrategy()
        result = strategy.run()
        result.details["elapsed_s"] = round(time.time() - t0, 1)
        return _format_result(result)

    @mcp.tool(name="strategy_scan_rps")
    def strategy_scan_rps() -> str:
        """RPS极强动量突破策略扫描 — 120日相对强度Top10%+接近新高。
        扫描全市场A股，返回满足RPS突破条件的股票列表。
        需要先运行 baostock_backfill 回填历史数据。
        """
        from tools.strategies import RpsBreakoutStrategy
        t0 = time.time()
        strategy = RpsBreakoutStrategy()
        result = strategy.run()
        result.details["elapsed_s"] = round(time.time() - t0, 1)
        return _format_result(result)

    # ── 全策略扫描 ──
    @mcp.tool(name="strategy_scan_all")
    def strategy_scan_all(strategies: str = "") -> str:
        """全策略扫描 — 一次运行所有技术面选股策略。

        Args:
            strategies: 逗号分隔的策略名，为空则全部运行。
                        可选: turtle_trade, ma_volume, high_tight_flag, rps_breakout
        """
        from tools.strategies import ALL_STRATEGIES

        t0 = time.time()
        wanted = [s.strip() for s in strategies.split(",") if s.strip()] if strategies else list(ALL_STRATEGIES.keys())
        results = {}
        total_selected = 0

        for name in wanted:
            cls = ALL_STRATEGIES.get(name)
            if not cls:
                results[name] = {"error": f"未知策略: {name}"}
                continue
            try:
                strategy = cls()
                result = strategy.run()
                results[name] = {
                    "selected_count": result.select_count,
                    "scan_count": result.scan_count,
                    "stocks": result.selected[:20],  # 限制返回数量
                }
                total_selected += result.select_count
            except Exception as e:
                results[name] = {"error": str(e)[:200]}

        elapsed = round(time.time() - t0, 1)
        return json.dumps({
            "strategy_results": results,
            "total_selected": total_selected,
            "elapsed_s": elapsed,
            "strategies_run": len(wanted),
        }, ensure_ascii=False, default=str)

    # ── baostock 数据回填 ──
    @mcp.tool(name="baostock_backfill")
    def baostock_backfill(symbols: str = "", days: int = 120) -> str:
        """回填 A 股历史日 K 线数据（baostock 免费数据源）。

        Args:
            symbols: 逗号分隔的股票代码，为空则回填全市场热门股
            days: 回填天数（默认120天，足够策略扫描使用）
        """
        from data_sources.baostock_source import backfill_batch

        t0 = time.time()
        if symbols:
            symbol_list = [s.strip() for s in symbols.split(",") if s.strip()]
        else:
            # 回填热门股（覆盖策略所需的 min_bars）
            hot = [
                "600519", "000858", "300750", "601318", "000333",
                "000001", "600000", "601398", "600276", "002475",
                "300059", "002594", "601012", "300274", "002415",
                "600809", "000568", "601888", "600036", "601166",
                "002304", "600309", "603259", "300014", "002352",
                "601899", "600900", "600585", "000725", "601328",
            ]
            symbol_list = hot

        result = backfill_batch(symbol_list, "2024-01-01")
        result["elapsed_s"] = round(time.time() - t0, 1)
        return json.dumps(result, ensure_ascii=False)


def _format_result(result) -> str:
    """格式化策略结果为 JSON 字符串"""
    return json.dumps({
        "strategy": result.strategy_name,
        "selected_count": result.select_count,
        "scan_count": result.scan_count,
        "selected": result.selected,
        "error": result.error or None,
        "details": result.details or None,
    }, ensure_ascii=False, default=str)
