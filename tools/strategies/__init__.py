"""技术面策略模块 — 移植自 Sequoia-X 的 4 个经典策略。

策略列表：
1. TurtleTrade  — 海龟突破（20日新高+成交额+阳线过滤）
2. MaVolume     — 均线金叉放量（MA5上穿MA20+放量1.5x）
3. HighTightFlag — 高窄旗形整理（强动量+极度收敛+缩量）
4. RpsBreakout  — 欧奈尔RPS突破（120日强度排位≥90%+创新高）

数据源：baostock 本地缓存（data/baostock_cache.db）
"""
from __future__ import annotations

from .base import BaseStrategy, StrategyResult
from .turtle_trade import TurtleTradeStrategy
from .ma_volume import MaVolumeStrategy
from .high_tight_flag import HighTightFlagStrategy
from .rps_breakout import RpsBreakoutStrategy

ALL_STRATEGIES: dict[str, type[BaseStrategy]] = {
    "turtle_trade": TurtleTradeStrategy,
    "ma_volume": MaVolumeStrategy,
    "high_tight_flag": HighTightFlagStrategy,
    "rps_breakout": RpsBreakoutStrategy,
}

__all__ = [
    "BaseStrategy", "StrategyResult",
    "TurtleTradeStrategy", "MaVolumeStrategy",
    "HighTightFlagStrategy", "RpsBreakoutStrategy",
    "ALL_STRATEGIES",
]
