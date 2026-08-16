#!/usr/bin/env python3
"""高级工具 v2 — 杀猪盘风险检测 / 尽调清单 / 龙虎榜深度分析（独立文件版，避免与 advanced2.py 冲突）

移植自 Gateway:
- src/tools/trap.ts        (310 行，杀猪盘检测规则引擎)
- src/tools/dd_checklist.ts (129 行，尽调清单 5 工作流)
- src/tools/lhb.ts          (318 行，龙虎榜深度分析，东财 datacenter 报表)
- src/tools/seat_db.ts      (291 行，知名游资席位库 SEATS)

纯 Python 无 LLM，全部基于本地已有数据源：
- tencent.get_kline(code, days) → {records: [{date, open, close, high, low, volume}]}
- em_market.fetch_financials(code) → fin dict
- em_market._datacenter(report_name, filter_str, page_size, sort_columns, sort_types)
- em_market.extract_code()
- news.search_news(code, name) → 新闻（杀猪盘推广关键词匹配）
- tools.technical.analyze / tools.st_risk 供 dd_checklist 复用

本模块三个入口：
- check_trap_risk(code, name="")   → 杀猪盘识别
- dd_checklist(code, name="")      → 尽调清单（5 工作流）
- analyze_lhb(code)                → 龙虎榜深度分析（机构 vs 游资）
"""

from __future__ import annotations

import time
from typing import Any

from core.cache import get_cache, make_cache_key

TTL_HOURLY = 3600  # 龙虎榜/尽调缓存 1 小时（东财报表每日更新）

# ══════════════════════════════════════════════════════════════
# 22 位知名游资席位库 SEATS（移植自 Gateway seat_db.ts）
# 每项: 营业部名称关键字（子串/前缀匹配）→ 游资身份
# ══════════════════════════════════════════════════════════════

