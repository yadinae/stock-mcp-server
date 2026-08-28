"""
消融测试框架 — 对比不同漏斗配置的筛选效果

借鉴 WyckoffTradingAgent 的消融测试设计：
- 每次只改变一个变量，对比效果
- 记录通过率、分布、候选重叠度
- 支持 A/B 配置对比

用法:
    from core.ablation import AblationRunner

    runner = AblationRunner()
    runner.add_config("baseline", {"min_amount": 5_000_000})
    runner.add_config("strict", {"min_amount": 50_000_000})
    runner.add_config("loose", {"min_amount": 1_000_000})

    results = runner.run()
    runner.print_report(results)
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("stock-mcp.ablation")


@dataclass
class AblationConfig:
    """消融测试配置"""
    name: str
    context: dict = field(default_factory=dict)
    stages: Optional[List[str]] = None  # None = 使用默认 stages


@dataclass
class AblationResult:
    """单次消融结果"""
    config_name: str
    input_count: int
    output_count: int
    pass_rate: float
    channel_distribution: Dict[str, int]
    candidate_codes: List[str]
    duration_ms: int
    stages_run: List[str]


@dataclass
class AblationReport:
    """消融测试报告"""
    results: List[AblationResult]
    baseline_name: str = "baseline"

    def print_report(self):
        """打印对比报告"""
        print("\n" + "=" * 70)
        print("消融测试报告")
        print("=" * 70)

        # 表头
        header = f"{'配置':<20} {'输入':>6} {'输出':>6} {'通过率':>8} {'耗时':>8}"
        print(header)
        print("-" * 70)

        baseline_candidates = set()
        for r in self.results:
            if r.config_name == self.baseline_name:
                baseline_candidates = set(r.candidate_codes)

            rate = f"{r.pass_rate:.1%}" if r.pass_rate else "N/A"
            print(f"{r.config_name:<20} {r.input_count:>6} {r.output_count:>6} {rate:>8} {r.duration_ms:>6}ms")

        # 候选重叠度
        if baseline_candidates:
            print(f"\n与 baseline ({self.baseline_name}) 的重叠度:")
            for r in self.results:
                if r.config_name != self.baseline_name:
                    current = set(r.candidate_codes)
                    overlap = len(baseline_candidates & current)
                    total = len(baseline_candidates | current)
                    jaccard = overlap / total if total > 0 else 0
                    print(f"  {r.config_name}: {overlap}/{total} 重叠 (Jaccard={jaccard:.2%})")

        # 通道分布对比
        print(f"\n通道分布:")
        for r in self.results:
            dist_str = ", ".join(f"{k}:{v}" for k, v in sorted(r.channel_distribution.items()))
            print(f"  {r.config_name}: {dist_str}")

        print("=" * 70)


class AblationRunner:
    """
    消融测试运行器

    Args:
        fetch_fn: 获取全市场数据的函数 () -> List[dict]
        enrich_fn: 数据增强函数 (List[dict]) -> List[dict]
    """

    def __init__(
        self,
        fetch_fn: Optional[Callable[[], List[dict]]] = None,
        enrich_fn: Optional[Callable[[List[dict]], List[dict]]] = None,
    ):
        self.fetch_fn = fetch_fn
        self.enrich_fn = enrich_fn
        self._configs: List[AblationConfig] = []
        self._universe: Optional[List[dict]] = None

    def add_config(self, name: str, context: Optional[dict] = None, stages: Optional[List[str]] = None):
        """添加消融配置"""
        self._configs.append(AblationConfig(name=name, context=context or {}, stages=stages))
        return self

    def _get_universe(self) -> List[dict]:
        """获取并缓存全市场数据"""
        if self._universe is None:
            if self.fetch_fn:
                self._universe = self.fetch_fn()
            else:
                # 默认从 baostock 缓存获取
                from scripts.run_funnel import _fetch_from_baostock_cache
                self._universe = _fetch_from_baostock_cache()

            if self.enrich_fn:
                self._universe = self.enrich_fn(self._universe)
            else:
                from scripts.run_funnel import _enrich_baostock_direct
                _enrich_baostock_direct(self._universe)

        return self._universe

    def run(self, baseline: str = "baseline") -> AblationReport:
        """
        运行所有消融配置

        Args:
            baseline: 基准配置名称（用于计算重叠度）
        """
        from core.funnel import (
            stage_basic_filter,
            stage_technical_multi_channel,
            stage_fund_flow,
            stage_fundamental,
            stage_ranking,
        )

        # 默认 Stage 映射
        stage_map = {
            "basic_filter": stage_basic_filter,
            "technical": stage_technical_multi_channel,
            "fund_flow": stage_fund_flow,
            "fundamental": stage_fundamental,
            "ranking": stage_ranking,
        }

        # 默认 stages
        default_stages = ["basic_filter", "technical", "ranking"]

        universe = self._get_universe()
        results = []

        for config in self._configs:
            t0 = time.time()
            stage_names = config.stages or default_stages

            current = list(universe)  # 深拷贝
            for stage_name in stage_names:
                stage_fn = stage_map.get(stage_name)
                if stage_fn:
                    current = stage_fn(current, config.context)

            # 统计通道分布
            channel_dist: Dict[str, int] = {}
            for s in current:
                for ch in s.get("channels", []):
                    channel_dist[ch] = channel_dist.get(ch, 0) + 1

            elapsed = int((time.time() - t0) * 1000)

            result = AblationResult(
                config_name=config.name,
                input_count=len(universe),
                output_count=len(current),
                pass_rate=len(current) / len(universe) if universe else 0,
                channel_distribution=channel_dist,
                candidate_codes=[s.get("code", "") for s in current],
                duration_ms=elapsed,
                stages_run=stage_names,
            )
            results.append(result)
            logger.info(
                "[%s] %d → %d (%dms)", config.name, len(universe), len(current), elapsed,
            )

        return AblationReport(results=results, baseline_name=baseline)

    def compare_channels(self, channel_name: str) -> Dict[str, int]:
        """对比不同配置下某通道的通过数"""
        report = self.run()
        return {r.config_name: r.channel_distribution.get(channel_name, 0) for r in report.results}
