# MCP Gateway — 架构设计 v1

> 核心命题：在 Cloudflare Workers 上构建 MCP 协议网关，用你的基础设施赚钱。
> 将 stock-mcp-server 作为旗舰服务，打通认证→用量→计费全链路。

---

## 一、核心约束

1. **Workers 边界**：单个 Worker 128MB 内存、10ms CPU/请求（free）/ 30s（paid）、100MB 响应体
2. **MCP 协议**：JSON-RPC 2.0 over SSE（Server-Sent Events）— 客户端发起连接，服务端推送结果
3. **存量资产**：stock-mcp-server 是 Python 进程（不能直接跑在 Workers 上），edge-key 是独立 Worker
4. **外部依赖**：Telegram Bot API 已经是 Workers 友好型，LLM 调用通过 HTTP API
5. **计费粒度**：按工具调用次数计费，需要可靠累加、幂等、防刷

---

## 二、三种架构方案

### 方案 A：一元架构（单一 Gateway Worker）

```
                ┌──────────────────────────────────────┐
                │        MCP Gateway Worker             │
                │                                      │
  Client ──SSE──▶  /mcp 路由                            │
                │  ├─ MCP 协议解析 + SSE 推送           │
                │  ├─ 认证（KV）+ 用量（D1）+ 限流      │
                │  └─ 工具执行（内联或 fetch 后端）     │
                │                                      │
                │  ┌─ 内联工具（纯 JS/TS）              │
                │  │  ├─ stock_realtime → fetch(Tencent)│
                │  │  ├─ stock_kline → fetch(Yahoo)     │
                │  │  └─ cache → KV                     │
                │  │                                     │
                │  └─ 外部工具（HTTP 转发）              │
                │     ├─ stock_ai_analysis → LLM API    │
                │     └─ third_party → 第三方 URL        │
                └──────────────────────────────────────┘
```

| 维度 | 评价 |
|------|------|
| **复杂度** | ⭐⭐ 低 — 单 Worker，单一代码库 |
| **延迟** | ⭐⭐⭐⭐⭐ 最低 — 无内部网络跳转 |
| **可扩展性** | ⭐⭐ 受限 — 128MB 内存限制代码规模 |
| **工具部署** | ⭐⭐⭐ 中等 — 内联工具需用 fetch 重写 Python 代码 |
| **适合阶段** | **MVP（Phase 0-3）** |

### 方案 B：网关 + 工具 Workers（分层架构）

```
           ┌──────────────┐
           │  Client      │
           └──────┬───────┘
                  │ SSE
           ┌──────▼───────┐
           │  Gateway     │  ← Workers A：认证、协议、路由、计费
           │  Worker      │
           └──┬────┬──────┘
              │    │
     ┌────────▼┐ ┌─▼──────────┐
     │ Stock   │ │ ThirdParty │  ← Workers B/C：每个工具组一个 Worker
     │ Worker  │ │ Worker     │
     └─────────┘ └────────────┘
```

| 维度 | 评价 |
|------|------|
| **复杂度** | ⭐⭐⭐⭐ 较高 — 多 Worker 部署、子请求路由 |
| **延迟** | ⭐⭐⭐ 中等 — Service Binding 子请求+5~10ms |
| **可扩展性** | ⭐⭐⭐⭐⭐ 最高 — 各工具独立扩缩容 |
| **工具部署** | ⭐⭐⭐ 中等 — 每个 Worker 各自构建部署 |
| **适合阶段** | **Phase 4+（开放第三方注册时）** |

### 方案 C：网关 + 外部 Python 进程（当前存量利用）

```
           ┌──────────────┐
           │  Client      │
           └──────┬───────┘
                  │ SSE
           ┌──────▼───────┐
           │  Gateway     │
           │  Worker      │  ← Workers：协议、认证、用量、计费
           └──────┬───────┘
                  │ HTTP fetch
           ┌──────▼───────┐
           │ stock-mcp    │  ← Python 进程（现状：本机运行）
           │ server       │
           └──────────────┘
```

| 维度 | 评价 |
|------|------|
| **复杂度** | ⭐ 最低 — 不改 stock-mcp-server，直接调 |
| **延迟** | ⭐⭐ 较高 — HTTP 网络往返 + Python 启动 |
| **可扩展性** | ⭐ 差 — 依赖单机 Python 进程 |
| **工具部署** | ⭐⭐⭐⭐⭐ 零改造 — 直接用现有服务 |
| **适合阶段** | **快速验证（Phase 0）** |

### 建议路线：A → B 演进

```
Phase 0: 方案 C（快速跑通链路，验证商业模式）
Phase 1: 方案 A（内联股票数据源，去掉 Python 依赖）
Phase 2: 方案 A+（加认证/用量/计费）
Phase 3: 方案 B（工具 Worker 化，支持第三方注册）
```

---

## 三、组件详解（以方案 A Phase 1 视角）