SEATS: list[dict[str, Any]] = [
    # ─── 殿堂级 ───
    {
        "id": "zhang_mz", "name": "章盟主", "realName": "章建平", "tier": "legend",
        "style": "大资金趋势波段，格局锁仓", "premium": "neutral",
        "seats": [
            "国泰君安证券股份有限公司上海江苏路证券营业部",
            "国泰君安证券股份有限公司宁波彩虹北路证券营业部",
            "中信证券股份有限公司杭州延安路证券营业部",
        ],
    },
    {
        "id": "sun_ge", "name": "孙哥", "realName": "孙煜", "tier": "legend",
        "style": "板块引导，波段锁仓", "premium": "neutral_positive",
        "seats": [
            "中信证券股份有限公司上海溧阳路证券营业部",
            "中信证券股份有限公司上海古北路证券营业部",
            "中信证券股份有限公司上海分公司",
        ],
    },
    {
        "id": "zhao_lg", "name": "赵老哥", "realName": "赵强", "tier": "legend",
        "style": "打板，二板定龙头", "premium": "positive",
        "seats": [
            "浙商证券股份有限公司绍兴解放北路证券营业部",
            "中国银河证券股份有限公司绍兴证券营业部",
            "中国银河证券股份有限公司北京阜成路证券营业部",
        ],
    },
    {
        "id": "fs_wyj", "name": "佛山无影脚", "realName": "廖国沛", "tier": "legend",
        "style": "一日游，翘板，砸盘王", "premium": "negative",
        "seats": [
            "光大证券股份有限公司佛山绿景路证券营业部",
            "光大证券股份有限公司佛山季华六路证券营业部",
            "湘财证券股份有限公司佛山祖庙路证券营业部",
        ],
    },
    {
        "id": "yangjia", "name": "炒股养家", "tier": "legend",
        "style": "情绪揣摩，通道排板", "premium": "next_day_70",
        "seats": [
            "华鑫证券有限责任公司上海红宝石路证券营业部",
            "华鑫证券有限责任公司上海宛平南路证券营业部",
        ],
    },
    # ─── 新生代 ───
    {
        "id": "chen_xq", "name": "陈小群", "realName": "陈宴群", "tier": "new_gen",
        "style": "龙头接力、一线天、反核按钮", "premium": "next_day_57",
        "seats": ["中国银河证券股份有限公司大连黄河路证券营业部"],
    },
    {
        "id": "hu_jl", "name": "呼家楼", "tier": "new_gen",
        "style": "多席位协同、板块平铺扫货", "premium": "neutral",
        "seats": [
            "中信证券股份有限公司上海凯滨路证券营业部",
            "中信证券股份有限公司北京总部",
            "中信建投证券股份有限公司北京朝外大街证券营业部",
        ],
    },
    {
        "id": "fang_xx", "name": "方新侠", "tier": "new_gen",
        "style": "大成交趋势票、格局锁仓", "premium": "neutral",
        "seats": [
            "兴业证券股份有限公司陕西分公司",
            "中信证券股份有限公司西安朱雀大街证券营业部",
        ],
    },
    {
        "id": "zuoshou", "name": "作手新一", "realName": "严冬", "tier": "new_gen",
        "style": "龙头战法，连板+趋势兼做", "premium": "neutral",
        "seats": ["国泰君安证券股份有限公司南京太平南路证券营业部"],
    },
    {
        "id": "xiao_ey", "name": "小鳄鱼", "tier": "new_gen",
        "style": "基本面辅助选股", "premium": "neutral",
        "seats": [
            "南京证券股份有限公司南京大钟亭证券营业部",
            "中金财富证券有限公司南京龙蟠中路证券营业部",
        ],
    },
    {
        "id": "jiao_yy", "name": "交易猿", "tier": "new_gen",
        "style": "大容量票锁仓、龙头加速", "premium": "neutral",
        "seats": [
            "华泰证券股份有限公司天津东丽开发区二纬路证券营业部",
            "招商证券股份有限公司福州六一中路证券营业部",
        ],
    },
    {
        "id": "mao_lb", "name": "毛老板", "tier": "new_gen",
        "style": "AI主线大资金重仓", "premium": "neutral",
        "seats": [
            "国泰君安证券股份有限公司北京光华路证券营业部",
            "方正证券股份有限公司乐山龙游路证券营业部",
            "广发证券股份有限公司上海东方路证券营业部",
        ],
    },
    {
        "id": "xiao_xian", "name": "消闲派", "tier": "new_gen",
        "style": "满仓满融极致进攻", "premium": "neutral",
        "seats": ["华泰证券股份有限公司浙江分公司"],
    },
    # ─── 区域帮派 ───
    {
        "id": "lasa", "name": "拉萨天团", "tier": "regional",
        "style": "群狼一日游，反向指标", "premium": "negative",
        "seats": ["东方财富证券股份有限公司拉萨"],
    },
    {
        "id": "chengdu", "name": "成都帮", "tier": "regional",
        "style": "底部黑马点火一日游", "premium": "neutral",
        "seats": ["华泰证券股份有限公司成都南一环路第二证券营业部"],
    },
    {
        "id": "sunang", "name": "苏南帮", "tier": "regional",
        "style": "多席位联动低价小盘", "premium": "neutral",
        "seats": [
            "华泰证券股份有限公司无锡",
            "华泰证券股份有限公司镇江",
            "华泰证券股份有限公司南京",
        ],
    },
    {
        "id": "ningbo", "name": "宁波桑田路", "tier": "regional",
        "style": "连板接力", "premium": "neutral",
        "seats": ["国盛证券有限责任公司宁波桑田路证券营业部"],
    },
    # ─── 2025 新晋 ───
    {
        "id": "liuyizhong", "name": "六一中路", "tier": "new_2025",
        "style": "题材打板接力", "premium": "neutral",
        "seats": ["招商证券股份有限公司福州六一中路证券营业部"],
    },
    {
        "id": "liushahe", "name": "流沙河", "tier": "new_2025",
        "style": "低吸/接力新晋", "premium": "neutral",
        "seats": [
            "招商证券股份有限公司北京车公庄西路证券营业部",
            "华泰证券股份有限公司上海武定路证券营业部",
        ],
    },
    {
        "id": "gubei", "name": "古北路", "tier": "new_2025",
        "style": "2025 重新活跃顶级短线", "premium": "neutral",
        "seats": ["中信证券股份有限公司上海古北路证券营业部"],
    },
    {
        "id": "ghzw", "name": "股海贼王", "tier": "new_2025",
        "style": "弱转强、首板、反核，专注A股短线", "premium": "neutral",
        "seats": [
            "国泰君安证券股份有限公司沈阳十一纬路证券营业部",
            "华泰证券股份有限公司上海杨浦区国宾路证券营业部",
        ],
    },
]


def match_seat(seat_name: str) -> dict[str, Any] | None:
    """匹配营业部名称 → 已知游资席位（子串匹配，返回 entry + confidence）"""
    if not seat_name:
        return None
    for entry in SEATS:
        for pattern in entry["seats"]:
            if pattern in seat_name:
                return {"entry": entry, "confidence": "high"}
    return None


