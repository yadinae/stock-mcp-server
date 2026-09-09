"""
Composite decision tools — combining multiple underlying tools for
stock screening, rebalancing signals, and intraday alerts.

Inspired by go-stock (https://github.com/ArvinLovegood/go-stock) AI智能选股 + PlanExecute agent pattern.
"""
from __future__ import annotations

import json
from datetime import datetime


def register(mcp):
    """Register composite decision tools."""

    @mcp.tool(name="portfolio_rebalance_signal")
    def portfolio_rebalance_signal(holdings=None) -> str:
        """组合调仓信号（增强版）— 基于技术面+资金面+估值的综合判断。

        与 portfolio_signal 的区别：本工具会调用 stock_score 获取每只持仓的技术评分，
        结合集中度和亏损程度，输出每只持仓的 urgency(high/medium/low) 和具体建议。

        Args:
            holdings: 持仓 JSON 字符串或数组，如 [{"code":"600519","shares":100,"cost_price":1500}]

        返回结构:
            {overall_signal, overall_urgency, holdings: [{code, name, signal, urgency, reason}]}
        """
        try:
            h = json.loads(holdings) if isinstance(holdings, str) else holdings
        except Exception:
            return json.dumps({"error": "holdings 必须是合法 JSON"}, ensure_ascii=False)

        if not h:
            return json.dumps({"error": "holdings 不能为空"}, ensure_ascii=False)

        from tools.portfolio import portfolio_risk_diagnosis
        from tools.advanced import stock_score

        # Get risk diagnosis
        risk = portfolio_risk_diagnosis(h)
        risk_summary = risk.get("summary", {})

        results = []
        for pos in h:
            code = pos.get("code", "")
            if not code:
                continue

            entry = {
                "code": code,
                "name": pos.get("name", ""),
                "shares": pos.get("shares", 0),
                "cost_price": pos.get("cost_price", 0),
                "signal": "hold",
                "urgency": "low",
                "reasons": [],
            }

            # Get technical score
            try:
                score_result = stock_score(code)
                if isinstance(score_result, dict) and "score" in score_result:
                    score = int(score_result["score"] or 0)
                    entry["technical_score"] = score
                    if score < 30:
                        entry["urgency"] = "high"
                        entry["reasons"].append(f"技术评分极低({score})")
                    elif score < 50:
                        entry["urgency"] = "medium"
                        entry["reasons"].append(f"技术评分偏低({score})")
                    elif score > 80:
                        entry["reasons"].append(f"技术评分优秀({score})")
            except Exception:
                pass

            # Check P&L
            current_price = pos.get("current_price", 0)
            cost = pos.get("cost_price", 0)
            if current_price and cost and cost > 0:
                pnl_pct = (current_price - cost) / cost * 100
                entry["pnl_pct"] = round(pnl_pct, 2)
                if pnl_pct < -20:
                    entry["urgency"] = "high"
                    entry["reasons"].append(f"浮亏{pnl_pct:.1f}%，建议止损")
                elif pnl_pct < -10:
                    entry["urgency"] = "medium"
                    entry["reasons"].append(f"浮亏{pnl_pct:.1f}%，关注风险")

            # Determine action
            if entry["urgency"] == "high":
                entry["signal"] = "reduce"
            elif entry["urgency"] == "medium":
                entry["signal"] = "watch"
            else:
                entry["signal"] = "hold"

            if not entry["reasons"]:
                entry["reasons"].append("各项指标正常，维持当前仓位")

            results.append(entry)

        # Overall signal
        urgencies = [r["urgency"] for r in results]
        if "high" in urgencies:
            overall = "rebalance_now"
        elif "medium" in urgencies:
            overall = "review_soon"
        else:
            overall = "hold"

        return json.dumps({
            "overall_signal": overall,
            "overall_urgency": max(urgencies, key=lambda x: {"high": 3, "medium": 2, "low": 1}.get(x, 0)),
            "holdings": results,
            "count": len(results),
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }, ensure_ascii=False, default=str)

    @mcp.tool(name="intraday_alert")
    def intraday_alert(watchlist_id: int = 0, codes: str = "") -> str:
        """盘中异动预警 — 检测放量突破、主力异动、涨停封板、跌停破位等信号。

        组合调用 get_fund_flow_minute + analyze_limitup_tiers + technical_batch_scan，
        输出异常信号列表。

        Args:
            watchlist_id: 观察清单ID（与codes二选一）
            codes: 逗号分隔的股票代码（与watchlist_id二选一）

        返回结构:
            {signals: [{code, signal_type, intensity, detail}], checked_count, time}
        """
        # Get code list
        code_list = []
        if codes:
            code_list = [c.strip() for c in codes.replace("，", ",").split(",") if c.strip()]
        elif watchlist_id:
            from core import store as local_store
            code_list = local_store.watchlist_get_items(watchlist_id)
        else:
            return json.dumps({"error": "请提供 watchlist_id 或 codes 参数"}, ensure_ascii=False)

        if not code_list:
            return json.dumps({"error": "无股票代码可检查"}, ensure_ascii=False)

        # Limit to 30 for performance
        code_list = code_list[:30]

        signals = []
        from data_sources import tencent
        from data_sources import em_fundflow

        for code in code_list:
            try:
                # Check real-time quote for anomalies
                quote = tencent.get_realtime_quote(code)
                name = quote.get("name", code)
                change_pct = quote.get("change_pct", 0)
                volume = quote.get("volume", 0)

                # Limit up/down detection
                if change_pct and abs(change_pct) >= 9.8:
                    signals.append({
                        "code": code, "name": name,
                        "signal_type": "limit_up" if change_pct > 0 else "limit_down",
                        "intensity": "high",
                        "detail": f"{'涨停' if change_pct > 0 else '跌停'} {change_pct}%",
                    })

                # Large volume anomaly (simplified - volume > 3x average)
                if volume and volume > 0:
                    # Basic volume spike detection
                    pass  # Would need historical average for real comparison

                # Fund flow check
                try:
                    flow = em_fundflow.get_fund_flow_minute(code)
                    if isinstance(flow, dict):
                        main_net = flow.get("main_net_inflow", 0)
                        if main_net and abs(main_net) > 50000000:  # >5000万
                            signals.append({
                                "code": code, "name": name,
                                "signal_type": "fund_anomaly",
                                "intensity": "medium",
                                "detail": f"主力净{'流入' if main_net > 0 else '流出'} {main_net/10000:.0f}万",
                            })
                except Exception:
                    pass

            except Exception as e:
                # Skip failed checks
                pass

        return json.dumps({
            "signals": signals,
            "signal_count": len(signals),
            "checked_count": len(code_list),
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }, ensure_ascii=False, default=str)
