"""
Prompt 版本管理 + 评分存储 — Autoresearch 基础设施

灵感来源：ATLAS (General Intelligence Capital, https://github.com/chrisworsey55/atlas-gic) 的 autoresearch 机制
核心思想：prompt 是权重，质量评分是损失函数，版本控制用 git-like 语义

存储结构 (prompt_store.json):
{
  "prompts": {
    "bull_researcher": {
      "current_version": "v1.2",
      "versions": {
        "v1.0": {"template": "...", "created_at": "...", "scores": [...]},
        "v1.1": {"template": "...", "created_at": "...", "scores": [...]},
        "v1.2": {"template": "...", "created_at": "...", "scores": [...]}
      }
    }
  },
  "run_log": [
    {"timestamp": "...", "stock": "...", "scores": {"bull": 78, "bear": 82, ...}}
  ]
}
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Optional

STORE_PATH = Path(__file__).parent.parent.parent / "data" / "prompt_store.json"

# ── 默认 prompt 模板（v1.0 基线）──

DEFAULT_PROMPTS = {
    "bull_researcher": {
        "template": """你是一名看多研究员。基于以下客观事实底稿，为股票 {code} ({name}) 做多头分析。

## 事实底稿
{dossier}

## 要求
1. 列出3-5个核心看多论点，每个论点必须标明依据的数据来源
2. 论点按置信度从高到低排列
3. 没有数据支撑的论点必须标注「⚠️ 无数据支撑」
4. 分析逻辑链必须清晰：数据 → 掐理 → 结论
5. 总字数控制在800-1200字""",
        "description": "多头研究员 — 基于事实底稿做多头分析",
    },
    "bear_researcher": {
        "template": """你是一名看空研究员。基于以下客观事实底稿，为股票 {code} ({name}) 做空头分析。

## 事实底稿
{dossier}

## 要求
1. 列出3-5个核心看空论点，每个论点必须标明依据的数据来源
2. 论点按风险严重度从高到低排列
3. 没有数据支撑的论点必须标注「⚠️ 无数据支撑」
4. 分析逻辑链必须清晰：数据 → 推理 → 结论
5. 总字数控制在800-1200字""",
        "description": "空头研究员 — 基于事实底稿做空头分析",
    },
    "cross_examination": {
        "template": """你是一名交叉审查员。基于多方和空方的分析，逐条审查。

## 多方论点
{bull_points}

## 空方论点
{bear_points}

## 事实底稿
{dossier}

## 要求
1. 逐条回应：承认对方合理之处，指出数据错误或逻辑漏洞
2. 标注「✅ 承认」「❌ 反驳」「⚠️ 数据不足」
3. 总字数控制在600-800字""",
        "description": "交叉审查员 — 逐条审查多空论点",
    },
    "moderator": {
        "template": """你是一名中立主持人。基于多空双方的分析，做最终归纳。

## 多方立场
{bull_analysis}

## 空方立场
{bear_analysis}

## 交叉反驳
{cross_examination}

## 事实底稿
{dossier}