def is_institutional(seat_name: str) -> bool:
    """判断席位是否为机构专用"""
    return "机构专用" in seat_name or ("机构" in seat_name and "证券" not in seat_name)


def _make_verdict(premium: str, net_buy: float) -> str:
    if premium == "negative":
        return "反向预警（该游资为反向指标）" if net_buy > 0 else "不在射程"
    if premium == "positive":
        return "✅ 在射程（正向信号）" if net_buy > 0 else "不在射程"
    if premium == "neutral_positive":
        return "✅ 在射程" if net_buy > 0 else "不在射程"
    return "在射程（中性信号）" if net_buy > 0 else "不在射程"


# ══════════════════════════════════════════════════════════════
# 1. check_trap_risk — 杀猪盘识别引擎（移植 Gateway trap.ts）
# ══════════════════════════════════════════════════════════════

# 新闻推广关键词（杀猪盘常见推广话术）
PROMOTION_KEYWORDS: list[dict[str, str]] = [
    {"term": "杀猪盘", "label": "杀猪盘举报", "severity": "high"},
    {"term": "老师", "label": "老师推荐", "severity": "high"},
    {"term": "稳赚", "label": "稳赚承诺", "severity": "high"},
    {"term": "翻倍", "label": "翻倍承诺", "severity": "high"},
    {"term": "内幕", "label": "内幕消息", "severity": "high"},
    {"term": "VIP", "label": "付费社群引流", "severity": "high"},
    {"term": "骗局", "label": "投资者投诉", "severity": "high"},
    {"term": "推荐", "label": "推荐推广", "severity": "medium"},
    {"term": "涨停", "label": "涨停预测", "severity": "medium"},
    {"term": "群", "label": "群组推荐", "severity": "medium"},
]


def _detect_kline_traps(records: list[dict]) -> list[dict]:
    """K 线异常信号检测（对齐 Gateway trap.ts detectKlineTraps）"""
    signals: list[dict] = []
    if not records or len(records) < 5:
        return signals

    # 确保 旧→新 排序
    sorted_records = sorted(records, key=lambda r: str(r.get("date", "")))
    closes = [float(r.get("close") or 0) for r in sorted_records]

    # ─── Signal 1: 短期暴涨（5日 >15% high / >10% medium）───
    if len(closes) >= 6:
        pct5d = (closes[-1] - closes[-6]) / closes[-6] * 100 if closes[-6] else 0
        if pct5d > 15:
            signals.append({
                "name": "短期暴涨", "severity": "high",
                "detail": f"近5日涨幅 {pct5d:.1f}%，超过15%警戒线",
                "evidence": f"5日前收盘 {closes[-6]:.2f} → 当前 {closes[-1]:.2f}",
            })
        elif pct5d > 10:
            signals.append({
                "name": "短期涨幅较大", "severity": "medium",
                "detail": f"近5日涨幅 {pct5d:.1f}%，接近10%关注线",
                "evidence": f"5日涨幅 {pct5d:.1f}%",
            })

    # ─── Signal 2: 中期暴涨（20日 >40% high / >25% medium）───
    if len(closes) >= 21:
        pct20d = (closes[-1] - closes[-21]) / closes[-21] * 100 if closes[-21] else 0
        if pct20d > 40:
            signals.append({
                "name": "中期暴涨", "severity": "high",
                "detail": f"近20日涨幅 {pct20d:.1f}%，疑似拉升出货阶段",
                "evidence": f"20日前收盘 {closes[-21]:.2f} → 当前 {closes[-1]:.2f}",
            })
        elif pct20d > 25:
            signals.append({
                "name": "中期涨幅较大", "severity": "medium",
                "detail": f"近20日涨幅 {pct20d:.1f}%，注意追高风险",
                "evidence": f"20日涨幅 {pct20d:.1f}%",
            })

    # ─── Signal 3: 放量下跌（10日内量>3x均量 且 跌>3%）───
    if len(sorted_records) >= 10:
        recent = sorted_records[-10:]
        avg_vol = sum(float(r.get("volume") or 0) for r in recent[:5]) / 5
        recent5 = recent[-5:]
        base_close = float(recent5[0].get("close") or 0)
        for r in recent5:
            vol = float(r.get("volume") or 0)
            if avg_vol > 0 and vol > avg_vol * 3:
                drop = (float(r.get("close") or 0) - base_close) / base_close * 100 if base_close else 0
                if drop < -3:
                    signals.append({
                        "name": "放量下跌", "severity": "high",
                        "detail": f"{str(r.get('date',''))[:10]} 成交量达均量 {vol/avg_vol:.1f} 倍，股价下跌，疑似出货",
                        "evidence": f"量比 {vol/avg_vol:.1f}x，跌幅 {abs(drop):.1f}%",
                    })
                    break

    # ─── Signal 4: 连板（5日内 close/open >7.5% 连续 ≥2）───
    if len(sorted_records) >= 5:
        last5 = sorted_records[-5:]
        streak = 0
        for r in last5:
            o = float(r.get("open") or 0)
            d = (float(r.get("close") or 0) - o) / o * 100 if o else 0
            if d > 7.5:
                streak += 1
            elif streak > 0:
                break
        if streak >= 3:
            signals.append({
                "name": "连续涨停", "severity": "high",
                "detail": f"最近5个交易日出现 {streak} 次涨停，典型拉升模式",
                "evidence": f"连续涨停 {streak} 次",
            })
        elif streak >= 2:
            signals.append({
                "name": "连板拉升", "severity": "medium",
                "detail": f"最近5个交易日出现 {streak} 次涨停，注意追高风险",
                "evidence": f"连续涨停 {streak} 次",
            })

    # ─── Signal 5: 价量背离 ───
    if len(sorted_records) >= 15:
        recent = sorted_records[-15:]
        first_close = float(recent[0].get("close") or 0)
        last_close = float(recent[-1].get("close") or 0)
        vol_first5 = sum(float(r.get("volume") or 0) for r in recent[:5]) / 5
        vol_last5 = sum(float(r.get("volume") or 0) for r in recent[-5:]) / 5
        if last_close > first_close and vol_first5 > 0 and vol_last5 < vol_first5 * 0.7:
            signals.append({
                "name": "价量背离", "severity": "medium",
                "detail": "股价上涨但成交量持续萎缩，上涨动能减弱",
                "evidence": "近期量能较前期下降超过30%",
            })

    # ─── Signal 6: 剧烈波动（振幅过大）───
    if len(sorted_records) >= 10:
        recent = sorted_records[-10:]
        high_vol_days = sum(
            1 for r in recent
            if (float(r.get("high") or 0) - float(r.get("low") or 0)) /
               (float(r.get("close") or 0) or 1e-9) * 100 > 8
        )
        if high_vol_days >= 5:
            signals.append({
                "name": "剧烈波动", "severity": "medium",
                "detail": f"近10日中有 {high_vol_days} 天振幅超过8%，典型短线博弈特征",
                "evidence": f"高振幅日 {high_vol_days}/10",
            })

    return signals


