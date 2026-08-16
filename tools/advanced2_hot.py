#!/usr/bin/env python3
"""游资深度分析 + 政策影响分析（P2 补全，移植自 Gateway analyze_hot_money.ts / analyze_policy.ts，2026-08-16）

纯规则组合，零新数据源（复用本地已有工具）。
"""
import json
import time

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"


# ─── analyze_hot_money: 游资博弈全景 ───

def analyze_hot_money(code: str = ""):
    """游资深度分析 — 综合龙虎榜+资金流向+板块资金+概念热度，输出游资博弈全景图。"""
    code = (code or "").strip().upper()
    if not code:
        return {"error": "code 不能为空"}

    from data_sources import tencent, em_market, em_fundflow
    from tools.advanced2_lhb import analyze_lhb

    analysis = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
        "code": code, "name": "",
        "lhb_summary": {"recent_count": 0, "net_amount": 0, "trend": "博弈激烈"},
        "seat_analysis": {"total_seats": 0, "institutional": {"buy": 0, "sell": 0, "net": 0},
                          "hot_money": {"buy": 0, "sell": 0, "net": 0}, "dominant": "均衡"},
        "fund_flow_trend": {"signal": "无数据"},
        "sector_context": {},
        "risk_level": "低",
        "analysis": [],
    }

    # 1. 股票名
    try:
        q = tencent.get_realtime_quote(code)
        if q and q.get("name"):
            analysis["name"] = q["name"]
    except Exception:
        pass

    # 2. 龙虎榜深度分析
    try:
        lhb = analyze_lhb(code)
        records = lhb.get("lhb_records") or []
        if records:
            analysis["lhb_summary"]["recent_count"] = lhb.get("lhb_count_30d") or len(records)
            total_buy = sum(r.get("buy_amount") or 0 for r in records)
            total_sell = sum(r.get("sell_amount") or 0 for r in records)
            analysis["lhb_summary"]["net_amount"] = round(total_buy - total_sell, 2)
            ivy = lhb.get("inst_vs_youzi") or {}
            if ivy:
                analysis["seat_analysis"]["institutional"] = {
                    "buy": round(ivy.get("institutional_buy") or 0, 2),
                    "sell": round(ivy.get("institutional_sell") or 0, 2),
                    "net": round((ivy.get("institutional_buy") or 0) - (ivy.get("institutional_sell") or 0), 2),
                }
                analysis["seat_analysis"]["hot_money"] = {
                    "buy": round(ivy.get("youzi_buy") or 0, 2),
                    "sell": round(ivy.get("youzi_sell") or 0, 2),
                    "net": round((ivy.get("youzi_buy") or 0) - (ivy.get("youzi_sell") or 0), 2),
                }
                inst_total = (ivy.get("institutional_buy") or 0) + (ivy.get("institutional_sell") or 0)
                yz_total = (ivy.get("youzi_buy") or 0) + (ivy.get("youzi_sell") or 0)
                analysis["seat_analysis"]["dominant"] = "机构" if inst_total > yz_total else "游资"
            analysis["seat_analysis"]["total_seats"] = len(set(r.get("seat_name") for r in records if r.get("seat_name")))
            net = analysis["lhb_summary"]["net_amount"]
            analysis["lhb_summary"]["trend"] = "净买入" if net > 200 else ("净卖出" if net < -200 else "博弈激烈")
            for yz in lhb.get("matched_youzi") or []:
                y = yz.get("youzi") or {}
                analysis["analysis"].append(
                    f"🔍 游资 {y.get('name', '')}({y.get('style', '')}) {yz.get('verdict', '')} — "
                    f"净{'买' if (yz.get('net') or 0) >= 0 else '卖'}{abs(yz.get('net') or 0):.0f}万")
    except Exception as e:
        analysis["analysis"].append(f"龙虎榜分析失败: {str(e)[:60]}")

    # 3. 资金流
    try:
        ff = em_fundflow.get_fund_flow_120d(code, days=120)
        flow = ff.get("flow") or []
        if flow:
            main_net = sum(f.get("main_net") or 0 for f in flow)
            analysis["fund_flow_trend"]["main_net_120d"] = round(main_net / 1e8, 2)  # 亿
            analysis["fund_flow_trend"]["signal"] = "主力流入" if main_net > 0 else "主力流出"
    except Exception:
        pass

    # 4. 板块概念
    try:
        boards = em_market.get_stock_boards(code)
        tags = boards.get("concept_tags") or []
        if tags:
            cf = em_fundflow.get_concept_fund_flow(50)
            records = cf.get("records") or []
            matched = next((r for r in records if r.get("name") in tags), None)
            if matched:
                analysis["sector_context"]["concept_name"] = matched["name"]
                analysis["sector_context"]["concept_net_inflow"] = matched["net_inflow"]
                inflow = (matched.get("net_inflow") or 0) / 1e8
                analysis["analysis"].append(
                    f"📊 所属概念「{matched['name']}」主力净流入: {'+' if inflow > 0 else ''}{inflow:.2f}亿")
    except Exception:
        pass

    # 5. 全市场龙虎榜背景
    try:
        market_lhb = em_market.get_market_lhb()
        stocks = market_lhb.get("stocks") or []
        if stocks:
            top_buy = sum(1 for s in stocks if (s.get("net_buy_wan") or 0) > 0)
            top_sell = sum(1 for s in stocks if (s.get("net_buy_wan") or 0) < 0)
            analysis["analysis"].append(f"🏆 今日全市场龙虎榜: {top_buy}只净买入, {top_sell}只净卖出")
    except Exception:
        pass

    # 6. 风险
    risk = 0
    if analysis["lhb_summary"]["recent_count"] >= 5:
        risk += 2
    if analysis["fund_flow_trend"].get("signal") == "主力流出":
        risk += 2
    if analysis["fund_flow_trend"].get("signal") == "分歧":
        risk += 1
    if analysis["seat_analysis"]["dominant"] == "游资" and analysis["seat_analysis"]["hot_money"]["net"] < 0:
        risk += 1
    if analysis["lhb_summary"]["trend"] == "净卖出":
        risk += 1
    analysis["risk_level"] = "高" if risk >= 4 else ("中" if risk >= 2 else "低")

    analysis["analysis"].insert(0, f"📈 {analysis['name'] or code} 资金博弈分析")
    tips = {"高": "游资活跃度高，短期波动风险较大，建议谨慎操作",
            "中": "存在一定资金博弈，注意仓位控制", "低": "资金面较为平稳"}
    analysis["analysis"].append(f"⚠️ 风险等级: {analysis['risk_level']}")
    analysis["analysis"].append(f"  提示: {tips.get(analysis['risk_level'], '')}")
    return analysis


