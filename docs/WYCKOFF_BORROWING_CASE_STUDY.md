# Wyckoff TradingAgent → stock-mcp-server 架构借鉴案例

**日期**: 2026-08-28
**参考项目**: https://github.com/YoungCan-Wang/WyckoffTradingAgent (v0.9.234, 583⭐)
**目标项目**: stock-mcp-server (123+ MCP tools, FastMCP)

## 背景

研究 WyckoffTradingAgent 项目，提取 5 个可借鉴的设计思想，融入 stock-mcp-server。

## 提取的设计思想

| # | Wyckoff 原版 | 移植方案 | 价值 |
|---|-------------|---------|------|
| 1 | 五阶段漏斗 L1→L5 | Funnel Pipeline（MVP 简化为 2 Stage） | 把散装工具串成流水线 |
| 2 | AI 只做 veto | AIAuditor（LLM 不可用时自动 PASS） | 杜绝幻觉推荐 |
| 3 | DETECTED→SURVIVED→VALIDATED | Signal State Machine（SQLite WAL） | 信号跨日存活检验 |
| 4 | shadow→on 反馈闭环 | Signal Feedback（≥30 样本才可评价） | 系统自我学习策略有效性 |
| 5 | GitHub Actions 定时调度 | Hermes cron | 自动化盘前/盘后 |

## 迭代过程

### v2（初版）→ v3（修正版）

关键变更来自判别者反馈：

| v2 | v3 | 原因 |
|----|----|------|
| 5 个 Stage | **2 个核心 Stage** | 现实检验者 2.9/10：1人团队无法交付5个子系统 |
| 自研调度引擎 | **Hermes cron** | 重复造轮子 |
| 同步 AI 审计 | **异步可选** | 单点延迟 |
| 13 数据源全覆盖 | **MVP 只用腾讯+东财** | 组合爆炸 |

### 判别者评审结果

| 判别者 | 分数 | 核心发现 |
|--------|------|---------|
| 🏛️ 架构评审者 | 5.3/10 | 代码截断、协作协议缺失、状态机无实现 |
| 🧠 优化师 | — | 漏斗异常处理缺陷、Prompt 硬编码、缺超时控制 |
| 🎯 现实检验者 | 2.9/10 | **架构复杂度与团队规模严重不匹配** |

**关键教训**: 现实检验者的低分直接导致方案从"5个子系统"简化为"2个核心Stage + MVP验证"。

## 实际实现

### 文件结构

```
stock-mcp-server/
├── core/
│   ├── orchestrator.py     # Pipeline 编排层（150行）
│   ├── funnel.py           # 2 Stage 漏斗 + 4通道（260行）
│   ├── signal_state.py     # 信号状态机 SQLite（220行）
│   └── ...
└── scripts/
    └── run_funnel.py       # 执行入口（300行）
```

### 验证结果

```
48 只测试股 → 基础筛选 48 → 技术面 26 → 排序去重 6 只候选
通道分布: 趋势 3 + 吸筹 24 + 突破 0 + 反转 0
信号状态机: 7 个信号（accumulation 5 + trend 2）
```

## 数据源降级模式

**问题**: 东财 push2 API 返回 502（网络/IP 限制）

**解决方案**: 双数据源降级链
```
东财 push2 API（全市场 ~5000 只）
    ↓ 502 / 不可用
baostock 本地缓存（~50 只测试股）
```

**实现要点**:
- 东财 API 需要正确的 User-Agent 和 Referer 头
- baostock 价格单位是"分"，需除以 100 转为"元"
- baostock 有 `turnover`（成交额）字段可直接用作 `amount`

## LLM 判别者降级模式

**问题**: OpenRouter 额度耗尽，3 个 delegate_task 子代理全部失败

**解决方案**: 直接调用 Agnes AI API
```python
# 通过 execute_code 调用 Agnes API
payload = json.dumps({
    "model": "agnes-2.0-flash",
    "messages": [{"role": "user", "content": prompt}],
    "max_tokens": 4096,
    "temperature": 0.3
})
result = terminal(f'curl -s "https://apihub.agnes-ai.com/v1/chat/completions" ...')
```

**适用场景**: 当默认 LLM provider 不可用时，可用任何 OpenAI-compatible API 作为判别者后端。

## 坑点清单

1. **东财 API 502**: 非交易时段或 IP 限制时可能返回 502，必须有 fallback
2. **baostock 价格单位**: 数据库中价格是"分"不是"元"，需 `/100`
3. **baostock 无股票名称**: 缓存只有代码，没有中文名称
4. **Agnes reasoning_tokens**: agnes-2.0-flash 的 `max_tokens` 需要预留 reasoning 部分，建议 ≥4096
5. **类型注解**: `def func(x: dict = None)` 会触发 Pyright 报错，需用 `Optional[dict]`