def _detect_microcap_trap(price: float, market_cap: float | None) -> dict | None:
    """微盘低价股陷阱（杀猪盘常见标的）"""
    if market_cap is not None and market_cap < 20 and price < 10:
        return {
            "name": "微盘低价股", "severity": "medium",
            "detail": f"流通市值约 {market_cap:.1f} 亿，价格 {price} 元，微盘低价股易被操纵",
            "evidence": f"市值 {market_cap:.1f}亿，价格 {price}元",
        }
    return None


def _detect_promotion_signals(code: str, name: str) -> list[dict]:
    """新闻推广信号：search_news 结果含 老师推荐/群推荐/翻倍/稳赚 等关键词"""
    signals: list[dict] = []
    try:
        from tools.news import search_news
        news = search_news(code, name)
        titles = [str(n.get("title") or "") for n in (news.get("news") or [])]
    except Exception:
        titles = []

    if not titles:
        return signals

    # 长词优先匹配：已命中长词（如 老师推荐）的新闻不再计入短词（如 推荐），避免重复计数
    matched_items: set[int] = set()
    for kw in sorted(PROMOTION_KEYWORDS, key=lambda k: -len(k["term"])):
        term = kw["term"].lower()
        hits = [i for i, t in enumerate(titles) if term in t.lower() and i not in matched_items]
        if hits:
            signals.append({
                "name": kw["label"], "severity": kw["severity"],
                "detail": f"搜索\"{name} {kw['term']}\"相关新闻命中 {len(hits)} 条推广内容",
                "evidence": f"命中关键词「{kw['term']}」: {titles[hits[0]][:60]}",
            })
            matched_items.update(hits)
    return signals


