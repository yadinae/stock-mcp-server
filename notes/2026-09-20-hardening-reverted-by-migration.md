# 2026-09-20 · 安全加固被迁移 commit 静默 revert

- **类型**：踩坑排查 / 安全
- **涉及文件**：`core/mcp_auth.py`、`server.py`、`tools/news.py`、`core/cache.py`、`core/parallel.py`
- **证据**：commit `2e6e662` → 被 `76380e7` 迁移 revert → `6550e89` 恢复
- **记录于**：2026-10-18（回填，逐条对照当前代码验证）

## 问题

security-audit run-1 查出两件事，第二件比第一件更棘手：

1. **P0**：MCP HTTP 模式完全没有认证，且监听 `0.0.0.0`，还配了公网 IP
   `8.208.28.70` 白名单 —— 等于服务在公网上裸奔。
2. **P1**：更早的 `2e6e662` commit message 里**声称**做了 URL 编码、LRU 上限、
   deadline 等加固，但后来的 `76380e7` 迁移把这些**整体 revert 掉了**。
   代码库里留着一条"已加固"的 commit 记录，而实际代码没有加固。

## 权衡

| 决策点 | 选项 | 选择与理由 |
|---|---|---|
| 无 API key 时 | 警告后启动 / fail-closed 拒绝启动 | **拒绝启动**。警告会被日志淹没，一旦裸奔无人察觉；宁可启动失败也不要静默暴露 |
| 默认监听 | `0.0.0.0` + IP 白名单 / `127.0.0.1` | **`127.0.0.1`**。白名单是假安全（同源 IP、代理转发都能绕），关端口才是真边界 |
| token 比对 | `==` / 恒定时间比对 | 恒定时间，避免时序侧信道 |
| 被 revert 的 P1 | 重新发明 / 按原 commit message 逐条复原 | 按 message 逐条复原并**当场验证代码里真的有**，而不是相信 message |

## 结论

`6550e89` 恢复了全部加固项。

**2026-10-18 逐条复查，全部仍在位**：

- `core/mcp_auth.py` + `EnvBearerVerifier` 存在
- `server.py` 无 key 时 fail-closed（`STOCK_MCP_API_KEY` 检查在位）
- 默认监听确认为 `127.0.0.1`：`host = os.environ.get("STOCK_MCP_HOST", "127.0.0.1")`。
  注意 `server.py:82` 还有一处 `0.0.0.0` 字样，那只是拼占位 URL 的条件分支
  （`host if host != '0.0.0.0' else '127.0.0.1'`），**不是**生效的默认值 —— 别被 grep 误导
- `tools/news.py` 的 `quote()` + `follow_redirects=False` 在位
- `core/cache.py` 的 `max_size` / `OrderedDict` LRU 在位

**可复用规则**：commit message 是**意图记录，不是状态保证**。一次大规模迁移或
rebase 就能把已提交的加固整块抹掉，而 git log 里那条"已加固"的记录依然好看。
凡是安全加固，要针对**当前工作树**逐项断言（写成可执行的 grep/测试），
每次迁移后重跑一遍，不要相信 commit message 说过做过。
