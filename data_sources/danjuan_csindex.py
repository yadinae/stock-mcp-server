#!/usr/bin/env python3
"""蛋卷基金 + 中证指数数据源（移植自 Gateway danjuan_fund.ts / csindex.ts）

本地实测: danjuanapp.com/djapi/* ✅ 200 | www.csindex.com.cn/csindex-home/* ✅ 200
"""
import json
import urllib.request
import urllib.parse
import re

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"


def _get(url: str, referer: str = "https://danjuanapp.com/", timeout: float = 15.0):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA, "Accept": "application/json, text/plain, */*", "Referer": referer,
    })
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", "replace")


def norm_code(code: str) -> str:
    return re.sub(r"\D", "", code or "")


# ═══════════════════ 基金（蛋卷）═══════════════════

def fund_info(code: str) -> dict:
    c = norm_code(code)
    if not re.fullmatch(r"\d{6}", c):
        return {"error": f"基金代码格式错误: {code}（应为6位数字）"}
    try:
        d = json.loads(_get(f"https://danjuanapp.com/djapi/fund/{c}"))
        info = d.get("data") or {}
        return {
            "code": c,
            "name": info.get("fd_name") or "",
            "full_name": info.get("fd_full_name") or "",
            "fund_type": info.get("fd_type") or "",
            "found_date": info.get("found_date") or "",
            "status": info.get("fd_status") or "",
            "total_share": info.get("totshare") or "",
            "keeper": info.get("keeper_name") or "",
            "manager": info.get("manager_name") or "",
            "trustee": info.get("trup_name") or "",
            "risk_level": info.get("risk_level") or "",
            "source": "danjuanapp.com",
        }
    except Exception as e:
        return {"code": c, "error": f"蛋卷基金接口异常: {e}"}


def fund_detail(code: str) -> dict:
    c = norm_code(code)
    if not re.fullmatch(r"\d{6}", c):
        return {"error": f"基金代码格式错误: {code}（应为6位数字）"}
    try:
        d = json.loads(_get(f"https://danjuanapp.com/djapi/fund/detail/{c}"))
        data = d.get("data") or {}
        pos = data.get("fund_position") or {}
        stocks = pos.get("stock_list") or []
        # manager_list 可能是 list 或 dict，做兼容
        ml = data.get("manager_list") or data.get("fund_manager") or []
        if isinstance(ml, dict):
            ml = ml.get("list") or ml.get("managers") or []
        managers = [{
            "name": m.get("name") or m.get("manager_name") or "",
            "work_years": m.get("work_years") or m.get("work_year") or "",
            "tenure": m.get("tenure") or m.get("manage_date") or "",
            "tenure_return": m.get("tenure_return") or m.get("return") or "",
        } for m in ml if isinstance(m, dict)]
        return {
            "code": c,
            # fund_company 可能是 dict（company_desc）或 str（公司名），做兼容
            "company_desc": (data.get("fund_company").get("company_desc") if isinstance(data.get("fund_company"), dict) else (data.get("fund_company") or "")),
            "top10_stocks": [{
                "name": s.get("name") or s.get("stock_name") or "",
                "code": s.get("code") or s.get("stock_code") or "",
                "ratio": s.get("percent") or s.get("stock_ratio") or 0,
            } for s in stocks[:10]],
            "stock_percent": pos.get("stock_percent") or 0,
            "bond_percent": pos.get("bond_percent") or 0,
            "cash_percent": pos.get("cash_percent") or 0,
            "managers": managers,
            "source": "danjuanapp.com",
        }
    except Exception as e:
        return {"code": c, "error": f"蛋卷基金接口异常: {e}"}


def fund_nav_history(code: str, page: int = 1, size: int = 30) -> dict:
    c = norm_code(code)
    if not re.fullmatch(r"\d{6}", c):
        return {"error": f"基金代码格式错误: {code}（应为6位数字）"}
    try:
        url = f"https://danjuanapp.com/djapi/fund/nav/history/{c}?page={page}&size={size}"
        d = json.loads(_get(url))
        items = (d.get("data") or {}).get("items") or []
        navs = [{
            "date": it.get("date") or "",
            "nav": it.get("nav") or "",
            "percent": it.get("percent") or "",
        } for it in items]
        return {"code": c, "page": page, "total": len(navs), "items": navs}
    except Exception as e:
        return {"code": c, "error": f"蛋卷基金接口异常: {e}"}


def fund_growth(code: str, day: str = "ty") -> dict:
    """基金阶段涨幅 — day: ty(今年)/1y/3y/5y 或具体日期"""
    c = norm_code(code)
    if not re.fullmatch(r"\d{6}", c):
        return {"error": f"基金代码格式错误: {code}（应为6位数字）"}
    try:
        url = f"https://danjuanapp.com/djapi/fund/growth/{c}?day={day}"
        d = json.loads(_get(url))
        data = d.get("data") or {}
        items = data.get("items") or data.get("navs") or []
        if isinstance(items, dict):
            items = items.get("items") or []
        points = [{
            "date": it.get("date") or it.get("time") or "",
            "nav": it.get("nav") or it.get("value") or "",
            "percentage": it.get("percentage") or it.get("percent") or "",
        } for it in items]
        return {"code": c, "day": day, "total": len(points), "items": points[:200]}
    except Exception as e:
        return {"code": c, "error": f"蛋卷基金接口异常: {e}"}


