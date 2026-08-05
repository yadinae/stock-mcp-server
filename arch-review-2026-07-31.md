# 架构评审报告：stock-mcp-server 优化方案

## 评审范围
- Local Server：`/home/admin/projects/stock-mcp-server`（Python/FastMCP，本地进程）
- Gateway：`/home/admin/projects/stock-mcp-gateway`（TypeScript/Cloudflare Workers，云端）
- 关联 cron：`/home/admin/.hermes/cron/jobs.json`（8 个相关任务）

---

## 一、双服务器架构合理性评估

### 现状工具分布（实证数据）
| 维度 | 数量 |
|------|------|
| Local 已注册 MCP 工具 | 28 |
| Gateway MCP 工具 | ~100+（含分类工具） |
| 重叠工具 | 18 |
| Local-only | 10（主要是美股/港股专属 + `run_alert_check`） |
| Gateway-only | 90+（投研增强型） |

### Bridge 依赖关系（关键发现）

Gateway → Local 存在硬依赖：
```
gateway/src/tools/portfolio.ts:128
→ fetchWithBreaker("activeagent-bridge", "http://localhost:8901/config/holdings")
```

这是架构中唯一的跨服务器通信路径，且是反向的——Gateway 需要本地服务才能提供持仓诊断功能。

### 双架构是否合理？

**结论：部分合理，但方向反了。**

当前架构的意图：
- Gateway = 生产级边缘服务（有 circuit breaker / KV cache / audit / rate limit / admin panel）
- Local = 开发/降级容器（TTL 内存缓存 + webhook 模块）

**实际问题：**
1. Gateway 已经能处理所有本地核心工具（实时行情/K线/A股分析），18 个重叠工具意味着维护两份代码
2. Local 服务器没有任何外部调用者（无 cron 直接指向 `http://localhost:8901`，除了 Gateway 的 bridge 依赖）
3. Gateway 到 Local 的单向依赖违背了"边缘优先"的设计意图

---

## 二、本地服务器的保留价值

### 值得保留的功能

| 功能 | 理由 | 优先级 |
|------|------|--------|
| mootdx 通达信 TCP 数据源 | Gateway 未移植，本地特有优势 | P2 |
| `get_tdx_company_info` / `get_tdx_finance_info` / `get_tdx_xdxr_info` | 通达信 F10 数据增强 | P3 |
| TTL 缓存层（`core/cache.py`） | Gateway 已有 L1+L2 KV，可合并 | P4 |
| Webhook 配置/规则存储 | JSON 文件格式，无状态依赖 | P4 |

### 应移除的功能

| 功能 | 理由 |
|------|------|
| 18 个重叠工具（quote/kline/info/technical/news等） | Gateway 已全覆盖，维护两份是技术债 |
| `global_stock.py`（953 行） | 包裹 yahoo.py + tencent.py + sina，逻辑冗余 |
| `run_alert_check` MCP 工具 | Alerter 已停止，cron 脚本不存在 |
| 独立的 alerter.py 模块 | 告警逻辑应由 Gateway 承载 |

---

## 三、Alerter 迁移策略

### 现状诊断

**Cron 任务 `2c1285d3`（持仓预警检查）：**
- 调度：`*/30 9-14 * * 1-5`（交易日 9-14 点每 30 分钟）
- 最后运行：2026-07-31T14:30:51 ✅
- 脚本：`stock_alerter.sh`
- **问题：该脚本不存在于 `/home/admin/.hermes/cron/scripts/`**
- prompt：`"run stock-mcp-server alert checker"` —— 没有指定具体调用方式

**Local `run_alert_check` 工具：**
- 调用 `webhook.alerter.run_alert_check()`
- 检查维度：价格跌幅、放量下跌、ST风险、MACD金叉死叉、RSI超买超卖、ETF评分

**Gateway 中没有对应的 alerter 工具。**

### 迁移选项对比

| 方案 | 优点 | 缺点 |
|------|------|------|
| **A: 完全停止 alerter** | 简化架构，消除无用 cron | 丢失实时预警能力 |
| **B: 在 Gateway 重建 alerter 工具** | 统一架构，利用现有 circuit breaker/audit | 需移植 webhook/alerter.py 逻辑 |
| **C: 保留 local 侧 alerter，修复 cron 脚本** | 改动最小 | 维持双架构，技术债积累 |

