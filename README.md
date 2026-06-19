# Stock Analysis MCP Server 📈

> 股票分析 MCP 服务 — A 股 + 美股 + 港股，集成技术分析、AI 分析、ST 风险检测、策略回测。

## 功能一览

**12 个 MCP 工具：**

| 工具 | 说明 |
|:-----|:-----|
| `get_realtime_quote` | 实时行情（价格、涨跌幅、成交量） |
| `get_kline` | 历史 K 线数据 |
| `get_stock_info` | 股票基本信息 |
| `analyze_stocks` | 批量行情摘要 |
| `get_technical_analysis` | 技术分析（MA/MACD/RSI/布林带/Ichimoku/K线形态） |
| `search_stock_news` | 股票新闻搜索 |
| `get_stock_context` | 综合数据（行情 + K线 + 技术 + 新闻） |
| `analyze_stock_ai` | AI 决策仪表盘 |
| `check_st_risk` | ST/退市/异常风险检测 |
| `get_cache_stats` | 缓存命中率统计 |
| `get_data_source_health` | 数据源健康监控 |
| `check_backtest` | 策略回测 |

## 数据源架构

```
                    ┌──────────┐
  A 股 ────────────→│  Tencent  │ ← 主源（HTTP API）
                    ├──────────┤
                    │  mootdx  │ ← Fallback（通达信 TCP，零配置）
                    └─────┬────┘
                          │
  美股/港股 ────────────→│ Yahoo Finance
                          │
                    ┌─────▼────┐
                    │  缓存层   │ ← TTL 内存缓存（30秒~10分钟）
                    ├──────────┤
                    │ 健康追踪  │ ← 三源成功率/失败率统计
                    └──────────┘
```

- **Tencent**（主源）：HTTP API，覆盖主流 A 股
- **mootdx**（自动 fallback）：通达信 TCP 直连，支持 ETF 和数十年 K 线
- **Yahoo Finance**：美股/港股数据

## 技术分析

集成 **9 项技术指标**：

| 指标 | 说明 |
|:-----|:------|
| **MA 均线** | MA5/MA10/MA20/MA60，趋势排列判断 |
| **MACD** | DIF/DEA/柱状图，金叉死叉信号 |
| **RSI(14)** | 超买/超卖/强弱判断 |
| **布林带** | 上/中/下轨，带宽，价格位置 |
| **Ichimoku** | 一目均衡表（Tenkan/Kijun/云层/趋势信号） |
| **K 线形态** | 十字星、锤子、射击之星、阳吞没、阴吞没 |
| **量比** | 当日量 / 5日均量 |
| **乖离率** | 价格偏离均线程度 |
| **综合评分** | 0-100 评分 + 买卖建议 |

## AI 分析

使用 LLM 生成**决策仪表盘**，含：

- 核心结论 + 多空判断
- 价格位置 + 支撑压力位
- 量能分析
- 新闻情绪解读
- 买卖计划 + 仓位建议
- 风险提示

自动从 Hermes config 读取 LLM 配置，支持指数退避重试和 JSON 格式校验。

## ST 风险检测

基于公开数据，4 维度评分：

| 维度 | 检测内容 |
|:-----|:---------|
| **ST/*ST 状态** | 从股票名称自动识别 |
| **面值退市风险** | 股价 < 1 元触发警告，< 0.5 元高风险 |
| **放量下跌** | 量比 > 3 + 跌幅 > 5% 标记高风险 |
| **综合评估** | 无异常时标记"正常" |

风险等级：正常 🟢 → 关注 🟡 → 警告 🟠 → 高风险 🔴

## 策略回测

5 种内置交易策略，零新依赖：

| 策略 | ID | 信号逻辑 |
|:-----|:---|:---------|
| **MA 金叉/死叉** | `ma_crossover` | MA5 上穿/下穿 MA20 |
| **MACD** | `macd` | DIF 上穿/下穿 DEA |
| **RSI 均值回归** | `rsi` | 超卖区回升 / 超买区回落 |
| **布林带反弹** | `bollinger` | 触下轨反弹 / 触上轨回落 |
| **组合信号** | `combined` | MA(40%) + MACD(30%) + RSI(30%) 加权 |

**交易模拟参数：**
- 初始资金：100,000（可配置）
- 手续费：买入万 2.5 / 卖出万 2.5 + 印花税千 1
- 滑点：0.1%
- T+1 限制（A 股）

**绩效指标：** 总收益率 / 年化收益率 / 最大回撤 / 夏普比率 / 胜率 / 盈亏比 / 平均持仓

## 架构

```
stock-mcp-server/
├── server.py                  # MCP 入口，12 个工具注册
├── core/
│   ├── cache.py               # TTL 内存缓存
│   ├── parallel.py            # 并行执行工具
│   └── health.py              # 数据源健康追踪
├── data_sources/
│   ├── tencent.py             # 腾讯行情（+ mootdx fallback）
│   ├── mootdx.py              # 通达信 TCP 直连
│   └── yahoo.py               # Yahoo Finance
└── tools/
    ├── technical.py           # 技术分析（9 项指标）
    ├── news.py                # 新闻搜索（新浪 + 百度）
    ├── analyzer.py            # AI 分析（LLM 决策仪表盘）
    ├── st_risk.py             # ST 风险检测
    └── backtest/              # 策略回测模块
        ├── __init__.py        # 入口
        ├── strategies.py      # 5 种策略信号生成
        ├── simulator.py       # 交易模拟引擎
        ├── metrics.py         # 绩效指标计算
        └── report.py          # 报告格式化
```

## 快速开始

```bash
# 安装依赖
pip install "mcp[cli]" httpx yfinance

# 可选：mootdx（A 股备选数据源）
pip install mootdx

# 启动服务
python3 server.py

# 或通过 MCP CLI 检查
mcp dev server.py
```

### 配置 AI 分析

AI 分析自动使用 Hermes config 中的 LLM 配置。也可用环境变量覆盖：

```bash
export STOCK_LLM_BASE_URL="https://api.openai.com/v1"
export STOCK_LLM_API_KEY="sk-xxx"
export STOCK_LLM_MODEL="gpt-4o-mini"
```

## 测试

```bash
# 快速测试（不调用外部 API）
python3 scripts/test_tools.py       # 54 项

# 回测专项测试
python3 scripts/test_backtest.py    # 43 项

# 完整测试（含外部 API 调用）
python3 scripts/test_tools.py --full
```

## 技术栈

- **运行时**：Python 3.11+（Hermes venv）
- **框架**：[MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk) (FastMCP)
- **外部依赖**：httpx, yfinance, mootdx（可选）
- **零依赖回测**：纯 Python 标准库

## Gateway（Cloudflare Workers 版）

stock-mcp-server 的 Cloudflare Workers 版本已拆分到独立仓库：
🔗 https://github.com/yadinae/stock-mcp-gateway

43 个 MCP 工具，部署在 `https://mcp-gateway.yadinae.workers.dev`，覆盖：
A 股/美股/港股行情、K线、技术分析、财报、资金流、龙虎榜、SEC Filing、期权链等。

## 版本历史

| 阶段 | 内容 |
|:-----|:------|
| **Phase 1** | 缓存 + 并行化 + mootdx fallback + Ichimoku + K线形态 |
| **Phase 2** | ST 风险检测 + 数据源健康监控 + 缓存统计 |
| **Phase 3** | 输入校验 + 统一错误格式 + Yahoo 健康追踪 |
| **Phase 4** | 5 策略回测 + 交易模拟 + 绩效指标 |

## License

MIT
