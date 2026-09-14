#!/usr/bin/env python3
"""宏观经济数据系列

数据源：东财 datacenter-web（已实测可用）
- PMI: RPT_ECONOMY_PMI（制造业+非制造业）
- CPI: RPT_ECONOMY_CPI（同比/环比/累计）
- M2:  RPT_ECONOMY_CURRENCY_SUPPLY（货币供应量）

注意：社融/RPT 报表名未确认，暂不纳入。
"""
from __future__ import annotations

import json
import urllib.request
import urllib.parse
from datetime import datetime
from typing import Any

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
DATACENTER_API = "https://datacenter-web.eastmoney.com/api/data/v1/get"


def _datacenter(report_name: str, columns: str, page_size: int = 12,
                sort_columns: str = "REPORT_DATE", sort_types: str = "-1") -> list[dict]:
    """调用东财 datacenter API"""
    params = {
        "reportName": report_name,
        "columns": columns,
        "pageSize": str(page_size),
        "sortColumns": sort_columns,
        "sortTypes": sort_types,
        "source": "WEB",
        "client": "WEB",
    }
    url = f"{DATACENTER_API}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Referer": "https://data.eastmoney.com/",
        "Accept": "application/json, text/plain, */*",
    })
    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        result = data.get("result")
        if result and result.get("data"):
            return result["data"]
    except Exception as e:
        return [{"error": str(e)}]
    return []


def get_pmi(months: int = 12) -> dict[str, Any]:
    """获取制造业PMI + 非制造业PMI

    Returns: {indicators: [{date, manufacturing, non_manufacturing, ...}], latest, trend}
    """
    rows = _datacenter(
        "RPT_ECONOMY_PMI",
        "REPORT_DATE,MAKE_INDEX,NMAKE_INDEX",
        page_size=months,
    )
    if not rows or "error" in rows[0]:
        return {"error": rows[0].get("error", "PMI数据获取失败") if rows else "无数据"}

    indicators = []
    for r in rows:
        date_str = r.get("REPORT_DATE", "")[:10]
        indicators.append({
            "date": date_str,
            "manufacturing": r.get("MAKE_INDEX"),
            "non_manufacturing": r.get("NMAKE_INDEX"),
        })

    latest = indicators[0] if indicators else {}
    # 趋势判断
    if len(indicators) >= 3:
        recent = [i["manufacturing"] for i in indicators[:3] if i.get("manufacturing") is not None]
        if len(recent) >= 2:
            trend = "上升" if recent[0] > recent[-1] else "下降" if recent[0] < recent[-1] else "持平"
        else:
            trend = "数据不足"
    else:
        trend = "数据不足"

    return {
        "indicator": "PMI",
        "indicators": indicators,
        "latest": latest,
        "trend": trend,
        "source": "eastmoney_datacenter",
    }


def get_cpi(months: int = 12) -> dict[str, Any]:
    """获取CPI（全国同比/环比/累计）

    Returns: {indicators: [{date, yoy, mom, cumulative}], latest, trend}
    """
    rows = _datacenter(
        "RPT_ECONOMY_CPI",
        "REPORT_DATE,NATIONAL_SAME,NATIONAL_SEQUENTIAL,NATIONAL_ACCUMULATE",
        page_size=months,
    )
    if not rows or "error" in rows[0]:
        return {"error": rows[0].get("error", "CPI数据获取失败") if rows else "无数据"}

    indicators = []
    for r in rows:
        date_str = r.get("REPORT_DATE", "")[:10]
        indicators.append({
            "date": date_str,
            "yoy": r.get("NATIONAL_SAME"),           # 同比 %
            "mom": r.get("NATIONAL_SEQUENTIAL"),      # 环比 %
            "cumulative": r.get("NATIONAL_ACCUMULATE"),  # 累计 %
        })

    latest = indicators[0] if indicators else {}
    if len(indicators) >= 2:
        yoy = latest.get("yoy")
        prev_yoy = indicators[1].get("yoy")
        if yoy is not None and prev_yoy is not None:
            trend = "通胀上升" if yoy > prev_yoy else "通胀回落" if yoy < prev_yoy else "持平"
        else:
            trend = "数据不足"
    else:
        trend = "数据不足"

    return {
        "indicator": "CPI",
        "indicators": indicators,
        "latest": latest,
        "trend": trend,
        "source": "eastmoney_datacenter",
    }


