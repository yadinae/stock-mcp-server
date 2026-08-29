# Stock MCP Server 📈

> 126 个 MCP 工具，覆盖 A 股 / 美股 / 港股 / 数字货币的全栈投资分析引擎。
> 从实时行情到 Wyckoff 漏斗选股，从技术分析到 DCF 估值，一个 MCP 端点搞定。

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE.md)
[![MCP Protocol](https://img.shields.io/badge/MCP-Protocol-8B5CF6.svg)](https://modelcontextprotocol.io)

## 项目现状

| 指标 | 数值 |
|:-----|:-----|
| MCP 工具总数 | **126** |
| 代码规模 | ~25,000 行 Python |
| 数据源 | **14 个**（东财 / 腾讯 / baostock / Yahoo / Binance / TradingView / 新浪 / ...） |
| 技术指标 | **16 项**（MA / MACD / RSI / 布林 / KDJ / CCI / ATR / DMI / OBV / MFI / VWAP / SAR / Ichimoku / 量比 / 乖离率 / K线形态） |
| 回测策略 | **5 种内置** + **5 种 Wyckoff 策略** + 缠论 |
| 独立运行 | `python server.py`（localhost:8901） |

---

## 🏗️ 架构总览

```
                        ┌──────────────────────────────┐
                        │     MCP Client (Hermes)      │
                        └──────────────┬───────────────┘
                                       │ stdio / SSE
                        ┌──────────────▼───────────────┐
                        │     server.py (FastMCP)       │
                        │     126 tools auto-register   │
                        └──────────────┬───────────────┘
                                       │
              ┌────────────────────────┼────────────────────────┐
              ▼                        ▼                        ▼
     ┌────────────────┐     ┌────────────────┐     ┌────────────────┐
     │  tools/handlers │     │   core/funnel   │     │  core/backtest │
     │  (20 模块, 126 工具) │   (Wyckoff 漏斗)  │     │  (向量化回测)    │
     └───────┬────────┘     └───────┬────────┘     └───────┬────────┘
             │                      │                      │
     ┌───────▼──────────────────────▼──────────────────────▼────────┐
     │                    14 个数据源适配器                           │
     │  东财 · 腾讯 · baostock · Yahoo · Binance · TradingView · …  │
     └───────────────────────────┬──────────────────────────────────┘
                                 │
                    ┌────────────▼────────────┐
                    │   内存缓存 + TTL + 降级   │
                    │   baostock 19.5MB 常驻    │
                    └─────────────────────────┘
```

---

## 📦 126 个 MCP 工具一览

### 行情与 K 线（22 个）

| 工具 | 说明 |
|:-----|:-----|
| `get_realtime_quote` | A 股实时行情 |
| `get_kline` | 历史 K 线 |
| `get_stock_info` | 股票基本信息 |
| `get_global_quote` / `get_global_kline` | 美股 / 港股行情与 K 线 |
| `get_tv_quote` | TradingView REST 行情（东财 502 降级） |
| `get_crypto_quote` / `get_crypto_kline` | 数字货币行情（Binance） |
| `get_index_info` / `get_index_perf` | 指数信息与区间表现 |
| `analyze_stocks` | 批量行情摘要 |
| `get_stock_context` | 综合数据（行情+K线+技术+新闻） |
| `search_global_stock` | 全球股票搜索 |
| `search_tradingview_market` | TradingView 行情代码搜索 |
| `market_overview` | 全市场总览（A 股指数 + 美股） |

### 技术分析（8 个）

| 工具 | 说明 |
|:-----|:-----|
| `get_technical_analysis` | 16 项指标完整分析（MA/MACD/RSI/布林/KDJ/CCI/ATR/DMI/OBV/MFI/VWAP/SAR/Ichimoku） |
| `technical_batch_scan` | 批量技术指标扫描 |
| `stock_score` | 多维度综合评分（0-100） |
| `stock_signals` | 多因子信号聚合 |
| `analyze_chanlun` | 缠论分析（笔/段/中枢/背驰） |
| `intraday_alert` | 盘中异动预警 |
| `sector_rotation` | 板块轮动追踪 |
| `market_regime` | 市场状态判断（牛/熊/震荡） |

### 基本面与财务（25 个）

| 工具 | 说明 |
|:-----|:-----|
| `fetch_financials` | 财务报表核心数据 |
| `get_financial_reports` | 新浪财报三表（资产负债/利润/现金流） |
| `get_company_profile` / `get_company_financials` | F10 公司资料与财务指标 |
| `get_management_team` / `get_top_shareholders` | 管理层与十大股东 |
| `get_holder_change` | 股东户数变化 |
| `get_dividend_history` | 分红送转历史 |
| `get_lockup_calendar` | 限售解禁日历 |
| `get_margin_trading` | 融资融券明细 |
| `get_block_trade` | 大宗交易记录 |
| `get_announcements` | 公告全文检索 |
| `get_research_reports` | 研报列表 |
| `dcf_valuation` | DCF 估值模型（两阶段 FCF + 5×5 敏感性表） |
| `ic_memo` | 投委会备忘录（质量评分 × DCF → 买入/观望/回避） |
| `dd_checklist` | 5 大维度尽调清单 |
| `unit_economics` | 单元经济分析（ARPU/LTV/CAC） |
| `value_creation_plan` | 5 年 EBITDA Bridge |
| `get_tdx_company_info` / `get_tdx_finance_info` / `get_tdx_xdxr_info` | 通达信 F10 |

### 资金流与龙虎榜（14 个）

| 工具 | 说明 |
|:-----|:-----|
| `get_fund_flow_120d` / `get_fund_flow_minute` | 个股资金流向（日级/分钟级） |
| `get_industry_fund_flow` / `get_concept_fund_flow` | 行业 / 概念板块资金流 |
| `analyze_lhb` / `get_market_lhb` | 龙虎榜深度分析 |
| `analyze_hot_money` | 游资席位分析 |
| `analyze_limitup_tiers` | 涨停梯队分析 |
| `get_industry_rank` / `get_tv_industry_rank` | 行业涨跌排名 |

### 投资情报（15 个）

| 工具 | 说明 |
|:-----|:-----|
| `get_all_sectors_briefing` / `get_sector_briefing` | 12 大赛道 AI 摘要 |
| `get_sector_news` / `search_industry_news` | 赛道新闻 |
| `get_wallstreetcn_news` | 华尔街见闻 7×24 快讯 |
| `search_stock_news` | 个股新闻搜索 |
| `get_market_hot_stocks` | 当日强势股清单 |
| `list_sectors` | 投资情报赛道列表 |
| `refresh_intel_cache` | 刷新情报缓存 |

### 投资组合（10 个）

| 工具 | 说明 |
|:-----|:-----|
| `portfolio_full_report` | 综合组合报告 |
| `portfolio_risk_diagnosis` | 组合风险诊断 |
| `portfolio_correlation` | 持仓相关性矩阵 |
| `portfolio_rebalance` / `portfolio_rebalance_signal` | 调仓建议与信号 |
| `portfolio_signal` | 组合调仓信号 |
| `watchlist_create` / `watchlist_add` / `watchlist_list` / `watchlist_brief` / `watchlist_remove` | 观察清单管理 |

### 策略扫描（8 个）

| 工具 | 说明 |
|:-----|:-----|
| `strategy_scan` | 通用策略扫描入口 |
| `strategy_scan_ma_vol` | 均线+量能策略 |
| `strategy_scan_rps` | RPS 相对强度策略 |
| `strategy_scan_turtle` | 海龟交易策略 |
| `strategy_scan_flag` | 高位旗形策略 |
| `strategy_scan_all` | 全策略并行扫描 |
| `stock_finder` | 策略选股推荐 |

### 美股 / 港股 / 数字货币（15 个）

| 工具 | 说明 |
|:-----|:-----|
| `get_us_financials` / `get_us_key_indicators` | 美股财务与指标 |
| `get_us_fund_flow` / `get_us_market_ranking` | 美股资金流与排名 |
| `get_institutional_holders` | 美股机构持仓 |
| `get_sec_filings` / `get_sec_xbrl` | SEC EDGAR 文件与 XBRL |
| `get_options_chain` | 美股期权链 |
| `get_yahoo_statistics` | Yahoo 财务指标 |
| `get_institutional_holders` | 机构持仓（港股） |

### AI 分析与审计（6 个）

| 工具 | 说明 |
|:-----|:-----|
| `analyze_stock_ai` | AI 决策仪表盘（评分+建议+风险） |
| `analyze_stock_agent` | Agent 模式综合分析（PlanExecute 编排） |
| `analyze_policy` | 政策影响分析（宏观/行业/公司三层） |
| `check_st_risk` | ST / 退市 / 异常风险检测 |
| `check_trap_risk` | 杀猪盘检测 |
| `analyze_chanlun` | 缠论 AI 分析 |

### 系统与可观测性（12 个）

| 工具 | 说明 |
|:-----|:-----|
| `get_cache_stats` | 缓存命中率统计 |
| `get_data_source_health` | 数据源健康监控 |
| `probe_data_sources` | 数据源实时探测 |
| `get_tool_stats` | 工具调用统计 |
| `search_tools` | 按关键词搜索工具 |
| `list_tool_groups` | 工具分组列表 |
| `tdx_test` | 通达信协议测试 |
| `tv_ws_status` | TradingView WebSocket 状态 |
| `cleanup_metrics` | 清理过期统计 |
| `cache_warmup` | 缓存预热 |
| `trade_journal_*` | 交易日志（开仓/平仓/查询/统计） |

### 回测（1 个入口 + 内部模块）

| 工具 | 说明 |
|:-----|:-----|
| `check_backtest` | 策略回测（5 种策略 + 绩效指标） |

---

## 📊 核心特性

### 1. Wyckoff 漏斗选股引擎

借鉴 WyckoffTradingAgent 架构设计，4 阶段流水线：

```
全市场 5000+ A 股
    │
    ▼ Stage 1: 基础筛选（ST/停牌/流动性/价格）
  2000+ stocks
    │
    ▼ Stage 2: 技术面多通道（趋势/反转/突破/吸筹）
  200+ stocks
    │
    ▼ Stage 3: 资金面筛选（成交额/量比/振幅）
  50+ stocks
    │
    ▼ Stage 4: 基本面筛选（价格/涨幅/距年低）
  20+ candidates
    │
    ▼ AI 审计（Agnes LLM veto-only）
  final picks
```

- **向量化计算**：DataFrame 布尔掩码替代逐条循环，吞吐 ~100,000 stocks/sec
- **baostock 内存缓存**：19.5MB 常驻内存，enrich 从 4s → 10ms
- **多通道信号**：趋势 / 反转 / 突破 / 吸筹 4 种 Wyckoff 阶段各配独立检测

### 2. 向量化回测引擎

- **参数扫描**：54 种参数组合 ~24s 完成（预加载 + MA 缓存）
- **内置策略**：MA 金叉 / MACD / RSI / 布林带 / 组合信号
- **Wyckoff 策略**：均线量能 / RPS 突破 / 海龟交易 / 高位旗形
- **缠论模块**：笔 / 段 / 中枢 / 背驰 / 买卖点信号
- **绩效指标**：年化收益 / 最大回撤 / 夏普比率 / 胜率 / 盈亏比

### 3. 技术分析引擎（16 项指标）

参考 MyTT/mpquant 向量化算法，全部基于 NumPy/pandas：

| 指标 | 核心算法 |
|:-----|:---------|
| MA / EMA / SMA | `pd.Series.rolling()` / `ewm()` |
| MACD | DIF = EMA(12) - EMA(26), DEA = EMA(DIF, 9) |
| RSI | SMA(MAX(DIF,0), N) / SMA(ABS(DIF), N) × 100 |
| 布林带 | MA(20) ± 2σ |
| KDJ | RSV → K → D → J |
| CCI | (TP - MA(TP)) / (0.015 × AVEDEV(TP)) |
| ATR | MAX(H-L, |H-Cp|, |L-Cp|) → MA(20) |
| DMI | +DI / -DI / ADX |
| OBV | 累计量能潮 |
| MFI | 带成交量的 RSI |
| VWAP | Σ(TP × Vol) / Σ(Vol) |
| SAR | 抛物转向 |
| Ichimoku | 转换线 / 基准线 / 先行带 / 迟行带 |
| 量比 | 当日量 / N 日均量 |
| 乖离率 | (Price - MA) / MA × 100 |
| K 线形态 | 十字星 / 锤子 / 射击之星 / 吞没 |

### 4. 14 个数据源 + 智能降级

```
东财 push2 ──→ 主源（A 股列表 + 资金流）
    │ 502
    ▼
TradingView REST ──→ 降级（5000+ A 股全市场扫描）
    │ 失败
    ▼
baostock ──→ 本地缓存兜底（36MB SQLite）

腾讯行情 ──→ A 股实时行情主源
    │ 超时
    ▼
mootdx ──→ 通达信 TCP 直连兜底

Yahoo Finance ──→ 美股 / 港股
Binance ──→ 数字货币
Kraken ──→ 数字货币备选
```

- **数据源健康追踪**：每个源独立成功率 / 延迟统计
- **缓存三层**：baostock 内存常驻 → TTL 内存缓存（30s~10min）→ SQLite 持久化

---

## 🚀 快速开始

### 安装

```bash
# 克隆仓库
git clone https://github.com/yadinae/stock-mcp-server.git
cd stock-mcp-server

# 安装依赖
pip install "mcp[cli]" httpx yfinance numpy pandas

# 可选依赖
pip install mootdx      # 通达信 TCP 数据源
pip install akshare     # 东财数据
```

### 启动服务

```bash
# 直接启动（stdio 模式，供 Hermes 调用）
python server.py

# 或指定端口（SSE 模式）
python server.py --port 8901
```

### 在 Hermes 中配置

```yaml
# ~/.hermes/config.yaml
mcp_servers:
  stock:
    command: python
    args: ["/path/to/stock-mcp-server/server.py"]
    # 或 SSE 模式
    # url: "http://localhost:8901/sse"
```

### 在 Claude Desktop 中配置

```json
{
  "mcpServers": {
    "stock": {
      "command": "python",
      "args": ["/path/to/stock-mcp-server/server.py"]
    }
  }
}
```

---

## 🗂️ 项目结构

```
stock-mcp-server/
├── server.py                     # MCP 入口，126 工具自动注册
│
├── core/                         # 核心引擎
│   ├── funnel.py                 # Wyckoff 漏斗选股（向量化）
│   ├── backtest.py               # 向量化回测引擎
│   ├── baostock_cache.py         # baostock 内存缓存（19.5MB）
│   ├── orchestrator.py           # Pipeline 编排层
│   ├── signal_state.py           # 信号状态机
│   ├── signal_feedback.py        # 信号反馈闭环
│   ├── ai_auditor.py             # AI 审计员（Agnes LLM）
│   ├── ablation.py               # 消融测试
│   ├── cache.py                  # TTL 内存缓存
│   ├── health.py                 # 数据源健康追踪
│   ├── resilience.py             # 重试/熔断/降级
│   ├── store.py                  # SQLite 持久化
│   └── metrics.py                # 指标采集
│
├── tools/                        # MCP 工具层
│   ├── handlers/                 # 20 个工具模块
│   │   ├── quote.py              # 行情工具（10 个）
│   │   ├── fundamental.py        # 基本面工具（19 个）
│   │   ├── fundflow.py           # 资金流工具（7 个）
│   │   ├── technical.py          # 技术分析工具（4 个）
│   │   ├── market.py             # 市场工具（12 个）
│   │   ├── analysis.py           # AI 分析工具（12 个）
│   │   ├── portfolio.py          # 组合工具（6 个）
│   │   ├── risk.py               # 风险工具（6 个）
│   │   ├── lhb.py                # 龙虎榜工具（7 个）
│   │   ├── crypto.py             # 数字货币工具（7 个）
│   │   ├── intel.py              # 投资情报工具（9 个）
│   │   ├── fund_index.py         # 基金/指数工具（10 个）
│   │   ├── strategy_scan.py      # 策略扫描工具（8 个）
│   │   ├── trade.py              # 交易日志工具（6 个）
│   │   ├── watchlist.py          # 观察清单工具（6 个）
│   │   ├── decisions.py          # 决策工具（3 个）
│   │   ├── system.py             # 系统工具（6 个）
│   │   ├── observability.py      # 可观测性工具（4 个）
│   │   ├── toolsearch.py         # 工具搜索（3 个）
│   │   └── chanlun.py            # 缠论工具（2 个）
│   ├── strategies/               # 策略库
│   │   ├── ma_volume.py          # 均线+量能策略
│   │   ├── rps_breakout.py       # RPS 相对强度策略
│   │   ├── turtle_trade.py       # 海龟交易策略
│   │   └── high_tight_flag.py    # 高位旗形策略
│   ├── backtest/                 # 回测模块
│   │   ├── strategies.py         # 策略信号生成
│   │   ├── simulator.py          # 交易模拟引擎
│   │   ├── metrics.py            # 绩效指标计算
│   │   ├── report.py             # 报告格式化
│   │   └── chanlun/              # 缠论分析
│   ├── technical.py              # 16 项技术指标（向量化）
│   ├── portfolio.py              # 组合分析
│   └── registry.py               # 工具自动发现注册
│
├── data_sources/                 # 14 个数据源适配器
│   ├── em_market.py              # 东财 push2（A 股列表+行情）
│   ├── tencent.py                # 腾讯行情（A 股主源）
│   ├── baostock_source.py        # baostock（本地缓存）
│   ├── global_stock.py           # Yahoo Finance（美股/港股）
│   ├── binance.py                # Binance（数字货币）
│   ├── tv_ws.py                  # TradingView WebSocket
│   ├── em_fundflow.py            # 东财资金流
│   ├── em_f10.py                 # 东财 F10
│   ├── intel.py                  # 投资情报聚合
│   ├── mootdx.py                 # 通达信 TCP
│   ├── kraken.py                 # Kraken（数字货币）
│   ├── sina_financial.py         # 新浪财报
│   └── danjuan_csindex.py        # 蛋卷基金（指数）
│
├── webhook/                      # 告警通知
│   ├── alerter.py                # 告警引擎
│   ├── notifier.py               # 飞书/TG 推送
│   └── rules.py                  # 告警规则
│
├── scripts/                      # 运维脚本
│   ├── run_funnel.py             # 漏斗运行入口
│   ├── quality_gate.py           # 质量门禁
│   └── generate_dashboard.py     # 仪表盘生成
│
├── tests/                        # 测试
│   └── test_funnel_integration.py
│
└── docs/                         # 架构文档
    ├── WYCKOFF_INSPIRED_ARCHITECTURE.md
    └── WYCKOFF_BORROWING_CASE_STUDY.md
```

---

## 🔧 技术栈

| 层 | 技术 |
|:---|:-----|
| **运行时** | Python 3.11+ |
| **MCP 框架** | [FastMCP](https://github.com/modelcontextprotocol/python-sdk) |
| **数值计算** | NumPy + pandas（向量化引擎） |
| **数据获取** | httpx（异步 HTTP） |
| **数据源** | 东财 push2 / 腾讯 / baostock / Yahoo / Binance / TradingView / 通达信 |
| **AI 分析** | Agnes AI（OpenAI 兼容 API） |
| **缓存** | 内存 TTL + SQLite 持久化 + baostock 内存常驻 |
| **调度** | Hermes Cron（盘后 15:30 / 盘前 08:20） |

---

## 📈 性能基准

| 操作 | 耗时 | 说明 |
|:-----|:-----|:-----|
| baostock 内存加载 | 2.3s（首次） | 441 symbols / 282k rows / 19.5MB |
| enrich_with_baostock | 10ms | 内存缓存命中后 |
| 500 股漏斗 stage | ~220ms | 4 个向量化 Stage 合计 |
| 单次回测 | ~1.6s | 441 symbols × 160 bars |
| 54 组合参数扫描 | ~24s | 预加载 + MA 缓存 |

---

## 🔄 版本历史

| 阶段 | 日期 | 内容 |
|:-----|:-----|:-----|
| **Phase 1** | 2026-06 | 缓存 + 并行化 + mootdx fallback + Ichimoku + K线形态 |
| **Phase 2** | 2026-06 | ST 风险检测 + 数据源健康监控 + 缓存统计 |
| **Phase 3** | 2026-06 | 输入校验 + 统一错误格式 + Yahoo 健康追踪 |
| **Phase 4** | 2026-06 | 5 策略回测 + 交易模拟 + 绩效指标 |
| **Phase 5** | 2026-07 | Wyckoff 漏斗 + AI 审计 + 信号状态机 + 反馈闭环 |
| **Phase 6** | 2026-08 | 向量化重写 + baostock 内存缓存 + 参数扫描 |

---

## 🌐 相关项目

| 项目 | 说明 |
|:-----|:-----|
| [stock-mcp-gateway](https://github.com/yadinae/stock-mcp-gateway) | Cloudflare Workers 版 MCP 网关 |
| [Hermes Agent](https://github.com/nousresearch/hermes-agent) | AI Agent 框架，本项目的主要调用方 |

---

## License

MIT
