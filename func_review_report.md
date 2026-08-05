# Stock-MCP-Server 功能审查报告

> 审查时间: 2026-07-31 | 审查者: 🔌 功能审查者 (Discriminator-Functionality)
> 项目路径: /home/admin/projects/stock-mcp-server
> 代码规模: ~6000行Python, 28个MCP工具, 953行server.py

---

## 执行摘要

**加权总分: 62/100**（满分100，分数越低问题越严重）

| 维度 | 评分 | 说明 |
|------|------|------|
| 工具完整性 | 85/100 | 28工具覆盖全，但部分工具缺少缓存 |
| 数据源Fallback链 | 60/100 | 主要有fallback，但全局层未集成 |
| Cache Invalidation | 40/100 | 无主动失效机制，仅依赖TTL过期 |
| Alerter停止根因 | 75/100 | 非交易日静默退出，功能正常 |
| MCP Tool Registration | 90/100 | 注册无遗漏，但命名规范需统一 |
| 代码质量 | 35/100 | 104处bare except，无输入校验中间件 |

---

## P0 级问题（必须修复，阻断功能）

### P0-1: Cache Invalidation 缺失 — 影响数据新鲜度
**位置**: `core/cache.py`, `data_sources/*.py`
**问题**: 
- 缓存只有 TTL 自动过期，无任何主动 invalidate 机制
- 当腾讯 API 字段结构变更（如新增字段导致索引偏移）时，旧缓存持续使用错误数据
- 股票名称、退市状态等元数据变化后无法感知
**影响**: 可能导致告警系统基于过时数据触发误报或漏报
**建议**: 
```python
# 添加 version key 到 cache key
cache_key = make_cache_key("tx_realtime", code, api_version="v2")
# 或提供 invalidate_by_prefix(code) 方法
```
**权重**: 0.25 × 10 = 2.5分扣分

### P0-2: 全局层无 Tencent → Yahoo Fallback — 美股港股断裂
**位置**: `server.py` `_get_realtime_quote()`, `_get_kline()`
**问题**: 
- A股有 tencent→mootdx fallback（`tencent.py:159-171`）
- 美股港股只调 yahoo，无 eastmoney/global_stock fallback
- `global_quote()` 工具内部有 sina→tencent→eastmoney fallback，但主流程未用
**影响**: Yahoo Finance 被墙时，美股港股所有工具完全失效
**建议**: 
```python
def _get_realtime_quote(code: str):
    if ctype == "a":
        return tencent.get_realtime_quote(code)  # 已有 mootdx fallback
    if ctype in ("us", "hk"):
        result = yahoo.get_realtime_quote(code)
        return result or global_stock.global_quote(code)  # 缺此fallback
```
**权重**: 0.20 × 10 = 2.0分扣分

---

## P1 级问题（高风险，严重影响可用性）

