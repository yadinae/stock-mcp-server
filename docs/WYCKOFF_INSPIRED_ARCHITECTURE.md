# 借鉴 WyckoffTradingAgent 的架构方案 v3（MVP）

## 背景

从 WyckoffTradingAgent 提炼 5 个可借鉴的设计思想，融入 stock-mcp-server。
v3 吸收 3 位 Agnes AI 判别者的评审反馈，大幅简化为 **1人团队可交付的 MVP**。

### v2 → v3 关键变更
| v2 | v3 | 原因 |
|----|----|----|
| 5 个 Stage | **2 个核心 Stage** | 现实检验者 P0：团队规模不匹配 |
| 自研调度引擎 | **Hermes cron** | 现实检验者 P2：重复造轮子 |
| 同步 AI 审计 | **异步可选** | 现实检验者 P0：单点延迟 |
| 13 数据源全覆盖 | **MVP 只用腾讯+东财** | 现实检验者 P1：组合爆炸 |
| 全量代码 | **MVP + 扩展点** | 架构评审者 P0：代码截断 |

---

## 设计总览

```
┌─────────────────────────────────────────────────┐
│              Orchestrator (编排层)                │
│  core/orchestrator.py                            │
│  串联各组件，管理生命周期                          │
└───────────────┬─────────────────────────────────┘
                │
    ┌───────────┼───────────┐
    ▼           ▼           ▼
┌────────┐ ┌────────┐ ┌────────┐
│ Funnel │ │ Signal │ │Feedback│
│Engine  │ │Tracker │ │ Loop   │
│(2 Stage)│ │(SQLite)│ │(SQLite)│
└────┬───┘ └────┬───┘ └────┬───┘
     │          │          │
     ▼          ▼          ▼
┌─────────────────────────────────────────────────┐
│              Core Infrastructure                 │
│  core/store.py (SQLite WAL) · core/helpers.py   │
│  core/cache.py · core/resilience.py             │
└─────────────────────────────────────────────────┘
                │
    ┌───────────┼───────────┐
    ▼           ▼           ▼
┌────────┐ ┌────────┐ ┌────────┐
│ 腾讯   │ │ 东财   │ │ Yahoo  │
│ 行情   │ │ 行情   │ │(Phase2)│
└────────┘ └────────┘ └────────┘
```

---

## 核心组件实现

### 1. Orchestrator — 编排层（新增）

```python
# core/orchestrator.py

from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from enum import Enum
import logging
import time

logger = logging.getLogger("stock-mcp.orchestrator")

class PipelinePhase(Enum):
    FUNNEL = "funnel"           # 漏斗筛选
    SIGNAL_CHECK = "signal_check"  # 信号存活检查
    AUDIT = "audit"             # AI 审计（可选）
    FEEDBACK = "feedback"       # 反馈记录

@dataclass
class PipelineResult:
    phase: PipelinePhase
    status: str                 # "ok" | "error" | "skipped"
    input_count: int = 0
    output_count: int = 0
    duration_ms: int = 0
    error: Optional[str] = None
    data: Any = None

@dataclass
class OrchestratorResult:
    """一次完整执行的结果"""
    runs: List[PipelineResult] = field(default_factory=list)
    candidates: List[dict] = field(default_factory=list)
    total_ms: int = 0
    
    def summary(self) -> dict:
        return {
            "phases": len(self.runs),
            "candidates": len(self.candidates),
            "total_ms": self.total_ms,
            "errors": [r.error for r in self.runs if r.error],
        }

class Orchestrator:
    """
    编排层 — 串联各组件，管理生命周期
    
    职责：
    1. 按顺序执行 Pipeline 各阶段
    2. 记录每个阶段的耗时和状态
    3. 异常降级：某阶段失败不影响后续
    4. 提供统一的结果格式
    """
    
    def __init__(self, config: dict = None):
        self.config = config or {}
        self._stages: List[tuple] = []
    
    def add_stage(self, phase: PipelinePhase, fn, name: str = ""):
        """注册阶段"""
        self._stages.append((phase, fn, name or phase.value))
        return self
    
    def run(self, universe: List[dict], context: dict = None) -> OrchestratorResult:
        """执行完整 Pipeline"""
        result = OrchestratorResult()
        ctx = context or {}
        current = universe
        start = time.time()
        
        for phase, fn, name in self._stages:
            phase_start = time.time()
            input_count = len(current)
            
            try:
                current = fn(current, ctx)
                result.runs.append(PipelineResult(
                    phase=phase, status="ok",
                    input_count=input_count,
                    output_count=len(current),
                    duration_ms=int((time.time() - phase_start) * 1000),
                    data=current,
                ))
                logger.info(f"[{name}] {input_count} → {len(current)} ({result.runs[-1].duration_ms}ms)")
            except Exception as e:
                logger.error(f"[{name}] FAILED: {e}")
                result.runs.append(PipelineResult(
                    phase=phase, status="error",
                    input_count=input_count, output_count=0,
                    duration_ms=int((time.time() - phase_start) * 1000),
                    error=str(e),
                ))
                # 降级：失败阶段清空 candidates，短路后续
                current = []
        
        result.candidates = current
        result.total_ms = int((time.time() - start) * 1000)
        return result
```

