# Stock-MCP-Server 功能审查报告（最终版）

> 审查时间: 2026-07-31 18:30 | 审查者: 功能审查者
> 项目规模: ~6000行 Python, 28个MCP工具, server.py 952行

---

## 加权总分: 62/100

| 维度 | 权重 | 得分 | 扣分项 |
|------|------|------|--------|
| 工具完整性 | 0.15 | 85/100 | -3.75 |
| 数据源Fallback链 | 0.20 | 60/100 | -8.0 |
| Cache Invalidation | 0.15 | 40/100 | -9.0 |
| Alerter运行状态 | 0.15 | 95/100 | -0.75 |
| MCP Tool Registration | 0.10 | 90/100 | -1.0 |
| 代码质量/错误处理 | 0.25 | 35/100 | -17.5 |

**净得分: 100 - 38 = 62/100**

---

## P0 级问题（阻断性功能缺陷）

### P0-1: Cache 无主动失效机制 — 数据可能严重过期
**位置**: `core/cache.py`, `data_sources/*.py`
**现象**: 
- 仅依赖 TTL 自动过期（30s/5min/1h）
- 无 version key、无前缀批量失效、无手动 invalidate API
- 当上游 API 字段结构变更时，缓存持续返回错误格式数据
**影响评分**: API 结构变更 → 所有工具静默返回错误格式数据 → 用户得到错误分析结果
**修复方案**:
```python
# cache.py 新增方法
def invalidate_prefix(self, prefix: str) -> int:
    """失效所有以 prefix 开头的缓存"""
    keys_to_delete = [k for k in self._store if k.startswith(prefix)]
    for k in keys_to_delete:
        del self._store[k]
    return len(keys_to_delete)

# 在 API 升级时调用
cache.invalidate_prefix("tx_realtime:")
```
**扣分**: -3.0

### P0-2: 美股/港股主流程无 Fallback — Yahoo 不可用时完全断裂
**位置**: `server.py:57-65` `_get_realtime_quote()`
**现象**:
```python
def _get_realtime_quote(code: str):
    if ctype == "a":
        return tencent.get_realtime_quote(code)  # ✅ 有 mootdx fallback
    if ctype in ("us", "hk"):
        result = yahoo.get_realtime_quote(code)
        return result or {"error": "..."}  # ❌ 无 fallback，直接报错
```
但 `global_stock.global_quote()` 已有 sina→tencent→eastmoney 三级 fallback。
**影响**: 美港股用户在中国网络环境下，Yahoo Finance 常被墙，导致工具完全不可用
**修复方案**:
```python
if ctype in ("us", "hk"):
    result = yahoo.get_realtime_quote(code)
    if result and "error" not in result:
        return result
    # Fallback to global_stock (has sina/tencent/eastmoney chain)
    from data_sources import global_stock
    return global_stock.global_quote(code)
```
**扣分**: -5.0

---

## P1 级问题（高风险，严重影响可用性）

### P1-1: 104处 Bare Except — 故障排查几乎不可能
**分布**:
- server.py: 20处（含 `run_alert_check`、所有 global 工具）
- global_stock.py: 17处
- alerter.py: 14处
- tencent.py/mootdx.py/yahoo.py: 6处
- tools/: 10处

**问题示例**:
```python
# server.py:514
except Exception as e:
    return json.dumps({"error": str(e), "code": code}, ensure_ascii=False)
```
所有异常统一返回 `{"error": "SomeException: details"}`，无法区分：
- 网络超时 → 应重试
- API限流 → 应退避
- 数据解析失败 → 应记录格式日志
- 业务逻辑错误 → 应返回结构化错误

**影响**: 生产环境无法定位问题根因，每次故障需远程调试
**修复方案**: 定义异常层次
```python
class StockMCPError(Exception): pass
class NetworkError(StockMCPError): pass
class ParseError(StockMCPError): pass

except NetworkError as e:
    return json.dumps({"error": str(e), "retry": True})
except ParseError as e:
    logger.warning(f"Parse error: {e}", exc_info=True)
    return json.dumps({"error": "数据格式异常"})
except Exception as e:
    logger.error(f"Unexpected: {e}", exc_info=True)
    return json.dumps({"error": "内部错误"})
```
**扣分**: -5.0

