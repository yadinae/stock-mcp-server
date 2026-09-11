from __future__ import annotations
import json

from tools.advanced2_lhb import check_trap_risk, dd_checklist
from tools.advanced2_hot import analyze_policy
from data_sources import em_market


def register(mcp):
    @mcp.tool(name="check_trap_risk")
    def check_trap_risk_tool(code: str) -> str:
        """杀猪盘检测 — 从K线 + 新闻检测推广/拉盘/出货等杀猪盘特征信号。
        Args:
            code: 股票代码
        检测维度：K线形态异常、新闻推广关键词、量价背离等。
        """
        result = check_trap_risk(code)
        return json.dumps(result, ensure_ascii=False, default=str)

    @mcp.tool(name="dd_checklist")
    def dd_checklist_tool(code: str) -> str:
        """尽调清单 — 5大工作流（财务/商业/法律/运营/市场）自动尽调。
        Args:
            code: 股票代码
        """
        result = dd_checklist(code)
        return json.dumps(result, ensure_ascii=False, default=str)

    @mcp.tool(name="analyze_policy")
    def analyze_policy_tool(code: str = "", sector: str = "") -> str:
        """政策影响分析 — 宏观/行业/公司三层政策动态 + 影响评估。
        Args:
            code: 股票代码(可选)
            sector: 行业名称(可选)
        """
        result = analyze_policy(code=code, sector=sector)
        return json.dumps(result, ensure_ascii=False, default=str)

    @mcp.tool(name="get_stock_boards")
    def get_stock_boards_tool(code: str) -> str:
        """个股所属板块 — 行业/概念/地域。
        Args:
            code: 股票代码
        """
        result = em_market.get_stock_boards(code)
        return json.dumps(result, ensure_ascii=False, default=str)

    @mcp.tool(name="analyze_stock_agent")
    def analyze_stock_agent_tool(code: str) -> str:
        """Agent 模式综合股票分析 — PlanExecute 编排多工具深度分析。
        Args:
            code: 股票代码
        """
        from tools.advanced2_hot import analyze_hot_money
        from tools.advanced2_dcf import dcf_valuation
        from tools.advanced2_lhb import check_trap_risk, analyze_lhb
        from data_sources import tencent, em_market

        result = {"code": code, "steps": []}

        try:
            q = tencent.get_realtime_quote(code)
            result["steps"].append({"step": "行情", "name": q.get("name", code),
                                    "price": q.get("price"),
                                    "change_pct": q.get("change_pct")})
        except Exception as e:
            result["steps"].append({"step": "行情", "error": str(e)[:80]})

        try:
            fin = em_market.fetch_financials(code)
            result["steps"].append({"step": "财务",
                                    "revenue_yi": round((fin.get("revenue") or 0) / 1e8, 1),
                                    "net_profit_yi": round((fin.get("net_profit") or 0) / 1e8, 1),
                                    "net_margin": fin.get("net_margin")})
        except Exception as e:
            result["steps"].append({"step": "财务", "error": str(e)[:80]})

        try:
            d = dcf_valuation(code)
            result["steps"].append({"step": "估值",
                                    "intrinsic": d.get("intrinsic_per_share"),
                                    "safety_margin_pct": d.get("safety_margin_pct")})
        except Exception as e:
            result["steps"].append({"step": "估值", "error": str(e)[:80]})

        try:
            t = check_trap_risk(code)
            result["steps"].append({"step": "风险",
                                    "risk_level": t.get("risk_level"),
                                    "signals": len(t.get("signals") or [])})
        except Exception as e:
            result["steps"].append({"step": "风险", "error": str(e)[:80]})

        try:
            hm = analyze_hot_money(code)
            result["steps"].append({"step": "资金博弈",
                                    "risk_level": hm.get("risk_level"),
                                    "lhb_trend": hm.get("lhb_summary", {}).get("trend")})
        except Exception as e:
            result["steps"].append({"step": "资金博弈", "error": str(e)[:80]})

        risks = [s.get("risk_level") for s in result["steps"] if s.get("risk_level") == "高"]
        result["conclusion"] = "⚠️ 存在高风险信号，建议谨慎" if risks else "基本面+资金面综合评估正常"
        return json.dumps(result, ensure_ascii=False, default=str)
