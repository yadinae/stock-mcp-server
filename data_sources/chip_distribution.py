#!/usr/bin/env python3
"""筹码分布 (Chip Distribution / CYQ) 计算器

基于换手率的筹码迁移模型：
- 每日按换手率比例"搬移"筹码到当日均价附近
- 支持获利盘/套牢盘/平均成本/集中度等核心指标
- 数据源：push2his K线（含换手率字段）
"""
from __future__ import annotations

import math
import urllib.request
import json
from typing import Any

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"


def _secid(code: str) -> str:
    """股票代码转东财 secid (market.code)"""
    code = code.strip()
    if code.startswith(("sh", "sz", "SH", "SZ")):
        prefix = code[:2].upper()
        num = code[2:]
        return f"1.{num}" if prefix == "SH" else f"0.{num}"
    if code.startswith("6") or code.startswith("9"):
        return f"1.{code}"
    if code.startswith(("0", "3", "4", "8")):
        return f"0.{code}"
    if code.startswith("1"):  # 指数
        return f"1.{code}"
    return f"0.{code}"


def _fetch_kline_with_turnover(code: str, days: int = 250) -> list[dict]:
    """从 push2his 获取含换手率的K线数据

    字段: date, open, close, high, low, volume(手), amount(元),
          amplitude%, change%, change_abs%, turnover_rate%
    """
    secid = _secid(code)
    url = (
        f"https://push2his.eastmoney.com/api/qt/stock/kline/get?"
        f"secid={secid}&fields1=f1,f2,f3,f4,f5,f6"
        f"&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61"
        f"&klt=101&fqt=1&end=20500101&lmt={days}"
    )
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Referer": "https://finance.eastmoney.com/",
    })
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    klines_raw = data.get("data", {}).get("klines", [])
    if not klines_raw:
        return []

    result = []
    for line in klines_raw:
        parts = line.split(",")
        if len(parts) < 11:
            continue
        try:
            result.append({
                "date": parts[0],
                "open": float(parts[1]),
                "close": float(parts[2]),
                "high": float(parts[3]),
                "low": float(parts[4]),
                "volume": int(parts[5]),        # 手
                "amount": float(parts[6]),       # 元
                "amplitude": float(parts[7]),    # %
                "change_pct": float(parts[8]),   # %
                "change_abs": float(parts[9]),   # 元
                "turnover_rate": float(parts[10]),  # %
            })
        except (ValueError, IndexError):
            continue
    return result


