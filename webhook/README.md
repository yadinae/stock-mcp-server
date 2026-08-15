# Webhook 通知模块

> 持仓预警、ST 异动、ETF 信号 → 飞书/TG 推送

## 架构

```
webhook/
├── alerter.py        # 告警引擎：拉数据 → 验规则 → 发通知
├── rules.py          # 告警规则定义与评估（价格跌、MACD金叉、RSI等）
├── notifier.py       # 飞书 Webhook/App API + Telegram Bot 推送
├── config.py         # 配置管理（持仓、规则、渠道）
├── alert_rules.json  # 告警规则持久化文件
└── .alerter_state.json  # 告警状态（自动管理，冷却抑制）
```

## 告警类型

| 类型 | 检测条件 | 级别 |
|------|---------|------|
| 📉 **价格跌幅** | -3% / -5% / -8% 阈值 | 提醒/警告/紧急 |
| 📊 **放量下跌** | 量比 > 3 + 跌幅 > 3% | 警告 |
| 🛡️ **ST 风险** | 风险等级 >= 警告级 | 警告/紧急 |
| 💹 **MACD 金叉/死叉** | DIF 上穿/下穿 DEA | 警告 |
| 📈 **RSI 超买/超卖** | RSI < 30 或 > 70 | 提醒 |
| 🎯 **ETF 评分** | 技术评分 >= 70 | 提醒 |

## 使用方式

### 1. 命令行运行

```bash
# Dry-run（仅检查，不发送通知）
cd ~/projects/stock-mcp-server
python3.11 -m webhook.alerter --dry-run

# 正式运行（检查 + 发送飞书通知）
python3.11 -m webhook.alerter

# 指定发送渠道
python3.11 -m webhook.alerter --channel all
```

### 2. 通过 MCP 工具调用

```python
# 在 Hermes 中通过 MCP 工具调用
tool: run_alert_check
params: {"dry_run": true}   # 仅检查
params: {"channel": "feishu"}  # 发送到飞书
```

### 3. 定时 cron（已配置）

自动运行：交易时段（周一~周五 9:30~15:00）每 30 分钟检查一次。

## 配置

### 告警规则

编辑 `webhook/alert_rules.json`：

```json
{
  "holdings": [
    {"code": "159949", "name": "创业板50ETF华安", "status": "套牢"}
  ],
  "price_drop": {
    "enabled": true,
    "thresholds": [-3, -5, -8]
  },
  "etf_signal": {
    "enabled": true,
    "min_score": 70,
    "macd": {"detect_golden_cross": true, "detect_death_cross": true},
    "rsi": {"oversold_threshold": 30, "overbought_threshold": 70}
  }
}
```

### 通知渠道

通过环境变量配置：

| 变量 | 说明 |
|------|------|
| `FEISHU_APP_ID` | 飞书自建应用 App ID（从 Hermes 继承） |
| `FEISHU_APP_SECRET` | 飞书自建应用 App Secret（从 Hermes 继承） |
| `FEISHU_STOCK_CHAT_ID` | 飞书群 ID（默认龙虾群） |
| `FEISHU_WEBHOOK_URL` | 飞书群机器人 Webhook URL（可选降级） |
| `TELEGRAM_BOT_TOKEN` | Telegram Bot Token（可选） |
| `TELEGRAM_STOCK_CHAT_ID` | Telegram 目标 Chat ID（可选） |
| `WEBHOOK_CHANNELS` | 启用渠道（逗号分隔，默认 `feishu`） |

## MCP Gateway 工具

Gateway 额外提供两个远程通知工具：

- `send_feishu_message` — 远程发送飞书消息（需配置 FEISHU_WEBHOOK_URL）
- `send_telegram_message` — 远程发送 Telegram 消息（需配置 TELEGRAM_BOT_TOKEN）
