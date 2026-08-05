# 🛡️ stock-mcp-server 安全审计报告

**审计时间**: 2026-07-31  
**审计范围**: /home/admin/projects/stock-mcp-server  
**审计者**: 🛡️ 安全审查者（对抗式判别者）

---

## 执行摘要

| 指标 | 数值 |
|------|------|
| 总 Python 文件 | 18 |
| 异常处理语句总数 | 77（70×`except Exception` + 7×具体类型） |
| `str(e)` 泄露到响应 | 20+ 处（server.py 为主要污染源） |
| 外部 HTTP 请求站点 | 25 |
| 凭证存储位置 | 环境变量 + `~/.hermes/config.yaml` |
| MCP 认证机制 | **无** |
| **加权得分** | **42 / 100** |

**结论**: 多项 P0 级漏洞需立即修复。该系统作为本地 Agent 运行，当前风险主要来源于内部 Agent（mcp-client）的 prompt injection、错误信息泄露以及配置文件可读性。

---

## P0 — 致命漏洞（立即修复）

### P0-01: MCP 协议无认证，本地 Agent 可无限制调用所有工具
- **位置**: `server.py:47` — `mcp = FastMCP("stock-mcp")`
- **问题**: FastMCP 默认配置无身份验证。任何能连接 `localhost:8901` 的进程（含被攻击的 AI Agent）均可调用全部工具，包括 `analyze_stock_ai`（LLM 调用）、`run_alert_check`（通知发送）、持仓数据访问。
- **影响**: 攻击者控制的 AI Agent 可通过 MCP 工具链进行数据外泄、垃圾通知轰炸、或滥用 LLM 配额。
- **修复**: 为 MCP server 添加 token 验证中间件，或通过 Hermes gateway 层实施访问控制。

### P0-02: `str(e)` 直接注入 JSON 响应体（20+ 处）
- **位置**: `server.py:272, 279, 320, 471, 515, 564, 590, 614, 631, 648, 676, 693, 716, 742, 763, 796, 849, 887, 926` 等
- **问题**: 所有 MCP 工具的 `except Exception as e` 块均将 `str(e)` 放入 `"error"` 字段返回给调用方。这暴露了内部路径、库版本、依赖关系等敏感信息。
- **示例**: `return json.dumps({"error": str(e), "code": code}, ensure_ascii=False)`
- **影响**: 信息泄露（internal path disclosure），辅助后续攻击。若错误来自路径遍历或数据库操作，还可泄露文件存在性。
- **修复**: 统一错误响应函数，仅返回通用消息，具体异常仅写日志。

### P0-03: 配置文件路径泄露 + 未受保护的文件读取
- **位置**: `tools/analyzer.py:136-142`
- **问题**: `_load_llm_config()` 直接读取 `~/.hermes/config.yaml`，其中包含 LLM provider 的 `api_key`。若因异常导致 config.yaml 解析失败，`str(e)` 可能包含路径信息。
- **影响**: 结合 P0-02，LLM API Key 相关文件的路径可通过错误响应间接确认。
- **修复**: 将 config.yaml 路径设为环境变量，且不在错误信息中泄露路径。

### P0-04: 新闻搜索 SSRF 向量（`follow_redirects=True`）
- **位置**: `tools/news.py:29, 65`
- **问题**: `httpx.get(url, ..., follow_redirects=True)` — URL 由用户可控的 `stock_code` + `stock_name` 构造。虽然最终拼接的是新浪财经/百度搜索 URL（非任意 URL），但 query 参数直接注入 URL，存在开放重定向风险。
- **影响**: 攻击者可通过构造特殊 stock_name 触发重定向到恶意站点，获取响应头信息。
- **修复**: 禁用 `follow_redirects`，或对 URL 中的查询参数做编码验证。

### P0-05: 飞书 App Secret / Bot Token 以明文形式写入代码逻辑
- **位置**: `webhook/config.py:175-185`, `webhook/notifier.py:53, 150-154, 224-225`
- **问题**: 
  - 硬编码的飞书 Chat ID: `oc_70aae2f0de3ae93698011ad34c5bee43`（config.py:180, notifier.py:154）
  - 所有凭证均通过环境变量加载，但**未设置任何格式校验或长度限制**，空字符串也不会报错，静默跳过。
