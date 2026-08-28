#!/usr/bin/env python3
"""
集成测试 — 漏斗 + AI 审计 + 信号反馈全流程

验证:
1. 漏斗 Pipeline 正常执行
2. AI 审计员（无 LLM 降级模式）正常工作
3. 信号状态机正确记录
4. 信号反馈闭环正确统计
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

_root = Path(__file__).parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from core.orchestrator import Pipeline
from core.funnel import (
    stage_basic_filter,
    stage_technical_multi_channel,
    stage_ranking,
)
from core.ai_auditor import AIAuditor, AuditResult
from core.signal_state import SignalTracker, SignalState
from core.signal_feedback import SignalFeedback

# 这两个函数在 run_funnel.py 中，需要直接导入
sys.path.insert(0, str(_root / "scripts"))
from run_funnel import _fetch_from_baostock_cache, _enrich_baostock_direct


def test_full_pipeline():
    """完整 Pipeline 测试"""
    print("=" * 60)
    print("Phase 2 集成测试 — 漏斗 + 审计 + 反馈")
    print("=" * 60)

    # ── Step 1: 漏斗 ──────────────────────────────────────
    print("\n[Step 1] Running funnel pipeline...")

    t0 = time.time()
    universe = _fetch_from_baostock_cache()
    print(f"  Fetched {len(universe)} stocks from baostock cache")

    _enrich_baostock_direct(universe)

    pipe = Pipeline()
    pipe.add_stage("basic_filter", stage_basic_filter)
    pipe.add_stage("technical_multi_channel", stage_technical_multi_channel)
    pipe.add_stage("ranking", stage_ranking)

    result = pipe.run(universe, {"min_amount": 0})  # 不限成交额（测试用）
    elapsed = time.time() - t0

    print(f"  Funnel completed in {elapsed:.2f}s")
    print(f"  Candidates: {len(result.candidates)}")
    for stage in result.stages:
        print(f"    {stage.name}: {stage.input_count} → {stage.output_count}")

    # ── Step 2: AI 审计 ───────────────────────────────────
    print("\n[Step 2] Running AI audit (no LLM mode)...")

    auditor = AIAuditor(llm_fn=None)  # 无 LLM，全 PASS
    audit_result = auditor.audit(result.candidates)

    print(f"  {audit_result.summary()}")
    assert audit_result.passed_count == len(result.candidates), "All should PASS"
    print("  ✓ All candidates passed (LLM unavailable mode)")

    # ── Step 3: 信号记录 ──────────────────────────────────
    print("\n[Step 3] Recording signals to state machine...")

    tracker = SignalTracker()
    tracker.expire_stale()

    recorded = 0
    for candidate in result.candidates:
        for ch in candidate.get("channels", []):
            tracker.record(
                code=candidate["code"],
                signal_type=ch,
                state=SignalState.DETECTED,
                key_level=candidate.get("price"),
            )
            recorded += 1

    stats = tracker.get_stats()
    print(f"  Recorded {recorded} signals")
    print(f"  Stats: {stats}")

    active = tracker.get_active_signals()
    print(f"  Active signals: {len(active)}")
    for sig in active[:5]:
        print(f"    {sig['code']} {sig['signal_type']} @ {sig['detected_at']}")

    # ── Step 4: 信号反馈 ──────────────────────────────────
    print("\n[Step 4] Testing signal feedback...")

    feedback = SignalFeedback()

    # 模拟一些历史结果（测试统计功能）
    test_outcomes = [
        ("000977", "trend", 37.0, 39.0, 5),      # win
        ("000725", "trend", 2.2, 2.1, 3),         # loss
        ("300033", "accumulation", 28.0, 29.5, 7), # win
        ("300059", "accumulation", 15.0, 14.5, 4), # loss
        ("600030", "accumulation", 1.35, 1.40, 6), # win
    ]

    for code, sig_type, entry, exit, days in test_outcomes:
        feedback.record_outcome(code, sig_type, entry, exit, days)

    # 查看统计
    trend_stats = feedback.compute_stats("trend")
    accum_stats = feedback.compute_stats("accumulation")

    print(f"  Trend stats: {trend_stats.to_dict()}")
    print(f"  Accumulation stats: {accum_stats.to_dict()}")

    # Shadow pool
    pool = feedback.get_shadow_pool()
    print(f"  Shadow pool: {len(pool)} signal types")
    for p in pool:
        print(f"    {p['signal_type']}: {p['status']} (win_rate={p['win_rate']:.1%})")

    # ── Step 5: 验证 ──────────────────────────────────────
    print("\n[Step 5] Verification...")

    # 验证信号状态机
    assert len(active) > 0, "Should have active signals"
    print(f"  ✓ Signal state machine: {len(active)} active signals")

    # 验证反馈闭环
    assert trend_stats.total_samples == 2, f"Expected 2 trend samples, got {trend_stats.total_samples}"
    assert accum_stats.total_samples == 3, f"Expected 3 accum samples, got {accum_stats.total_samples}"
    print(f"  ✓ Signal feedback: correct sample counts")

    # 验证审计
    assert audit_result.passed_count == len(result.candidates)
    print(f"  ✓ AI audit: all {len(result.candidates)} candidates passed")

    # ── 总结 ──────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("✅ Phase 2 集成测试通过!")
    print("=" * 60)
    print(f"  漏斗: {len(universe)} → {len(result.candidates)} candidates")
    print(f"  审计: {audit_result.passed_count} PASS, {audit_result.vetoed_count} VETO")
    print(f"  信号: {len(active)} active, {recorded} recorded")
    print(f"  反馈: {feedback.summary()}")

    return True


if __name__ == "__main__":
    try:
        success = test_full_pipeline()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