def get_m2(months: int = 12) -> dict[str, Any]:
    """获取M2货币供应量（同比/环比）

    Returns: {indicators: [{date, m2, m2_yoy, m1, m1_yoy}], latest, trend}
    """
    rows = _datacenter(
        "RPT_ECONOMY_CURRENCY_SUPPLY",
        "REPORT_DATE,TIME,BASIC_CURRENCY,BASIC_CURRENCY_SAME,BASIC_CURRENCY_SEQUENTIAL,CURRENCY,CURRENCY_SAME,CURRENCY_SEQUENTIAL",
        page_size=months,
    )
    if not rows or "error" in rows[0]:
        return {"error": rows[0].get("error", "M2数据获取失败") if rows else "无数据"}

    indicators = []
    for r in rows:
        date_str = r.get("REPORT_DATE", "")[:10]
        indicators.append({
            "date": date_str,
            "period": r.get("TIME", ""),
            "m2": r.get("BASIC_CURRENCY"),               # 亿元
            "m2_yoy": r.get("BASIC_CURRENCY_SAME"),      # 同比 %
            "m2_mom": r.get("BASIC_CURRENCY_SEQUENTIAL"), # 环比 %
            "m1": r.get("CURRENCY"),
            "m1_yoy": r.get("CURRENCY_SAME"),
            "m1_mom": r.get("CURRENCY_SEQUENTIAL"),
        })

    latest = indicators[0] if indicators else {}
    # M2-M1 剪刀差
    if latest.get("m2_yoy") is not None and latest.get("m1_yoy") is not None:
        scissors = round(latest["m2_yoy"] - latest["m1_yoy"], 2)
        latest["m2_m1_scissors"] = scissors
        latest["scissors_interpretation"] = (
            "资金活化（M1增速快）" if scissors < 0
            else "资金淤积（M2增速快）" if scissors > 2
            else "均衡"
        )

    return {
        "indicator": "M2",
        "indicators": indicators,
        "latest": latest,
        "source": "eastmoney_datacenter",
    }


def get_macro_summary() -> dict[str, Any]:
    """一次性获取宏观数据全景（PMI + CPI + M2）"""
    pmi = get_pmi(6)
    cpi = get_cpi(6)
    m2 = get_m2(6)

    # 综合判断
    signals = []
    pmi_latest = pmi.get("latest", {})
    cpi_latest = cpi.get("latest", {})
    m2_latest = m2.get("latest", {})

    mfg = pmi_latest.get("manufacturing")
    if mfg is not None:
        if mfg >= 50:
            signals.append(f"制造业PMI={mfg}，扩张区间")
        else:
            signals.append(f"制造业PMI={mfg}，收缩区间")

    yoy = cpi_latest.get("yoy")
    if yoy is not None:
        if yoy > 3:
            signals.append(f"CPI同比={yoy}%，通胀偏高")
        elif yoy < 0:
            signals.append(f"CPI同比={yoy}%，通缩风险")
        else:
            signals.append(f"CPI同比={yoy}%，温和")

    m2y = m2_latest.get("m2_yoy")
    if m2y is not None:
        signals.append(f"M2同比={m2y}%")

    scissors = m2_latest.get("m2_m1_scissors")
    if scissors is not None:
        signals.append(f"M2-M1剪刀差={scissors}")

    return {
        "pmi": pmi,
        "cpi": cpi,
        "m2": m2,
        "signals": signals,
        "time": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "source": "eastmoney_datacenter",
    }