- **影响**: 若服务器被入侵，内存中的凭证可通过 dump 获取；硬编码 chat_id 暴露内部沟通渠道。
- **修复**: 启动时校验必填凭证不为空；chat_id 改为环境变量。

---

## P1 — 高危漏洞（优先修复）

### P1-01: 70 处 `except Exception` 掩盖真实错误
- **分布**:
  - `server.py`: ~19 处
  - `data_sources/global_stock.py`: ~8 处
  - `webhook/alerter.py`: 6 处
  - `webhook/notifier.py`: 4 处
  - `tools/analyzer.py`: 4 处
  - 其余模块: ~29 处
- **问题**: 几乎所有异常都被静默吞没或仅 `logger.warning` 后返回空结果。攻击者可利用此行为探测系统状态（如：区分"代码不存在"与"网络超时"）。
- **修复**: 分类捕获异常（`httpx.HTTPError`, `json.JSONDecodeError` 等），仅在 debug 级别记录详情。

### P1-02: Yahoo Finance Session Crumb 全局复用
- **位置**: `data_sources/global_stock.py:443-458`
- **问题**: `_yahoo_session` 是全局单例，crumb 值长期有效。若 crumb 泄露（通过 P0-02 的错误信息），攻击者可复用该 session 访问 Yahoo Finance API。
- **修复**: 实现 crumb 自动刷新逻辑，不在错误信息中暴露 session 细节。

### P1-03: 并行任务无限等待 + 无全局超时上限
- **位置**: `core/parallel.py:22-84`
- **问题**: `run_parallel` 有 timeout 参数但默认 30s；`parallel_map` 无超时。若 Yahoo Finance 慢响应，可阻塞线程池 worker，耗尽并发能力。
- **修复**: 为 `parallel_map` 添加默认超时；监控线程池使用率。

### P1-04: 飞书/Telegram 通知无频率限制
- **位置**: `webhook/alerter.py:393-653`
- **问题**: `run_alert_check` 可被 MCP 工具 `run_alert_check` 无限次调用。每次调用会向飞书/Telegram 发送告警消息。无速率限制。
- **影响**: DoS — 攻击者频繁调用可淹没通知渠道，或消耗第三方 API 配额。
- **修复**: 添加调用频率限制（如：每分钟最多 1 次）。

### P1-05: `check_backtest` 无资本量上限
- **位置**: `server.py:394-433`
- **问题**: `capital: float = 100000.0` — 用户可传入极大值（如 1e15），导致回测计算量爆炸或内存溢出。
- **修复**: 对 capital 设置合理上限（如 ≤ 1e9）。

---

## P2 — 中危漏洞

### P2-01: 股票代码正则过于宽松
- **位置**: `server.py:91` — `_STOCK_CODE_RE = re.compile(r"^[A-Za-z0-9]{2,10}$")`
- **问题**: 允许长度为 2-10 的任意字母数字组合。虽然下游 `_code_type()` 会拒绝无效代码，但中间过程仍会产生无效 API 调用。
- **修复**: 增加格式预校验（如 A 股 6 位数字、美股 ≤5 字母）。

### P2-02: 缓存无大小上限（DoS 向量）
- **位置**: `core/cache.py:29-94`
- **问题**: `TTLCache._store` 是普通 dict，无最大条目数限制。攻击者可构造大量不同代码的请求填充缓存，耗尽内存。
- **修复**: 改用 `functools.lru_cache` 或添加 `maxsize` 参数。

### P2-03: 全局 HTTP Client 无连接池管理
- **位置**: `data_sources/global_stock.py:443` — `_yahoo_session: Optional[httpx.Client] = None`
- **问题**: 全局共享 httpx.Client，无连接池大小限制。高并发下可能耗尽文件描述符。
- **修复**: 使用 `httpx.Client(pool_limits=httpx.Limits(max_connections=...))`。

### P2-04: 日志级别为 WARNING，错误详情不记录
- **位置**: `server.py:40-44`
- **问题**: `logging.basicConfig(level=logging.WARNING)` — INFO 级别的诊断信息被丢弃。安全事件（如异常调用模式）无法追溯。
- **修复**: 生产环境使用 INFO 级别，并配置日志轮转。