### 2. 漏斗引擎（MVP 2 Stage）

```python
# core/funnel.py

from __future__ import annotations
from typing import List, Dict, Any
import logging

logger = logging.getLogger("stock-mcp.funnel")

# ── Stage 1: 基础筛选 ──────────────────────────────────────

def stage_basic_filter(stocks: List[dict], ctx: dict) -> List[dict]:
    """
    基础筛选：流动性 + ST排除 + 停牌排除
    
    输入: 全市场股票列表 [{code, name, close, volume, amount, ...}]
    输出: 通过基础筛选的股票列表
    """
    from core.helpers import is_st_stock, is_suspended
    
    min_amount = ctx.get("min_amount", 5_000_000)  # 默认500万日均成交额
    results = []
    
    for s in stocks:
        code = s.get("code", "")
        
        # ST/退市排除
        if is_st_stock(code):
            continue
        
        # 停牌排除
        if is_suspended(code):
            continue
        
        # 流动性过滤
        if s.get("amount", 0) < min_amount:
            continue
        
        results.append(s)
    
    logger.info(f"Basic filter: {len(stocks)} → {len(results)}")
    return results


# ── Stage 2: 技术面多通道筛选 ──────────────────────────────

def stage_technical_multi_channel(stocks: List[dict], ctx: dict) -> List[dict]:
    """
    技术面多通道筛选（借鉴 Wyckoff 八通道思想）
    
    不同市场位置用不同策略：
    - 趋势通道：MA50 > MA200 + 动量达标
    - 反转通道：超跌反弹 + MACD 底背离
    - 突破通道：放量突破 + 布林带扩张
    - 吸筹通道：底部缩量 + 量能萎缩
    
    输入: 基础筛选后的股票列表
    输出: 至少一个通道通过的股票列表
    """
    results = []
    
    for s in stocks:
        channels_passed = []
        
        # 趋势通道
        if _check_trend_channel(s):
            channels_passed.append("trend")
        
        # 反转通道
        if _check_reversal_channel(s):
            channels_passed.append("reversal")
        
        # 突破通道
        if _check_breakout_channel(s):
            channels_passed.append("breakout")
        
        # 吸筹通道
        if _check_accumulation_channel(s):
            channels_passed.append("accumulation")
        
        if channels_passed:
            s["channels"] = channels_passed
            results.append(s)
    
    logger.info(f"Technical filter: {len(stocks)} → {len(results)}")
    return results


# ── 通道检查函数 ──────────────────────────────────────────

def _check_trend_channel(s: dict) -> bool:
    """趋势通道：MA50 > MA200 + RPS 动量"""
    ma50 = s.get("ma50", 0)
    ma200 = s.get("ma200", 0)
    rps120 = s.get("rps120", 0)
    
    if not all([ma50, ma200]):
        return False
    
    return ma50 > ma200 and rps120 >= 70


def _check_reversal_channel(s: dict) -> bool:
    """反转通道：超跌反弹 + MACD 底背离"""
    change_pct_20d = s.get("change_pct_20d", 0)
    macd_hist = s.get("macd_hist", 0)
    prev_macd_hist = s.get("prev_macd_hist", 0)
    
    # 20日跌幅 > 15% + MACD 柱由负转正
    return change_pct_20d < -15 and macd_hist > 0 and prev_macd_hist < 0


def _check_breakout_channel(s: dict) -> bool:
    """突破通道：放量突破 + 布林带扩张"""
    close = s.get("close", 0)
    bb_upper = s.get("bb_upper", 0)
    volume_ratio = s.get("volume_ratio", 0)  # 量比
    
    if not all([close, bb_upper]):
        return False
    
    return close > bb_upper and volume_ratio > 2.0


def _check_accumulation_channel(s: dict) -> bool:
    """吸筹通道：底部缩量 + 量能萎缩"""
   距年低 = s.get("dist_from_year_low_pct", 100)
    volume_ratio_20d = s.get("volume_ratio_20d", 1)  # 20日量比
    
    return 距年低 <= 45 and volume_ratio_20d < 0.75
```