### 3.1 MCP 协议处理器

```
/mcp 端点：接收 JSON-RPC 请求
  输入: POST { jsonrpc: "2.0", method: "tools/call", params: { name: "stock_realtime", arguments: { code: "600519" } }, id: 1 }
  处理:
    1. 解析 method → 路由到对应工具处理函数
    2. 调用工具 → 得到结果
    3. 构建 JSON-RPC 响应 → 返回
  输出: { jsonrpc: "2.0", result: {...}, id: 1 }

/stream 端点：SSE 流式连接
  用于 MCP 的 streaming 场景（如 AI 分析结果逐步返回）
  使用 Workers 的 TransformStream 实现
```

MCP 协议方法映射：

| MCP Method | 动作 | 对应工具 |
|------------|------|---------|
| `tools/list` | 列出可用工具 | 返回注册表 |
| `tools/call` | 调用工具 | 路由到处理函数 |
| `resources/list` | 列出资源 | (可选) |
| `resources/read` | 读取资源 | (可选) |
| `prompts/list` | 列出提示词 | (可选) |

### 3.2 工具注册表（KV 存储）

```typescript
// KV key: "tool:stock_realtime"
// Value:
{
  name: "stock_realtime",
  description: "获取股票实时行情",
  inputSchema: { /* JSON Schema */ },
  handler: "inline",       // 或 "fetch:https://..."
  price: 0.001,            // 每次调用价格
  tier: "free",            // free | pro | enterprise
  rate_limit: 100,         // 每分钟上限
}
```

**工具注册类型：**
1. **内联型（inline）**：直接在 Worker 中用 fetch 调用数据源（腾讯、Yahoo）
2. **代理型（proxy）**：转发到外部 HTTP 服务（如 stock_ai_analysis → LLM API）
3. **第三方型（third_party）**：注册外部 MCP 工具 URL（Phase 4 开放）

### 3.3 认证系统

```typescript
// KV key: "apikey:sk_live_xxxxxxxxxxxx"
// Value:
{
  name: "张三",
  tier: "pro",
  balance: 5000,           // 剩余调用次数 / 余额（分）
  created_at: "...",
  last_used: "...",
}
```

认证流程：
```
请求头: Authorization: Bearer sk_live_xxxxxxxxxxxx
  → KV 查找 → 存在且未过期 → 放行
  → 不存在 → 401
```

### 3.4 用量跟踪（D1）

```sql
CREATE TABLE usage_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  api_key TEXT NOT NULL,
  tool_name TEXT NOT NULL,
  call_time INTEGER NOT NULL DEFAULT (unixepoch()),
  price REAL NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'success'  -- success | error | timeout
);

-- 查询语句
SELECT tool_name, COUNT(*) as calls, SUM(price) as cost
FROM usage_log
WHERE api_key = ? AND call_time > ?
GROUP BY tool_name;
```

### 3.5 计费集成（edge-key 联动）

```
用户注册 → 分配 API Key（免费额度 100 次/天）
额度耗尽 → D1 返回超过限额 → Gateway 返回错误
  → 前端引导用户去 edge-key 充值
  → edge-key 回调 → D1 更新额度
```

edge-key 已经是 Workers 服务，直接 service binding 调用即可。

### 3.6 速率限制

```typescript
// D1：分钟级 + 天级双层限流
const minKey = `ratelimit:min:${apiKey}:${Math.floor(Date.now() / 60000)}`;
const dayKey = `ratelimit:day:${apiKey}:${Math.floor(Date.now() / 86400000)}`;

// 使用 D1 原子计数器或 KV 的 TTL

const MIN_LIMIT = { free: 10, pro: 100, enterprise: 1000 };
const DAY_LIMIT = { free: 100, pro: 5000, enterprise: 100000 };
```

---

## 四、stock-mcp-server Workers 化分析

stock-mcp-server 当前 12 个工具按 Workers 友好度分组：

| 工具 | Workers 可行？ | 方案 |
|------|:------------:|------|
| `get_realtime_quote` | ✅ | fetch(Tencent API) 直调 |
| `get_kline` | ✅ | fetch(Tencent API) 直调 |
| `get_stock_info` | ✅ | fetch(Tencent API) 直调 |
| `get_technical_analysis` | ✅ | 纯计算（MA/MACD/RSI/布林带），js 实现 |
| `get_stock_context` | ✅ | 组合以上工具 |
| `analyze_stocks` | ✅ | 批量 fetch |
| `search_stock_news` | ✅ | 搜索引擎 API fetch |
| `check_st_risk` | ✅ | 规则引擎，纯计算 |
| `check_backtest` | ✅ | 纯计算 |
| `get_cache_stats` | ✅ | 内建统计 |
| `get_data_source_health` | ✅ | 内建健康检查 |
| **`analyze_stock_ai`** | ⚠️ | **需要 LLM 调用** — Worker 可 fetch 外部 LLM API |