def fund_asset(code: str) -> dict:
    """基金资产配置 — 股票/债券/现金比例+重仓股"""
    c = norm_code(code)
    if not re.fullmatch(r"\d{6}", c):
        return {"error": f"基金代码格式错误: {code}（应为6位数字）"}
    try:
        d = json.loads(_get(f"https://danjuanapp.com/djapi/fund/detail/{c}"))
        data = d.get("data") or {}
        pos = data.get("fund_position") or {}
        stocks = pos.get("stock_list") or []
        return {
            "code": c,
            "report_date": pos.get("date") or "",
            "stock_percent": pos.get("stock_percent") or 0,
            "bond_percent": pos.get("bond_percent") or 0,
            "cash_percent": pos.get("cash_percent") or 0,
            "top10": [{
                "name": s.get("stock_name") or "",
                "code": s.get("stock_code") or "",
                "ratio": s.get("stock_ratio") or 0,
            } for s in stocks[:10]],
            "source": "danjuanapp.com",
        }
    except Exception as e:
        return {"code": c, "error": f"蛋卷基金接口异常: {e}"}


def fund_manager(code: str) -> dict:
    """基金经理 — 任期/年限/业绩"""
    c = norm_code(code)
    if not re.fullmatch(r"\d{6}", c):
        return {"error": f"基金代码格式错误: {code}（应为6位数字）"}
    try:
        d = json.loads(_get(f"https://danjuanapp.com/djapi/fund/detail/{c}"))
        data = d.get("data") or {}
        managers = (data.get("manager_list") or []) or (data.get("fund_manager") or [])
        if isinstance(managers, dict):
            managers = managers.get("list") or []
        mlist = [{
            "name": m.get("name") or m.get("manager_name") or "",
            "work_years": m.get("work_years") or m.get("work_year") or "",
            "tenure": m.get("tenure") or m.get("manage_date") or "",
            "tenure_return": m.get("tenure_return") or m.get("return") or "",
        } for m in managers]
        return {"code": c, "total": len(mlist), "managers": mlist}
    except Exception as e:
        return {"code": c, "error": f"蛋卷基金接口异常: {e}"}


# ═══════════════════ 指数（中证）═══════════════════

def _cs_get(path: str):
    d = json.loads(_get(f"https://www.csindex.com.cn{path}", referer="https://www.csindex.com.cn/"))
    if d.get("code") != "200":
        raise Exception(f"中证指数返回异常: {d.get('msg') or d.get('code')}")
    return d.get("data") or {}


def index_basic_info(code: str) -> dict:
    c = norm_code(code)
    if not re.fullmatch(r"\d{6}", c):
        return {"error": f"指数代码格式错误: {code}（应为6位数字）"}
    try:
        info = _cs_get(f"/csindex-home/indexInfo/index-basic-info/{c}")
        return {
            "code": c,
            "name_cn": info.get("indexFullNameCn") or "",
            "short_cn": info.get("indexShortNameCn") or "",
            "name_en": info.get("indexFullNameEn") or "",
            "base_date": info.get("basicDate") or "",
            "base_point": info.get("basicIndex") if info.get("basicIndex") is not None else None,
            "publish_date": info.get("publishDate") or "",
            "cons_number": info.get("consNumber") if info.get("consNumber") is not None else None,
            "description": (info.get("indexCnDesc") or "")[:300],
            "source": "csindex.com.cn",
        }
    except Exception as e:
        return {"code": c, "error": f"中证指数接口异常: {e}"}


def index_details(code: str) -> dict:
    """指数详情文件清单 — 编制方案PDF/样本权重xls等直链"""
    c = norm_code(code)
    if not re.fullmatch(r"\d{6}", c):
        return {"error": f"指数代码格式错误: {code}（应为6位数字）"}
    try:
        data = _cs_get(f"/csindex-home/indexInfo/index-details-data?fileLang=1&indexCode={c}")
        pick = lambda key: [{
            "name": f.get("fileName") or "",
            "path": f.get("filePath") or "",
            "type": f.get("fileType") or "",
        } for f in (data.get(key) or [])] or None
        return {
            "code": c,
            "methodology": pick("编制方案"),
            "weight_file": pick("样本权重"),
            "cons_file": pick("样本列表"),
            "valuation_file": pick("指数估值"),
            "source": "csindex.com.cn",
        }
    except Exception as e:
        return {"code": c, "error": f"中证指数接口异常: {e}"}


def index_perf(code: str, days: int = 30) -> dict:
    """指数区间表现 — 每日开高低收/涨跌幅（需带日期参数）"""
    c = norm_code(code)
    if not re.fullmatch(r"\d{6}", c):
        return {"error": f"指数代码格式错误: {code}（应为6位数字）"}
    try:
        from datetime import datetime, timedelta
        n = max(1, min(int(days) or 30, 120))
        end = datetime.now()
        start = end - timedelta(days=n)
        fmt = lambda dt: dt.strftime("%Y%m%d")
        url = (f"https://www.csindex.com.cn/csindex-home/perf/index-perf"
               f"?indexCode={c}&startDate={fmt(start)}&endDate={fmt(end)}")
        d = json.loads(_get(url, referer="https://www.csindex.com.cn/"))
        if d.get("code") != "200":
            return {"code": c, "error": f"中证指数返回异常: {d.get('msg') or d.get('code')}"}
        items = d.get("data") or []
        points = [{
            "date": it.get("tradeDate") or "",
            "open": it.get("open"),
            "high": it.get("high"),
            "low": it.get("low"),
            "close": it.get("close"),
            "change_pct": it.get("changePct"),
            "trading_value_yi": it.get("tradingValue"),
            "cons_number": it.get("consNumber"),
        } for it in items]
        latest = points[-1] if points else None
        return {
            "code": c,
            "name": (items[0].get("indexNameCn") if items else "") or "",
            "points": len(points),
            "latest": latest,
            "items": points,
            "source": "csindex.com.cn",
        }
    except Exception as e:
        return {"code": c, "error": f"中证指数接口异常: {e}"}