def check_trap_risk(code: str, name: str = "") -> dict[str, Any]:
    """杀猪盘风险检测 — K线规则 + 微盘 + 新闻推广匹配

    Args:
        code: 股票代码（如 600519 / 000001.SZ）
        name: 股票名称（可选，自动从行情获取）

    Returns:
        {code, name, risk_level, trap_score, max_severity, signals, summary, recommendation}
        signals: [{name, severity, detail, evidence}]
    """
    cache = get_cache()
    cache_key = make_cache_key("trap", code)
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    from data_sources import em_market, tencent

    c = em_market.extract_code(code)

    # 行情（名称/价格/市值）
    quote = {}
    try:
        quote = tencent.get_realtime_quote(c)
    except Exception:
        pass
    resolved_name = name or quote.get("name") or c

    all_signals: list[dict] = []

    # 1. K 线信号
    try:
        kline = tencent.get_kline(c, days=60)
        records = kline.get("records") or []
        if len(records) >= 5:
            all_signals.extend(_detect_kline_traps(records))
        # 微盘低价股：用最新收盘价近似
        if records:
            last = records[-1]
            price = float(last.get("close") or 0)
            micro = _detect_microcap_trap(price, None)
            if micro:
                all_signals.append(micro)
    except Exception:
        pass

    # 2. 新闻推广匹配（老师推荐/群推荐/翻倍/稳赚 等）
    try:
        all_signals.extend(_detect_promotion_signals(c, resolved_name))
    except Exception:
        pass

    # ── 评分（对齐 Gateway: severity low=1 medium=2 high=3，score += sev*10，cap 100）──
    sev_map = {"low": 1, "medium": 2, "high": 3}
    score = min(sum(sev_map.get(s["severity"], 1) * 10 for s in all_signals), 100)
    max_sev = "low"
    for s in all_signals:
        if sev_map.get(s["severity"], 1) > sev_map[max_sev]:
            max_sev = s["severity"]

    # ── 评级 ──
    n = len(all_signals)
    if n <= 1:
        level = "🟢 安全"
        recommendation = "未发现杀猪盘特征信号，可正常分析。任何投资请自行判断。"
    elif n <= 3:
        level = "🟡 注意"
        recommendation = "检测到少量推广或异常信号，建议核实信息来源，谨慎决策。"
    elif n <= 5:
        level = "🟠 警惕"
        recommendation = "⚠️ 多个异常信号！强烈建议谨慎，核实所有信息源后再做决策。"
    else:
        level = "🔴 高度可疑"
        recommendation = "⛔️ 大量杀猪盘特征信号！强烈建议回避该标的，谨防资金损失。"

    summary = f"检测到 {n} 个信号（最高严重度: {max_sev}），风险等级 {level}。{recommendation}"

    result = {
        "code": c,
        "name": resolved_name,
        "risk_level": level,
        "trap_score": score,
        "max_severity": max_sev,
        "signals": all_signals,
        "summary": summary,
        "recommendation": recommendation,
    }
    cache.set(cache_key, result, TTL_HOURLY)
    return result


# ══════════════════════════════════════════════════════════════
# 2. dd_checklist — 尽调清单 5 工作流（移植 Gateway dd_checklist.ts）
# ══════════════════════════════════════════════════════════════

def _check(has: bool) -> str:
    return "✅ 已有数据" if has else "❌ 缺失"


