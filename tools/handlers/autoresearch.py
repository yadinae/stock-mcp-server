"""
Autoresearch 引擎 — Prompt 自动优化循环

灵感来源：ATLAS (General Intelligence Capital, https://github.com/chrisworsey55/atlas-gic) 的 autoresearch 机制
核心循环：
  1. 识别评分最低的 prompt 角色
  2. 分析最近 N 次运行的失败模式
  3. 用 LLM 生成针对性改进
  4. 替换 prompt → 跑测试 → 对比评分
  5. 保留（评分提升）或回滚（评分下降）

使用方式：
  from tools.handlers.autoresearch import AutoresearchEngine
  engine = AutoresearchEngine()
  result = engine.run_cycle()  # 执行一个完整优化循环
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Optional

from tools.handlers.prompt_store import PromptStore, DEFAULT_PROMPTS

try:
    from tools.handlers.debate import agnes_llm_call
    HAS_LLM = True
except ImportError:
    HAS_LLM = False

# ── 配置 ──

MIN_RUNS_FOR_OPTIMIZATION = 3   # 至少运行 N 次才开始优化
SCORE_IMPROVEMENT_THRESHOLD = 2  # 评分提升至少 N 分才保留新版本
MAX_VERSIONS = 10                # 每个角色最多保留 N 个版本
TEST_STOCKS = ["600519", "000001", "300750"]  # 测试用标的

# ── 改进生成 Prompt ──

IMPROVE_PROMPT = """你是一名 prompt 优化专家。以下是一个投研辩论 Agent 的 prompt，需要你改进它。

## 当前 Prompt（角色：{role_name}）
```
{current_prompt}
```

## 最近运行数据
- 平均评分：{avg_score}/100
- 运行次数：{total_runs}
- 最近评分趋势：{score_trend}

## 最近的评审发现（需要改进的问题）
{recent_issues}

## 改进目标
1. 提升分析质量（评分目标：>{target_score}）
2. 保持原有格式和输出结构不变
3. 只修改 prompt 文本，不改变变量占位符（{{code}}, {{name}}, {{dossier}} 等）

## 改进策略（选择 1-2 个）
- 增加领域知识约束（如 A 股特有的量价关系、板块联动）
- 强化逻辑链要求（数据→推理→结论 的完整性）
- 增加反模式警告（避免模糊表述、避免过度推断）
- 优化论点结构（更清晰的分层、更强的证据要求）
- 增加市场语境感知（牛熊市、震荡市的差异化分析）

## 输出要求
直接输出改进后的完整 prompt 文本，不要解释、不要前缀、不要 markdown 代码块。
保留所有 {{变量}} 占位符不变。"""

ANALYZE_PROMPT = """分析以下投研辩论 Agent 最近的运行问题，提取需要改进的关键点。

## 角色
{role_name}

## 最近 {n} 次运行的评审发现
{all_issues}

## 输出格式（JSON）
{{
  "top_issues": ["问题1", "问题2", "问题3"],
  "improvement_direction": "最值得改进的方向",
  "specific_suggestions": ["具体建议1", "具体建议2"]
}}