### 3. 信号状态机

```python
# core/signal_state.py

from __future__ import annotations
from enum import Enum
from datetime import datetime
from typing import List, Optional
import sqlite3
import json

class SignalState(Enum):
    DETECTED = "detected"       # 技术面信号刚触发
    SURVIVED = "survived"       # 跨日存活，信号未失效
    CONFIRMED = "confirmed"     # 出现量价确认
    EXPIRED = "expired"         # 信号失效
    REJECTED = "rejected"       # 被 AI 审计否决

class SignalTracker:
    """
    信号状态机 — 跟踪信号生命周期
    
    P0-2 修复（架构评审者）：明确 SQLite WAL 持久化
    P1-1 修复（现实检验者）：设定明确终止条件
    """
    
    def __init__(self, db_path: str = None):
        self.db_path = db_path or ":memory:"
        self.db = sqlite3.connect(self.db_path, timeout=10)
        self.db.execute("PRAGMA journal_mode=WAL")  # 并发安全
        self._init_table()
    
    def _init_table(self):
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS signal_states (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT NOT NULL,
                signal_type TEXT NOT NULL,
                state TEXT NOT NULL DEFAULT 'detected',
                detected_at TEXT NOT NULL,
                confirmed_at TEXT,
                expired_at TEXT,
                key_level REAL,
                context TEXT,
                UNIQUE(code, signal_type, detected_at)
            )
        """)
        self.db.commit()
    
    def record(self, code: str, signal_type: str, state: SignalState, 
               key_level: float = None, context: dict = None):
        """记录信号状态"""
        now = datetime.now().isoformat()
        
        if state == SignalState.CONFIRMED:
            self.db.execute("""
                UPDATE signal_states SET state=?, confirmed_at=?
                WHERE code=? AND signal_type=? AND state IN ('detected','survived')
            """, (state.value, now, code, signal_type))
        elif state == SignalState.EXPIRED:
            self.db.execute("""
                UPDATE signal_states SET state=?, expired_at=?
                WHERE code=? AND signal_type=? AND state != 'expired'
            """, (state.value, now, code, signal_type))
        else:
            self.db.execute("""
                INSERT OR IGNORE INTO signal_states 
                (code, signal_type, state, detected_at, key_level, context)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (code, signal_type, state.value, now, key_level, 
                  json.dumps(context or {})))
        self.db.commit()
    
    def get_active_signals(self) -> List[dict]:
        """获取所有活跃信号"""
        cursor = self.db.execute("""
            SELECT id, code, signal_type, state, detected_at, key_level
            FROM signal_states 
            WHERE state NOT IN ('expired', 'rejected')
            ORDER BY detected_at DESC
        """)
        return [{"id": r[0], "code": r[1], "signal_type": r[2], 
                 "state": r[3], "detected_at": r[4], "key_level": r[5]} 
                for r in cursor.fetchall()]
    
    def check_survival(self, code: str, current_price: float) -> bool:
        """检查信号是否存活（价格未跌破关键位）"""
        cursor = self.db.execute("""
            SELECT key_level FROM signal_states
            WHERE code=? AND state IN ('detected', 'survived')
        """, (code,))
        for row in cursor.fetchall():
            if row[0] and current_price < row[0] * 0.97:
                return False
        return True
    
    def expire_stale(self, max_age_days: int = 5):
        """
        过期陈旧信号（P1-1 修复：明确终止条件）
        超过 max_age_days 天未确认的信号自动过期
        """
        from datetime import timedelta
        cutoff = (datetime.now() - timedelta(days=max_age_days)).isoformat()
        self.db.execute("""
            UPDATE signal_states SET state='expired', expired_at=?
            WHERE state IN ('detected', 'survived') AND detected_at < ?
        """, (datetime.now().isoformat(), cutoff))
        self.db.commit()
```

