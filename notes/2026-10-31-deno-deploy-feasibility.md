# stock-mcp-server 移植到 Deno Deploy 可行性研究（2026-10-31）

## 问题

评估把 stock-mcp-server（Python/FastMCP，152 工具，~33K 行）移植到 deno.com（Deno Deploy）的可行性。

## 关键事实（按重要性排序）

### 1. Deno Deploy 将于 2027 年 4 月左右关停（决定性因素）

Deno 官方公告（deno.com/blog/cloudflare，2026-10-09，Ryan Dahl 署名）：

- **Deno 团队整体加入 Cloudflare**（2026-10-09 宣布）
- **Deno Deploy 继续运营 6 个月后关停** → 约 **2027-04-09** 停止服务；付费客户迁移到 Cloudflare Workers 有迁移支持
- **Deno runtime** 再维护 1 年（每月仅 bug fix + 安全更新），**2027-10 停止开发**
- JSR 继续运营，基础设施迁到 Cloudflare
- rusty_v8 继续支持，目标是整合进 workerd（即 CF Workers 运行时）
- Ryan Dahl 的新方向是 **celld**（celld.dev）：基于 CF Workers 编程模型、可自托管的分布式运行时，重点押注 Durable Objects 做 agent harness

**结论性影响：现在往 Deno Deploy 上投入是往 6 个月后关停的平台投资。此条一票否决"以 Deno Deploy 为长期目标"的方案。**

⚠️ 连带风险：**openllm.yadinae.deno.net 也部署在 Deno Deploy 上**（openllm-deno 项目），同样需要在 2027-04 前迁走。迁移目标大概率就是 Cloudflare Workers（代码已是 workerd 兼容的 TS + Hono，且 CF Workers 原生支持 TDX 的 cloudflare:sockets）。

### 2. TypeScript 移植版已经存在：stock-mcp-gateway

`~/projects/stock-mcp-gateway/` 是 stock-mcp-server 的**同源代码 TS 移植**，已部署在 **Cloudflare Workers**：

