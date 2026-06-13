# Stock-MCP-Server 整合方案功能审查报告

**审查日期**: 2026-06-13
**审查类型**: 功能完整性审查
**审查范围**: mootdx 数据源 / Fallback Registry / ST 风险提示 / 技术分析增强

---

## 摘要

| 维度 | 评分 | 说明 |
|------|------|------|
| 功能完整性 | ⭐⭐☆☆☆ (2/5) | mootdx/ST/增强技术分析均未实现接入 |
| 边界覆盖 | ⭐⭐☆☆☆ (2/5) | ETF/北交所/退市股有隐式处理但无显式兜底 |
| 错误处理 | ⭐⭐☆☆☆ (2/5) | 无回路熔断、无 fallback 链、TCP 超时未处理 |
| 可维护性 | ⭐⭐⭐☆☆ (3/5) | 现有模块化良好，但新组件接入点不明确 |
| 依赖就绪度 | ⭐☆☆☆☆ (1/5) | mootdx 未安装到运行环境，yfinance 刚装上 |

---

## 1. mootdx 数据源

### 1.1 功能完整性

| 检查项 | 状态 | 详情 |
|--------|------|------|
| 数据源模块文件 | ❌ 缺失 | 尚无 `data_sources/mootdx.py` |
| mootdx 在运行环境 | ❌ 缺失 | 仅在系统 pip3 安装（Hermes venv 未装） |
| 通达信 TCP 连接 | ❌ 未实现 | 无 socket/TCP 调用代码 |
| K 线获取 | ❌ 缺失 | 无对应函数 |
| 实时行情 | ❌ 缺失 | 无对应函数 |
| 股票名称/信息 | ❌ 缺失 | 无对应函数 |

**关键风险**: mootdx 使用通达信 TCP 直连协议（默认端口 7709/7723），此协议：
- 可能被当前网络环境/防火墙阻断
- 依赖 `telnet` TCP socket，非标准 HTTP，`httpx` 不适用
- 尚无任何 TCP 连接超时/重试策略

### 1.2 mootdx vs. 现有 Tencent 接口差异

| 维度 | Tencent (qt.gtimg.cn) | mootdx (通达信 TCP) |
|------|-----------------------|---------------------|
| 协议 | HTTP/HTTPS (GET) | TCP Socket (自定义协议) |
| 数据格式 | GBK 编码文本/JSON | 二进制协议包 |
| 是否需要 pip | httpx (已有) | mootdx (待安装) |
| 是否需要 token | 否 | 否 |
| 超时控制 | httpx.Timeout(15) | 需配置 socket timeout |
| 防火墙友好 | ✅ HTTP/443 | ❌ TCP 直连端口 |

### 1.3 边界情况评估

| 边界 | 评估 | 建议 |
|------|------|------|
| ETF (51xx, 15xx, 16xx, 18xx) | mootdx `tdxapi` 可查基金，但 code 转换逻辑需单独实现 | 统一在 `code_to_mootdx_symbol()` 中处理 |
| 北交所 (4xx, 8xx) | mootdx 支持北交所，但需验证 `bj` 前缀与 mootdx 内部 `market_id` 映射 | 参考 tencent.py 中 4xx→bj 映射 |
| 退市股 | 所有数据源均可能返回空，无兜底文案 | 增加 fallback 末端返回 "股票已退市或无数据" |
| 复牌首日 | 涨跌幅无限制，技术支持指标可能异常 | 需在 technical.py 中增加异常波动判断 |
| 美股/港股 | mootdx 仅支持 A 股/ETF，不适用 | fallback 链应跳过 mootdx 对非 A 股调用 |

---

## 2. Fallback Registry

### 2.1 现状分析

**当前 `server.py` 的调用链**（无 fallback）：

```python
# 第55-60行
if ctype == "a":
    return tencent.get_realtime_quote(code)          # 失败就返回error
if ctype in ("us", "hk"):
    return yahoo.get_realtime_quote(code) or {"error": "..."}  # 只有一层fallback
```