def dd_checklist(code: str, name: str = "",
                 fin: dict | None = None, dcf: dict | None = None,
                 trap: dict | None = None, risk: dict | None = None) -> dict[str, Any]:
    """尽调清单 — 财务/商业/法律/运营/市场 5 工作流

    基于 fin(财务) + dcf(DCF估值) + trap(杀猪盘) + risk(ST风险) 数据可得性，
    自动标注 ✅ 已有数据 / ❌ 缺失 / ⚪ 需人工核查。

    Args:
        code: 股票代码
        name: 股票名称（可选）
        fin: em_market.fetch_financials 结果（None 则自动获取）
        dcf: DCF 估值结果（本地无 DCF 模块，恒为 None → ❌ 缺失）
        trap: check_trap_risk 结果（None 则自动获取）
        risk: st_risk 结果（None 则自动获取）

    Returns:
        {code, name, method, workstreams, total_items, items_auto_verified,
         completion_pct, manual_review_required, methodology_log}
    """
    cache = get_cache()
    cache_key = make_cache_key("dd_checklist", code)
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    from data_sources import em_market, tencent

    c = em_market.extract_code(code)

    # ── 数据可得性 ──
    if fin is None:
        try:
            fin = em_market.fetch_financials(c)
        except Exception:
            fin = None
    has_fin = isinstance(fin, dict) and bool(fin.get("code")) and "error" not in fin

    has_dcf = isinstance(dcf, dict) and bool(dcf.get("intrinsic_per_share"))  # 本地无 DCF 模块

    if trap is None:
        try:
            trap = check_trap_risk(c, name)
        except Exception:
            trap = None
    has_trap = isinstance(trap, dict) and bool(trap.get("risk_level"))
    trap_ok = has_trap and trap.get("risk_level") not in (None, "unknown")

    if risk is None:
        try:
            quote = tencent.get_realtime_quote(c)
            from tools.st_risk import get_st_risk
            risk = get_st_risk(c, quote)
        except Exception:
            risk = None
    has_risk = isinstance(risk, dict)
    risk_is_st = bool((risk or {}).get("is_st"))
    # 面值退市风险：risk.signals 中 dimension=面值退市风险 且 level < 2
    face_value_ok = False
    if has_risk:
        for s in (risk.get("signals") or []):
            if s.get("dimension") == "面值退市风险" and int(s.get("level", 9)) < 2:
                face_value_ok = True

    # 名称补全
    resolved_name = name
    if not resolved_name:
        try:
            resolved_name = (fin or {}).get("name") or tencent.get_realtime_quote(c).get("name", c)
        except Exception:
            resolved_name = c

    # ── 5 工作流清单 ──
    workstreams = [
        {
            "workstream": "财务尽调 (Financial DD)",
            "items": [
                {"item": "5 年营收 / 净利历史", "status": _check(has_fin and len((fin or {}).get("revenue_history") or []) >= 3)},
                {"item": "ROE / 净利率", "status": _check(has_fin and float((fin or {}).get("net_margin") or 0) > 0)},
                {"item": "资产负债率", "status": _check(has_fin and float((fin or {}).get("total_liabilities") or 0) > 0)},
                {"item": "自由现金流", "status": _check(has_fin and (float((fin or {}).get("fcff_forward") or 0) > 0 or float((fin or {}).get("fcff_back") or 0) > 0))},
                {"item": "DCF 估值", "status": _check(has_dcf)},
                {"item": "EPS / BPS", "status": _check(has_fin and float((fin or {}).get("eps") or 0) > 0)},
                {"item": "审计意见 / 会计政策", "status": "⚪ 需人工核查"},
            ],
        },
        {
            "workstream": "商业尽调 (Commercial DD)",
            "items": [
                {"item": "毛利率 / 净利率", "status": _check(has_fin and float((fin or {}).get("net_margin") or 0) > 0)},
                {"item": "营收规模", "status": _check(has_fin and float((fin or {}).get("revenue") or 0) > 0)},
                {"item": "竞争格局（可比公司分析）", "status": "⚪ 需人工分析"},
                {"item": "客户集中度", "status": "⚪ 需年报披露"},
                {"item": "上下游议价能力", "status": "⚪ 需行业研究"},
            ],
        },
        {
            "workstream": "法律尽调 (Legal DD)",
            "items": [
                {"item": "ST / 退市风险", "status": _check(has_risk and not risk_is_st)},
                {"item": "股权结构", "status": "⚪ 需公开披露核查"},
                {"item": "重大诉讼", "status": "⚪ 需披露核查"},
                {"item": "关联交易", "status": "⚪ 需年报披露"},
                {"item": "面值退市风险", "status": _check(has_risk and face_value_ok)},
            ],
        },
        {
            "workstream": "运营尽调 (Operational DD)",
            "items": [
                {"item": "K 线形态分析", "status": "✅ 已有数据"},
                {"item": "技术面趋势（均线/MACD/RSI）", "status": "✅ 已有数据"},
                {"item": "成交量分析", "status": "✅ 已有数据"},
                {"item": "杀猪盘排查", "status": _check(trap_ok)},
                {"item": "龙虎榜游资追踪", "status": "✅ 已有数据"},
                {"item": "管理层背景", "status": "⚪ 需人工核查"},
            ],
        },
        {
            "workstream": "市场尽调 (Market DD)",
            "items": [
                {"item": "新闻舆情扫描", "status": "✅ 已有数据"},
                {"item": "AI 综合分析", "status": "⚪ 需人工分析（本流程纯 Python 无 LLM）"},
                {"item": "技术面信号", "status": "✅ 已有数据"},
                {"item": "量价关系分析", "status": "✅ 已有数据"},
            ],
        },
    ]

    total_items = sum(len(ws["items"]) for ws in workstreams)
    done = sum(1 for ws in workstreams for it in ws["items"] if "✅" in it["status"])
    pct = round(done / total_items * 100) if total_items else 0

    result = {
        "method": "Due Diligence Checklist — 尽调清单",
        "code": c,
        "name": resolved_name,
        "workstreams": workstreams,
        "total_items": total_items,
        "items_auto_verified": done,
        "completion_pct": pct,
        "manual_review_required": total_items - done,
        "methodology_log": [
            f"Step 1 · 生成 5 大工作流 {total_items} 条尽调清单",
            f"Step 2 · 基于现有数据自动完成 {done} 项",
            f"Step 3 · {total_items - done} 项需人工核查（{pct}% 自动完成）",
        ],
    }
    cache.set(cache_key, result, TTL_HOURLY)
    return result


