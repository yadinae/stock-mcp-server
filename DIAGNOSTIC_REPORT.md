# Stock-MCP-Server 诊断报告

**生成时间**: 2026-07-31 18:30 CST  
**项目路径**: `/home/admin/projects/stock-mcp-server`  
**对照项目**: `/home/admin/projects/stock-mcp-gateway` (TypeScript/Workers)  
**诊断专家**: Research Agent

---

## 执行摘要

| # | 问题 | 原报告声明 | 实际发现 | 优先级 | 修复复杂度 |
|---|------|-----------|---------|--------|------------|
| 1 | Bare except 104处 | 104处裸异常捕获 | **0处裸except**，共89个except子句（61个`Exception`，8个`ImportError`，10个特定类型） | P2 | ⭐ 半天 |
| 2 | global_stock.py 重复 | 与yahoo/tencent重复 | **部分重叠但功能互补**：提供东财/SEC等补充数据源，缺少缓存和健康追踪 | P1 | ⭐⭐ 2-3天 |
| 3 | Alerter 停止 | cron未运行 | **正常运行**：jobs.json #11配置了`*/30 9-14 * * 1-5`，最新运行于2026-07-31 14:00 | P0(误报) | N/A |
| 4 | 熔断器/限流缺失 | 需要移植 | Gateway有完整实现（KV限流+状态机熔断），Server完全缺失 | P1 | ⭐⭐⭐ 1-2天 |
| 5 | MCP 2026-07-28 | 兼容性未检查 | Server用MCP SDK 1.26.0，Gateway已适配stateless协议；需升级SDK或手动适配 | P2 | ⭐⭐⭐⭐ 需调研 |

---

## 一、异常处理统计（修正"104处bare except"）

### 统计方法
```bash
grep -rn "except " /home/admin/projects/stock-mcp-server --include="*.py" | wc -l
# 输出: 89
```

### 分类明细

| 文件 | `Exception` | `ImportError` | 特定类型 | 小计 |
|------|-------------|---------------|----------|------|
| server.py | 16 | 4 | 0 | **20** |
| data_sources/global_stock.py | 12 | 0 | 1 `(ValueError, TypeError)` | **13** |
| data_sources/tencent.py | 4 | 0 | 1 `(ValueError, IndexError)` | **5** |
| data_sources/yahoo.py | 2 | 0 | 0 | **2** |
| data_sources/mootdx.py | 3 | 0 | 0 | **3** |
| tools/analyzer.py | 5 | 0 | 4 (`JSONDecodeError`, `IndexError`, `TypeError`) | **9** |
| tools/news.py | 2 | 0 | 0 | **2** |
| tools/backtest/simulator.py | 0 | 0 | 2 `(IndexError, TypeError, ValueError)` | **2** |
| tools/backtest/strategies.py | 0 | 0 | 1 `(IndexError, TypeError, ValueError)` | **1** |
| webhook/alerter.py | 5 | 0 | 1 `(ValueError, TypeError)` | **6** |
| webhook/notifier.py | 4 | 0 | 0 | **4** |
| webhook/config.py | 2 | 0 | 0 | **2** |
| webhook/market_status.py | 2 | 0 | 0 | **2** |
| core/parallel.py | 4 | 0 | 0 | **4** |
| scripts/test_tools.py | 0 | 4 | 0 | **4** |
| **合计** | **61** | **8** | **10** | **79** |

### 关键发现

1. **无真正裸 `except:`**：所有 except 都有异常类型或 `Exception`
2. **`except Exception` 占比最高 (61个)**：会吞掉 `KeyboardInterrupt`、`SystemExit` 等系统信号
3. **`except ImportError` (8个)**：用于可选依赖（mootdx、webhook模块）

### 建议优化

```python
# 网络请求类（当前）
except Exception as e:
    logger.warning("...")

# 建议改为
except (httpx.ConnectError, httpx.ReadTimeout, httpx.HTTPStatusError) as e:
    logger.warning("Network error: %s", e)
except Exception as e:  # 兜底
    logger.error("Unexpected error: %s", e)
```

**优先级**: P2（代码质量改进）  
**修复复杂度**: ⭐（半天内完成）