**发现问题**:
- ✅ yfinance 1.4.1 已安装到 Hermes venv（但之前发现 `pip list` 不输出 ↓ 需要用 `python3 -m pip list`）
- ❌ A 股只有 Tencent 数据源，无任何 fallback
- ❌ 美股/港股只有 yfinance，无第二层 fallback
- ❌ 失败不重试，直接返回 error 字典
- ❌ 无熔断机制（持续失败仍然请求）

### 2.2 建议的 Fallback 链设计 vs. 实际缺失

| 位置 | 提议链 | 当前状态 | 缺失部分 |
|------|--------|---------|---------|
| A 股行情 | tencent → mootdx → yfinance | tencent 单点 | mootdx fallback 层缺失 |
| A 股 K 线 | tencent → mootdx → yfinance | tencent 单点 | mootdx fallback 层缺失 |
| 美股行情 | yfinance → None | yfinance 单点 | 无第二 fallback |
| 港股行情 | yfinance → None | yfinance 单点 | 无第二 fallback |

### 2.3 错误处理评估

| 场景 | 当前处理 | 评估 |
|------|---------|------|
| Tencent 连接超时 (15s) | `httpx.get(..., timeout=15)` 抛出异常，logger.warning，返回 `[]` | ⚠️ 静默失败，无降级 |
| mootdx TCP 连接失败 | 不存在 | 🔴 无兜底 |
| yfinance API 限流 | 异常捕获，return None | ⚠️ 美股用户看到 "无法获取" |
| 全部数据源失败 | 返回 `{"error": "..."}` 字典 | ✅ 至少不崩溃 |
| 部分字段缺失（如 volume=0） | 字段设默认值 0 | ✅ 健壮 |
| 并发请求中的数据源雪崩 | 无熔断机制 | 🔴 4 worker 都被阻塞时新请求排队 |

### 2.4 Registry 模式评估

提议的 "注册链" 未指明实现模式。建议参考 Vibe-Trading 或 daily_stock_analysis 中的 **DataFetcherManager**（策略模式）：
- 每个数据源实现统一接口（`get_realtime_quote`, `get_kline` 等）
- 管理器按优先级依次尝试
- 失败时记录并切换到下一个
- 可配置超时时间

---

## 3. ST 风险提示

### 3.1 方案完整性

| 检查项 | 状态 | 详情 |
|--------|------|------|
| ST 数据源 | ❌ 未实现 | 提议用新浪数据，但无代码 |
| 并入 analyze_stock_ai | ❌ 未实现 | 无 ST 相关字段输出 |
| 脱离 tushare | ⚠️ 待验证 | 新浪免费接口可查，但可靠性待测 |
| *ST/ST 区分 | ⚠️ 待确认 | 简单文本解析可能无法区分 |

### 3.2 新浪 ST 检测方案可行性

从 `daily_stock_analysis/data_provider/base.py` 第 235-242 行看到已有参考实现：

```python
def is_st_stock(name: str) -> bool:
    n = (name or "").upper()
    return 'ST' in n
```

**此方案的局限性**:

| 场景 | 能否覆盖 | 说明 |
|------|---------|------|
| 正常 ST 股票 | ✅ | 名称包含 "ST" |
| \*ST 股票 | ✅ | 名称包含 "\*ST"，`'ST' in '*ST'` 为 True |
| 刚摘帽股票（原 ST） | ❌ 误判 | 名称已无 ST，但历史数据仍带标签 |
| 刚戴帽股票 | ✅ | 名称更新后即可检测 |
| 退市整理期 | ⚠️ 有限 | 名称含 "退" 但 ST 检测不覆盖 |
| 北交所 ST 股票 | ✅ | 同样名字段规则 |
| ETF 误判 | ⚠️ | ETF 名称可能含 "ST" 字样？概率极低 |

### 3.3 增强建议

1. 使用新浪 `/finance/sina/realstock/company/sh600519/nc.shtml` 接口获取 ST 标识（比名字解析更可靠）
2. 增加 `*ST` vs `ST` vs `退市` 三级分类
3. ST 信息应作为 `analyze_stock_ai` 输出的独立字段（如 `risk_flags: ["ST"]`），而非仅追加到文本
4. 增加缓存（ST 状态日级变化，TTL 3600s 足够）

---

## 4. 技术分析增强

