"""缠论数据类型定义"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Direction(Enum):
    UP = "up"
    DOWN = "down"


class FXType(Enum):
    TOP = "top"       # 顶分型
    BOTTOM = "bottom"  # 底分型


class BCType(Enum):
    BI = "bi"           # 笔背驰
    PANZHENG = "pz"     # 盘整背驰
    QUSHI_UP = "qs_up"  # 趋势背驰(上)
    QUSHI_DOWN = "qs_down"  # 趋势背驰(下)


@dataclass
class Kline:
    """原始 K 线"""
    idx: int          # 在原始数据中的索引
    date: str
    open: float
    high: float
    low: float
    close: float
    volume: float = 0
    merged: bool = False  # 是否被合并过

    @property
    def typical(self) -> float:
        return (self.high + self.low + self.close) / 3


@dataclass
class CLKline:
    """缠论合并后的 K 线（经包含处理）"""
    idx: int
    date: str
    high: float
    low: float
    direction: Direction  # 合并方向（向上/向下）
    raw_start: int  # 对应原始 K 线起始索引
    raw_end: int    # 对应原始 K 线结束索引

    @property
    def typical(self) -> float:
        return (self.high + self.low + (self.high + self.low) / 2) / 3


@dataclass
class FX:
    """分型"""
    idx: int          # 在合并 K 线序列中的索引
    type: FXType
    date: str
    high: float
    low: float
    value: float     # 顶分型取 high，底分型取 low
    kline_idx: int   # 对应原始 K 线索引

    def __repr__(self) -> str:
        t = "顶" if self.type == FXType.TOP else "底"
        return f"FX({t} {self.date} h={self.high:.2f} l={self.low:.2f})"


@dataclass
class Bi:
    """笔 — 连接相邻异向分型"""
    idx: int
    start: FX
    end: FX
    direction: Direction
    high: float
    low: float
    confirmed: bool = True  # 是否已确认（后续出现反向笔）

    @property
    def bars(self) -> int:
        return abs(self.end.idx - self.start.idx)

    def __repr__(self) -> str:
        d = "↑" if self.direction == Direction.UP else "↓"
        return (f"Bi[{self.idx}] {d} {self.start.date}→{self.end.date} "
                f"h={self.high:.2f} l={self.low:.2f}")


@dataclass
class ZS:
    """中枢 — 至少3笔重叠区域"""
    idx: int
    zg: float    # 中枢上沿（区间内最高的低点）
    zd: float    # 中枢下沿（区间内最低的高点）
    gg: float    # 区间内最高价
    dd: float    # 区间内最低价
    lines: list[Bi] = field(default_factory=list)
    confirmed: bool = True  # 是否已脱离中枢

    @property
    def range(self) -> float:
        return self.zg - self.zd

    def __repr__(self) -> str:
        return (f"ZS[{self.idx}] zg={self.zg:.2f} zd={self.zd:.2f} "
                f"gg={self.gg:.2f} dd={self.dd:.2f} lines={len(self.lines)}")


@dataclass
class XD:
    """线段 — 比笔更大的走势单位"""
    idx: int
    start_bi: Bi
    end_bi: Bi
    direction: Direction
    high: float
    low: float

    def __repr__(self) -> str:
        d = "↑" if self.direction == Direction.UP else "↓"
        return (f"XD[{self.idx}] {d} {self.start_bi.start.date}→"
                f"{self.end_bi.end.date} h={self.high:.2f} l={self.low:.2f}")


@dataclass
class MMD:
    """买卖点信号"""
    type: str      # 1buy/2buy/3buy/1sell/2sell/3sell
    date: str
    price: float
    description: str
    kline_idx: int

    def __repr__(self) -> str:
        return f"MMD({self.type} {self.date} p={self.price:.2f})"


@dataclass
class BC:
    """背驰信号"""
    type: BCType
    date: str
    confirmed: bool
    description: str

    def __repr__(self) -> str:
        c = "✓" if self.confirmed else "…"
        return f"BC[{c}] {self.type.value}: {self.description}"


@dataclass
class ChanlunResult:
    """缠论完整分析结果"""
    code: str
    frequency: str
    raw_klines: int
    merged_klines: int
    fractals: list[FX]
    bis: list[Bi]
    zhongshus: list[ZS]
    xianduans: list[XD]
    signals: list[MMD]
    divergences: list[BC]

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "frequency": self.frequency,
            "summary": {
                "raw_klines": self.raw_klines,
                "merged_klines": self.merged_klines,
                "fractals": len(self.fractals),
                "bis": len(self.bis),
                "zhongshus": len(self.zhongshus),
                "xianduans": len(self.xianduans),
                "signals": len(self.signals),
                "divergences": len(self.divergences),
            },
            "bis": [self._bi_dict(b) for b in self.bis],
            "zhongshus": [self._zs_dict(z) for z in self.zhongshus],
            "signals": [self._sig_dict(s) for s in self.signals],
            "divergences": [self._bc_dict(d) for d in self.divergences],
        }

    @staticmethod
    def _bi_dict(b: Bi) -> dict:
        return {
            "idx": b.idx,
            "direction": b.direction.value,
            "start_date": b.start.date,
            "end_date": b.end.date,
            "high": round(b.high, 2),
            "low": round(b.low, 2),
            "bars": b.bars,
            "confirmed": b.confirmed,
        }

    @staticmethod
    def _zs_dict(z: ZS) -> dict:
        return {
            "idx": z.idx,
            "zg": round(z.zg, 2),
            "zd": round(z.zd, 2),
            "gg": round(z.gg, 2),
            "dd": round(z.dd, 2),
            "range": round(z.range, 2),
            "bi_count": len(z.lines),
            "confirmed": z.confirmed,
        }

    @staticmethod
    def _sig_dict(s: MMD) -> dict:
        return {
            "type": s.type,
            "date": s.date,
            "price": round(s.price, 2),
            "description": s.description,
        }

    @staticmethod
    def _bc_dict(d: BC) -> dict:
        return {
            "type": d.type.value,
            "date": d.date,
            "confirmed": d.confirmed,
            "description": d.description,
        }
