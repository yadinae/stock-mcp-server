# 2026-10-29 · OpenRung 本地代理接入 stock-mcp-server 双代理故障转移

- **来源会话**：@session:default/20261029_183522_879f189d
- **类型**：决策 / 实现
- **涉及文件**：`core/proxy.py`（⚠️ 仅 working tree，未提交）、`/etc/systemd/system/openrung.service`

## 问题

stock-mcp-server 的数据采集此前只有 Webshare 单一代理（10 个 IP 轮换，`~/.hermes/secrets/webshare.json`）。单点故障：Webshare 挂了或被封，全部 data_sources 直连或失败。需要一条免费、可常驻的降级链路。

## 权衡

| 方案 | 优点 | 代价 | 结论 |
|---|---|---|---|
| OpenRung 客户端本地 loopback 代理（**选用**） | 永久免费、GPL-3.0、VLESS+REALITY 伪装 TLS；systemd `Restart=always` 常驻；混合 HTTP/SOCKS 代理 127.0.0.1:17890，`ProxyHandler` 直接可接 | 出口 IP 随 relay 轮换（当天实测 3 个不同出口：188.245.27.90 / 88.198.149.218 / 2.28.70.17） | ✅ |
| 在 VPS 上跑 OpenRung 中继（volunteer） | 贡献网络容量 | 官方明示：中继出口节点 IP 就是你的 IP，法律/隐私风险等同 Tor 出口 | ❌ 业务机不做 |
| 只留 Webshare 单代理（现状） | 出口 IP 稳定 | 无冗余，单点故障即全断 | 作为主代理保留 |
| 商业 VPN | 稳定 | 付费闭源，本场景无增量 | ❌ |

## 结论

`core/proxy.py` 从 "Webshare Proxy Manager" 升级为双代理：Webshare 为主，`proxy_request()`/`proxy_urlopen()` 异常经 `_record_failure()` 计数，连续失败 ≥ `PROXY_FAILOVER_THRESHOLD`（默认 3）且 OpenRung 端口存活时切到 `127.0.0.1:17890`；每 60s `_try_recovery()` 探测主代理，恢复自动切回。`proxy_status()` 新增 `using_fallback` / `consecutive_failures` / `fallback_proxy` 三个可观测字段。OpenRung 客户端（`/usr/local/bin/openrung connect -headless`）由 `openrung.service` 托管。

**当日实测（2026-10-29 21:30 复核）：**
1. 主代理出口：经 `get_proxy_opener()` 打 `https://api.ipify.org` → `45.38.107.97` ✅
2. 故障转移：进程内 `_record_failure()` 调 3 次 → `using_fallback=True`、`fallback_proxy=http://127.0.0.1:17890`（第 3 次即触发，阈值行为符合代码）✅
3. 备代理出口：经 17890 打 ipify → `2.28.70.17`；systemd 日志显示 "connected via Nuremberg, Germany"，`ss` 确认 127.0.0.1:17890 LISTEN ✅
4. **代码未提交**：`git status` → `M core/proxy.py`；`git show HEAD:core/proxy.py` 还是旧版 Webshare-only。当前 HEAD = `e45dcd7`。

**遗留风险（未解决，勿当已定案）：**
- `core/proxy.py` 双代理逻辑只存在于 working tree——与本仓库 2026-09-20 笔记（安全加固被迁移 commit 静默 revert）同一风险模式，未 commit 前随时可能丢。
- 真实 Webshare 失败 → 切 OpenRung 的全链路从未在真实故障下观测过，只有进程内模拟。
- 出口 IP 漂移：OpenRung 每次重连可能换 relay，一天 3 个出口。若降级场景是登录态敏感接口（如雪球账号发布），出口漂移可能触发风控。
- 雪球发布管线并未接入本双代理：全机检索未在仓库中找到该管线代码（仅 blog 文章与 cron 输出提及 xueqiu），用户提问时假设它也需要代理，实际对接未做。

**可复用规则**：引入任何外部代理做 fallback，验收三件事——(a) fallback 端口真实存活（ss/nc，不信日志）、(b) 故障转移阈值能在进程内用失败注入复现、(c) 出口 IP 实测是你预期的那个；且双代理代码当天必须 commit，working tree 里的容灾逻辑等于没有。