### 4. AI 审计员（异步可选）

```python
# core/ai_auditor.py

from __future__ import annotations
from dataclasses import dataclass
from typing import List, Optional, Callable
import json
import logging

logger = logging.getLogger("stock-mcp.ai_auditor")

@dataclass
class AuditDecision:
    code: str
    action: str           # "PASS" | "VETO"
    reason: str
    confidence: float

class AIAuditor:
    """
    AI 审计员 — 只做 veto，不做升级
    
    P0-2 修复（现实检验者）：改为异步可选
    P0-3 修复（架构评审者）：补全解析逻辑
    P1-3 修复（优化师）：Prompt 提取为配置
    """
    
    DEFAULT_PROMPT_TEMPLATE = """你是威科夫量价分析审计员。对以下候选执行否决审计：

股票: {code} ({name})
技术面通道: {channels}
资金流: {fund_flow}

规则：
1. 你只能输出 PASS 或 VETO + 原因
2. 不能将规则未准入的股票加入候选
3. VETO 必须基于：结构已坏、基本面恶化、重大风险

输出 JSON: {{"action": "PASS 或 VETO", "reason": "否决原因", "confidence": 0.0-1.0}}"""
    
    def __init__(self, llm_fn: Callable = None, prompt_template: str = None):
        """
        Args:
            llm_fn: LLM 调用函数 (prompt: str) -> str
            prompt_template: 自定义 Prompt 模板
        """
        self.llm = llm_fn
        self.template = prompt_template or self.DEFAULT_PROMPT_TEMPLATE
    
    def audit(self, candidates: List[dict], context: dict = None) -> List[AuditDecision]:
        """审计候选列表"""
        # P0-2 修复：LLM 不可用时自动 PASS
        if self.llm is None:
            logger.warning("LLM unavailable, auto-PASS all candidates")
            return [AuditDecision(code=c["code"], action="PASS",
                    reason="LLM unavailable", confidence=1.0) for c in candidates]
        
        decisions = []
        for candidate in candidates:
            try:
                decision = self._audit_one(candidate)
                decisions.append(decision)
            except Exception as e:
                logger.error(f"Audit failed for {candidate.get('code')}: {e}")
                decisions.append(AuditDecision(
                    code=candidate.get("code", "?"), action="PASS",
                    reason=f"Audit error: {e}", confidence=0.5))
        
        return decisions
    
    def _audit_one(self, candidate: dict) -> AuditDecision:
        """审计单个候选"""
        prompt = self.template.format(
            code=candidate.get("code", ""),
            name=candidate.get("name", ""),
            channels=candidate.get("channels", []),
            fund_flow=candidate.get("fund_flow", "N/A"),
        )
        
        response = self.llm(prompt)
        return self._parse_response(candidate.get("code", ""), response)
    
    def _parse_response(self, code: str, response: str) -> AuditDecision:
        """解析 LLM 响应"""
        try:
            # 尝试提取 JSON（兼容 markdown code block）
            text = response.strip()
            if "```" in text:
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
            
            data = json.loads(text)
            return AuditDecision(
                code=code,
                action=data.get("action", "PASS"),
                reason=data.get("reason", ""),
                confidence=float(data.get("confidence", 0.8)),
            )
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning(f"Failed to parse audit response: {e}")
            return AuditDecision(code=code, action="PASS",
                reason=f"Parse error: {e}", confidence=0.5)
