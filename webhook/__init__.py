"""
stock-mcp-server Webhook 通知模块
==================================
持仓预警、ST 异动、ETF 信号 → 飞书/TG 推送

模块架构:
  alerter.py    — 告警引擎：加载规则、检查条件、生成通知
  rules.py      — 告警规则定义与评估
  notifier.py   — 飞书 Webhook + Telegram Bot 推送
  config.py     — 配置管理（持仓/规则/渠道）
"""