### P1-1: 104处 bare except 掩盖真实错误
**位置**: 全项目
- server.py: 20处（含 `run_alert_check`, `get_global_quote` 等关键工具）
- tencent.py: 2处
- alerter.py: 14处  
- global_stock.py: 多数
- tools/*.py: 6处
**问题**: `except Exception as e:` 吞掉所有错误，只返回 `{"error": str(e)}`，无法区分：
- 网络超时 vs API限流 vs 数据解析失败 vs 业务逻辑错误
**影响**: 故障排查困难，生产环境几乎无法定位问题根因
**建议**: 按异常类型分类：
```python
except (httpx.TimeoutException, httpx.ConnectError) as e:
    return json.dumps({"error": f"网络超时: {e}", "retry": True})
except ValueError as e:
    return json.dumps({"error": f"数据格式错误: {e}", "retry": False})
except Exception as e:
    logger.error(f"未知错误: {e}", exc_info=True)
    return json.dumps({"error": "内部错误"})
```
**权重**: 0.15 × 8 = 1.2分扣分

### P1-2: Alertelevel_name 与 max_level 不一致 — ST风险级别显示错误
**位置**: `webhook/alerter.py:578-624`
**问题**:
```python
def _simple_st_risk(name, quote):
    ...
    return {
        "max_level": max((s["level"] for s in signals), default=0),  # 正确计算
        "level_name": "正常",  # ← BUG: 硬编码为"正常"，忽略max_level
        ...
    }
```
**影响**: 即使检测到ST/*ST/退市股票（max_level=3），告警消息仍显示"正常"
**建议**: 
```python
"level_name": ["正常", "关注", "警告", "高风险"][max_level] if max_level > 0 else "正常"
```
**权重**: 0.12 × 8 = 0.96分扣分

### P1-3: 北交所(4/8开头)支持不完整
**位置**: `tencent.py`, `mootdx.py`, `server.py`
**问题**:
- `tencent.py:code_to_tx_symbol()` 正确转换 `bj4xxxx`
- `mootdx.py:_is_supported()` 明确拒绝 `c[0] in ("4", "8")`
- 北交所股票走 tencent 源，但 mootdx fallback 不可用
**影响**: 北交所股票无 mootdx fallback，一旦腾讯API不稳定，完全无备选
**建议**: mootdx 支持北交所，或在 tencent fallback 中增加新浪备用
**权重**: 0.10 × 6 = 0.6分扣分

### P1-4: Cron 定时任务引用 mcp__stock_* 但无自动调用入口
**位置**: `.hermes/cron/jobs.json`
**问题**:
- 盘中简报 cron job 引用 `mcp__stock_*` 工具
- 但 server.py 无 HTTP endpoint 供外部调用（仅 MCP stdio）
- alerter 独立运行（`python -m webhook.alerter`），与 MCP server 解耦
**影响**: cron 任务实际运行时可能找不到对应工具，或调用方式错误
**建议**: 确认 cron 是通过 MCP SDK 调用还是直接调用 Python 模块
**权重**: 0.08 × 7 = 0.56分扣分

---

## P2 级问题（中等风险，影响体验）

### P2-1: 技术指标计算重复 — alerter vs technical分析
**位置**: `webhook/alerter.py:149-333` vs `tools/technical.py`
**问题**: alerter 独立实现了 MA/MACD/RSI/布林带计算，与 `technical.py` 的向量化实现重复
**影响**: 
- 逻辑不同步，同一股票在不同场景输出不同结果
- 维护成本双倍
**建议**: alerter 应复用 `tools.technical.analyze()` 或提取公共计算模块
**权重**: 0.10 × 5 = 0.5分扣分

### P2-2: Sina 美股行情已禁用但仍被引用
**位置**: `data_sources/global_stock.py:33-38`
**问题**:
```python
def us_quote_sina(ticker: str):
    return {"error": "新浪美股行情受地域限制不可用，请使用 tencent 或 eastmoney 源"}
```
但 `get_global_quote()` 仍支持 `source="sina"` 参数
**影响**: 用户显式指定 sina 时会得到错误响应，误导使用
**建议**: 移除 sina source 选项，或返回明确提示
**权重**: 0.06 × 4 = 0.24分扣分

### P2-3: ETF 池与持仓池重叠未去重
**位置**: `webhook/config.py:196-217`（默认配置）
**问题**: 159949、512010、512660 同时出现在 holdings 和 etf_pool 中
**影响**: alerter 对同一标的检查两次，浪费资源（但已有 `continue` 跳过逻辑）
**建议**: 在 alerter 主循环中过滤，或在配置层去重
**权重**: 0.04 × 3 = 0.12分扣分

### P2-4: 技术分析缓存键不含 days 参数
**位置**: `tools/technical.py`（查看完整实现）
**问题**: 缓存键仅用 `code`，但不同 days 返回不同数据
**影响**: 首次调用 days=60，后续 days=120 仍返回60天数据缓存
**建议**: 缓存键改为 `make_cache_key("tech_analysis", code, str(days))`
**权重**: 0.08 × 5 = 0.4分扣分

---

## P3 级问题（低风险，技术债）

### P3-1: 无重试逻辑（除 LLM 外）
**位置**: 全部数据源请求
**问题**: 
- `analyzer.py` 有 `_call_llm_with_retry()` 指数退避重试
- 其他所有 HTTP 请求无重试，单次超时即返回错误
**建议**: 至少对 tencent/yahoo/global_stock 添加 2次重试 + 1秒退避
**权重**: 0.05 × 4 = 0.2分扣分

### P3-2: Mootdx 客户端无单例缓存
**位置**: `data_sources/mootdx.py:51-54`
**问题**: 每次调用 `Quotes.factory()` 重新建立 TCP 连接
**影响**: 高频调用时连接开销大，且可能触发服务端限流
**建议**: 实现进程内单例或线程池
**权重**: 0.04 × 3 = 0.12分扣分

### P3-3: 无监控指标暴露
**位置**: 全局
**问题**: `get_data_source_health` 工具可查询健康状态，但无 Prometheus/metrics endpoint
**影响**: 无法集成到现有监控系统（Grafana等）
**建议**: 添加 `/metrics` HTTP endpoint 或暴露为 MCP tool
**权重**: 0.03 × 3 = 0.09分扣分

---

## P4 级问题（轻微，可延后）

### P4-1: global_stock.py 953行过度膨胀
**问题**: 单一文件承担行情/K线/财务/资金流/期权/SEC filings搜索等全部全球股票功能
**建议**: 按功能拆分：quotes.py, financials.py, sec.py, search.py
**权重**: 0.02 × 2 = 0.04分扣分

### P4-2: 日志级别过于保守
**问题**: `logging.basicConfig(level=logging.WARNING)`，DEBUG 信息不可见
**影响**: 排查问题时需临时改代码
**建议**: 默认 INFO，通过环境变量 `LOG_LEVEL=DEBUG` 开启详细日志
**权重**: 0.01 × 2 = 0.02分扣分

### P4-3: 缺少集成测试
**问题**: `scripts/test_tools.py` 存在但未在 CI/CD 中集成
**建议**: 添加 GitHub Actions 或本地 pytest 钩子
**权重**: 0.01 × 2 = 0.02分扣分

---

## Alerter 停止根因分析

**观察到的现象**: 最新告警时间戳 2026-07-31 14:00（约4.4小时前）

**根因定位**:

1. **当前时间是盘后/非交易时段** → `market_status.is_trading_day()` 返回 `is_trading=False`
   - 触发条件: 周末/节假日 OR 数据日期 < 今天
   - 行为: 静默退出，返回 `{"status": "silent"}` 或不输出

2. **Alerte 独立运行，不依赖 MCP server**
   - Cron 调用: `python -m webhook.alerter`（直接运行）
   - MCP tool: `run_alert_check`（包装调用）
   - 两者共享同一套 logic，但入口不同

3. **冷却机制正常工作**
   - 同一告警类型+代码 60分钟内不重复发送
   - 状态持久化到 `.alerter_state.json`

**结论**: Alerter 停止是**正常行为**，符合"非交易日静默退出"设计。如需验证，执行：
```bash
cd /home/admin/projects/stock-mcp-server
python -m webhook.alerter --dry-run
```
应返回 `{"status": "skipped", "reason": "..."}` 或实际告警。

---

## 工具功能对照表

| 工具名 | 数据源 | 缓存 | Fallback | 状态 |
|--------|--------|------|----------|------|
| get_realtime_quote | tencent | ✅ 30s | mootdx | ✅ |
| get_kline | tencent | ✅ 5min | mootdx | ✅ |
| get_stock_info | tencent | ✅ 1h | 无 | ⚠️ |
| analyze_stocks | tencent+yahoo | 混合 | 无 | ✅ |
| get_technical_analysis | technical.py | ❓ | 无 | ⚠️ |
| search_stock_news | news.py | 无 | 无 | ✅ |
| get_stock_context | 并行 | 混合 | 无 | ✅ |
| analyze_stock_ai | 多源 | ❌ | 无 | ✅ |
| check_st_risk | tencent | 无 | 无 | ✅ |
| get_cache_stats | 本地 | N/A | N/A | ✅ |
| get_data_source_health | 本地 | N/A | N/A | ✅ |
| check_backtest | 历史K线 | 无 | 无 | ✅ |
| run_alert_check | 本地+HTTP | 状态持久化 | 无 | ✅ |
| get_global_quote | global_stock | 无 | sina/tencent/eastmoney | ⚠️ sina已死 |
| get_global_kline | global_stock | 无 | sina→yahoo | ⚠️ sina已死 |
| get_us_financials | eastmoney | 无 | 无 | ✅ |
| get_us_key_indicators | eastmoney | 无 | 无 | ✅ |
| get_yahoo_statistics | yahoo | 无 | 无 | ✅ |
| get_institutional_holders | yahoo | 无 | 无 | ✅ |
| get_us_fund_flow | global_stock | 无 | 无 | ✅ |
| get_options_chain | yahoo | 无 | 无 | ⚠️ 仅美股 |
| get_sec_filings | SEC EDGAR | 无 | 无 | ✅ |
| get_sec_xbrl | SEC EDGAR | 无 | 无 | ✅ |
| search_global_stock | eastmoney | 无 | 无 | ✅ |
| get_us_market_ranking | eastmoney | 无 | 无 | ✅ |
| get_tdx_company_info | mootdx | 无 | 无 | ⚠️ 需安装 |
| get_tdx_finance_info | mootdx | 无 | 无 | ⚠️ 需安装 |
| get_tdx_xdxr_info | mootdx | 无 | 无 | ⚠️ 需安装 |

---

## 改进优先级矩阵

| 优先级 | 问题 | 工作量 | 收益 |
|--------|------|--------|------|
| P0 | Cache Invalidation 机制 | 2h | 高（数据准确性） |
| P0 | 美股港股 Fallback 链补全 | 3h | 高（可用性） |
| P1 | Bare except 分类处理 | 8h | 中高（可维护性） |
| P1 | ST level_name 硬编码修复 | 0.5h | 高（正确性） |
| P2 | 技术指标计算复用 | 4h | 中（维护成本） |
| P2 | 缓存键包含 days 参数 | 1h | 中（正确性） |
| P3 | 添加重试逻辑 | 3h | 中（稳定性） |
| P3 | Mootdx 客户端单例 | 2h | 低（性能） |

---

## 总结

Stock-mcp-server 功能整体完整，核心数据流（行情→技术→告警）可用。主要风险点：

1. **数据可靠性**: 缓存无失效机制，API 变更后可能持续使用过期数据
2. **可用性缺口**: 美股港股无降级方案，Yahoo 不可用时完全断裂
3. **代码质量**: 104处 bare except 使故障排查困难
4. **逻辑错误**: ST风险级别显示 bug 会导致告警信息误导

**建议立即修复**: P0-2（Fallback链）+ P1-2（level_name bug），这两个问题影响最直接且修复成本低。