```

### 5. 信号反馈闭环

```python
# core/signal_feedback.py

from __future__ import annotations
from dataclasses import dataclass
from typing import List
from datetime import datetime
import sqlite3

@dataclass
class SignalOutcome:
    code: str
    signal_type: str
    entry_price: float
    exit_price: float
    pnl_pct: float
    result: str              # "win" | "loss" | "neutral"

class SignalFeedback:
    """
    信号反馈闭环 — 追踪推荐效果
    
    P1-1 修复（现实检验者）：明确终止条件
    - 最小样本数: 30
    - 最小胜率: 50%
    - 信号过期: 超过 5 天未确认自动过期
    """
    
    MIN_SAMPLES = 30
    MIN_WIN_RATE = 0.5
    
    def __init__(self, db_path: str = None):
        self.db_path = db_path or ":memory:"
        self.db = sqlite3.connect(self.db_path, timeout=10)
        self.db.execute("PRAGMA journal_mode=WAL")
        self._init_table()
    
    def _init_table(self):
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS signal_outcomes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT NOT NULL,
                signal_type TEXT NOT NULL,
                entry_price REAL,
                exit_price REAL,
                pnl_pct REAL,
                result TEXT,
                holding_days INTEGER,
                recorded_at TEXT
            )
        """)
        self.db.commit()
    
    def record_outcome(self, code: str, signal_type: str,
                       entry: float, exit: float, holding_days: int):
        """记录信号的实际结果"""
        pnl = (exit - entry) / entry * 100 if entry > 0 else 0
        result = "win" if pnl > 2 else ("loss" if pnl < -2 else "neutral")
        
        self.db.execute("""
            INSERT INTO signal_outcomes 
            (code, signal_type, entry_price, exit_price, pnl_pct, 
             result, holding_days, recorded_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (code, signal_type, entry, exit, pnl, result, 
              holding_days, datetime.now().isoformat()))
        self.db.commit()
    
    def compute_stats(self, signal_type: str, window: int = 30) -> dict:
        """计算信号类型的统计"""
        cursor = self.db.execute("""
            SELECT COUNT(*), 
                   SUM(CASE WHEN result='win' THEN 1 ELSE 0 END),
                   AVG(pnl_pct)
            FROM (
                SELECT result, pnl_pct FROM signal_outcomes
                WHERE signal_type = ?
                ORDER BY recorded_at DESC
                LIMIT ?
            )
        """, (signal_type, window))
        row = cursor.fetchone()
        total = row[0] or 0
        wins = row[1] or 0
        avg_pnl = row[2] or 0
        
        win_rate = wins / total if total > 0 else 0
        
        return {
            "signal_type": signal_type,
            "total_samples": total,
            "win_rate": round(win_rate, 3),
            "avg_pnl_pct": round(avg_pnl, 2),
            "is_mature": total >= self.MIN_SAMPLES,
            "should_activate": total >= self.MIN_SAMPLES and win_rate > self.MIN_WIN_RATE,
            "status": "active" if (total >= self.MIN_SAMPLES and win_rate > self.MIN_WIN_RATE) 
                      else "shadow" if total > 0 else "empty",
        }
    
    def get_all_stats(self) -> List[dict]:
        """获取所有信号类型的统计"""
        cursor = self.db.execute(
            "SELECT DISTINCT signal_type FROM signal_outcomes")
        types = [r[0] for r in cursor.fetchall()]
        return [self.compute_stats(t) for t in types]