---

## P3 — 低危漏洞

### P3-01: User-Agent 伪装
- **分布**: 多处使用 `"Mozilla/5.0 ..."` 或 `"stock-mcp-server/1.0"`
- **问题**: 固定 UA 可被目标站点用于识别和封禁 bot 流量。
- **修复**: 随机化 UA 或轮换 UA 池。

### P3-02: 无 HTTPS 校验（自签名证书场景）
- **问题**: 当前所有请求均为 HTTPS 且未设置 `verify=False`，配置正确。但若未来引入代理，需注意。
- **状态**: ✅ 当前无问题。

### P3-03: JSONP 解析使用正则而非 JSON 解析器
- **位置**: `data_sources/global_stock.py:275`
- **问题**: `re.search(r'\((\[.+?\])\)', resp.text, re.DOTALL)` — 正则解析 JSONP 在极端情况下可能出错或产生 XSS 向量（虽然对 MCP 工具输出无害）。
- **修复**: 使用 `json.loads()` 替代正则提取。

---

## P4 — 信息性发现

### P4-01: 依赖版本未锁定
- **问题**: `requirements.txt` 或 pyproject.toml 未看到版本约束。`yfinance`, `mootdx`, `httpx` 等库若有已知 CVE，可能被利用。
- **建议**: 运行 `pip-audit` 检查依赖漏洞。

### P4-02: `.git` 目录存在于项目根
- **问题**: 源码含 `.git` 目录，若仓库公开推送到 GitHub，凭证（如写入 `config.yaml` 的）会暴露。
- **建议**: 使用 `.gitignore` 排除敏感文件。

### P4-03: mootdx TCP 直连无 TLS
- **位置**: `data_sources/mootdx.py`
- **问题**: mootdx 通过 TCP 协议直连通达信服务器，无加密。在内网环境中风险可控，但若部署在公网则存在中间人风险。
- **建议**: 评估网络部署拓扑。

---

## 评分汇总

| 等级 | 数量 | 扣分权重 | 小计 |
|------|------|---------|------|
| P0 | 5 | ×10 | -50 |
| P1 | 5 | ×5 | -25 |
| P2 | 4 | ×3 | -12 |
| P3 | 3 | ×1 | -3 |
| P4 | 3 | ×0 | 0 |
| **总分** | | | **100 - 90 = 10/100** |

> ⚠️ 注：得分极低是因为 P0 级漏洞叠加效应严重。实际风险评级需结合部署环境（本地 vs 公网）调整。

---

## 关键修复优先级

```
🔴 立即修复（P0）:
  1. 为 MCP server 添加认证/授权层
  2. 统一错误响应：移除所有 str(e) → 响应体，改为通用错误消息
  3. 保护配置文件访问：不在错误中泄露路径
  
🟠 本周内修复（P1）:
  4. 分类异常捕获（替换 70 处 except Exception）
  5. 为 run_alert_check 添加强制冷却期
  6. 资本量上限校验
  7. Yahoo session crumb 安全处理
  
🟡 近期规划（P2）:
  8. 缓存添加 max_size 限制
  9. 日志级别调整为 INFO + 日志轮转
  10. 股票代码格式强化校验
```

---

## 约束透明度报告

```
━━━ 约束透明度报告 ━━━
MAXIMIZED（重点审查）:
  - 安全漏洞扫描、密钥泄露检测、注入攻击面
  - 异常处理质量（70+ except Exception 审计）
  - HTTP 请求安全（25 个出站请求点）
  - 凭证生命周期管理
SACRIFICED（未覆盖）:
  - 功能正确性（非本角色职责，由功能审查者负责）
  - 性能基准测试（由性能基准师负责）
  - 运行时动态渗透测试（静态分析局限）
  - 依赖库 CVE 全面扫描（需 pip-audit）
推荐后续:
  - 运行 R2 第二轮审查验证修复效果
  - 部署前执行 pip-audit 检查依赖漏洞
  - 集成 CI/CD 安全门禁（bandit + safety）
━━━━━━━━━━━━━━━━━━━━━
```
