#!/usr/bin/env python3
"""
节假日检查模块 — 基于 JwOKR/calendar-subscription-tool 生成的 .ics 日历

数据源:
  /home/admin/.hermes/calendar-subscription-tool/output/china-holidays.ics
  数据来自 timor.tech，涵盖 2021-2028 年中国法定节假日 + 调休安排。

用法:
  from vacation_checker import is_holiday, is_workday_adjusted, get_today_holiday_name
  is_holiday(2026, 10, 7)   # True (国庆节假期)
  is_holiday(2026, 10, 10)  # False (周六但是调休补班日) -- 用于判断 A 股休市

A 股休市规则:
  - 周末(周六/周日)默认休市
  - 法定节假日(国庆/春节/清明/劳动/端午/中秋/元旦)休市
  - 调休补班日(周末但需上班)不等于交易日 — A 股周末补班日依然休市
  因此: 交易日 = 周中 AND 非节假日
"""

import os
import re
from datetime import datetime, date

# ICS 日历文件路径（环境变量覆盖，默认相对 hermes 目录）
_ICS_DEFAULT = "/home/admin/.hermes/calendar-subscription-tool/output/china-holidays.ics"
ICS_PATH = os.environ.get("STOCK_MCP_HOLIDAY_ICS", _ICS_DEFAULT)

# 缓存：首次解析后存内存，避免重复读文件
_holiday_ranges = None  # list of (start_date, end_date_exclusive, name)
_makeup_workdays = None  # set of date — 调休补班日（周末但需上班）


def _parse_ics(path=ICS_PATH):
    """解析 ICS 文件，提取假期区间和补班日"""
    global _holiday_ranges, _makeup_workdays
    if _holiday_ranges is not None and _makeup_workdays is not None:
        return _holiday_ranges, _makeup_workdays

    holidays = []
    workdays = set()

    if not os.path.exists(path):
        # 回退：旧的仅周中判断（import error 路径已在外层处理）
        _holiday_ranges, _makeup_workdays = [], set()
        return _holiday_ranges, _makeup_workdays

    with open(path, encoding="utf-8") as f:
        content = f.read()

    # 按 VEVENT 块分割
    events = re.split(r"BEGIN:VEVENT", content)[1:]
    for ev in events:
        summary_m = re.search(r"SUMMARY:([^\r\n]+)", ev)
        start_m = re.search(r"DTSTART;VALUE=DATE:(\d{8})", ev)
        if not summary_m or not start_m:
            continue

        summary = summary_m.group(1).strip()
        start_str = start_m.group(1)
        start_date = datetime.strptime(start_str, "%Y%m%d").date()

        end_m = re.search(r"DTEND;VALUE=DATE:(\d{8})", ev)

        if "补班" in summary or "需要上班" in ev:
            # 调休补班日（单日事件）
            workdays.add(start_date)
        elif "假期" in summary:
            # 假期区间 [start, end)
            if end_m:
                end_date = datetime.strptime(end_m.group(1), "%Y%m%d").date()
            else:
                end_date = start_date  # 单日
            holidays.append((start_date, end_date, summary))

    _holiday_ranges = holidays
    _makeup_workdays = workdays
    return _holiday_ranges, _makeup_workdays


def is_holiday(year, month, day):
    """判断某天是否为法定节假日（休市日）

    周末且不是补班日 → True（休市）
    周中但在假期区间 → True（休市）
    补班日（周末但需上班）→ A 股依然休市，返回 True
    """
    d = date(year, month, day)
    ranges, _ = _parse_ics()

    # 检查是否在任何假期区间内
    for start, end, _name in ranges:
        if start <= d <= end:
            return True

    # 周末 → 休市（A 股不因调休补班开市）
    if d.weekday() >= 5:
        return True

    # 周中且不在假期区间 → 非休市
    return False


def is_workday_adjusted(year, month, day):
    """判断某天是否为调休补班日（周末但需要上班，对 A 股仍休市）"""
    d = date(year, month, day)
    _, makeup = _parse_ics()
    return d in makeup


def is_a_share_trading_day(year=None, month=None, day=None):
    """A 股交易日判定：周中 AND 非节假日"""
    if year is None:
        today = datetime.now()
        year, month, day = today.year, today.month, today.day
    d = date(year, month, day)
    # 周末休市
    if d.weekday() >= 5:
        return False
    # 周中且非假期
    return not is_holiday(year, month, day)


def get_today_holiday_name(year=None, month=None, day=None):
    """获取某天的节假日名称，非节假日返回 None"""
    if year is None:
        today = datetime.now()
        year, month, day = today.year, today.month, today.day
    d = date(year, month, day)
    ranges, _ = _parse_ics()
    for start, end, name in ranges:
        if start <= d <= end:
            return name
    return None


if __name__ == "__main__":
    today = datetime.now()
    print(f"今天: {today.strftime('%Y-%m-%d %A')}")
    print(f"is_holiday: {is_holiday(today.year, today.month, today.day)}")
    print(f"is_a_share_trading_day: {is_a_share_trading_day()}")
    name = get_today_holiday_name()
    print(f"节假日名称: {name}")
    print()
    # 测试几个关键日期
    test_dates = [
        (2026, 10, 7),   # 国庆假期
        (2026, 10, 8),   # 节后首日
        (2026, 10, 10),  # 周六补班
        (2026, 9, 25),   # 中秋假期
        (2026, 6, 19),   # 端午假期
        (2026, 5, 1),    # 劳动节
        (2026, 4, 4),    # 清明
        (2026, 2, 16),   # 春节
        (2026, 1, 1),    # 元旦
        (2026, 10, 9),   # 周五，正常交易日
    ]
    for y, m, d in test_dates:
        h = is_holiday(y, m, d)
        t = is_a_share_trading_day(y, m, d)
        n = get_today_holiday_name(y, m, d) or ""
        print(f"  {y}-{m:02d}-{d:02d} {'周' + '一二三四五六日'[date(y, m, d).weekday()]}: "
              f"holiday={h!s:5} trading={t!s:5} {n}")