```

---

## 编排示例

```python
# scripts/run_funnel.py — 实际执行入口

from core.orchestrator import Orchestrator, PipelinePhase
from core.funnel import stage_basic_filter, stage_technical_multi_channel
from core.signal_state import SignalTracker
from core.ai_auditor import AIAuditor

def run_daily_funnel():
    """每日漏斗执行"""
    
    # 1. 获取全市场数据
    from data_sources.tencent import get_market_universe
    universe = get_market_universe()
    
    # 2. 构建编排器
    orch = Orchestrator()
    orch.add_stage(PipelinePhase.FUNNEL, stage_basic_filter, "basic_filter")
    orch.add_stage(PipelinePhase.FUNNEL, stage_technical_multi_channel, "technical")
    
    # 3. 执行漏斗
    result = orch.run(universe, context={"min_amount": 5_000_000})
    
    # 4. 记录信号
    tracker = SignalTracker()
    for candidate in result.candidates:
        for ch in candidate.get("channels", []):
            tracker.record(
                code=candidate["code"],
                signal_type=ch,
                state="detected",
                key_level=candidate.get("close"),
            )
    
    # 5. AI 审计（可选）
    if len(result.candidates) > 0:
        auditor = AIAuditor(llm_fn=None)  # MVP 阶段不调 LLM
        decisions = auditor.audit(result.candidates)
        vetoed = [d for d in decisions if d.action == "VETO"]
        if vetoed:
            print(f"AI vetoed {len(vetoed)} candidates")
    
    # 6. 输出结果
    print(f"\n漏斗结果:")
    print(f"  输入: {len(universe)} 只")
    print(f"  输出: {len(result.candidates)} 只")
    print(f"  耗时: {result.total_ms}ms")
    for run in result.runs:
        print(f"  [{run.phase.value}] {run.input_count} → {run.output_count} ({run.duration_ms}ms)")
    
    return result

if __name__ == "__main__":
    run_daily_funnel()
```

---

## 文件结构（MVP）

```
stock-mcp-server/
├── core/
│   ├── orchestrator.py     # 🆕 编排层
│   ├── funnel.py           # 🆕 漏斗引擎（2 Stage MVP）
│   ├── ai_auditor.py       # 🆕 AI 审计员（异步可选）
│   ├── signal_state.py     # 🆕 信号状态机
│   ├── signal_feedback.py  # 🆕 信号反馈闭环
│   ├── cache.py            # 已有
│   ├── helpers.py          # 已有（扩展 is_st_stock 等）
│   ├── health.py           # 已有
│   ├── metrics.py          # 已有
│   ├── resilience.py       # 已有
│   ├── store.py            # 已有（SQLite WAL）
│   └── ...
├── tools/                  # 123+ 工具不变
├── scripts/
│   ├── run_funnel.py       # 🆕 漏斗执行入口
│   └── ...
└── data/                   # 已有
```

---

## 实施路线（修正版）

### Phase 1（1周）— MVP 核心
1. `core/orchestrator.py` — 编排层
2. `core/funnel.py` — 2 Stage 漏斗
3. `core/signal_state.py` — 信号状态机
4. 扩展 `core/helpers.py` — 新增辅助函数
5. `scripts/run_funnel.py` — 执行入口
6. **测试**: 用腾讯行情数据跑一次完整漏斗

### Phase 2（1周）— AI 审计 + 反馈
1. `core/ai_auditor.py` — AI 审计员（含 Prompt 配置）
2. `core/signal_feedback.py` — 反馈闭环
3. 扩展 SQLite — 新增 signal_outcomes 表
4. **测试**: 记录信号结果，验证反馈统计

### Phase 3（可选）— 扩展
1. 增加 Stage（资金面/基本面）
2. Hermes cron 调度
3. 盘前/盘后自动化
4. 消融测试框架
5. 代码质量门禁