def calculate_chip_distribution(
    code: str,
    days: int = 120,
    price_bins: int = 100,
) -> dict[str, Any]:
    """计算筹码分布

    算法：换手率驱动的筹码迁移模型
    1. 初始筹码 = 全部集中在第一天的收盘价
    2. 每天：旧筹码按 (1 - turnover_rate/100) 比例保留
              新筹码按 turnover_rate/100 比例加入当日均价
    3. 新筹码在 [low, high] 范围内按正态分布分配

    Returns:
        {
            code, name, current_price, avg_cost, profit_ratio,
            concentration_90, concentration_70, price_range,
            chips: [{price, percentage, is_profit}, ...]
        }
    """
    klines = _fetch_kline_with_turnover(code, days)
    if not klines:
        return {"error": f"无法获取 {code} 的K线数据", "code": code}

    name = ""
    # 从 API 响应获取名称
    try:
        secid = _secid(code)
        url = (
            f"https://push2his.eastmoney.com/api/qt/stock/kline/get?"
            f"secid={secid}&fields1=f1&fields2=f51&klt=101&fqt=1&end=20500101&lmt=1"
        )
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Referer": "https://finance.eastmoney.com/"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            meta = json.loads(resp.read().decode("utf-8"))
            name = meta.get("data", {}).get("name", "")
    except Exception:
        pass

    current_price = klines[-1]["close"]

    # 价格范围
    all_highs = [k["high"] for k in klines]
    all_lows = [k["low"] for k in klines]
    price_min = min(all_lows) * 0.95
    price_max = max(all_highs) * 1.05
    bin_size = (price_max - price_min) / price_bins if price_max > price_min else 1

    # 初始化筹码数组
    chips = [0.0] * price_bins

    def _price_to_bin(price: float) -> int:
        idx = int((price - price_min) / bin_size)
        return max(0, min(price_bins - 1, idx))

    def _distribute_chips(center_price: float, low: float, high: float, amount: float):
        """将筹码按正态分布在 [low, high] 范围"""
        spread = (high - low) / 4  # 95% 在 [low, high]
        if spread <= 0:
            spread = bin_size
        for i in range(price_bins):
            price = price_min + (i + 0.5) * bin_size
            z = (price - center_price) / spread
            weight = math.exp(-0.5 * z * z)
            chips[i] += amount * weight

    total_chips = 0.0
    decay = 0.97  # 长期筹码自然衰减（模拟获利了结）

    for k in klines:
        avg_price = (k["high"] + k["low"] + k["close"]) / 3
        turnover = k["turnover_rate"] / 100.0
        volume_shares = k["volume"] * 100  # 手 → 股

        # 旧筹码衰减 + 保留
        for i in range(price_bins):
            chips[i] *= decay

        retained = 1.0 - min(turnover, 0.5)  # 上限50%换手
        for i in range(price_bins):
            chips[i] *= retained

        # 新进场筹码
        new_chips = volume_shares * turnover
        if new_chips > 0:
            _distribute_chips(avg_price, k["low"], k["high"], new_chips)

        total_chips = sum(chips)

    if total_chips <= 0:
        return {"error": "筹码计算结果为零", "code": code}

    # 归一化
    percentages = [c / total_chips * 100 for c in chips]

    # 计算核心指标
    avg_cost = 0.0
    for i in range(price_bins):
        price = price_min + (i + 0.5) * bin_size
        avg_cost += price * percentages[i] / 100

    # 获利盘比例
    profit_ratio = 0.0
    for i in range(price_bins):
        price = price_min + (i + 0.5) * bin_size
        if price <= current_price:
            profit_ratio += percentages[i]

    # 集中度 (90% 筹码的价格区间)
    sorted_chips = sorted(
        [(price_min + (i + 0.5) * bin_size, percentages[i]) for i in range(price_bins)],
        key=lambda x: x[0],
    )
    cumulative = 0.0
    p5 = p95 = sorted_chips[0][0]
    p15 = p85 = sorted_chips[0][0]
    for price, pct in sorted_chips:
        cumulative += pct
        if cumulative <= 5:
            p5 = price
        if cumulative <= 15:
            p15 = price
        if cumulative <= 85:
            p85 = price
        if cumulative <= 95:
            p95 = price

    # 压缩输出：只返回有意义的价格区间
    chip_output = []
    for i in range(price_bins):
        if percentages[i] > 0.01:  # 过滤噪声
            price = round(price_min + (i + 0.5) * bin_size, 2)
            chip_output.append({
                "price": price,
                "percentage": round(percentages[i], 2),
                "is_profit": price <= current_price,
            })

    return {
        "code": code,
        "name": name,
        "current_price": current_price,
        "avg_cost": round(avg_cost, 2),
        "profit_ratio": round(profit_ratio, 1),
        "loss_ratio": round(100 - profit_ratio, 1),
        "concentration_90": {
            "low": round(p5, 2),
            "high": round(p95, 2),
            "width_pct": round((p95 - p5) / current_price * 100, 1) if current_price > 0 else 0,
        },
        "concentration_70": {
            "low": round(p15, 2),
            "high": round(p85, 2),
            "width_pct": round((p85 - p15) / current_price * 100, 1) if current_price > 0 else 0,
        },
        "price_range": {
            "low": round(price_min, 2),
            "high": round(price_max, 2),
        },
        "days_used": len(klines),
        "chips": chip_output,
        "source": "push2his_kline_cyq",
    }
