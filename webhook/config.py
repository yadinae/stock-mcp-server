"""
Webhook 通知配置
================
管理持仓、规则、通知渠道的配置。
从 JSON 文件加载，支持运行时热更新。
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger("stock-mcp.webhook.config")

# ── 默认路径 ────────────────────────────────────────────────
DEFAULT_RULES_PATH = os.path.join(os.path.dirname(__file__), "alert_rules.json")
DEFAULT_STATE_PATH = os.path.join(
    os.path.dirname(__file__), ".alerter_state.json"
)


# ── 通知渠道配置 ─────────────────────────────────────────────

@dataclass
class FeishuConfig:
    """飞书群机器人 Webhook 配置"""
    webhook_url: str = ""               # 群机器人 Webhook URL
    app_id: str = ""                    # 飞书自建应用 App ID
    app_secret: str = ""                # 飞书自建应用 App Secret
    chat_id: str = ""                   # 群 ID（用 app 方式发送时需要）

    @property
    def enabled(self) -> bool:
        return bool(self.webhook_url or (self.app_id and self.app_secret))


@dataclass
class TelegramConfig:
    """Telegram Bot 配置"""
    bot_token: str = ""                 # Bot Token
    chat_id: str = ""                   # 目标 Chat ID

    @property
    def enabled(self) -> bool:
        return bool(self.bot_token and self.chat_id)


@dataclass
class NotifierConfig:
    """全局通知渠道配置"""
    feishu: FeishuConfig = field(default_factory=FeishuConfig)
    telegram: TelegramConfig = field(default_factory=TelegramConfig)
    enabled_channels: list[str] = field(default_factory=lambda: ["feishu"])

    @property
    def has_any_enabled(self) -> bool:
        if "feishu" in self.enabled_channels and self.feishu.enabled:
            return True
        if "telegram" in self.enabled_channels and self.telegram.enabled:
            return True
        return False


# ── 告警规则定义 ────────────────────────────────────────────

@dataclass
class Holding:
    """持仓定义"""
    code: str
    name: str = ""
    status: str = "持有"  # 持有/观察/已清仓


@dataclass
class PriceDropRule:
    """价格跌幅告警规则"""
    enabled: bool = True
    thresholds: list[float] = field(default_factory=lambda: [-3, -5, -8])
    # 百分比阈值列表，如 -3% → 提醒，-5% → 警告，-8% → 紧急


@dataclass
class VolumeSpikeRule:
    """量能异常告警规则"""
    enabled: bool = True
    volume_ratio_threshold: float = 3.0  # 量比 > 3.0
    change_pct_threshold: float = -3.0  # 跌幅 > 3%


@dataclass
class StRiskRule:
    """ST 风险异动告警规则"""
    enabled: bool = True
    min_level: int = 2  # level >= 2 (警告) 触发告警
    check_interval_minutes: int = 60  # 检查间隔


@dataclass
class MacdSignalRule:
    """MACD 金叉/死叉告警规则"""
    enabled: bool = True
    detect_golden_cross: bool = True
    detect_death_cross: bool = True


@dataclass
class RsiSignalRule:
    """RSI 超买/超卖告警规则"""
    enabled: bool = True
    oversold_threshold: float = 30.0   # RSI < 30 → 超卖
    overbought_threshold: float = 70.0  # RSI > 70 → 超买


@dataclass
class EtfSignalRule:
    """ETF 技术信号告警规则"""
    enabled: bool = True
    min_score: int = 70  # 评分 >= 70 推荐关注
    macd: MacdSignalRule = field(default_factory=MacdSignalRule)
    rsi: RsiSignalRule = field(default_factory=RsiSignalRule)


@dataclass
class AlertRules:
    """完整告警规则配置"""
    holdings: list[Holding] = field(default_factory=list)
    watchlist: list[Holding] = field(default_factory=list)  # 观察池
    etf_pool: list[Holding] = field(default_factory=list)   # ETF 雷达池
    price_drop: PriceDropRule = field(default_factory=PriceDropRule)
    volume_spike: VolumeSpikeRule = field(default_factory=VolumeSpikeRule)
    st_risk: StRiskRule = field(default_factory=StRiskRule)
    etf_signal: EtfSignalRule = field(default_factory=EtfSignalRule)
    check_interval_minutes: int = 15  # 全局检查间隔


# ── 工具函数 ────────────────────────────────────────────────

def load_rules(path: str = "") -> AlertRules:
    """从 JSON 文件加载告警规则配置"""
    path = path or DEFAULT_RULES_PATH
    if not os.path.exists(path):
        logger.warning("告警规则文件不存在: %s，使用默认配置", path)
        return _default_rules()

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return _dict_to_rules(data)
    except Exception as e:
        logger.error("加载告警规则失败: %s", e)
        return _default_rules()


def save_rules(rules: AlertRules, path: str = "") -> bool:
    """保存告警规则到 JSON 文件"""
    path = path or DEFAULT_RULES_PATH
    try:
        data = _rules_to_dict(rules)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        logger.error("保存告警规则失败: %s", e)
        return False


def load_notifier_config() -> NotifierConfig:
    """加载通知渠道配置（优先从环境变量读取）"""
    cfg = NotifierConfig()

    # 飞书配置
    cfg.feishu.webhook_url = os.environ.get("FEISHU_WEBHOOK_URL", "")
    cfg.feishu.app_id = os.environ.get("FEISHU_APP_ID", "")
    cfg.feishu.app_secret = os.environ.get("FEISHU_APP_SECRET", "")
    cfg.feishu.chat_id = os.environ.get(
        "FEISHU_STOCK_CHAT_ID",
        "oc_70aae2f0de3ae93698011ad34c5bee43"
    )

    # Telegram 配置
    cfg.telegram.bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    cfg.telegram.chat_id = os.environ.get("TELEGRAM_STOCK_CHAT_ID", "")

    # 启用渠道
    channels = os.environ.get("WEBHOOK_CHANNELS", "feishu").split(",")
    cfg.enabled_channels = [c.strip() for c in channels if c.strip()]

    return cfg


def _default_rules() -> AlertRules:
    """创建默认告警规则（基于已知持仓）"""
    return AlertRules(
        holdings=[
            Holding(code="159949", name="创业板50ETF华安"),
            Holding(code="512010", name="医药ETF易方达"),
            Holding(code="512660", name="军工ETF国泰"),
            Holding(code="510200", name="上证券商ETF汇安"),
        ],
        watchlist=[
            Holding(code="603310", name="巍华新材", status="观察"),
        ],
        etf_pool=[
            Holding(code="512480", name="半导体ETF国联安"),
            Holding(code="588000", name="科创50ETF华夏"),
            Holding(code="510300", name="沪深300ETF华泰柏瑞"),
            Holding(code="510050", name="上证50ETF华夏"),
            Holding(code="513100", name="纳指ETF国泰"),
            Holding(code="513050", name="中概互联网ETF易方达"),
            Holding(code="515030", name="新能源车ETF华夏"),
            Holding(code="159949", name="创业板50ETF华安"),
            Holding(code="512010", name="医药ETF易方达"),
            Holding(code="512660", name="军工ETF国泰"),
        ],
    )


def _dict_to_rules(data: dict) -> AlertRules:
    """将 JSON dict 转换为 AlertRules 对象"""
    rules = AlertRules()

    # 持仓
    for h in data.get("holdings", []):
        rules.holdings.append(Holding(
            code=h.get("code", ""),
            name=h.get("name", ""),
            status=h.get("status", "持有"),
        ))

    # 观察池
    for h in data.get("watchlist", []):
        rules.watchlist.append(Holding(
            code=h.get("code", ""),
            name=h.get("name", ""),
            status="观察",
        ))

    # ETF 池
    for h in data.get("etf_pool", []):
        rules.etf_pool.append(Holding(
            code=h.get("code", ""),
            name=h.get("name", ""),
        ))

    # 规则
    pd = data.get("price_drop", {})
    rules.price_drop = PriceDropRule(
        enabled=pd.get("enabled", True),
        thresholds=pd.get("thresholds", [-3, -5, -8]),
    )

    vs = data.get("volume_spike", {})
    rules.volume_spike = VolumeSpikeRule(
        enabled=vs.get("enabled", True),
        volume_ratio_threshold=vs.get("volume_ratio_threshold", 3.0),
        change_pct_threshold=vs.get("change_pct_threshold", -3.0),
    )

    sr = data.get("st_risk", {})
    rules.st_risk = StRiskRule(
        enabled=sr.get("enabled", True),
        min_level=sr.get("min_level", 2),
        check_interval_minutes=sr.get("check_interval_minutes", 60),
    )

    es = data.get("etf_signal", {})
    rules.etf_signal = EtfSignalRule(
        enabled=es.get("enabled", True),
        min_score=es.get("min_score", 70),
        macd=MacdSignalRule(
            enabled=es.get("macd", {}).get("enabled", True),
            detect_golden_cross=es.get("macd", {}).get("detect_golden_cross", True),
            detect_death_cross=es.get("macd", {}).get("detect_death_cross", True),
        ),
        rsi=RsiSignalRule(
            enabled=es.get("rsi", {}).get("enabled", True),
            oversold_threshold=es.get("rsi", {}).get("oversold_threshold", 30.0),
            overbought_threshold=es.get("rsi", {}).get("overbought_threshold", 70.0),
        ),
    )

    rules.check_interval_minutes = data.get("check_interval_minutes", 15)
    return rules


def _rules_to_dict(rules: AlertRules) -> dict:
    """将 AlertRules 对象转换为 JSON dict"""
    return {
        "holdings": [
            {"code": h.code, "name": h.name, "status": h.status}
            for h in rules.holdings
        ],
        "watchlist": [
            {"code": h.code, "name": h.name} for h in rules.watchlist
        ],
        "etf_pool": [
            {"code": h.code, "name": h.name} for h in rules.etf_pool
        ],
        "price_drop": {
            "enabled": rules.price_drop.enabled,
            "thresholds": rules.price_drop.thresholds,
        },
        "volume_spike": {
            "enabled": rules.volume_spike.enabled,
            "volume_ratio_threshold": rules.volume_spike.volume_ratio_threshold,
            "change_pct_threshold": rules.volume_spike.change_pct_threshold,
        },
        "st_risk": {
            "enabled": rules.st_risk.enabled,
            "min_level": rules.st_risk.min_level,
            "check_interval_minutes": rules.st_risk.check_interval_minutes,
        },
        "etf_signal": {
            "enabled": rules.etf_signal.enabled,
            "min_score": rules.etf_signal.min_score,
            "macd": {
                "enabled": rules.etf_signal.macd.enabled,
                "detect_golden_cross": rules.etf_signal.macd.detect_golden_cross,
                "detect_death_cross": rules.etf_signal.macd.detect_death_cross,
            },
            "rsi": {
                "enabled": rules.etf_signal.rsi.enabled,
                "oversold_threshold": rules.etf_signal.rsi.oversold_threshold,
                "overbought_threshold": rules.etf_signal.rsi.overbought_threshold,
            },
        },
        "check_interval_minutes": rules.check_interval_minutes,
    }