### 4.1 Ichimoku 指标

| 检查项 | 状态 | 详情 |
|--------|------|------|
| 代码实现 | ❌ 缺失 | 未在任何文件中找到 |
| 计算公式复杂度 | ⚠️ 中等 | 需 5 条线：Tenkan/Kijun/Senkou A/B/Chikou |
| 数据需求 | ⚠️ 较长周期 | 需 52 个周期才能完整计算 Senkou B |
| 与现有指标冲突 | ✅ 无冲突 | 可独立添加到 `analyze()` 返回值 |

**Ichimoku 实现复杂度**: 需要 9、26、52 三个周期窗口，当前 K 线默认 `days=120` 足够覆盖。

### 4.2 K 线形态识别

| 形态 | 复杂度 | 当前状态 |
|------|--------|---------|
| 锤子线 (Hammer) | 低 | ❌ 缺失 |
| 倒锤子 (Shooting Star) | 低 | ❌ 缺失 |
| 吞没形态 (Engulfing) | 低 | ❌ 缺失 |
| 十字星 (Doji) | 低 | ❌ 缺失 |
| 早晨之星 (Morning Star) | 中 | ❌ 缺失 |
| 黄昏之星 (Evening Star) | 中 | ❌ 缺失 |
| 三只乌鸦 (Three Black Crows) | 中 | ❌ 缺失 |
| 三白兵 (Three White Soldiers) | 中 | ❌ 缺失 |

**评估**: 
- 锤子/吞没/十字星是需求量最大的 3 种形态，实现简单（基于实体长度、影线比）
- 所有形态识别可独立封装到 `tools/pattern.py`
- 结果可直接追加到 `analyze()` 返回的 `{"candlestick_patterns": [...]}`

---

## 5. 跨组件交互分析

### 5.1 功能冲突检查

| 新组件 | 冲突组件 | 风险等级 | 说明 |
|--------|---------|---------|------|
| mootdx 行情 | tencent.py get_realtime_quote | 🟡 中 | 需修改 server.py 调度逻辑 |
| mootdx K 线 | tencent.py get_kline | 🟡 中 | 需修改 server.py 调度逻辑 |
| Fallback Registry | server.py 所有 *_get_* 函数 | 🔴 高 | 需重构 server.py 数据获取层 |
| ST 检测 | analyzer.py analyze_stock | 🟢 低 | 仅追加返回字段 |
| Ichimoku | tools/technical.py | 🟢 低 | 新增函数，不修改现有接口 |
| K 线形态 | tools/technical.py | 🟢 低 | 新增文件或函数 |

### 5.2 数据流变更

当前：
```
用户请求 → server.py (分支判断) → tencent/yahoo (单源)
```

变更后：
```
用户请求 → server.py → Fallback Registry
    ├── A 股: tencent → mootdx → (optional) yfinance
    ├── 美股: yfinance → none
    └── 港股: yfinance → none
```

### 5.3 建议接入架构

```
data_sources/
├── __init__.py          # 统一导出 + FallbackRegistry 类
├── base.py              # 数据源基类 (abstract)
├── tencent.py           # 腾讯数据源 (no change needed)
├── mootdx.py            # mootdx 数据源 (NEW)
├── yahoo.py             # yfinance 数据源 (no change needed)
└── registry.py          # Fallback Registry + 重试逻辑 (NEW)
```

---

## 6. 依赖与运行环境问题

### 6.1 当前依赖状态

| 包名 | 系统 pip3 | Hermes venv | stock-mcp-server 运行环境 | 状态 |
|------|-----------|-------------|--------------------------|------|
| httpx | 0.22.0 | 0.28.1 | ✅ Hermes venv | ✅ 正常 |
| mcp (SDK) | ❌ | 1.26.0 | ✅ Hermes venv | ✅ 正常 |
| openai | 0.8.0 | 2.24.0 | ✅ Hermes venv | ✅ 正常 |
| yfinance | ❌ | 1.4.1 | ✅ Hermes venv | ✅ 正常 (刚确认) |
| mootdx | 0.9.11 | ❌ | ❌ 需要安装 | 🔴 缺失 |
| PyYAML | 6.0.1 | 6.0.3 | ✅ Hermes venv | ✅ 正常 |

