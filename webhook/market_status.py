"""
A股交易日检测模块
================
判断当前是否为 A 股交易日，避免休市期间用昨日数据装模作样分析。

检测逻辑（多重保障）:
1. 周末检查 → 周六周日直接返回非交易日
2. 实时行情时间戳对比 → 取上证指数最新数据，看日期是否等于今天
3. 节假日 API → 调用免费 API 校验（bitefu.net）
4. 兜底 → 数据日期 < 今天 → 非交易日

市场状态:
  open        — 交易中（9:30-11:30 / 13:00-15:00）
  closed      — 已收盘（15:00后）
  holiday     — 休市日（周末/节假日，全无数据）
  pre_open    — 盘前（9:30前，数据还是昨天的）
"""

from __future__ import annotations

import logging
from datetime import date, datetime, time, timezone, timedelta

import httpx

logger = logging.getLogger("stock-mcp.webhook.market_status")

# 北京时间
BJT = timezone(timedelta(hours=8))

# A 股交易时段
MORNING_START = time(9, 30)
MORNING_END = time(11, 30)
AFTERNOON_START = time(13, 0)
AFTERNOON_END = time(15, 0)

# 上证指数代码（用于检测数据新鲜度）
SH_INDEX = "000001"


def now_bjt() -> datetime:
    """返回当前北京时间"""
    return datetime.now(BJT)


def is_weekend() -> bool:
    """检查今天是不是周末"""
    return now_bjt().weekday() >= 5  # 5=周六, 6=周日


def is_market_hours() -> bool:
    """检查当前是否在交易时段内（不考虑节假日）"""
    t = now_bjt().time()
    if MORNING_START <= t <= MORNING_END:
        return True
    if AFTERNOON_START <= t <= AFTERNOON_END:
        return True
    return False


def is_market_open_now() -> bool:
    """精确判断当前是否在交易时段内（节假日已排除）"""
    if is_weekend():
        return False
    if not is_market_hours():
        return False
    return True


def check_data_freshness() -> dict:
    """通过上证指数实时行情判断数据新鲜度

    用腾讯行情 API 获取上证指数，对比数据日期与今天是否一致。

    Returns:
        {is_fresh: bool, data_date: str|None, today: str, detail: str}
    """
    today_str = now_bjt().strftime("%Y-%m-%d")
    try:
        url = f"https://qt.gtimg.cn/q=sh{SH_INDEX}"
        resp = httpx.get(url, headers={
            "User-Agent": "Mozilla/5.0",
        }, timeout=10)
        resp.encoding = "gbk"
        text = resp.text.strip()
        import re
        m = re.search(r'"(.+)"', text)
        if not m:
            return {
                "is_fresh": False,
                "data_date": None,
                "today": today_str,
                "detail": "行情接口未返回数据",
            }
        fields = m.group(1).split("~")
        # 腾讯行情中字段30是时间戳
        # 腾讯行情时间戳格式多样:
        # A股: "202606181600" 或 "2026-06-18 16:00:02"
        # 美股: "2026-06-18 16:00:02"
        # 港股: "2026-06-18 16:00:02"
        timestamp = fields[30] if len(fields) > 30 else ""
        data_date = ""
        if timestamp and len(timestamp) >= 8:
            # "202606181600" → 取前8位 "20260618"
            if timestamp.isdigit() and len(timestamp) >= 8:
                d = timestamp[:8]
                data_date = f"{d[:4]}-{d[4:6]}-{d[6:8]}"
            else:
                # "2026-06-18 16:00:02" → 取前10位
                data_date = timestamp[:10]

        if data_date == today_str:
            return {
                "is_fresh": True,
                "data_date": data_date,
                "today": today_str,
                "detail": f"数据日期 {data_date} = 今天 {today_str}，数据新鲜",
            }
        elif data_date:
            return {
                "is_fresh": False,
                "data_date": data_date,
                "today": today_str,
                "detail": f"数据日期 {data_date} ≠ 今天 {today_str}，可能是节假日或盘前",
            }
        else:
            return {
                "is_fresh": False,
                "data_date": None,
                "today": today_str,
                "detail": "未能从行情中提取日期",
            }
    except Exception as e:
        logger.warning("上证指数行情获取失败: %s", e)
        return {
            "is_fresh": False,
            "data_date": None,
            "today": today_str,
            "detail": f"行情获取异常: {e}",
        }


def check_holiday_api() -> dict:
    """调用节假日 API 检测今天是否为交易日

    使用 bitefu.net 免费接口。

    Returns:
        {is_trading: bool, detail: str}
    """
    today_str = now_bjt().strftime("%Y-%m-%d")
    try:
        resp = httpx.get(
            "https://tool.bitefu.net/jiari/",
            params={"d": today_str},
            timeout=10,
        )
        data = resp.json()
        # 返回格式: {"code": 0, "data": {"2026-06-19": "0"}}
        # 0=工作日非节假日, 1=节假日, 2=周末
        if isinstance(data, dict) and "data" in data:
            day_info = data["data"].get(today_str, "0")
            if day_info == "0":
                return {
                    "is_trading": True,
                    "detail": f"{today_str} 是工作日",
                }
            else:
                return {
                    "is_trading": False,
                    "detail": f"{today_str} 是{'节假日' if day_info == '1' else '周末'}",
                }
        return {"is_trading": None, "detail": f"API 返回格式异常: {data}"}
    except Exception as e:
        logger.warning("节假日 API 不可用: %s", e)
        return {"is_trading": None, "detail": f"API 不可用: {e}"}


def is_trading_day() -> dict:
    """综合判断今天是否为 A 股交易日

    检测链: weekend → data_freshness → holiday_api，取最确定的结果。

    Returns:
        {is_trading: bool, reason: str, data_freshness: dict|None}
        确保 is_trading 一定返回 bool 值。
    """
    result = {"is_trading": False, "reason": "", "data_freshness": None}

    # 1. 周末快速判断
    if is_weekend():
        weekday_names = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
        wd = weekday_names[now_bjt().weekday()]
        result["reason"] = f"今天是{wd}，非交易日"
        return result

    # 2. 数据新鲜度检查
    freshness = check_data_freshness()
    result["data_freshness"] = freshness
    today_str = now_bjt().strftime("%Y-%m-%d")

    if freshness["is_fresh"]:
        result["is_trading"] = True
        result["reason"] = f"数据日期等于今天 ({today_str})，交易日"
        return result

    # 3. 数据日期不是今天 → 用节假日 API 确认
    api_result = check_holiday_api()
    if api_result["is_trading"] is not None:
        result["is_trading"] = api_result["is_trading"]
        result["reason"] = api_result["detail"]
        return result

    # 4. 兜底: 数据日期 < 今天 → 非交易日
    data_date = freshness.get("data_date", "")
    if data_date and data_date < today_str:
        result["is_trading"] = False
        result["reason"] = (
            f"数据日期 {data_date} < 今天 {today_str}，"
            f"且节假日API不可用，判定为非交易日 (safe default)"
        )
        return result

    # 5. 全都不确定 → safe default 非交易日
    result["reason"] = "无法确认交易日状态，默认非交易日 (safe default)"
    return result


def is_data_from_today(quote: dict) -> bool:
    """检查单条行情数据的日期是否等于今天

    Args:
        quote: 腾讯行情 dict，需含 "timestamp" 字段（格式 "2026-06-19 15:00:02"）

    Returns:
        True=数据是今天的，False=数据是历史或无法判断
    """
    ts = quote.get("timestamp", "")
    if not ts or len(ts) < 10:
        return False
    data_date = ts[:10]
    return data_date == now_bjt().strftime("%Y-%m-%d")