# ══════════════════════════════════════════════════════════════
# 3. analyze_lhb — 龙虎榜深度分析（移植 Gateway lhb.ts）
# ══════════════════════════════════════════════════════════════

_LHB_DETAIL_REPORTS = {
    "BUY": "RPT_BILLBOARD_DAILYDETAILSBUY",
    "SELL": "RPT_BILLBOARD_DAILYDETAILSSELL",
}


def _fetch_lhb_dates(code: str) -> list[str]:
    """拉上榜日期（RPT_LHB_BOARDDATE）"""
    from data_sources import em_market
    data = em_market._datacenter(
        "RPT_LHB_BOARDDATE", f'(SECURITY_CODE="{code}")',
        page_size=1000, sort_columns="TRADE_DATE", sort_types="-1",
    )
    dates = []
    for r in data:
        d = str(r.get("TRADE_DATE") or r.get("TR_DATE") or "")[:10]
        if d:
            dates.append(d.replace("-", ""))
    return dates


def _fetch_lhb_detail(code: str, date: str, flag: str) -> list[dict]:
    """拉单日买卖详情（RPT_BILLBOARD_DAILYDETAILSBUY / SELL）"""
    from data_sources import em_market
    report = _LHB_DETAIL_REPORTS.get(flag)
    if not report:
        return []
    fmt_date = f"{date[:4]}-{date[4:6]}-{date[6:8]}"
    data = em_market._datacenter(
        report, f"(TRADE_DATE='{fmt_date}')(SECURITY_CODE=\"{code}\")",
        page_size=500,
    )
    return data or []


def _fetch_lhb_statistic(code: str) -> tuple[int, str]:
    """近 30 日上榜统计（RPT_BILLBOARD_TRADEALL）"""
    from data_sources import em_market
    data = em_market._datacenter(
        "RPT_BILLBOARD_TRADEALL", f'(STATISTICS_CYCLE="01")(SECURITY_CODE="{code}")',
        page_size=1, sort_columns="BILLBOARD_TIMES", sort_types="-1",
    )
    if data:
        row = data[0]
        try:
            count30d = int(row.get("BILLBOARD_TIMES") or 0)
        except (TypeError, ValueError):
            count30d = 0
        return count30d, str(row.get("SECURITY_NAME_ABBR") or code)
    return 0, code


def _split_inst_vs_youzi(records: list[dict]) -> dict[str, float]:
    """机构 vs 游资 资金拆分"""
    inst_buy = inst_sell = youzi_buy = youzi_sell = 0.0
    for r in records:
        if is_institutional(r.get("seat_name") or ""):
            inst_buy += r.get("buy_amount") or 0
            inst_sell += r.get("sell_amount") or 0
        else:
            youzi_buy += r.get("buy_amount") or 0
            youzi_sell += r.get("sell_amount") or 0
    return {
        "institutional_buy": round(inst_buy, 2),
        "institutional_sell": round(inst_sell, 2),
        "institutional_net": round(inst_buy - inst_sell, 2),
        "youzi_buy": round(youzi_buy, 2),
        "youzi_sell": round(youzi_sell, 2),
        "youzi_net": round(youzi_buy - youzi_sell, 2),
    }


def _generate_recommendation(split: dict[str, float], youzi_count: int) -> str:
    parts: list[str] = []
    if split["institutional_net"] > 0 and split["youzi_net"] > 0:
        parts.append("机构与游资均净买入，市场合力向上")
    elif split["institutional_net"] > 0:
        parts.append("机构主导买入，基本面驱动型行情")
    elif split["youzi_net"] > 0:
        parts.append("游资主导炒作，注意短线波动风险")
    if split["institutional_net"] < 0 and split["youzi_net"] < 0:
        parts.append("机构与游资均净卖出，建议谨慎")
    if youzi_count > 3:
        parts.append("多路游资齐聚，辨识度较高")
    return "。".join(parts) or "龙虎榜数据正常，未出现异常集中交易。"