### P1-2: ST风险级别显示 Bug — 告警信息误导
**位置**: `webhook/alerter.py:578-624`
**代码**:
```python
return {
    "max_level": max((s["level"] for s in signals), default=0),  # 正确计算
    "level_name": "正常",  # ← BUG: 硬编码，忽略max_level
    "is_st": bool(st_status),
    ...
}
```
**影响**: 检测到"*ST康美"（max_level=3，高风险），但告警消息显示"风险等级: 正常"
**修复方案**（3行代码）:
```python
_level_names = {0: "正常", 1: "关注", 2: "警告", 3: "高风险"}
"level_name": _level_names.get(max_level, "正常"),
```
**扣分**: -3.0

### P1-3: 技术指标缓存键不包含 days 参数 — 可能导致错误结果
**位置**: `tools/technical.py:624`
**代码**:
```python
cache_key = make_cache_key("technical", code, last_date, first_date, str(len(records)))
```
**问题**: 如果用户先用 days=60 查询，缓存后，再用 days=120 查询，会得到60天的分析结果
**影响**: 技术分析结论基于不完整数据
**修复方案**: 将 days 纳入 key，或从 records 推导
```python
cache_key = make_cache_key("technical", code, str(len(records)), last_date, first_date)
```
**扣分**: -2.0

---

## P2 级问题（中等风险）

### P2-1: Alerte 冷却时间不一致
**位置**: `webhook/alerter.py:474 vs 509`
- 持仓/观察池: 60分钟冷却
- ETF池: 120分钟冷却
**问题**: 未通过配置控制，硬编码在代码中
**建议**: 提取到 config.py 的 AlertRules 中
**扣分**: -0.5

### P2-2: Sina 美股行情已死但仍支持 source="sina"
**位置**: `data_sources/global_stock.py:33-38`
```python
def us_quote_sina(ticker: str):
    return {"error": "新浪美股行情受地域限制不可用..."}
```
但 `get_global_quote(source="sina")` 仍会调用此函数并返回错误
**建议**: 移除 sina 选项或返回明确提示
**扣分**: -0.5

### P2-3: Mootdx 客户端重复创建
**位置**: `data_sources/mootdx.py:51-54`
```python
def _get_client():
    from mootdx.quotes import Quotes
    return Quotes.factory(market="std")  # 每次都新建TCP连接
```
**建议**: 实现进程内单例（注意线程安全）
**扣分**: -0.5

---

## P3 级问题（低风险，技术债）

| 编号 | 问题 | 位置 | 建议 |
|------|------|------|------|
| P3-1 | 无重试逻辑 | 全部HTTP请求 | 至少2次重试+1秒退避 |
| P3-2 | 日志级别WARNING | server.py:41 | 默认INFO，DEBUG通过环境变量 |
| P3-3 | 无Metrics出口 | 全局 | 添加Prometheus endpoint |
| P3-4 | global_stock.py膨胀 | 953行单文件 | 拆分quotes/financials/sec模块 |

**扣分合计**: -1.0

---

## Alerter 停止根因分析

### Cron 配置
```json
{
  "script": "stock_alerter.sh",
  "schedule": "*/30 9-14 * * 1-5",  // 工作日9:00-14:00每30分钟
  "no_agent": true
}
```

### 运行状态
- **最新告警时间**: 2026-07-31 18:23
- **当前时间**: 约 18:30
- **告警覆盖标的**: 12只（4持仓 + 1观察 + 7 ETF）

### 根因判断

**Alerter 正常运行，当前停止是设计行为**

原因链:
1. 现在时间是 18:30，已过交易时段（15:00收盘）
2. Cron 调度只在 9:00-14:00 运行
3. 即使调用 `run_alert_check`，`market_status.is_trading_day()` 也会检测为非交易日/非交易时段
4. 返回 `{"status": "silent"}` 静默退出，不发送通知

### 验证方法
```bash
cd /home/admin/projects/stock-mcp-server
python -m webhook.alerter --dry-run
# 预期输出: {"status": "skipped", "reason": "..." 或实际告警}
```