## 要求 (严格遵守)
1. **不裁决谁对谁错**, 不给评级或倾向
2. 列出双方共识点
3. 列出真正分歧点(是数据不足还是解读不同?)
4. 给出验证清单(要确认哪些数据才能判断)
5. 标注数据缺口(哪些关键数据缺失)
6. **不输出买卖结论**
7. 总字数控制在500-800字""",
        "description": "中立主持人 — 归纳共识与分歧",
    },
}


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())


class PromptStore:
    """Prompt 版本管理器"""

    def __init__(self, path: Optional[Path] = None):
        self.path = path or STORE_PATH
        self._data = self._load()

    def _load(self) -> dict:
        if self.path.exists():
            try:
                return json.loads(self.path.read_text())
            except Exception:
                return {"prompts": {}, "run_log": []}
        return {"prompts": {}, "run_log": []}

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self._data, ensure_ascii=False, indent=2))

    # ── Prompt 管理 ──

    def get_prompt(self, role: str) -> str:
        """获取当前版本的 prompt 模板"""
        entry = self._data["prompts"].get(role)
        if not entry:
            # 初始化默认版本
            self.init_prompt(role)
            entry = self._data["prompts"][role]
        ver = entry["current_version"]
        return entry["versions"][ver]["template"]

    def init_prompt(self, role: str, template: Optional[str] = None):
        """初始化一个 prompt 角色（如果不存在）"""
        if role in self._data["prompts"]:
            return
        default = DEFAULT_PROMPTS.get(role, {})
        tpl = template or default.get("template", "")
        self._data["prompts"][role] = {
            "current_version": "v1.0",
            "description": default.get("description", role),
            "versions": {
                "v1.0": {
                    "template": tpl,
                    "created_at": _now_iso(),
                    "scores": [],
                    "avg_score": None,
                }
            },
        }
        self._save()

    def record_score(self, role: str, score: float, stock: str = "", meta: Optional[dict] = None):
        """记录一次评分到当前版本"""
        entry = self._data["prompts"].get(role)
        if not entry:
            return
        ver = entry["current_version"]
        version_data = entry["versions"][ver]
        version_data["scores"].append({
            "score": score,
            "stock": stock,
            "timestamp": _now_iso(),
            "meta": meta or {},
        })
        # 更新均分
        scores = [s["score"] for s in version_data["scores"]]
        version_data["avg_score"] = round(sum(scores) / len(scores), 1) if scores else None
        self._save()

    def new_version(self, role: str, template: str, reason: str = "") -> str:
        """创建新版本（自增版本号）"""
        entry = self._data["prompts"].get(role)
        if not entry:
            self.init_prompt(role)
            entry = self._data["prompts"][role]

        # 解析当前版本号 → 自增
        cur = entry["current_version"]  # e.g. "v1.2"
        try:
            major, minor = cur.replace("v", "").split(".")
            new_ver = f"v{major}.{int(minor) + 1}"
        except ValueError:
            new_ver = "v2.0"

        entry["versions"][new_ver] = {
            "template": template,
            "created_at": _now_iso(),
            "reason": reason,
            "scores": [],
            "avg_score": None,
        }
        entry["current_version"] = new_ver
        self._save()
        return new_ver

    def rollback(self, role: str) -> Optional[str]:
        """回滚到上一个版本"""
        entry = self._data["prompts"].get(role)
        if not entry:
            return None
        versions = list(entry["versions"].keys())
        cur = entry["current_version"]
        if cur == versions[0]:
            return None  # 已是最早的版本
        idx = versions.index(cur)
        prev = versions[idx - 1]
        entry["current_version"] = prev
        self._save()
        return prev

    def get_stats(self, role: Optional[str] = None) -> dict:
        """获取评分统计"""
        if role:
            entry = self._data["prompts"].get(role)
            if not entry:
                return {}
            cur = entry["current_version"]
            vd = entry["versions"][cur]
            return {
                "role": role,
                "version": cur,
                "avg_score": vd["avg_score"],
                "total_runs": len(vd["scores"]),
                "description": entry.get("description", ""),
            }
        # 全部角色
        stats = {}
        for r in self._data["prompts"]:
            stats[r] = self.get_stats(r)
        return stats

    def get_worst_role(self) -> Optional[str]:
        """找出评分最低的角色"""
        worst = None
        worst_score = float("inf")
        for role in self._data["prompts"]:
            entry = self._data["prompts"][role]
            ver = entry["current_version"]
            avg = entry["versions"][ver].get("avg_score")
            if avg is not None and avg < worst_score:
                worst_score = avg
                worst = role
        return worst

    def log_run(self, stock: str, scores: dict):
        """记录一次完整的辩论运行"""
        self._data.setdefault("run_log", []).append({
            "timestamp": _now_iso(),
            "stock": stock,
            "scores": scores,
        })
        # 保留最近 200 条
        if len(self._data["run_log"]) > 200:
            self._data["run_log"] = self._data["run_log"][-200:]
        self._save()
