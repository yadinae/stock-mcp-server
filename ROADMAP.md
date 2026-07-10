# 🗺️ MCP Gateway 开发路线图

> 项目：MCP Gateway（Cloudflare Workers 版 stock-mcp-server）
> 端点：`https://mcp-gateway.yadinae.workers.dev`
> 更新：2026-06-30

---

## ✅ 已完成

| # | 事项 | 等级 | 说明 | 模块 |
|:-:|:-----|:----:|:-----|:-----|
| 1 | **缓存+并行化** | 🔴 P0 | in-memory L1 + KV L2 双层缓存；数据源并行请求 | `cache.ts` |
| 2 | **请求频率限制** | 🔴 P0 | per-key 限频（60req/min + 5000req/day），D1 持久化 | `rate_limit.ts` |
| 3 | **请求日志/审计追踪** | 🟡 P1 | 每次 tools/call 记录到 D1，GET /logs 查询 | `audit_log.ts` |
| 4 | **用量追踪与计费** | 🟡 P1 | daily/monthly 聚合，20 工具计价模型（0-5 credits） | `usage.ts` |
| 5 | **MCP Resources 支持** | 🟡 P1 | resources/list + resources/read；7 种资源 URI | `index.ts` |
| 6 | **管理 Dashboard** | 🟡 P1 | 暗色主题 Web 面板，5 个标签页（工具/用量/日志/Key/监控） | `index.ts` |
| 7 | **MCP Prompts 支持** | 🟡 P1 | prompts/list + prompts/get；6 个预设分析模板 | `prompts.ts` |
| 8 | **Webhook 通知** | 🟢 P3 | 飞书/TG 推送：持仓预警、ST 异动、ETF 信号 | `webhook/` |
| 9 | **美股港股数据增强** | 🟢 P3 | 整合 Yahoo Finance 数据，12 个新工具 | `yahoo.ts`, `sources/` |
| 10 | **请求重试与断路器** | 🟡 P2 | 10 个数据源独立熔断配置，已接入工具调用流程 | `circuit_breaker.ts` |
| 11 | **跨实例监控指标** | 🟡 P2 | KV 聚合，每 50 次调用 + Dashboard 访问 checkpoint | `metrics.ts` |
| 12 | **多 API Key 管理** | 🟡 P2 | admin.ts 完整 CRUD（创建/吊销/列 Key/按 Key 查用量） | `admin.ts` |
| 13 | **TradingView 工具移植** | 🟡 P2 | 6 个 TV 工具通过 Durable Objects 运行，替代本地 tv-bridge | `tv-do/` |
| 14 | **KV → D1 迁移** | 🟡 P2 | rate_limit/audit_log/usage 全迁移到 D1，KV 写入归零 | 多处 |

---

## 🟡 P2 — 待办（按优先级）

| # | 事项 | 说明 | 预估 |
|:-:|:-----|:-----|:----:|
| 1 | **edge-key 发卡系统对接** | 支付完成自动创建 API Key；等 edgeKey 自身完善后再推进 | 2d |
| 2 | **监控集成 / Grafana** | Workers 指标接入外部可视化（目前有面板级监控） | 2d |
| 3 | **第三方 MCP 工具注册** | 开放外部工具注册到 Gateway，支持权限隔离 | 3d |

---

## 🔮 远期规划

| # | 事项 | 说明 |
|:-:|:-----|:-----|
| 1 | **SSE streaming** | MCP 协议 Server-Sent Events 流式支持 |
| 2 | **多区域部署** | 美/欧/亚多区域 Workers，降低延迟 |
| 3 | **用量计费正式版** | 对接支付宝/微信支付，按量计费 |
| 4 | **OpenTelemetry 集成** | 接入 Cloudflare Observability |

---

*P0/P1 全部完成。P2 按需推进。*
