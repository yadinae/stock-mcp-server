# 🗺️ stock-mcp-server 开发路线图

> 项目：stock-mcp-server (gateway)
> 仓库：https://github.com/yadinae/stock-mcp-server
> 更新：2026-06-17

---

## ✅ 已完成

| # | 事项 | 等级 | 完成日期 | 说明 |
|:-:|:-----|:----:|:--------:|:-----|
| 1 | **缓存+并行化** | 🔴 P0 | 6/13 | in-memory L1 + KV L2 双层缓存；数据源并行请求 |
| 2 | **请求频率限制** | 🔴 P0 | 6/14 | per-key KV 计数器（60req/min + 5000req/day） |
| 3 | **请求日志/审计追踪** | 🟡 P1 | 6/16 | 每次 tools/call 日志到 KV，7d TTL；GET /logs |
| 4 | **用量追踪与计费** | 🟡 P1 | 6/16 | daily/monthly KV 聚合；20 工具计价模型（0-5 credits）；GET /usage/history + /usage/billing |
| 5 | **MCP Resources 支持** | 🟡 P1 | 6/17 | resources/list + resources/read 端点；7种资源 URI（quote/kline/technical/financials/news/context/hot） |
| 6 | **管理 Dashboard** | 🟡 P1 | 6/17 | 暗色主题 Web 面板，4个标签页（工具列表/用量详情/审计日志/Key管理），GET /dashboard |

---

## 🟡 待办

### P1 — 生产关键

*（P1 全部完成 ✅）*

### P2 — 重要

| # | 事项 | 说明 | 预估 |
|:-:|:-----|:-----|:----:|
| 3 | **MCP Prompts 支持** | `prompts/list`、`prompts/get`，暴露预设的股票分析模板 | 1d |
| 4 | **多 API Key 管理** | 对接 edge-key（自动发卡系统），支持创建/撤销 Key、按 Key 分配配额、按账号查看用量 | 2d |
| 5 | **请求重试与断路器** | 后端数据源（Tencent/Yahoo）故障时自动重试、熔断降级，避免单源故障级联 | 2d |

### P3 — 远期

| # | 事项 | 说明 | 预估 |
|:-:|:-----|:-----|:----:|
| 6 | **Webhook 通知** | 飞书/TG 推送：持仓预警、ST 异动、ETF 买入信号 | 2d |
| 7 | **监控集成 / Grafana** | Cloudflare Workers 指标接入，用量/响应时间/错误率可视化 | 2d |

---

## 📡 agent-evolution MCP 服务化（独立项目）

| # | 事项 | 说明 | 状态 |
|:-:|:-----|:-----|:----:|
| 1 | MCP Server v2.1 | Node.js stdio MCP server，已有 execute_plan 工具 | ✅ 已完成，已接入 config.yaml |
| 2 | 增强 execute_plan | 支持更多操作类型（skill 创建/更新、cron 管理） | ⏳ 待推进 |
| 3 | GEP 引擎深度集成 | MCP 工具调用 GEP 进化引擎进行系统优化 | 🔮 调研中 |
| 4 | 部署为 HTTP MCP | 从 stdio 改为 HTTP，支持远程调用 | 🔮 待规划 |

---

*优先级建议：Roadmap 按标注顺序依次推进。每个 P1 事项完成后自动轮替下一个。*
