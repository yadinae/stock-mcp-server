#!/usr/bin/env python3
"""新浪财报三表（移植自 Gateway sina_financial.ts）

数据源: quotes.sina.cn CompanyFinanceService.getFinanceReport2022（本地 200 ✅）
报告类型: lrb(利润表) / fzb(资产负债表) / llb(现金流量表)
"""
import json
import urllib.request
import urllib.parse

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
SINA_API = "https://quotes.sina.cn/cn/api/openapi.php/CompanyFinanceService.getFinanceReport2022"
REPORT_NAMES = {"lrb": "利润表", "fzb": "资产负债表", "llb": "现金流量表"}


def _code_to_paper(code: str) -> str:
    code = code.strip().lower()
    if code.startswith(("sh", "sz", "bj")):
        return code
    if code.startswith("6"):
        return f"sh{code}"
    return f"sz{code}"


def get_sina_financial_report(code: str, report_type: str = "lrb", periods: int = 8):
    """获取新浪财报三表数据。"""
    code = code.strip()
    if not code:
        return {"error": "股票代码不能为空"}
    if report_type not in ("lrb", "fzb", "llb"):
        return {"error": "报表类型必须为 lrb(利润表)/fzb(资产负债表)/llb(现金流量表)"}
    periods = max(1, min(int(periods or 8), 20))
    paper = _code_to_paper(code)

    params = urllib.parse.urlencode({
        "paperCode": paper, "source": report_type,
        "type": "0", "page": "1", "num": str(periods),
    })
    url = f"{SINA_API}?{params}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            d = json.loads(resp.read().decode("utf-8", "replace"))
    except Exception as e:
        return {
            "code": code, "reportType": report_type,
            "reportName": REPORT_NAMES.get(report_type, ""),
            "totalPeriods": 0, "periods": [], "error": str(e)[:120],
        }

    report_list = (d or {}).get("result", {}).get("data", {}).get("report_list") or {}
    out_periods = []
    for period_key in sorted(report_list.keys(), reverse=True)[:periods]:
        obj = report_list[period_key]
        items, tongbi = {}, {}
        for row in (obj or {}).get("data") or []:
            title = row.get("item_title") or ""
            value = row.get("item_value")
            if not title or value is None:
                continue
            items[title] = str(value)
            tb = row.get("item_tongbi")
            if tb not in (None, "", "null"):
                tongbi[title] = str(tb)
        out_periods.append({
            "period": f"{period_key[:4]}-{period_key[4:6]}-{period_key[6:8]}",
            "items": items,
            "tongbi": tongbi,
        })

    return {
        "code": code,
        "reportType": report_type,
        "reportName": REPORT_NAMES.get(report_type, ""),
        "totalPeriods": len(out_periods),
        "periods": out_periods,
    }


if __name__ == "__main__":
    import sys
    t = sys.argv[1] if len(sys.argv) > 1 else "lrb"
    code = sys.argv[2] if len(sys.argv) > 2 else "600519"
    r = get_sina_financial_report(code, t, 3)
    print(f"{r.get('reportName')}: {r.get('totalPeriods')}期 error={r.get('error', '')}")
    if r.get("periods"):
        p = r["periods"][0]
        keys = list(p["items"].keys())[:8]
        parts = [f'{k}={p["items"][k]}' for k in keys]
        print(f"最新期 {p['period']}: {', '.join(parts)}")