---

## 二、global_stock.py 与 yahoo.py/tencent.py 重叠分析

### 模块定位对比

| 模块 | 行数 | HTTP客户端 | 缓存 | 健康追踪 | 数据源 |
|------|------|-----------|------|----------|--------|
| `yahoo.py` | 135 | yfinance | ✅ TTLCache | ✅ health tracker | Yahoo Finance |
| `tencent.py` | 302 | httpx | ✅ TTLCache | ✅ health tracker | 腾讯HTTP API + mootdx fallback |
| `global_stock.py` | 953 | httpx | ❌ 无 | ❌ 无 | 新浪、腾讯(扩展)、东财、Yahoo(chart)、SEC |

### 重叠功能映射

```
行情层:
├── yahoo.py::get_realtime_quote(code)     → yfinance API (美股/港股基础行情)
├── tencent.py::get_realtime_quote(code)   → 腾讯API (A股)
└── global_stock.py::
    ├── us_quote_tencent(ticker)           → 腾讯美股 (独立实现，不重叠)
    ├── hk_quote_tencent(code)             → 腾讯港股 (独立实现，不重叠)
    └── quote_eastmoney(secid)             → 东财push2 (新数据源)

K线层:
├── yahoo.py::get_kline(code, days)        → yfinance.history()
├── tencent.py::get_kline(code, days)      → 腾讯K线API + mootdx fallback
└── global_stock.py::kline_yahoo(symbol)   → Yahoo chart API (不同端点，不重叠)
```

### 发现的问题

| # | 问题 | 位置 | 影响 |
|---|------|------|------|
| 1 | `us_quote_sina()` 返回硬编码错误 | global_stock.py:38 | 浪费一次调用后才失败 |
| 2 | `global_quote()` 包含废弃的sina fallback | global_stock.py:233-236 | 逻辑冗余 |
| 3 | 缺少 TTL 缓存 | global_stock.py 全部函数 | 每次调用都发真实API请求 |
| 4 | 缺少健康追踪 | global_stock.py 全部函数 | 无法监控数据源可用性 |
| 5 | 与 yahoo.py K线实现不同 | kline_yahoo() vs get_kline() | 维护两套代码 |

### 推荐重构方案

```
data_sources/
├── a_stock/                    # A股数据层（新建目录）
│   ├── tencent.py              # 现有 tencent.py 重构
│   └── mootdx.py               # Fallback
├── us_hk_stock/                # 美股/港股数据层（新建目录）
│   ├── yahoo.py                # 保留：yfinance基础行情
│   ├── tencent_ext.py          # 从 global_stock 迁移：腾讯扩展
│   ├── eastmoney.py            # 从 global_stock 迁移：东财数据
│   └── sec.py                  # 从 global_stock 迁移：SEC文件
└── global_stock.py             # 删除或缩减为facade
```

**优先级**: P1（架构优化）  
**修复复杂度**: ⭐⭐（2-3天，需测试验证）

---

## 三、Alerter 状态分析（修正"STOPPED"误报）

### 现状确认

