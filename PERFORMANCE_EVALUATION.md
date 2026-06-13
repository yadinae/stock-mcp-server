# Stock-MCP-Server 性能基准评估报告

**评估日期**: 2026-06-13
**评估师**: 性能基准师
**Python版本**: 3.11.13
**项目路径**: `/home/admin/projects/stock-mcp-server/`

---

## 1. 缓存 TTL 设置评估

| 缓存项 | TTL | 评估 | 说明 |
|--------|-----|------|------|
| TTL_REALTIME | 30s | ✅ **合理** | 实时行情盘中变化快，30秒过期合理 |
| TTL_KLINE | 300s (5min) | ✅ **合理** | K线每5分钟变化不大，300秒缓存合适 |
| TTL_STOCK_INFO | 300s (5min) | ✅ **合理** | 基本资料几乎不变，可考虑延长至3600s但5分钟不影响 |
| TTL_TECHNICAL | 300s (5min) | ✅ **合理** | 技术分析基于K线，与K线同频变化 |
| TTL_NEWS | 600s (10min) | ✅ **合理** | 新闻更新周期较长，10分钟缓存合理 |
| TTL_AI_ANALYSIS | 0 (不缓存) | ✅ **正确** | AI分析每次可能不同，不应缓存 |

**缓存实现质量**:
- `TTLCache` 使用 `threading.Lock` 实现线程安全 ⭐
- `get_or_compute` 方法减少重复计算（原子化获取或计算）
- `time.monotonic()` 实现过期检查，不受系统时间调整影响
- 有缓存命中率统计（hits/misses/ratio），可观测性好
- 全局单例 `get_cache()` 模式简单有效

**改进建议**: `TTL_STOCK_INFO` 可延长至 3600s（1小时），股票名称/代码等基本信息几乎不变。

---

## 2. 并行化效果评估

### 实测加速比

| 任务数 | 顺序执行 | 并行执行 | 加速比 | 说明 |
|--------|---------|---------|--------|------|
| 3 (各300/400/500ms) | 1.200s | 0.508s | **2.4x** | 受最大并行任务数限制 |
| parallel_map 5×100ms | 0.500s | 0.202s | **2.5x** | 接近理论最优 |

### 并行化使用位置

| 函数 | 并行任务 | Workers | 评估 |
|------|---------|---------|------|
| `get_stock_context` | realtime + kline（2个） | 共享池4 | ✅ 合适 |
| `get_stock_context` (第二次) | news（1个） | 共享池4 | ✅ 单任务无意义 |
| `analyze_stock_ai` | realtime + kline + news（3个） | 共享池4 | ✅ **最佳使用** |
| `analyze_stocks` (美股) | 每只美股1个并行 | parallel_map 4 | ✅ 合理 |

**评估**: 并行化策略正确，关键路径（analyze_stock_ai 3任务并行）受益最大。`get_stock_context` 第二次只并行1个任务是多余的，单任务并行退化为串行。

---

## 3. 线程池大小评估

### 全局线程池 `_executor`

```
ThreadPoolExecutor(max_workers=4, thread_name_prefix="stock-mcp")
```

| 维度 | 评估 | 风险 |
|------|------|------|
| max_workers=4 | ✅ 合理 | 4个worker足以充分利用API并发 |
| 全局单例 | ✅ 资源复用 | 避免每次创建新线程池 |
| 线程名前缀 | ✅ 可观测性 | 便于线程DUMP诊断 |
| **daemon=False** | ⚠️ **风险** | 线程在Python 3.11下为daemon=False，会阻止进程退出 |

### 线程池容量分析

```
典型并发需求:
  analyze_stock_ai: 3任务   → 占用3/4 workers ✓
  get_stock_context: 2任务   → 占用2/4 workers ✓
  并发调用: 同时2个analyze_stock_ai → 6任务，2个排队
```

最多4个并发API调用。对于MCP单用户服务器，容量充足。但如果遇到15s HTTP超时，4个worker可能全被阻塞，后续请求排队。

### `parallel_map` 临时线程池

```python
def parallel_map(fn, items, max_workers=4):
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        return list(pool.map(fn, items))
```