**推荐：方案 B**
- Gateway 已有 portfolio 诊断工具链（`diagnosePortfolio`, `portfolioSignal`）
- 可复用现有 auth/rate-limit/audit infrastructure
- 避免 Local-Gateway bridge 耦合

---

## 四、架构升级路径

### 阶段划分（最小破坏 vs 最大收益）

**Phase 1：止血（1-2天）**
1. 删除或注释掉 18 个重叠 MCP 工具定义
2. 修复 `stock_alerter.sh` 空引用（或暂停该 cron）
3. 将 `global_stock.py` 引用改为直接 import `yahoo.py` + `tencent.py`

**Phase 2：解耦（2-3天）**
1. Gateway 实现 alerter 工具（从 alerter.py 移植核心逻辑）
2. 删除 Local 的 `run_alert_check` 工具
3. 更新 cron 任务指向 Gateway endpoint

**Phase 3：清理（3-5天）**
1. 删除 Local 的 `webhook/` 目录（逻辑已在 Gateway）
2. 删除 Local 的 `global_stock.py`（逻辑分散到 yahoo/tencent）
3. Local 仅保留 mootdx 相关工具作为边缘补充

**Phase 4：协议升级（可选）**
- Local 升级到 MCP spec 2026-07-28（与 Gateway 对齐）
- 当前 Local 使用旧版 FastMCP，无 protocolVersion 协商

---

## 五、P0-P4 问题清单

### 🔴 P0 — 架构阻塞问题

| # | 问题 | 影响 |
|---|------|------|
| P0-1 | Gateway 通过 `http://localhost:8901` 硬依赖 Local 获取持仓数据 | 一旦 Local 停止，Gateway 持仓诊断功能失效 |
| P0-2 | Cron `2c1285d3` 指向不存在的脚本 `stock_alerter.sh` | 持仓预警 cron 实际不工作，但状态显示 last_run 正常（可能是缓存） |

### 🟠 P1 — 严重架构缺陷

| # | 问题 | 影响 |
|---|------|------|
| P1-1 | 18 个重叠工具双重维护，变更需要同步两处 | 功能漂移风险，维护成本翻倍 |
| P1-2 | `global_stock.py`（953 行）封装 yahoo+tencent+sina，与独立模块重复 | 代码膨胀，单一故障点 |
| P1-3 | 70 个裸 `except Exception` 吞没所有错误 | 无法追踪生产环境问题 |

### 🟡 P2 — 一般架构问题

| # | 问题 | 影响 |
|---|------|------|
| P2-1 | Local 无 circuit breaker / rate limit / audit | 与 Gateway 能力差距大，降级时无保障 |
| P2-2 | MCP spec 2026-07-28 仅在 Gateway 实现 | 客户端协议版本不一致可能导致兼容性问题 |
| P2-3 | Local `run_alert_check` 工具指向已停用的 alerter | 文档与实现不符 |

### 🟢 P3 — 轻微架构问题

| # | 问题 | 影响 |
|---|------|------|
| P3-1 | `bridge_url` 参数默认值硬编码为 `http://localhost:8901` | 部署环境切换成本高 |
| P3-2 | 两套缓存策略（Local TTL 内存 vs Gateway L1+L2 KV） | 缓存一致性无法保证 |

### 🔵 P4 — 改进建议

| # | 建议 |
|---|------|
| P4-1 | 考虑将 Local 作为 Gateway 的 fallback 数据源（而非对等服务） |
| P4-2 | mootdx 数据源可移植到 Gateway（通过 HTTP wrapper） |
| P4-3 | 统一 error response schema（Local 用 json.dumps，Gateway 用结构化对象） |

---

## 六、加权评分

| 等级 | 数量 | 扣分 |
|:----:|:----:|:----:|
| P0 | 2 | -10 |
| P1 | 3 | -15 |
| P2 | 3 | -9 |
| P3 | 2 | -2 |
| P4 | 3 | 0 |
| **总分** | | **74/100** |

---

## 七、核心结论

1. **双架构方向正确但执行反了**：Gateway 应该成为唯一生产入口，Local 应退化为 mootdx 专用补充节点
2. **最关键 P0 是 bridge 硬依赖**：需要重构为 Gateway 直接管理持仓数据（可通过 D1 表或 KV 持久化）
3. **Alerter 迁移推荐方案 B**：在 Gateway 重建，消灭 Local-Gateway 通信依赖
4. **最小破坏路径**：Phase 1 止血（删除重叠工具）→ Phase 2 解耦（迁移 alerter）→ Phase 3 清理（删除冗余代码）