关键发现：**11/12 个工具可以纯 Workers 实现**。唯一需要 LLM 的 `analyze_stock_ai` 也可以 Workers → fetch(OpenAI API) 完成。

需要重写的模块：
- **腾讯行情**：`tencent.py` → `fetch()` + KV 缓存
- **Yahoo 行情**：`yahoo.py` → `fetch()` + KV 缓存
- **技术分析**：`technical.py` → TypeScript 实现（纯数学，无依赖）
- **回测**：`backtest/*.py` → TypeScript 实现（纯计算）
- **缓存**：`cache.py` → Workers KV 原生 TTL

无需改造的：
- **合约/接口结构**（JSON Schema、错误格式）— 复用协议定义
- **策略配置** — 静态配置

---

## 五、Phase 拆分

| Phase | 内容 | 工期 | 交付物 |
|-------|------|:----:|--------|
| **Phase 0** | 快速验证：Gateway Worker 基础架子（协议解析 + stock-mcp-server HTTP 代理） | 1 天 | 能通过 MCP 协议调通本机的 stock-mcp-server |
| **Phase 1** | 内联化：将股票数据源用 fetch 重写，去掉 Python 依赖，Worker 独立运行 | 2-3 天 | Worker 自带 stock 数据能力，不依赖外部进程 |
| **Phase 2** | 认证+用量+计费：API Key 认证，D1 用量跟踪，edge-key 计费联动 | 2 天 | 用户可注册、调接口、扣费的全链路 |
| **Phase 3** | 开发者门户：文档、Web 控制台、API Key 管理 | 2 天 | 完整的开发者自助平台 |
| **Phase 4** | 第三方工具注册：开放工具注册，支持外部 MCP 转发 | 3-5 天 | MCP Marketplace 雏形 |

---

## 六、关键决策记录（ADR）

### ADR-1：方案 A 作为 Phase 1 目标
- **决策**：Phase 1 采用方案 A（单一 Worker），不作方案 B 的分层
- **理由**：MVP 阶段不需要多 Worker 的复杂度。128MB 足够容纳 12 个工具的代码
- **代价**：未来拆分时需重构工具路由

### ADR-2：用 Workers KV 而非 D1 做活跃认证
- **决策**：API Key 认证走 KV（O(1) 读取），用量计费走 D1（支持 SQL 聚合）
- **理由**：KV 延迟 < 10ms，认证是每次请求必经路径，必须快
- **代价**：需注意 KV 的 eventual consistency（最多 60s 延迟），对认证场景可接受

### ADR-3：技术分析算法在 Workers 内用 TS 重写
- **决策**：不依赖外部 Python，将所有算法移植到 TypeScript
- **理由**：MA/MACD/RSI/布林带/Ichimoku/K线形态 都是纯数学，无外部依赖，TS 实现 200 行内
- **代价**：需要维护两套代码（直到 Python 版下线）

### ADR-4：不直接在 Workers 上实现 analyze_stock_ai
- **决策**：LLM 调用走 HTTP fetch 到外部 API，不在 Workers 内运行 LLM
- **理由**：Workers 的 Workers AI 尚不支持 stock-mcp-server 所需的模型（deepseek-v4-flash 等）
- **代价**：额外的一次 HTTP 网络延迟（100-500ms）

### ADR-5：计费幂等设计（防刷）
- **决策**：每次工具调用请求携带可选的幂等键 `idempotency_key`，D1 中 UNIQUE 约束防重复记账
- **理由**：网络重试、客户端重连可能导致同一笔调用被多次计费
- **实现**：Gateway 检查 `usage_log` 中是否已存在相同 `idempotency_key`，存在则返回缓存结果不计费
- **代价**：需要客户端配合传幂等键；不传时走常规路径（最终一致性）

### ADR-6：API Key 安全策略
- **决策**：Key 使用 `sk_live_` 前缀区分环境，KV 存储时用 PREFIX 隔离
- **理由**：防止开发/生产 Key 混用，KV 前缀扫描可快速批量操作
- **实现**：Key 前缀校验：`^sk_(live|test)_[a-f0-9]{32}$`

---

## 七、风险与缓解

| 风险 | 概率 | 影响 | 缓解 |
|------|:----:|:----:|------|
| Workers 10ms CPU 限制 | 高 | 高 | Workers Paid 计划 30s CPU，或交易数据用边缘 KV 缓存 |
| 腾讯 API 限流 | 中 | 中 | 多数据源 fallback（腾讯→mootdx→Yahoo）已有 |
| MCP 协议标准变更 | 低 | 高 | 协议适配层隔离，变更时只需改 Gateway 不涉及工具 |
| 用户 API Key 泄露 | 中 | 高 | 即时吊销、按 Key 限流、IP 白名单可选 |
| edge-key 计费延迟 | 低 | 中 | 异步结算+预付费模式，先扣额度再提供服务 |