- 使用 `with` 上下文管理器，**正确清理** ✅
- 但每次调用创建/销毁新线程池，有性能开销
- 仅用于 `analyze_stocks` 中美股部分，调用频率低，可接受

---

## 4. 潜在性能瓶颈 🔴

### 瓶颈 1（严重）: `as_completed` 超时计算错误

**文件**: `core/parallel.py` 第49行
```python
for future in as_completed(futures, timeout=timeout * len(tasks)):
```

**问题**: 超时 = `用户指定timeout × 任务数`。例如 `analyze_stock_ai(timeout=25, tasks=3)` → 实际等待 **75秒**，远超用户预期。

**影响**: 
- 如果一个任务挂起，用户需等待 `25×3=75s` 才能收到超时错误
- 被超时的任务线程仍在后台运行（daemon=False），**造成线程泄漏**
- 与docstring声称的"每个任务timeout秒"不符

**建议修复**: 
```python
# 改为：每个任务的独立超时控制
for future in as_completed(futures, timeout=timeout):
```

### 瓶颈 2（中等）: 全局线程永不关闭

**文件**: `core/parallel.py` 第17行
```python
_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="stock-mcp")
```

**问题**: 
- 线程为 daemon=False（Python 3.11默认），阻止进程正常退出
- 如果程序需要优雅关闭，线程池无法干净停止

**建议修复**: 
```python
# 增加 shutdown hook
import atexit
atexit.register(lambda: _executor.shutdown(wait=False))
# 或设为 daemon=True
```

### 瓶颈 3（低）: 单任务并行开销

**文件**: `server.py` 第213-216行
```python
news_tasks = {
    "news": lambda: search_news(code, _get_stock_info(code).get("name", "")),
}
news_results = run_parallel(news_tasks, timeout=15)
```

**问题**: 只有1个任务也走 `run_parallel` 完整流程（锁、Future、as_completed），增加不必要的开销。

**建议**: 单任务直接调用，不经过线程池。

### 瓶颈 4（低）: `parallel_map` 每次创建新线程池

```python
def parallel_map(fn, items, max_workers=4):
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        return list(pool.map(fn, items))
```

**问题**: 每次调用创建/销毁线程池。对于 `analyze_stocks` 不频繁的调用问题不大，但模式不一致（一个用全局池，一个用临时池）。

**建议**: 复用全局 `_executor` 或只在调用方需要时创建。

### 瓶颈 5（信息）: 无熔断/重试保护

- 没有API调用失败的熔断机制
- 没有请求级超时（依赖HTTP客户端15s超时）
- 如果某个数据源持续失败，会一直消耗线程

---

## 5. 综合评分

| 维度 | 评分 | 说明 |
|------|------|------|
| 缓存TTL设置 | ⭐⭐⭐⭐⭐ (5/5) | 所有TTL设置合理，实现线程安全 |
| 并行化效果 | ⭐⭐⭐⭐ (4/5) | 加速比2.4x有效，但单任务并行浪费 |
| 线程池大小 | ⭐⭐⭐⭐ (4/5) | max_workers=4合理，daemon线程问题需关注 |
| 潜在瓶颈 | ⭐⭐⭐ (3/5) | **超时计算错误**需优先修复 |
| 代码质量 | ⭐⭐⭐⭐ (4/5) | 模块化清晰，缓存高效，但超时逻辑有bug |

**总体**: **3.8/5** — 优化方向正确，缓存和并行化显著提升性能，但 `as_completed` 超时计算存在缺陷需修复。

---

## 6. 优先级行动项

1. **🔴 紧急**: 修复 `run_parallel` 中超时计算（`timeout * len(tasks)` → `timeout`），防止线程泄漏和响应延迟
2. **🟡 建议**: 添加 `atexit` 清理钩子或设置daemon线程，确保进程可正常退出
3. **🟢 优化**: 单任务不走 `run_parallel` 以降低开销
4. **🟢 建议**: 考虑 `TTL_STOCK_INFO` 延长至3600s
5. **ℹ️ 可选**: 考虑添加熔断器防止连续API失败耗尽线程
