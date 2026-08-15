#!/usr/bin/env python3
"""东财 F10 数据源 — emweb + datacenter 双通道（移植自 Gateway tdx_company.ts）

本地实测: emweb.securities.eastmoney.com / datacenter-web.eastmoney.com 均 200
对应工具: get_company_profile / get_company_financials / get_top_shareholders / get_management_team
         + TDX 兼容名（get_tdx_company_info / get_tdx_finance_info / get_tdx_xdxr_info）
"""
import json
import time
import urllib.request
import urllib.parse

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
DATACENTER_API = "https://datacenter-web.eastmoney.com/api/data/v1/get"


def _http_get(url: str, referer: str = "https://emweb.securities.eastmoney.com/", timeout: float = 12.0):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Referer": referer,
        "Accept": "application/json, text/plain, */*",
    })
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", "replace")


def _http_post(url: str, data: dict, referer: str = "https://emweb.securities.eastmoney.com/", timeout: float = 12.0):
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(url, data=body, headers={
        "User-Agent": UA,
        "Referer": referer,
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json, text/plain, */*",
    })
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", "replace")


def extract_code(code: str) -> str:
    c = code.strip()
    c = c.replace(".SH", "").replace(".SZ", "").replace(".BJ", "").upper()
    c = c.replace("SH", "").replace("SZ", "").replace("BJ", "")
    return c.strip()


def to_secu_code(code: str) -> str:
    """600519 → 600519.SH / 000001 → 000001.SZ / 8开头 → .BJ"""
    c = extract_code(code)
    if not c:
        return ""
    if c[0] in "69":
        return f"{c}.SH"
    if c[0] in "84":
        return f"{c}.BJ"
    return f"{c}.SZ"


def em_market(code: str) -> str:
    secu = to_secu_code(code)
    if secu.endswith(".SH"):
        return "SH"
    if secu.endswith(".BJ"):
        return "BJ"
    return "SZ"


# ─────────────────────────────────────────────
# get_company_profile — emweb CompanySurvey 主源
# ─────────────────────────────────────────────
def get_company_profile(code: str) -> dict:
    c = extract_code(code)
    if len(c) != 6:
        return {"error": f"无效的股票代码: {code}", "code": code}

    # 方式 1: emweb F10 CompanySurvey（字段最全）
    try:
        url = f"https://emweb.securities.eastmoney.com/PC_HSF10/CompanySurvey/PageAjax?code={em_market(code)}{c}"
        raw = _http_get(url)
        data = json.loads(raw)
        jbzl = (data.get("jbzl") or [{}])[0]
        if jbzl:
            return {
                "code": code,
                "name": jbzl.get("SECURITY_NAME_ABBR") or code,
                "full_name": jbzl.get("ORG_NAME") or jbzl.get("FULL_NAME") or "",
                "established_date": jbzl.get("FOUND_DATE") or "",
                "listing_date": jbzl.get("LISTING_DATE") or "",
                "registered_address": jbzl.get("REGISTERED_ADDRESS") or jbzl.get("REG_ADDRESS") or "",
                "business_scope": jbzl.get("BUSINESS_SCOPE") or "",
                "main_business": jbzl.get("MAIN_OPERATION") or jbzl.get("MAIN_BUSINESS") or "",
                "industry": jbzl.get("INDUSTRY_NAME") or jbzl.get("INDUSTRY") or "",
                "employees": jbzl.get("EMP_NUM") or jbzl.get("EMPLOYEES") or None,
                "legal_representative": jbzl.get("LEGAL_PERSON") or jbzl.get("CHAIRMAN") or "",
                "secretary": jbzl.get("SECRETARY") or "",
                "total_shares": jbzl.get("TOTAL_SHARES") or jbzl.get("REG_CAPITAL") or 0,
                "circulating_shares": jbzl.get("FREE_SHARES") or 0,
                "source": "eastmoney_emweb",
            }
    except Exception as e:
        pass

    # 方式 2: datacenter RPT_LICO_FN_CPD（部分字段）
    try:
        params = urllib.parse.urlencode({
            "reportName": "RPT_LICO_FN_CPD", "columns": "ALL",
            "pageNumber": "1", "pageSize": "1", "sortTypes": "-1",
            "sortColumns": "NOTICE_DATE",
            "filter": f'(SECUCODE="{to_secu_code(code)}")',
            "source": "WEB", "client": "WEB",
        })
        raw = _http_get(f"{DATACENTER_API}?{params}")
        data = json.loads(raw)
        records = (data.get("result") or {}).get("data") or []
        if records:
            item = records[0]
            return {
                "code": code,
                "name": item.get("SECURITY_NAME_ABBR") or code,
                "full_name": item.get("FULL_NAME") or item.get("ORG_NAME") or "",
                "established_date": item.get("ESTABLISH_DATE") or "",
                "listing_date": item.get("LISTING_DATE") or "",
                "registered_address": item.get("REGISTERED_ADDRESS") or "",
                "business_scope": item.get("BUSINESS_SCOPE") or "",
                "main_business": item.get("MAIN_BUSINESS") or "",
                "industry": item.get("INDUSTRY") or item.get("BOARD_NAME") or "",
                "employees": item.get("EMPLOYEES") or None,
                "legal_representative": item.get("LEGAL_REPRESENTATIVE") or "",
                "secretary": item.get("SECRETARY") or "",
                "total_shares": item.get("TOTAL_SHARES") or 0,
                "circulating_shares": item.get("CIRCULATING_SHARES") or 0,
                "source": "eastmoney_f10",
            }
    except Exception:
        pass

    return {"error": "公司资料获取失败（emweb + datacenter 均无数据）", "code": code}


# ─────────────────────────────────────────────
# get_company_financials — RPT_F10_FINANCE_MAINFINADATA
# ─────────────────────────────────────────────
def get_company_financials(code: str, periods: int = 8) -> dict:
    c = extract_code(code)
    secu = to_secu_code(code)
    records = []

    # 方式 1: datacenter RPT_F10_FINANCE_MAINFINADATA
    try:
        params = urllib.parse.urlencode({
            "reportName": "RPT_F10_FINANCE_MAINFINADATA", "columns": "ALL",
            "pageNumber": "1", "pageSize": str(periods), "sortTypes": "-1",
            "filter": f'(SECUCODE="{secu}")',
            "source": "WEB", "client": "WEB",
        })
        raw = _http_get(f"{DATACENTER_API}?{params}")
        data = json.loads(raw)
        records = (data.get("result") or {}).get("data") or []
    except Exception:
        pass

    # 方式 2: emweb NewFinanceAnalysis
    if not records:
        try:
            url = f"https://emweb.securities.eastmoney.com/PC_HSF10/NewFinanceAnalysis/ZYZBAjaxNew?type=0&code={em_market(code)}{c}"
            raw = _http_get(url)
            data = json.loads(raw)
            em_data = data.get("data") or []
            records = em_data[:periods]
        except Exception:
            pass

    if not records:
        return {"error": "暂无财务数据", "code": code, "records": []}

    indicators = []
    for r in records:
        indicators.append({
            "date": r.get("REPORT_DATE") or r.get("REPORTDATE") or "",
            "eps": r.get("EPSJB") or r.get("BASIC_EPS") or None,
            "revenue": r.get("TOTALOPERATEREVE") or r.get("TOTAL_OPERATE_INCOME") or None,
            "net_profit": r.get("PARENTNETPROFIT") or r.get("PARENT_NETPROFIT") or None,
            "gross_margin": r.get("XSMLL") or r.get("SALE_GROSSPROFIT_RATIO") or None,
            "roe": r.get("ROEJQ") or r.get("WEIGHTAVG_ROE") or None,
            "debt_ratio": r.get("ZCFZL") or r.get("DEBT_ASSET_RATIO") or None,
            "bvps": r.get("BPS") or r.get("BVPS") or None,
            "cfps": r.get("MGJYXJJE") or r.get("CFPS") or None,
        })

    return {"code": code, "count": len(indicators), "indicators": indicators, "source": "eastmoney_f10"}


# ─────────────────────────────────────────────
# get_top_shareholders — RPT_F10_EH_HOLDERS + emweb
# ─────────────────────────────────────────────
def get_top_shareholders(code: str) -> dict:
    c = extract_code(code)
    secu = to_secu_code(code)
    records = []

    # 方式 1: datacenter RPT_F10_EH_HOLDERS
    try:
        params = urllib.parse.urlencode({
            "reportName": "RPT_F10_EH_HOLDERS", "columns": "ALL",
            "pageNumber": "1", "pageSize": "10", "sortTypes": "-1",
            "sortColumns": "END_DATE",
            "filter": f'(SECUCODE="{secu}")',
            "source": "WEB", "client": "WEB",
        })
        raw = _http_get(f"{DATACENTER_API}?{params}")
        data = json.loads(raw)
        records = (data.get("result") or {}).get("data") or []
    except Exception:
        pass

    # 方式 2: emweb ShareholderResearch
    if not records:
        try:
            url = f"https://emweb.securities.eastmoney.com/PC_HSF10/ShareholderResearch/PageAjax?code={em_market(code)}{c}"
            raw = _http_get(url)
            data = json.loads(raw)
            sdgd = data.get("sdgd") or []
            records = [{
                "END_DATE": r.get("END_DATE") or "",
                "HOLDER_RANK": r.get("HOLDER_RANK"),
                "HOLDER_NAME": r.get("HOLDER_NAME"),
                "HOLD_NUM": r.get("HOLD_NUM"),
                "HOLD_NUM_RATIO": r.get("HOLD_NUM_RATIO"),
                "HOLD_NUM_CHANGE": r.get("HOLD_NUM_CHANGE"),
                "CHANGE_RATIO": r.get("CHANGE_RATIO"),
            } for r in sdgd]
        except Exception:
            pass

    shareholders = []
    for i, r in enumerate(records):
        change = r.get("HOLD_NUM_CHANGE")
        shareholders.append({
            "rank": r.get("HOLDER_RANK") or i + 1,
            "name": r.get("HOLDER_NAME") or "",
            "shares": r.get("HOLD_NUM") or 0,
            "ratio": r.get("HOLD_NUM_RATIO") or 0,
            "change": f"变动:{change}" if change else "",
        })

    return {
        "code": code,
        "count": len(shareholders),
        "shareholders": shareholders,
        "report_date": records[0].get("END_DATE", "")[:10] if records else "",
        "source": "eastmoney_f10",
    }


# ─────────────────────────────────────────────
# get_management_team — emweb CompanySurvey jbzl
# ─────────────────────────────────────────────
def get_management_team(code: str) -> dict:
    c = extract_code(code)
    managers = []

    try:
        url = f"https://emweb.securities.eastmoney.com/PC_HSF10/CompanySurvey/PageAjax?code={em_market(code)}{c}"
        raw = _http_get(url)
        data = json.loads(raw)
        jbzl = (data.get("jbzl") or [{}])[0]
        if jbzl:
            def add(name, title):
                if name and name != "-" and name != "":
                    if "独立董事" in title:
                        for n in name.replace("，", ",").split(","):
                            n = n.strip()
                            if n:
                                managers.append({"name": n, "title": "独立董事"})
                    else:
                        managers.append({"name": str(name).strip(), "title": title})
            add(jbzl.get("CHAIRMAN"), "董事长")
            add(jbzl.get("PRESIDENT"), "总经理")
            add(jbzl.get("SECPRESENT"), "副总经理")
            add(jbzl.get("LEGAL_PERSON"), "法定代表人")
            add(jbzl.get("SECRETARY"), "董事会秘书")
            add(jbzl.get("INDEDIRECTORS"), "独立董事")
    except Exception:
        pass

    return {
        "code": code,
        "count": len(managers),
        "managers": managers,
        "source": "eastmoney_emweb" if managers else "eastmoney_f10",
    }


# ─────────────────────────────────────────────
# 除权除息 — datacenter RPT_LIFT_STAGE 或东财 F10
# ─────────────────────────────────────────────
def get_xdxr_info(code: str) -> dict:
    c = extract_code(code)
    secu = to_secu_code(code)
    try:
        params = urllib.parse.urlencode({
            "reportName": "RPT_LICO_FN_CPD", "columns": "ALL",
            "pageNumber": "1", "pageSize": "20", "sortTypes": "-1",
            "sortColumns": "NOTICE_DATE",
            "filter": f'(SECUCODE="{secu}")',
            "source": "WEB", "client": "WEB",
        })
        raw = _http_get(f"{DATACENTER_API}?{params}")
        data = json.loads(raw)
        records = (data.get("result") or {}).get("data") or []
        return {"code": code, "count": len(records), "records": records, "source": "eastmoney_f10"}
    except Exception as e:
        return {"error": str(e), "code": code}