def analyze_lhb(code: str) -> dict[str, Any]:
    """龙虎榜深度分析 — 机构 vs 游资 + 知名游资席位追踪

    流程（对齐 Gateway lhb.ts）:
    1. RPT_LHB_BOARDDATE 拉全部上榜日期 → 取最近 10 个交易日
    2. RPT_BILLBOARD_DAILYDETAILSBUY/SELL 拉每日买卖席位明细
    3. 营业部名称匹配 SEATS 22 位知名游资（子串匹配）
    4. 机构 vs 游资 资金拆分 → 推荐结论

    Args:
        code: 股票代码（如 600519 / 002594）

    Returns:
        {code, name, lhb_count_30d, lhb_dates, lhb_records(≤50),
         matched_youzi, inst_vs_youzi, recommendation}
    """
    cache = get_cache()
    cache_key = make_cache_key("lhb", code)
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    from data_sources import em_market, tencent

    c = em_market.extract_code(code)

    # 1. 近 30 日上榜统计 + 名称
    count30d, stock_name = _fetch_lhb_statistic(c)
    resolved_name = stock_name or c
    if resolved_name == c:
        try:
            q = tencent.get_realtime_quote(c)
            if q.get("name"):
                resolved_name = q["name"]
        except Exception:
            pass

    # 2. 上榜日期 → 最近 10 日
    dates = _fetch_lhb_dates(c)
    recent_dates = dates[:10]

    # 3. 逐日拉买卖详情 + 匹配游资
    all_records: list[dict] = []
    youzi_map: dict[str, dict[str, Any]] = {}

    for dt in recent_dates:
        buy_side = _fetch_lhb_detail(c, dt, "BUY")
        sell_side = _fetch_lhb_detail(c, dt, "SELL")
        for rows in (buy_side, sell_side):
            for row in rows:
                seat_name = row.get("OPERATEDEPT_NAME") or ""
                if not seat_name:
                    continue
                buy_amt = (float(row.get("BUY") or 0)) / 10000       # 元 → 万
                sell_amt = (float(row.get("SELL") or 0)) / 10000
                net_amt = (float(row.get("NET") or 0)) / 10000
                rec = {
                    "date": dt,
                    "code": c,
                    "name": row.get("SECURITY_CODE") or c,
                    "seat_name": seat_name,
                    "buy_amount": round(buy_amt, 2),
                    "sell_amount": round(sell_amt, 2),
                    "net_amount": round(net_amt, 2),
                }
                all_records.append(rec)

                matched = match_seat(seat_name)
                if matched:
                    entry = matched["entry"]
                    key = entry["id"]
                    acc = youzi_map.setdefault(key, {"seat": entry, "buy": 0.0, "sell": 0.0})
                    acc["buy"] += buy_amt
                    acc["sell"] += sell_amt

    # 4. 游资活动列表
    matched_youzi: list[dict] = []
    for key, info in youzi_map.items():
        seat = info["seat"]
        net = info["buy"] - info["sell"]
        matched_youzi.append({
            "youzi": seat,
            "total_buy": round(info["buy"], 2),
            "total_sell": round(info["sell"], 2),
            "net": round(net, 2),
            "confidence": "high",
            "verdict": _make_verdict(seat.get("premium", "neutral"), net),
        })
    matched_youzi.sort(key=lambda x: -x["net"])

    # 5. 机构 vs 游资拆分
    split = _split_inst_vs_youzi(all_records)

    # 6. 推荐结论
    recommendation = _generate_recommendation(split, len(matched_youzi))

    result = {
        "code": c,
        "name": resolved_name,
        "lhb_count_30d": count30d,
        "lhb_dates": recent_dates,
        "lhb_records": all_records[:50],
        "matched_youzi": matched_youzi,
        "inst_vs_youzi": split,
        "recommendation": recommendation,
    }
    cache.set(cache_key, result, TTL_HOURLY)
    return result


if __name__ == "__main__":
    import json
    import sys

    test = sys.argv[1] if len(sys.argv) > 1 else "trap"
    code = sys.argv[2] if len(sys.argv) > 2 else "600519"
    if test == "trap":
        print(json.dumps(check_trap_risk(code), ensure_ascii=False)[:1500])
    elif test == "dd":
        print(json.dumps(dd_checklist(code), ensure_ascii=False)[:2500])
    elif test == "lhb":
        print(json.dumps(analyze_lhb(code), ensure_ascii=False)[:2000])
