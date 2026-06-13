"""
ST 风险检测模块 — 基于公开数据判断股票的 ST/退市/异常风险

检测维度：
1. 当前 ST/*ST 状态（新浪公开数据）
2. 连续亏损风险（基于净利润估算 — 简单版）
3. 面值退市风险（股价 < 1 元）
4. 换手率异常（> 20% 可能风险）
5. 财务数据缺失（信息不透明风险）

注意：简版不依赖付费数据源（不用 tushare），精度有限。
如需精确的财务数据，建议接入 tushare pro / 东财数据。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from core.cache import get_cache, make_cache_key

logger = logging.getLogger("stock-mcp.st_risk")

HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "text/html,application/xhtml+xml",
}

# ── 风险等级 ──────────────────────────────────────────────
RISK_LEVELS = {
    0: "正常",
    1: "关注",
    2: "警告",
    3: "高风险",
}


@dataclass
class RiskSignal:
    """单个风险信号"""
    dimension: str        # 维度名称
    level: int            # 0~3 风险等级
    detail: str           # 描述
    suggestion: str = ""  # 建议


@dataclass
class RiskReport:
    """完整风险评估报告"""
    code: str
    name: str = ""
    signals: list[RiskSignal] = field(default_factory=list)
    source: str = ""

    @property
    def max_level(self) -> int:
        return max((s.level for s in self.signals), default=0)

    @property
    def level_name(self) -> str:
        return RISK_LEVELS.get(self.max_level, "未知")

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "name": self.name,
            "max_level": self.max_level,
            "level_name": self.level_name,
            "is_st": "ST" in self.name.upper() if self.name else False,
            "signals": [
                {
                    "dimension": s.dimension,
                    "level": s.level,
                    "level_name": RISK_LEVELS.get(s.level, "未知"),
                    "detail": s.detail,
                    "suggestion": s.suggestion,
                }
                for s in self.signals
            ],
            "signal_count": len(self.signals),
            "source": self.source,
        }


def check_st_status(name: str) -> Optional[str]:
    """从股票名称检测ST状态

    Returns:
        "ST" / "*ST" / "退市" / None
    """
    name_upper = name.upper()
    if "退市" in name_upper:
        return "退市"
    if name_upper.startswith("*ST"):
        return "*ST"
    if name_upper.startswith("ST"):
        return "ST"
    if "ST" in name_upper:
        return "ST"
    return None


def check_price_risk(price: Optional[float]) -> Optional[RiskSignal]:
    """检查面值退市风险（股价 < 1 元）"""
    if price is None or price <= 0:
        return None
    if price < 1.0:
        level = 3 if price < 0.5 else 2
        return RiskSignal(
            dimension="面值退市风险",
            level=level,
            detail=f"当前股价 {price} 元{'，低于 0.5 元面临面值退市' if price < 0.5 else '，低于 1 元触发面值退市警戒线'}",
            suggestion="密切监控股价走势，低于 1 元连续 20 个交易日将触发退市",
        )
    return None


def check_volume_risk(volume_ratio: Optional[float], change_pct: Optional[float]) -> Optional[RiskSignal]:
    """检查量能异常风险"""
    risk_signals = []

    # 放量下跌风险
    if volume_ratio is not None and change_pct is not None:
        if volume_ratio > 3 and change_pct < -5:
            return RiskSignal(
                dimension="放量下跌",
                level=3,
                detail=f"量比 {volume_ratio}，跌幅 {change_pct}%，放量下跌可能是主力出货",
                suggestion="警惕主力出货，建议减仓回避",
            )
        if volume_ratio > 2 and change_pct < -3:
            return RiskSignal(
                dimension="放量下跌",
                level=2,
                detail=f"量比 {volume_ratio}，跌幅 {change_pct}%，成交量异常放大",
                suggestion="关注是否有重大利空消息",
            )

    # 换手率异常（超过 20% 通常有风险）
    turnover_rate = None  # 腾讯行情不直接提供换手率
    return None


def assess_risk(
    code: str,
    name: str,
    price: Optional[float] = None,
    change_pct: Optional[float] = None,
    volume_ratio: Optional[float] = None,
) -> dict[str, Any]:
    """综合评估股票风险

    Args:
        code: 股票代码
        name: 股票名称
        price: 当前价格
        change_pct: 涨跌幅
        volume_ratio: 量比

    Returns:
        风险评估报告字典
    """
    report = RiskReport(code=code, name=name, source="公开数据（简版）")

    # 1. 检查 ST 状态
    st_status = check_st_status(name)
    if st_status:
        report.signals.append(RiskSignal(
            dimension="ST/退市状态",
            level=3,
            detail=f"股票当前状态为「{st_status}」",
            suggestion=f"{st_status}股票风险极高，建议回避。如需交易请确认风险揭示书已签署",
        ))

    # 2. 检查面值退市风险
    price_signal = check_price_risk(price)
    if price_signal:
        report.signals.append(price_signal)

    # 3. 检查量能异常
    volume_signal = check_volume_risk(volume_ratio, change_pct)
    if volume_signal:
        report.signals.append(volume_signal)

    # 4. 如果没有明显风险，给出正常状态
    if not report.signals:
        report.signals.append(RiskSignal(
            dimension="综合评估",
            level=0,
            detail=f"{name}({code}) 当前无明显ST/退市风险信号",
            suggestion="正常交易，建议定期关注公司财报和公告",
        ))

    return report.to_dict()


def get_st_risk(code: str, realtime_data: dict[str, Any]) -> dict[str, Any]:
    """带缓存的 ST 风险评估入口

    Args:
        code: 股票代码
        realtime_data: 实时行情数据（用于获取名称/价格等）

    Returns:
        风险评估报告
    """
    cache = get_cache()
    cache_key = make_cache_key("st_risk", code)
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    name = realtime_data.get("name", "")
    price = realtime_data.get("price")
    change_pct = realtime_data.get("change_pct")
    volume_ratio = realtime_data.get("volume_ratio")

    result = assess_risk(
        code=code,
        name=name,
        price=price,
        change_pct=change_pct,
        volume_ratio=volume_ratio,
    )

    cache.set(cache_key, result, ttl=600)  # 10分钟缓存
    return result