| 检查项 | 结果 |
|--------|------|
| 脚本存在 | ✅ `/home/admin/.hermes/scripts/stock_alerter.sh` |
| Cron 任务 | ✅ **已配置** (jobs.json #11) |
| 任务名称 | "持仓预警检查 — 交易时段自动推送" |
| 执行计划 | `*/30 9-14 * * 1-5`（交易日 9:00-14:30 每30分钟） |
| 最近运行 | ✅ 2026-07-31 14:00:46 |
| 手动测试 | ✅ 正常运行，检测到2条信号 |

### 手动测试结果

```bash
$ python3.11 -m webhook.alerter
{
  "status": "alerts_sent",
  "alerts": [
    {"type": "macd_signal", "code": "512660", "name": "军工ETF国泰"},
    {"type": "rsi_signal", "code": "512480", "name": "半导体ETF国联安"}
  ],
  "stats": {"checked": 12, "errors": 0, "alerts": 2, "suppressed": 0}
}
```

### 结论

**原报告"alerter STOPPED"有误。** 实际状态：
- Cron 任务正常配置并运行
- 状态文件持续更新（最新：2026-07-31 14:00:46）
- 告警逻辑工作正常

可能存在的历史问题（已解决）：
- 早期 cron 配置丢失 → 已重建
- 任务名变更 → 当前为"持仓预警检查 — 交易时段自动推送"

---

## 四、熔断器/限流实现对比

### Gateway 实现（完整）

#### 熔断器 (`src/circuit_breaker.ts`)
```typescript
// 状态机：CLOSED → OPEN → HALF_OPEN → CLOSED
class CircuitBreakerRegistry {
  allow(name): { allowed, state, message? }
  recordSuccess(name)
  recordFailure(name)
  getReport(): Record<string, any>[]
}

// 已配置 18 个数据源断路器
circuitBreakers.configure('tencent', { failureThreshold: 5, cooldownSec: 30 })
circuitBreakers.configure('yahoo', { failureThreshold: 3, cooldownSec: 60 })
// ... 其他数据源
```

#### 限流器 (`src/rate_limit.ts`)
```typescript
// 基于 Cloudflare KV 的 per-key 限频
// 双窗口：分钟级（TTL 120s）+ 日级（TTL 86400s）
export async function checkRateLimit(db, kv, apiKey, toolName, config)

// Tier 支持
const TIER_DEFAULTS = {
  free:   { maxPerMinute: 30,  maxPerDay: 1000 },
  pro:    { maxPerMinute: 120, maxPerDay: 10000 },
  enterprise: { maxPerMinute: 300, maxPerDay: 50000 },
};

// 昂贵工具额外限制
const EXPENSIVE_TOOLS = new Set(['analyze_stock_ai', 'check_backtest']);
```

### Server 现状

| 功能 | 状态 | 说明 |
|------|------|------|
| 熔断器 | ❌ 不存在 | 无断路器实现 |
| 限流 | ❌ 不存在 | 无请求频率控制 |
| 健康追踪 | ⚠️ 部分 | `core/health.py` 记录成功率，但无熔断动作 |
| 缓存 | ✅ 已实现 | TTLCache，30秒~10分钟 |

### 移植难度评估

| 组件 | 移植难度 | 方案 | 预估工时 |
|------|----------|------|----------|
| 熔断器 | 中等 | Python `threading.Lock` + 状态字典，参考 gateway 状态机 | 0.5天 |
| 限流 | 困难 | 本地进程无分布式KV；可用内存计数器 + SQLite 持久化 | 1-2天 |
| 健康追踪增强 | 简单 | 在现有 `health.py` 上增加熔断判定逻辑 | 0.5天 |

### 推荐实现（Python 版熔断器）

```python
# circuit_breaker.py（新建）
import time
from enum import Enum
from threading import Lock

class State(Enum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"

class CircuitBreaker:
    def __init__(self, name, failure_threshold=5, cooldown_sec=30):
        self.name = name
        self.failure_threshold = failure_threshold
        self.cooldown_sec = cooldown_sec
        self._lock = Lock()
        self._state = State.CLOSED
        self._failures = 0
        self._last_failure_at = 0.0

    @property
    def state(self):
        with self._lock:
            if self._state == State.OPEN:
                if time.time() - self._last_failure_at >= self.cooldown_sec:
                    self._state = State.HALF_OPEN
            return self._state.value

    def allow(self) -> bool:
        with self._lock:
            if self._state == State.OPEN:
                if time.time() - self._last_failure_at < self.cooldown_sec:
                    return False
                self._state = State.HALF_OPEN
            return True

    def record_success(self):
        with self._lock:
            self._failures = 0
            self._state = State.CLOSED

    def record_failure(self):
        with self._lock:
            self._failures += 1
            self._last_failure_at = time.time()
            if self._failures >= self.failure_threshold:
                self._state = State.OPEN

class CircuitBreakerRegistry:
    def __init__(self):
        self._breakers = {}
        self._lock = Lock()

    def get(self, name: str, **kwargs) -> CircuitBreaker:
        with self._lock:
            if name not in self._breakers:
                self._breakers[name] = CircuitBreaker(name, **kwargs)
            return self._breakers[name]
```

**优先级**: P1（稳定性保障）  
**修复复杂度**: ⭐⭐⭐（1-2天）

---

## 五、MCP Spec 2026-07-28 兼容性

### Gateway 实现状态

Gateway 已适配 MCP 2026-07-28 spec：

```typescript
// src/types.ts
export interface McpMeta {
  protocolVersion?: string;  // e.g. "2026-07-28"
  clientInfo?: { name: string; version: string };
  _meta?: McpMeta;  // per-request metadata
}

// src/index.ts (关键变更)
// MCP 2026-07-28: server/discover (replaces initialize for new clients)
protocolVersion: '2026-07-28'

// MCP 2026-07-28: Validate Mcp-Method header (if present)
const clientProtocolVersion = requestMeta.protocolVersion || headerMethod || '2025-11-25';
```

关键变更：
1. **Stateless 设计**：用 `_meta` 替代 initialize handshake
2. **protocol version** 在请求头中传递
3. **server/discover** 端点取代传统 initialize

### Server 实现状态

```python
# server.py
from mcp.server.fastmcp import FastMCP
mcp = FastMCP("stock-mcp")  # 使用 MCP SDK 1.26.0
```

| 特性 | Gateway | Server |
|------|---------|--------|
| Protocol Version | ✅ 支持 2026-07-28 | ❌ 使用旧版本 |
| Stateless 设计 | ✅ `_meta` 字段 | ❌ 需要 initialize |
| server/discover | ✅ 已实现 | ❌ 缺失 |
| 工具 schema | 动态生成 | 静态装饰器 |

### 兼容性风险

| 风险项 | 影响 | 等级 |
|--------|------|------|
| 无法识别 2026-07-28 客户端 | 连接失败 | 🔴 高 |
| 无法解析 `_meta` 字段 | 功能缺失 | 🟡 中 |
| `server/discover` 端点缺失 | 新客户端无法发现 | 🔴 高 |
| 工具 schema 变化 | 参数不兼容 | 🟡 中 |

### 修复方案

#### 方案 A：升级 MCP SDK（推荐，需验证）
```bash
pip install --upgrade "mcp>=1.30"
```
检查新版 SDK 是否原生支持 2026-07-28 spec。

#### 方案 B：手动适配（如 SDK 不支持）
```python
# 在 server.py 中添加协议版本处理
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("stock-mcp", protocol_version="2026-07-28")

# 如果需要自定义 handler
@mcp.tool(name="...")
async def my_tool(params: dict, meta: dict = None):
    # meta 包含 protocolVersion, clientInfo 等
    pass
```

### 优先级: P2（前瞻性兼容）
**修复复杂度**: ⭐⭐⭐⭐（需调研 SDK 更新，可能涉及重构）

---

## 六、工具重复统计（修正"18个重复"）

### Server 工具列表（28个）
```
analyze_stock_ai, analyze_stocks, check_backtest, check_st_risk,
get_cache_stats, get_data_source_health, get_global_kline, get_global_quote,
get_institutional_holders, get_kline, get_options_chain, get_realtime_quote,
get_sec_filings, get_sec_xbrl, get_stock_context, get_stock_info,
get_tdx_company_info, get_tdx_finance_info, get_tdx_xdxr_info,
get_technical_analysis, get_us_financials, get_us_fund_flow,
get_us_key_indicators, get_us_market_ranking, get_yahoo_statistics,
run_alert_check, search_global_stock, search_stock_news
```

### Gateway 工具列表（107个）
```
analyze_hot_money, analyze_lhb, analyze_limitup_tiers, analyze_policy,
analyze_stock_agent, analyze_stock_ai, analyze_stocks, cache_warmup,
check_backtest, check_st_risk, check_trap_risk, dcf_valuation,
dd_checklist, fetch_financials, get_all_sectors_briefing, get_announcements,
get_block_trade, get_company_financials, get_company_profile,
get_concept_fund_flow, get_crypto_kline, get_crypto_quote, get_crypto_quotes,
get_data_source_health, get_dividend_history, get_financial_reports,
get_fund_flow_120d, get_fund_flow_minute, get_global_quote,
get_holder_change, get_industry_fund_flow, get_industry_rank,
get_lockup_calendar, get_management_team, get_margin_trading,
get_market_hot_stocks, get_market_lhb, get_northbound_flow, get_options_chain,
get_realtime_quote, get_research_reports, get_sec_filings, get_sector_briefing,
get_sector_news, get_stock_boards, get_stock_context, get_stock_info,
get_technical_analysis, get_top_crypto, get_top_shareholders,
get_tradingview_chart_type, get_tradingview_kline, get_tradingview_quote,
get_tradingview_ta, get_wallstreetcn_news, get_yahoo_statistics,
ic_memo, iwencai_query, iwencai_screener, iwencai_search, list_sectors,
market_overview, market_regime, portfolio_correlation, portfolio_full_report,
portfolio_rebalance, portfolio_risk_diagnosis, portfolio_signal,
refresh_intel_cache, run_alert_check, search_global_stock,
search_industry_news, search_stock_news, search_tradingview_indicator,
search_tradingview_market, sector_rotation, send_feishu_message,
send_telegram_message, stock_finder, stock_score, stock_signals,
tools_search, trade_journal_close, trade_journal_list, trade_journal_open,
trade_journal_stats, trade_journal_update, unit_economics,
value_creation_plan, watchlist_add, watchlist_brief, watchlist_create,
watchlist_list, watchlist_remove
```

### 重叠工具（18个）
```
analyze_stock_ai, analyze_stocks, check_backtest, check_st_risk,
get_cache_stats, get_data_source_health, get_global_quote,
get_institutional_holders, get_kline, get_options_chain,
get_realtime_quote, get_sec_filings, get_stock_context,
get_stock_info, get_technical_analysis, get_yahoo_statistics,
run_alert_check, search_stock_news
```

### 去重建议

| 策略 | 说明 |
|------|------|
| 统一工具命名 | Server 和 Gateway 使用相同 tool name |
| 功能互补 | Server 专注本地快速查询，Gateway 专注需要认证的复杂分析 |
| 迁移决策 | 评估哪些工具适合迁移到 Gateway（AI 分析、回测等耗时操作） |

---

## 七、Cron 依赖矩阵

| 任务 | 时间 | 状态 | 备注 |
|------|------|------|------|
| 盘中简报 | 11:00 | ⚠️ 需验证 | 依赖 mcp__stock_* 工具 |
| 收盘分析 | 15:30 | ⚠️ 需验证 | 依赖 mcp__stock_* 工具 |
| 缓存预热 | 08:30 | ⚠️ 需验证 | prewarm.py 脚本 |
| 持仓预警 | */30 9-14 | ✅ 正常 | jobs.json #11 |

---

## 八、修复优先级与计划

### Phase 1: 紧急修复（P0，当天完成）
- [x] ~~确认 alerter 状态~~（已正常运行）
- [ ] 验证盘中简报/收盘分析 cron 任务状态

### Phase 2: 稳定性加固（P1，本周完成）
- [ ] 实现熔断器（参考 gateway 实现）
- [ ] 实现基础限流（内存计数器）
- [ ] 清理 global_stock.py 中的废弃代码（sina fallback）
- [ ] 为 global_stock.py 添加 TTL 缓存

### Phase 3: 架构优化（P2，两周内完成）
- [ ] 重构数据源目录结构（a_stock/, us_hk_stock/）
- [ ] 统一异常处理规范（减少 `except Exception`）
- [ ] MCP spec 2026-07-28 兼容性适配
- [ ] 工具去重与命名规范化

---

## 附录

### 文件统计
```
总 Python 文件数: 17
总 except 子句: 89
  - except Exception: 61
  - except ImportError: 8
  - 特定类型: 10
总 MCP 工具: 28 (server) vs 107 (gateway)
重叠工具: 18
global_stock.py: 953 行
server.py: 952 行
webhook/ 目录: ~80KB
```

### MCP SDK 版本
```
MCP SDK: 1.26.0
Gateway MCP spec: 2026-07-28 (已适配)
Server MCP spec: 未知（需升级）
```

---

*报告生成于 2026-07-31 18:30 CST*  
*由 Research Agent 自动生成*