# ─── analyze_policy: 政策影响分析 ───

def _categorize_policy(content, sector):
    lower = content.lower()
    if sector and sector.lower() in lower:
        return "industry"
    if any(k in content for k in ["股票", "股份", "公司"]):
        return "company"
    return "macro"


def analyze_policy(code: str = "", sector: str = ""):
    """政策影响分析 — 宏观/行业/公司三层政策动态 + 影响评估。"""
    code = (code or "").strip().upper()
    sector = (sector or "").strip()

    from data_sources import tencent, em_market
    from data_sources.em_market import get_wallstreetcn_news
    from tools.news import search_news

    stock_info = {}
    stock_sector = sector
    if code:
        try:
            q = tencent.get_realtime_quote(code)
            if q:
                stock_info["name"] = q.get("name")
            boards = em_market.get_stock_boards(code)
            tags = boards.get("concept_tags") or []
            if tags:
                stock_sector = stock_sector or tags[0]
                stock_info["sectors"] = tags[:5]
        except Exception:
            pass

    target_sector = stock_sector or "股市"

    # 华尔街见闻快讯（本地签名: get_wallstreetcn_news(limit, mode)，无 policy 频道 → 用 macro+all）
    all_macro, all_industry = [], []
    try:
        for mode in ("all",):
            src = get_wallstreetcn_news(limit=15, mode=mode)
            items = []
            live = (src or {}).get("live_news") or {}
            items.extend(live.get("items") or [])
            arts = (src or {}).get("hot_articles") or {}
            items.extend(arts.get("articles") or [])
            for item in items:
                content = item.get("content") or item.get("title") or ""
                cat = _categorize_policy(content, target_sector)
                entry = {"time": item.get("time") or "", "content": content[:1000],
                         "source": "华尔街见闻", "url": item.get("url") or ""}
                if cat == "industry":
                    all_industry.append(entry)
                else:
                    all_macro.append(entry)
    except Exception:
        pass

    # 个股政策相关新闻
    company_news = []
    if code:
        try:
            news = search_news(code, stock_info.get("name", ""))
            for n in (news.get("news") or [])[:5]:
                title = n.get("title") or ""
                if any(k in title for k in ["政策", "规定", "监管", "通知", "意见", "办法", "条例", "规划", "纲要", "指示", "改革"]):
                    company_news.append(f"📄 {title}")
        except Exception:
            pass

    # 影响评估
    risk_signals, impact_lines = [], []
    if all_macro:
        impact_lines.append(f"📊 **宏观政策动态**（{len(all_macro)}条）")
        for item in all_macro:
            if any(k in item["content"] for k in ["加息", "收紧", "去杠杆", "从严", "处罚", "风险", "降温"]):
                risk_signals.append(f"⚠️ 收紧信号: {item['content'][:80]}...")
            if any(k in item["content"] for k in ["降准", "降息", "宽松", "支持", "补贴", "鼓励", "减免"]):
                impact_lines.append(f"✅ 宽松信号: {item['content'][:80]}...")
    if all_industry:
        impact_lines.append(f"\n🏭 **{target_sector}行业政策**（{len(all_industry)}条）")
        for item in all_industry[:5]:
            impact_lines.append(f"• {item['content'][:100]}")
    if company_news:
        impact_lines.append(f"\n🏢 **公司层面**（{len(company_news)}条）")
        impact_lines.extend(company_news)
    if not impact_lines and not risk_signals:
        impact_lines.append("当前未发现明显政策信号")

    return {
        "code": code, "name": stock_info.get("name", ""), "sector": target_sector,
        "stock_info": stock_info,
        "policy_signals": {"macro_count": len(all_macro), "industry_count": len(all_industry),
                           "company_count": len(company_news)},
        "risk_signals": risk_signals,
        "impact_assessment": impact_lines,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
    }


if __name__ == "__main__":
    import sys
    test = sys.argv[1] if len(sys.argv) > 1 else "hot"
    code = sys.argv[2] if len(sys.argv) > 2 else "600519"
    if test == "hot":
        print(json.dumps(analyze_hot_money(code), ensure_ascii=False)[:800])
    else:
        print(json.dumps(analyze_policy(code, ""), ensure_ascii=False)[:800])