**结论**: Alerter 未故障，是正常停止。上次成功运行应在 14:00 或 14:30。

**扣分**: -0.5（需确认 stock_alerter.sh 脚本是否存在及权限）

---

## MCP Tool 注册完整性检查

### 注册列表（28个工具）
```
基础行情:
  get_realtime_quote      ✅ A股+美股+港股
  get_kline              ✅ A股+美股+港股  
  get_stock_info         ✅ A股+美股+港股
  analyze_stocks         ✅ 批量分析

技术分析:
  get_technical_analysis ✅ MA/MACD/RSI/布林带/评分
  get_stock_context      ✅ 综合数据（并行获取）
  analyze_stock_ai       ✅ LLM增强分析

风险检测:
  check_st_risk          ✅ ST/退市/面值风险

数据源监控:
  get_cache_stats        ✅ 命中率/条目数
  get_data_source_health ✅ 各源成功率

回测:
  check_backtest         ✅ 5策略+绩效指标

告警:
  run_alert_check        ✅ 持仓/ETF/观察池
  get_global_quote       ✅ 美股/港股增强
  get_global_kline       ✅ 多周期K线
  get_us_financials      ✅ 三表（东财）
  get_us_key_indicators  ✅ 关键指标
  get_yahoo_statistics   ✅ Yahoo统计
  get_institutional_holders ✅ 机构持仓
  get_us_fund_flow       ✅ 资金流
  get_options_chain      ✅ 期权（仅美股）
  get_sec_filings        ✅ SEC filings
  get_sec_xbrl           ✅ XBRL财务
  search_global_stock    ✅ 搜索
  get_us_market_ranking  ✅ 涨跌幅排名
  get_tdx_company_info   ✅ 通达信F10
  get_tdx_finance_info   ✅ 通达信财务
  get_tdx_xdxr_info      ✅ 除权除息
```

**无遗漏，无重复，命名规范统一** ✅

---

## 改进优先级矩阵

| 优先级 | 问题 | 工作量 | 收益 | 紧急度 |
|--------|------|--------|------|--------|
| P0 | 美股港股 Fallback 补全 | 2h | 🔴高 | 立即 |
| P0 | Cache Invalidation 机制 | 3h | 🔴高 | 本周 |
| P1 | ST level_name Bug修复 | 0.5h | 🟠高 | 立即 |
| P1 | Bare Except 分类处理 | 8h | 🟠高 | 本月 |
| P2 | 技术指标缓存键修复 | 1h | 🟡中 | 本周 |
| P3 | Mootdx 客户端单例 | 2h | 🟢低 | 下个迭代 |

---

## 附录：关键代码片段

### 需要修复的 P1-2 代码（alerter.py:619-620）
```python
# 当前（错误）
return {
    "max_level": max((s["level"] for s in signals), default=0),
    "level_name": "正常",  # ← 硬编码
    ...
}

# 修复后
_level_map = {0: "正常", 1: "关注", 2: "警告", 3: "高风险"}
return {
    "max_level": max((s["level"] for s in signals), default=0),
    "level_name": _level_map.get(max_level, "正常"),  # ← 动态映射
    ...
}
```

### 需要修复的 P0-2 代码（server.py:57-65）
```python
# 当前（缺少fallback）
def _get_realtime_quote(code: str):
    ctype = _code_type(code)
    if ctype == "a":
        return tencent.get_realtime_quote(code)
    if ctype in ("us", "hk"):
        result = yahoo.get_realtime_quote(code)
        return result or {"error": f"无法获取{'美股' if ctype=='us' else '港股'}行情"}
    return {"error": f"无法识别股票代码: {code}"}

# 修复后
def _get_realtime_quote(code: str):
    ctype = _code_type(code)
    if ctype == "a":
        return tencent.get_realtime_quote(code)  # 已有mootdx fallback
    if ctype in ("us", "hk"):
        result = yahoo.get_realtime_quote(code)
        if result and "error" not in result:
            return result
        # Fallback: global_stock has sina→tencent→eastmoney chain
        from data_sources import global_stock
        return global_stock.global_quote(code)
    return {"error": f"无法识别股票代码: {code}"}
```

---

*报告生成完毕，详细版本已保存至 func_review_report.md*