- 111 个 MCP 工具（Python 版 152 个，缺口主要在 LLM 审计/缠论/漏斗重活）
- ~21.9K 行 TS，28 个 tools/*.ts + sources/ 数据源适配
- 技术栈：Hono + KV + D1 + Durable Objects + `cloudflare:sockets`（TDX 通达信 TCP 直连）
- 已含 Bearer token 认证、限流、熔断、审计日志、x402 微支付端点、TV WS DO（keepAlive 行情）

**所以"移植到 Deno"的真实工作量 = 把 stock-mcp-gateway 这个 CF Workers 应用迁到 Deno Deploy，而不是从 Python 重写。**

### 3. CF Workers → Deno Deploy 的 API 映射（技术可行性 8/10）

| CF Workers API | Deno Deploy 对应 | 迁移难度 |
|:--|:--|:--|
| D1 (SQLite) | Deno KV（KV 语义，需重写查询）或 Prisma Postgres（openllm-deno 已有完整模式） | 中 |
| KV binding | Deno KV（语义几乎一致） | 低 |
| CF Cache（`cf: cacheTtl` 边缘缓存） | 无等价物 → 进程内 TTL cache（gateway 已有 cache.ts）或 KV | 低 |
| Durable Objects（TV_WS_DO 持久 WS 会话） | 无等价物；出站 WebSocket 支持，但无单例持久化 → 每请求重连 TV WS 或 KV 缓存行情 | 中（功能降级点） |
| `cloudflare:sockets`（TDX TCP:7709） | `Deno.connect` / `Deno.connectTls`（Deploy Classic 文档确认支持出站 TCP；**新平台需实测**） | 低-中 |
| `nodejs_compat` | Deno 自带 Node compat | 低 |
| x402-hono / @x402/evm (npm) | npm: 导入，理论可用，需实测 | 低-中 |
| CF Access 认证头 | 去掉，Bearer-only（gateway auth.ts 本就支持降级） | 低 |

纯逻辑层（16 项技术指标、DCF、回测、TDX 协议编解码）全部零依赖纯 TS，逐字可用。

**预估工作量：1-2 周**（API 适配 3-5 天 + 111 工具对等性回归验证 3-5 天 + 部署接线 1-2 天），改动量 ~3-5K 行。部署管线可复用 openllm-deno 的 staging deploy.ts 模式（已踩过的坑：INCLUDE 白名单、deno.lock、secrets 走 deploy vars）。

### 4. Python 版独有、TS 版没有的能力（若以全功能为准）

- baostock 数据源（Python 库 + 19.5MB 本地 SQLite 缓存）→ Deno 无 baostock 绑定，需换东财/腾讯/TV 替代或自实现协议
- mootdx（通达信 TCP）→ TS 版已有 tdx_protocol.ts 等价实现 ✅
- 漏斗引擎 v2（pandas/numpy 向量化，全市场 5500 股扫描）→ 需纯 TS 重写（gateway 有简化版 strategy_screener）
- 缠论模块（chanlun/*）→ TS 版未移植
- LLM 审计/辩论（agnes_llm）→ 纯 fetch，可直迁
- SQLite 交易日志/观察清单 → KV 或 Postgres

## 权衡

| 方案 | 成本 | 收益 | 风险 |
|:--|:--|:--|:--|
| A. gateway 迁到 Deno Deploy | 1-2 周 | 边缘托管、免费额度 | **平台 2027-04 关停，6 个月后要再迁一次** |
| B. 维持 CF Workers（现状） | 0 | 已上线、功能最全 | 无 |
| C. OpenLLM + gateway 统一迁 CF Workers（2027-04 前） | 中等（主要是 openllm 的 D1/KV/DO 化） | 一次迁移、官方支持迁移 | 时间窗 6 个月，不急 |
| D. 用 celld / workerd 自托管到 VPS | 探索性 | 边缘语义 + 自持 | celld 太新，生态未验证 |

## 结论

1. **技术上可行（8/10）**：TS 代码库已存在（stock-mcp-gateway），平台 API 映射清晰，纯逻辑层零成本，1-2 周可完成迁移。
2. **战略上不推荐现在做**：Deno Deploy 官方确认 6 个月后（~2027-04）关停，现在迁过去等于 6 个月后再被迫迁一次到 CF Workers——而 CF Workers 版 gateway 已经在线上跑着。
3. **真正该做的两件事**（都指向同一方向）：
   - 把 stock-mcp-gateway（CF Workers）当作 Deno 移植的"事实完成态"，继续补它相对 Python 版的缺口（漏斗向量化、缠论、baostock 替代）
   - **制定 openllm-deno 的退出 Deno Deploy 计划**（目标 CF Workers，时间窗 2027-04 前；代码与 stock-mcp-gateway 同栈，迁移经验可直接复用）
4. 如果 6 个月后 Cloudflare 生态出现变数（celld 自托管成熟），届时再做"边缘运行时"选型不迟，代码层面的 TS 化已经完成，不受运行时选择影响。

## 补充（同日追问）：当年选 Deno/下线 gateway 的两条理由，现在还成立吗

1. **"Deno CPU 不计 IO 等待，CF 单次 CPU 不够"——表述需修正，载体已消亡**
   - CF Workers 从来也只计 CPU、不计网络 IO 等待（官方文档原话 "waiting on a database or upstream API does not count"）——这不是 Deno 独有优势，差异只在限额数字。
   - CF 现值（2026-10 实测文档）：paid 默认 30s CPU/请求，可经 wrangler `limits.cpu_ms` 提到 **5 分钟/请求**；cron 30s(<1h)/15min(≥1h)；128MB/isolate 不变；流式响应无 wall-clock 限制。
   - 结论：上限已放宽到对 LLM 网关绰绰有余；且 Deno Deploy（2027-04 关停）已不构成可选项。**这条不再是"选 Deno"的理由。**
2. **yadinae CF 账号从未付费（用户确认）**。2025-04-07 起 DO 开放 free（仅 SQLite-backed；KV-backed 仍需 paid），D1/KV 本就有 free 层——gateway 的 KV+D1+TV_WS_DO 全栈在 free 可跑。**推论：I/O-bound 纯 API 网关可以在 10ms/请求 CPU 内工作**（gateway 在 free 上跑了约 2 个月，89 工具正常响应）。openllm 若要落 CF free 需适配：cron 发现改分片/DO alarm、subrequest≤50/请求、D1 写≤10万/天；$5/月 paid 可全部绕开。

3. **"CF Workers 不支持 TV socket"——根因记错了，且换 Deno 也救不了**
   - 自家 git 记录：2026-06-30 Phase 4 已实现并部署 TV_WS_DO（DO 出站 WS + keepAlive）——CF 技术上支持出站 WS；真正死因是 2026-08-15 commit 记录"**WS通道机房IP风控502**"→ quote/kline/ta/search 全部降级 REST。即 TradingView 对机房 IP（CF AS13335 是爬虫重灾区）反爬封锁，不是运行时能力缺失。
   - Deno Deploy 出口同样是云厂商机房 IP（AWS/GCP），同一风控对象——**换 Deno Deploy 当年也会 502**。VPS 能用是因为阿里云国际 IP 池未被一刀切。
   - 2026-02 起 API 服务商封锁 CF 出口 IP 的案例只增不减，TV 无放宽迹象。
   - 正解：① 走住宅代理出网（Webshare 已接双代理故障转移，gateway 的 TV_BRIDGE 改指代理即可）② TV REST 降级链（已在产）。
   - 结论：**未改变**，属 IP 信誉问题，与 runtime 无关。
3. 实测：`mcp-gateway.yadinae.workers.dev` 探测返回 1042/404 —— workers.dev 子域已禁用或 worker 已删，与"已下线"一致；重测 TV WS 需先重新部署。

## 最终决策（2026-10-31，用户拍板）

**暂不考虑迁移。** 维持现状：stock-mcp-server 继续跑 VPS，gateway 保持下线，openllm-deno 留在 Deno Deploy。若未来重启此话题，先看本笔记再动手（含 CF free/paid 实测限额、全量迁移范围与唯一硬墙=漏斗 CPU vs free 10ms、CF paid 与 OpenCode Go 的 LLM 额度对比 ≈1/20~1/30）。2027-04 Deno Deploy 关停前，openllm 需要一次真实的平台决策，届时重新评估。

## 遗留风险

- Deno Deploy 新平台（非 Classic）的出站 TCP 支持未实测——若将来选择自托管 Deno，TDX 协议直连需验证
- CF Workers 对 TDX 的 `cloudflare:sockets` 有 75s 超时限制，TDX 长会话需 keepAlive（gateway 已有处理）
- x402 微支付端点在 CF Workers 上已跑通，换运行时需重新过一遍支付流程
