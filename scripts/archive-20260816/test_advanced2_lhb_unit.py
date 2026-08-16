#!/usr/bin/env python3
"""advanced2_lhb 单元验证 — 逐规则构造数据验证 K线信号触发"""
import sys
sys.path.insert(0, "/home/admin/projects/stock-mcp-server")
from tools.advanced2_lhb import _detect_kline_traps, _detect_microcap_trap, match_seat, is_institutional

def mk(close, open_, high, low, vol, date):
    return {"date": date, "open": open_, "close": close, "high": high, "low": low, "volume": vol}

def steady(base, days, vol=100000, start="2026-07-01"):
    """平稳上涨序列"""
    out = []
    for i in range(days):
        c = base * (1 + i * 0.005)
        out.append(mk(round(c, 2), round(c - 0.1, 2), round(c + 0.3, 2), round(c - 0.4, 2), vol,
                      f"2026-07-{start_day(start)+i:02d}"))
    return out

def start_day(d):
    return int(d.split("-")[2])

ok = fail = 0
def check(name, cond):
    global ok, fail
    print(("PASS" if cond else "FAIL"), name)
    if cond: ok += 1
    else: fail += 1

# ── 短期暴涨 (5日 >15%) ──
recs = steady(10, 20) + [mk(12.0, 11.8, 12.2, 11.7, 100000, "2026-07-21"),
                          mk(13.2, 12.1, 13.4, 12.0, 120000, "2026-07-22"),
                          mk(14.5, 13.3, 14.7, 13.2, 130000, "2026-07-23"),
                          mk(15.9, 14.6, 16.1, 14.5, 140000, "2026-07-24")]
sigs = _detect_kline_traps(recs)
check("短期暴涨 5日>15% 触发", any(s["name"] == "短期暴涨" and s["severity"] == "high" for s in sigs))

# ── 中期暴涨 (20日 >40%) ──
recs = steady(10, 21) + [mk(16.0, 15.5, 16.3, 15.4, 150000, "2026-07-22"),
                          mk(17.0, 16.1, 17.3, 16.0, 150000, "2026-07-23")]
sigs = _detect_kline_traps(recs)
check("中期暴涨 20日>40% 触发", any(s["name"] == "中期暴涨" and s["severity"] == "high" for s in sigs))

# ── 放量下跌 (10日内量>3x均量 且 跌>3%) ──
recs = steady(10, 9) + [mk(10.0, 9.9, 10.2, 9.8, 100000, "2026-07-10"),
                         mk(9.6, 10.0, 10.1, 9.5, 500000, "2026-07-11")]
sigs = _detect_kline_traps(recs)
check("放量下跌 量>3x 且 跌>3% 触发", any(s["name"] == "放量下跌" and s["severity"] == "high" for s in sigs))

# ── 连板 (5日内 close/open >7.5% 连续>=2 medium / >=3 high) ──
recs = steady(10, 3) + [mk(11.0, 10.0, 11.2, 9.9, 100000, "2026-07-04"),
                         mk(12.1, 11.0, 12.3, 10.9, 100000, "2026-07-07"),
                         mk(13.3, 12.1, 13.5, 12.0, 100000, "2026-07-08")]
sigs = _detect_kline_traps(recs)
check("连板>=3 连续涨停 high 触发", any(s["name"] == "连续涨停" and s["severity"] == "high" for s in sigs))
recs2 = steady(10, 4) + [mk(11.0, 10.0, 11.2, 9.9, 100000, "2026-07-04"),
                          mk(12.1, 11.0, 12.3, 10.9, 100000, "2026-07-07")]
sigs2 = _detect_kline_traps(recs2)
check("连板==2 连板拉升 medium 触发", any(s["name"] == "连板拉升" and s["severity"] == "medium" for s in sigs2))

# ── 微盘低价股 ──
check("微盘低价股 市值<20亿 价<10", _detect_microcap_trap(8.5, 15.0) is not None)
check("微盘不误报 大市值", _detect_microcap_trap(8.5, 500.0) is None)

# ── 游资席位匹配 ──
check("拉萨天团匹配", match_seat("东方财富证券股份有限公司拉萨团结路第二证券营业部")["entry"]["name"] == "拉萨天团")
check("孙哥匹配(上海溧阳路)", match_seat("中信证券股份有限公司上海溧阳路证券营业部")["entry"]["name"] == "孙哥")
check("古北路匹配(孙哥优先,同席位)", match_seat("中信证券股份有限公司上海古北路证券营业部")["entry"]["name"] == "孙哥")
check("无匹配返回None", match_seat("某某证券营业部") is None)
check("机构专用识别", is_institutional("机构专用") is True)
check("深股通不是机构", is_institutional("深股通专用") is False)
check("普通营业部不是机构", is_institutional("华泰证券股份有限公司上海武定路证券营业部") is False)

print(f"\n{ok} passed, {fail} failed")
sys.exit(1 if fail else 0)