只输出 JSON，不要解释。"""


class AutoresearchEngine:
    """Autoresearch 自动优化引擎"""

    def __init__(self, store: Optional[PromptStore] = None):
        self.store = store or PromptStore()

    def analyze_performance(self, role: str, n_recent: int = 10) -> dict:
        """分析某个角色的最近表现"""
        stats = self.store.get_stats(role)
        if not stats or stats.get("total_runs", 0) < 2:
            return {"status": "insufficient_data", "runs": stats.get("total_runs", 0)}

        # 从 run_log 提取该角色的最近评审发现
        run_log = self.store._data.get("run_log", [])
        recent_issues = []
        for entry in run_log[-n_recent:]:
            meta = entry.get("scores", {})
            if isinstance(meta, dict) and role in meta:
                role_data = meta[role]
                if isinstance(role_data, dict):
                    issues = role_data.get("findings", [])
                    recent_issues.extend(issues)

        # 评分趋势
        entry = self.store._data["prompts"].get(role, {})
        ver = entry.get("current_version", "v1.0")
        scores = entry.get("versions", {}).get(ver, {}).get("scores", [])
        recent_scores = [s["score"] for s in scores[-n_recent:]]
        score_trend = "→".join(str(int(s)) for s in recent_scores[-5:]) if recent_scores else "N/A"

        return {
            "status": "ok",
            "stats": stats,
            "recent_issues": recent_issues[:10],
            "score_trend": score_trend,
            "recent_scores": recent_scores,
        }

    def generate_improvement(self, role: str) -> Optional[str]:
        """用 LLM 生成 prompt 改进"""
        if not HAS_LLM:
            return None

        analysis = self.analyze_performance(role)
        if analysis["status"] != "ok":
            return None

        current_prompt = self.store.get_prompt(role)
        stats = analysis["stats"]
        issues_text = "\n".join(
            f"- [{f.get('severity', '?')}] {f.get('issue', '?')}: {f.get('suggestion', '')}"
            for f in analysis["recent_issues"]
        ) or "暂无具体评审发现"

        prompt = IMPROVE_PROMPT.format(
            role_name=stats.get("description", role),
            current_prompt=current_prompt,
            avg_score=stats.get("avg_score", "N/A"),
            total_runs=stats.get("total_runs", 0),
            score_trend=analysis["score_trend"],
            recent_issues=issues_text,
            target_score=min((stats.get("avg_score") or 50) + 10, 90),
        )

        try:
            improved = agnes_llm_call(
                prompt,
                system_prompt="你是 prompt 优化专家。直接输出改进后的 prompt 文本。",
                max_tokens=2048,
                temperature=0.3,
            )
            if improved and len(improved.strip()) > 50:
                return improved.strip()
        except Exception as e:
            print(f"  ⚠️ LLM 改进生成失败: {e}")
        return None

    def test_prompt(self, role: str, new_template: str, test_stocks: Optional[list] = None) -> float:
        """用测试标的评估新 prompt 的效果"""
        # 临时替换 prompt
        old_ver = self.store._data["prompts"][role]["current_version"]
        new_ver = self.store.new_version(role, new_template, reason="autoresearch test")

        scores = []
        stocks = test_stocks or TEST_STOCKS[:1]  # 默认只测 1 只（节省 token）

        try:
            from tools.handlers.debate import _run_debate
            for code in stocks:
                try:
                    result = _run_debate(code, rounds=0)  # rounds=0 只做各自陈述，快速测试
                    # 评估辩论质量
                    bull = result.get("steps", {}).get("bull", "")
                    bear = result.get("steps", {}).get("bear", "")
                    score = self._evaluate_debate(bull, bear)
                    scores.append(score)
                except Exception as e:
                    print(f"  ⚠️ 测试 {code} 失败: {e}")
        finally:
            # 恢复原版本（或保留新版本，由调用方决定）
            pass

        avg = sum(scores) / len(scores) if scores else 0
        return avg

    def _evaluate_debate(self, bull: str, bear: str) -> float:
        """简单评估辩论质量（不调用 LLM，纯规则）"""
        score = 50.0  # 基础分

        # 论点数量
        bull_points = len([l for l in bull.split("\n") if l.strip() and len(l.strip()) > 10])
        bear_points = len([l for l in bear.split("\n") if l.strip() and len(l.strip()) > 10])
        if bull_points >= 3:
            score += 10
        if bear_points >= 3:
            score += 10

        # 数据引用
        if "数据来源" in bull or "数据" in bull:
            score += 5
        if "数据来源" in bear or "数据" in bear:
            score += 5

        # 逻辑链
        if "推理" in bull or "逻辑" in bull or "→" in bull:
            score += 5
        if "推理" in bear or "逻辑" in bear or "→" in bear:
            score += 5

        # 长度合理性（800-1200字）
        if 400 <= len(bull) <= 3000:
            score += 5
        if 400 <= len(bear) <= 3000:
            score += 5

        # 无数据标注
        if "⚠️ 无数据" in bull:
            score += 3
        if "⚠️ 无数据" in bear:
            score += 3

        return min(score, 100)

    def run_cycle(self, auto_apply: bool = False) -> dict:
        """执行一个完整的 autoresearch 优化循环

        Args:
            auto_apply: True=自动应用改进; False=只建议不自动替换

        Returns:
            优化结果摘要
        """
        result = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "actions": [],
            "status": "ok",
        }

        # 1. 找出最差角色
        worst = self.store.get_worst_role()
        if not worst:
            result["status"] = "no_data"
            result["message"] = "无评分数据，无法优化"
            return result

        analysis = self.analyze_performance(worst)
        if analysis["status"] != "ok":
            result["status"] = "insufficient_data"
            result["message"] = f"{worst} 数据不足（{analysis.get('runs', 0)} 次运行）"
            return result

        stats = analysis["stats"]
        result["target_role"] = worst
        result["current_score"] = stats.get("avg_score")
        result["current_version"] = stats.get("version")

        # 2. 检查版本数限制
        ver_count = len(self.store._data["prompts"].get(worst, {}).get("versions", {}))
        if ver_count >= MAX_VERSIONS:
            result["actions"].append(f"版本数已达上限 ({ver_count}/{MAX_VERSIONS})，跳过优化")
            return result

        # 3. 生成改进
        print(f"🔍 分析 {worst} (v{stats.get('version', '?')}, avg={stats.get('avg_score', 'N/A')})")
        improved = self.generate_improvement(worst)
        if not improved:
            result["status"] = "improvement_generation_failed"
            result["message"] = "LLM 未能生成改进"
            return result

        result["actions"].append(f"生成改进 prompt ({len(improved)} chars)")

        if not auto_apply:
            result["actions"].append("auto_apply=False，仅建议不自动替换")
            result["improved_prompt_preview"] = improved[:200] + "..."
            return result

        # 4. 测试新 prompt
        print(f"🧪 测试新 prompt...")
        old_ver = self.store._data["prompts"][worst]["current_version"]
        old_avg = stats.get("avg_score", 50)
        test_score = self.test_prompt(worst, improved)

        result["test_score"] = test_score
        result["old_avg"] = old_avg

        # 5. 保留或回滚
        if test_score > old_avg + SCORE_IMPROVEMENT_THRESHOLD:
            result["actions"].append(f"✅ 保留新版本 (test={test_score:.0f} > old={old_avg:.0f}+{SCORE_IMPROVEMENT_THRESHOLD})")
            result["new_version"] = self.store._data["prompts"][worst]["current_version"]
        else:
            # 回滚
            prev = self.store.rollback(worst)
            result["actions"].append(f"↩️ 回滚到 {prev} (test={test_score:.0f} ≤ old={old_avg:.0f}+{SCORE_IMPROVEMENT_THRESHOLD})")
            result["rolled_back_to"] = prev

        return result

    def report(self) -> str:
        """生成可读的优化报告"""
        lines = ["## Autoresearch 状态报告\n"]
        stats = self.store.get_stats()
        for role, s in stats.items():
            if s:
                lines.append(f"- **{role}** ({s.get('version', '?')}): avg={s.get('avg_score', 'N/A')}, runs={s.get('total_runs', 0)}")
        lines.append(f"\n最差角色: {self.store.get_worst_role() or 'N/A'}")
        return "\n".join(lines)