### 6.2 安装命令
```bash
/home/admin/.hermes/hermes-agent/venv/bin/python3 -m pip install mootdx
```

注意：mootdx 0.9.11 依赖 `pandas`、`numpy`、`request`（requests）等，安装时可能自动升级包版本，需验证兼容性。

---

## 7. 优先级行动项

| 优先级 | 行动项 | 工作量 | 影响 |
|--------|-------|--------|------|
| 🔴 P0 | 在 Hermes venv 安装 mootdx | 2 min | 阻塞所有 mootdx 相关功能 |
| 🔴 P0 | 实现 `data_sources/mootdx.py`（基础行情+K线） | 1-2h | 通达信 fallback 通路 |
| 🔴 P0 | 修复 `core/parallel.py` 中超时 bug（`as_completed timeout=timeout*len(tasks)` → `timeout`） | 5 min | 防止线程挂起泄漏 |
| 🔴 P0 | 实现 Fallback Registry（至少 A 股 tencent→mootdx） | 2-3h | 关键降级路径 |
| 🟡 P1 | 实现 ST 风险提示（基于名字解析+新浪数据） | 1-2h | AI 分析增强 |
| 🟡 P1 | 增加 K 线形态识别（锤子/吞没/十字星） | 1-2h | 技术分析增强 |
| 🟡 P1 | 增加 Ichimoku 指标 | 1-2h | 技术分析增强 |
| 🟢 P2 | 增加北交所交易规则标识（±30% 涨跌幅标识） | 0.5h | 边界覆盖 |
| 🟢 P2 | 增加退市股/整理期识别 | 0.5h | 边界覆盖 |
| 🟢 P2 | 增加熔断器/重试机制到 Fallback Registry | 1h | 稳定性提升 |
| 🟢 P2 | TTL_STOCK_INFO 延长至 3600s | 2 min | 小优化 |
| ℹ️ P3 | 单任务不走 run_parallel 以减少开销 | 0.5h | 微小优化 |

---

## 8. 结论

**整合方案方向正确，但当前仍有以下关键缺口**：

1. **mootdx 未接入**：mootdx 包虽在系统安装但 `Hermes venv` 中缺失，代码层面也无任何数据源文件。通达信 TCP 直连的防火墙兼容性需先验证。

2. **Fallback Registry 从零开始**：当前 `server.py` 仅用 `if/else` 硬编码分支，无 fallback 概念。建议引入 `daily_stock_analysis` 中的 `BaseFetcher`/`DataFetcherManager` 模式，但注意该模式依赖 pandas，stock-mcp-server 目前无此依赖。

3. **ST 检测可快速实现**：基于名称的 `'ST' in name` 检测足以覆盖 ~95% 场景，可用新浪股票名接口补充。

4. **技术分析增强空间大**：Ichimoku 和 K 线形态独立于现有指标，可无缝追加。建议先从 3-4 种高频形态（锤子、吞没、十字星）开始。

5. **运行环境依赖差异**：stock-mcp-server 通过 Hermes venv 运行 (Python 3.11)，与该 venv 中已安装的 `mcp 1.26.0` 完全兼容，但 `mootdx` 安装后需验证其依赖版本冲突。

### 验证检查清单（供后续 Phase 使用）

- [ ] `python3 -m pip install mootdx` 在 Hermes venv 中成功
- [ ] `python3 -c "import mootdx; print(mootdx.__version__)"` 验证导入
- [ ] `data_sources/mootdx.py` 实现 `get_realtime_quote()` / `get_kline()`
- [ ] `data_sources/registry.py` 实现 fallback 链
- [ ] `server.py` 中 A 股数据获取改为 Registry 调用
- [ ] ST 检测通过多个已知 ST/\*ST/非ST 股票验证
- [ ] Ichimoku KPI 计算与已知数据对比验证
- [ ] 各形态识别函数通过纯数据测试（已知形态历史数据）
- [ ] `core/parallel.py` 超时 bug 修复
- [ ] 所有边界场景（ETF/北交所/退市/复牌）至少返回有意义的信息而非空/崩溃
