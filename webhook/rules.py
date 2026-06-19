"""
告警规则引擎
============
定义并评估各种告警条件：价格跌幅、ST 风险、MACD 金叉/死叉、RSI 超买/超卖。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from webhook.config import (
    AlertRules,
    Holding,
    PriceDropRule,
    VolumeSpikeRule,
    StRiskRule,
    EtfSignalRule,
)

logger = logging.getLogger("stock-mcp.webhook.rules")

# ── 告警级别 ────────────────────────────────────────────────

@dataclass
class Alert:
    """单个告警"""
    type: str                       # price_drop / st_risk / macd_signal / rsi_signal / volume_spike / etf_score
    level: int                      # 1=提醒, 2=警告, 3=紧急
    code: str
    name: str
    detail: str                     # 告警详情描述
    data: dict[str, Any] = field(default_factory=dict)  # 原始数据快照


@dataclass
class AlertResult:
    """一次告警检查的结果"""
    alerts: list[Alert] = field(default_factory=list)
    has_alerts: bool = False

    def add(self, alert: Alert):
        self.alerts.append(alert)
        self.has_alerts = True

    def merge(self, other: AlertResult):
        self.alerts.extend(other.alerts)
        self.has_alerts = self.has_alerts or other.has_alerts

    @property
    def max_level(self) -> int:
        return max((a.level for a in self.alerts), default=0)


# ═══════════════════════════════════════════════════════════
# 价格跌幅告警
# ═══════════════════════════════════════════════════════════

def check_price_drop(
    quote: dict[str, Any],
    holding: Holding,
    rule: PriceDropRule,
) -> AlertResult:
    """检查持仓价格跌幅是否触发阈值"""
    result = AlertResult()

    if not rule.enabled:
        return result

    code = holding.code
    name = quote.get("name", holding.name)
    change_pct = quote.get("change_pct")
    price = quote.get("price")

    if change_pct is None or price is None:
        return result

    # 从高到低检查阈值（避免重复告警）
    # sorted_thresholds = sorted(rule.thresholds)  # [-8, -5, -3]
    for threshold in sorted(rule.thresholds):
        if change_pct <= threshold:
            # 确定级别
            if threshold <= -8:
                level = 3
                level_label = "紧急"
            elif threshold <= -5:
                level = 2
                level_label = "警告"
            else:
                level = 1
                level_label = "提醒"

            result.add(Alert(
                type="price_drop",
                level=level,
                code=code,
                name=name,
                detail=(
                    f"{name}({code}) 跌幅 {change_pct:.2f}%，"
                    f"跌破 {threshold:.0f}% 阈值！"
                    f"现价 {price:.3f} 元"
                ),
                data={
                    "change_pct": change_pct,
                    "price": price,
                    "threshold": threshold,
                },
            ))
            # 只触发最高级别的告警
            break

    return result


# ═══════════════════════════════════════════════════════════
# ST 风险告警
# ═══════════════════════════════════════════════════════════

def check_st_risk(
    st_report: dict[str, Any],
    holding: Holding,
    rule: StRiskRule,
) -> AlertResult:
    """检查 ST 风险等级是否触发告警"""
    result = AlertResult()

    if not rule.enabled:
        return result

    max_level = st_report.get("max_level", 0)
    level_name = st_report.get("level_name", "正常")
    is_st = st_report.get("is_st", False)

    if max_level >= rule.min_level:
        # 收集危险信号
        signals = [
            s for s in st_report.get("signals", [])
            if s.get("level", 0) >= rule.min_level
        ]

        detail_parts = [
            f"{holding.name}({holding.code}) 风险等级: {level_name} 🔴"
        ]
        for s in signals:
            detail_parts.append(f"  • {s.get('dimension', '')}: {s.get('detail', '')}")

        result.add(Alert(
            type="st_risk",
            level=max_level,
            code=holding.code,
            name=holding.name,
            detail="\n".join(detail_parts),
            data={
                "max_level": max_level,
                "level_name": level_name,
                "is_st": is_st,
                "signals": signals,
            },
        ))

    return result


# ═══════════════════════════════════════════════════════════
# MACD 信号告警
# ═══════════════════════════════════════════════════════════

def check_macd_signal(
    technical: dict[str, Any],
    holding: Holding,
    rule: EtfSignalRule,
) -> AlertResult:
    """检查 MACD 金叉/死叉信号"""
    result = AlertResult()

    if not rule.enabled or not rule.macd.enabled:
        return result

    macd = technical.get("macd", {})
    if not macd:
        return result

    dif = macd.get("dif", 0)
    dea = macd.get("dea", 0)
    bar = macd.get("bar", 0)
    signal = macd.get("signal", "")
    status = macd.get("status", "")

    # 金叉检测: DIF 上穿 DEA，且红柱开始
    if rule.macd.detect_golden_cross:
        if signal == "金叉" or "金叉" in status:
            result.add(Alert(
                type="macd_signal",
                level=2,
                code=holding.code,
                name=holding.name,
                detail=(
                    f"{holding.name}({holding.code}) MACD 金叉信号！\n"
                    f"DIF={dif:.4f}, DEA={dea:.4f}, 红柱={bar:.4f}\n"
                    f"趋势: {status}"
                ),
                data={
                    "signal": "golden_cross",
                    "dif": dif,
                    "dea": dea,
                    "bar": bar,
                    "status": status,
                },
            ))

    # 死叉检测: DIF 下穿 DEA，且绿柱开始
    if rule.macd.detect_death_cross:
        if signal == "死叉" or "死叉" in status:
            result.add(Alert(
                type="macd_signal",
                level=2,
                code=holding.code,
                name=holding.name,
                detail=(
                    f"{holding.name}({holding.code}) MACD 死叉信号！\n"
                    f"DIF={dif:.4f}, DEA={dea:.4f}, 绿柱={bar:.4f}\n"
                    f"趋势: {status}"
                ),
                data={
                    "signal": "death_cross",
                    "dif": dif,
                    "dea": dea,
                    "bar": bar,
                    "status": status,
                },
            ))

    return result


# ═══════════════════════════════════════════════════════════
# RSI 超买/超卖告警
# ═══════════════════════════════════════════════════════════

def check_rsi_signal(
    technical: dict[str, Any],
    holding: Holding,
    rule: EtfSignalRule,
) -> AlertResult:
    """检查 RSI 超买/超卖信号"""
    result = AlertResult()

    if not rule.enabled or not rule.rsi.enabled:
        return result

    rsi_data = technical.get("rsi", {})
    if not rsi_data:
        return result

    rsi_value = rsi_data.get("value", 50)

    if rsi_value <= rule.rsi.oversold_threshold:
        result.add(Alert(
            type="rsi_signal",
            level=2,
            code=holding.code,
            name=holding.name,
            detail=(
                f"{holding.name}({holding.code}) RSI 超卖！\n"
                f"RSI(14)={rsi_value:.1f} ≤ {rule.rsi.oversold_threshold:.0f}\n"
                f"可能超跌反弹机会"
            ),
            data={
                "signal": "oversold",
                "rsi_value": rsi_value,
                "threshold": rule.rsi.oversold_threshold,
            },
        ))
    elif rsi_value >= rule.rsi.overbought_threshold:
        result.add(Alert(
            type="rsi_signal",
            level=1,
            code=holding.code,
            name=holding.name,
            detail=(
                f"{holding.name}({holding.code}) RSI 超买！\n"
                f"RSI(14)={rsi_value:.1f} ≥ {rule.rsi.overbought_threshold:.0f}\n"
                f"注意回调风险"
            ),
            data={
                "signal": "overbought",
                "rsi_value": rsi_value,
                "threshold": rule.rsi.overbought_threshold,
            },
        ))

    return result


# ═══════════════════════════════════════════════════════════
# 量能异常告警
# ═══════════════════════════════════════════════════════════

def check_volume_spike(
    quote: dict[str, Any],
    holding: Holding,
    rule: VolumeSpikeRule,
) -> AlertResult:
    """检查量能异常（放量下跌）"""
    result = AlertResult()

    if not rule.enabled:
        return result

    change_pct = quote.get("change_pct")
    volume_ratio = quote.get("volume_ratio")

    if change_pct is None or volume_ratio is None:
        return result

    if volume_ratio >= rule.volume_ratio_threshold and change_pct <= rule.change_pct_threshold:
        result.add(Alert(
            type="volume_spike",
            level=2,
            code=holding.code,
            name=holding.name,
            detail=(
                f"{holding.name}({holding.code}) 放量下跌！\n"
                f"量比 {volume_ratio:.2f}，跌幅 {change_pct:.2f}%\n"
                f"警惕主力出货或利空消息"
            ),
            data={
                "volume_ratio": volume_ratio,
                "change_pct": change_pct,
            },
        ))

    return result


# ═══════════════════════════════════════════════════════════
# ETF 评分关注告警
# ═══════════════════════════════════════════════════════════

def check_etf_score(
    technical: dict[str, Any],
    quote: dict[str, Any],
    holding: Holding,
    rule: EtfSignalRule,
) -> AlertResult:
    """检查 ETF 技术评分是否达到关注阈值"""
    result = AlertResult()

    if not rule.enabled:
        return result

    score = technical.get("score", 0)
    if score >= rule.min_score:
        change_pct = quote.get("change_pct", 0)
        advice = technical.get("advice", "")
        trend = technical.get("trend", {}).get("status", "")
        price = quote.get("price", 0)

        result.add(Alert(
            type="etf_score",
            level=1,
            code=holding.code,
            name=holding.name,
            detail=(
                f"{holding.name}({holding.code}) 评分 {score} 分 ✅\n"
                f"现价 {price:.3f} ({change_pct:+.2f}%)\n"
                f"趋势: {trend} | 建议: {advice}"
            ),
            data={
                "score": score,
                "advice": advice,
                "trend": trend,
                "price": price,
                "change_pct": change_pct,
            },
        ))

    return result


# ═══════════════════════════════════════════════════════════
# 全量规则检查
# ═══════════════════════════════════════════════════════════

def evaluate_all(
    holding: Holding,
    quote: dict[str, Any],
    st_report: dict[str, Any],
    technical: dict[str, Any],
    rules: AlertRules,
) -> AlertResult:
    """对单个标的执行所有已启用的规则检查"""
    result = AlertResult()

    # 价格跌幅
    result.merge(check_price_drop(quote, holding, rules.price_drop))

    # 量能异常
    result.merge(check_volume_spike(quote, holding, rules.volume_spike))

    # ST 风险
    result.merge(check_st_risk(st_report, holding, rules.st_risk))

    # MACD 信号（ETF 信号子规则）
    result.merge(check_macd_signal(technical, holding, rules.etf_signal))

    # RSI 信号
    result.merge(check_rsi_signal(technical, holding, rules.etf_signal))

    # ETF 评分
    result.merge(check_etf_score(technical, quote, holding, rules.etf_signal))

    return result


# ═══════════════════════════════════════════════════════════
# 格式化告警消息
# ═══════════════════════════════════════════════════════════

def format_alert_message(
    result: AlertResult,
    title: str = "🚨 持仓预警",
) -> str:
    """将告警结果格式化为飞书 Markdown 消息"""
    if not result.has_alerts:
        return ""

    lines: list[str] = []
    lines.append(f"**{title}**")
    lines.append("")

    # 按级别分组
    by_level: dict[int, list[Alert]] = {}
    for a in result.alerts:
        by_level.setdefault(a.level, []).append(a)

    for level in sorted(by_level.keys(), reverse=True):
        level_label = {1: "🔵 提醒", 2: "🟠 警告", 3: "🔴 紧急"}.get(level, f"L{level}")
        lines.append(f"**{level_label}**")
        for a in by_level[level]:
            lines.append(f"**{a.name}({a.code})** — {a.detail}")
            lines.append("")
        lines.append("")

    lines.append("━━━━━━━━━━━━━━━━━━━━")
    import datetime
    now = datetime.datetime.now(
        datetime.timezone(datetime.timedelta(hours=8))
    )
    lines.append(f"*生成时间: {now.strftime('%Y-%m-%d %H:%M')}*")

    return "\n".join(lines).strip()
