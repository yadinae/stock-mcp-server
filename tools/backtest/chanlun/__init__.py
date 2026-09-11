"""缠论（ChanLun）技术分析模块

基于缠论理论实现 K 线合并、分型识别、笔/中枢/买卖点/背驰计算。

核心 API::

    from tools.backtest.chanlun import ChanlunAnalyser

    analyser = ChanlunAnalyser(code="000001", frequency="DAILY")
    result = analyser.analyse(records)
    print(result.to_dict())
"""
from .types import (  # noqa: F401
    ChanlunResult,
    BC,
    Bi as BI,
    FX,
    MMD,
    XD,
    ZS,
    BCType,
    CLKline,
    Direction,
    FXType,
    Kline,
)
from .analyser import ChanlunAnalyser  # noqa: F401

__all__ = [
    "ChanlunAnalyser",
    "ChanlunResult",
    "BC",
    "BI",
    "FX",
    "MMD",
    "XD",
    "ZS",
    "BCType",
    "CLKline",
    "Direction",
    "FXType",
    "Kline",
]
