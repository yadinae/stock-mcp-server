# AGENTS.md — stock-mcp-server

股票数据 MCP 服务：Python (`server.py` + `core/` + `tools/`)，HTTP 与 stdio 双模式。

> ⚠️ 本项目涉及行情数据源，仅作个人研究用途，不用于商业用途。

## 笔记位置

本仓库的历史问答与决策记录在 `notes/` 目录：

- `notes/` — 每次重要问答沉淀一篇 `问题 / 权衡 / 结论` 摘要
- 文件命名：`notes/YYYY-MM-DD-<主题slug>.md`
- 索引：`notes/INDEX.md` 按时间倒序列出全部笔记

新会话开始前，如果任务与本项目相关，先读 `notes/INDEX.md`，
再按需读相关笔记，不要依赖模型内置记忆复述已有结论。

## 何时写一篇笔记

一次较长的技术问答结束时（涉及方案选型、踩坑排查、架构决策），
在 `notes/` 新增一篇摘要，正文三段式：

1. **问题** — 当时要解决什么，背景一句话
2. **权衡** — 考虑过的方案与各自的代价
3. **结论** — 最终怎么做、验证结果、遗留风险

结论必须写实际验证过的事实，不写推测。

## 安全红线（改动前必读）

本仓库做过一次完整安全审计，加固项**必须逐项确认仍在**，历史上发生过被静默 revert：

- `core/mcp_auth.py` 的 `EnvBearerVerifier` 必须在位
- HTTP 模式无 `STOCK_MCP_API_KEY` 时 **fail-closed 拒绝启动**
- 默认监听 `127.0.0.1`，不要改回 `0.0.0.0`，不要加公网 IP 白名单
- `tools/news.py` 的 query 参数必须 `quote()` 编码且 `follow_redirects=False`
- 错误响应不得回传 `str(e)` 的路径细节

详见 `notes/2026-09-20-hardening-reverted-by-migration.md`。
凭证一律走项目 `.env`（600，gitignored），禁止硬编码。
