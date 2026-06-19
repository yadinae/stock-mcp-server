"""
通知发送器 — 飞书 Webhook + Telegram Bot
=========================================
支持发送文本消息到飞书群（通过 Webhook 或应用 API）和 Telegram Bot。
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Optional

import httpx

from webhook.config import NotifierConfig, load_notifier_config

logger = logging.getLogger("stock-mcp.webhook.notifier")

HTTP_TIMEOUT = 15
HTTP_HEADERS = {
    "User-Agent": "stock-mcp-webhook/1.0",
    "Content-Type": "application/json",
}

# ── Tencent Cloud SCF Token Cache ──────────────────────────
# 飞书自建应用 token 缓存（避免每次请求重新获取）
_feishu_token: str = ""
_feishu_token_expires: float = 0


# ═══════════════════════════════════════════════════════════
# 飞书通知 (Webhook 模式)
# ═══════════════════════════════════════════════════════════

def send_feishu_webhook(
    content: str,
    webhook_url: str = "",
    title: str = "📊 持仓预警",
) -> bool:
    """通过飞书群机器人 Webhook 发送消息

    Args:
        content: 消息内容（支持 Markdown 格式）
        webhook_url: Webhook URL（默认从环境变量读取）
        title: 消息标题

    Returns:
        是否发送成功
    """
    if not webhook_url:
        webhook_url = os.environ.get("FEISHU_WEBHOOK_URL", "")
    if not webhook_url:
        logger.warning("飞书 Webhook URL 未配置，无法发送")
        return False

    # 飞书消息卡片格式
    payload = {
        "msg_type": "interactive",
        "card": {
            "header": {
                "title": {"tag": "plain_text", "content": title},
                "template": "orange",
            },
            "elements": [
                {
                    "tag": "markdown",
                    "content": content,
                }
            ],
        },
    }

    try:
        resp = httpx.post(
            webhook_url,
            json=payload,
            headers=HTTP_HEADERS,
            timeout=HTTP_TIMEOUT,
        )
        result = resp.json()
        if result.get("code") == 0:
            logger.info("飞书 Webhook 发送成功")
            return True
        else:
            logger.error(
                "飞书 Webhook 发送失败: code=%s, msg=%s",
                result.get("code"),
                result.get("msg"),
            )
            return False
    except Exception as e:
        logger.error("飞书 Webhook 请求异常: %s", e)
        return False


# ═══════════════════════════════════════════════════════════
# 飞书通知 (App API 模式)
# ═══════════════════════════════════════════════════════════

def _get_feishu_tenant_token(app_id: str, app_secret: str) -> Optional[str]:
    """获取飞书 tenant_access_token（带缓存）"""
    global _feishu_token, _feishu_token_expires

    now = time.time()
    if _feishu_token and _feishu_token_expires > now + 60:
        return _feishu_token

    try:
        resp = httpx.post(
            "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
            json={"app_id": app_id, "app_secret": app_secret},
            headers=HTTP_HEADERS,
            timeout=HTTP_TIMEOUT,
        )
        data = resp.json()
        token = data.get("tenant_access_token")
        expire = data.get("expire", 7200)
        if token:
            _feishu_token = token
            _feishu_token_expires = now + expire
            return token
        logger.error("获取飞书 token 失败: %s", data)
        return None
    except Exception as e:
        logger.error("获取飞书 token 异常: %s", e)
        return None


def send_feishu_app(
    content: str,
    chat_id: str = "",
    title: str = "📊 持仓预警",
    app_id: str = "",
    app_secret: str = "",
) -> bool:
    """通过飞书自建应用 API 发送消息到群

    Args:
        content: 消息内容（支持 Markdown）
        chat_id: 飞书群 ID
        title: 消息标题
        app_id: 飞书 App ID
        app_secret: 飞书 App Secret

    Returns:
        是否发送成功
    """
    app_id = app_id or os.environ.get("FEISHU_APP_ID", "")
    app_secret = app_secret or os.environ.get("FEISHU_APP_SECRET", "")
    chat_id = chat_id or os.environ.get(
        "FEISHU_STOCK_CHAT_ID",
        "oc_70aae2f0de3ae93698011ad34c5bee43",
    )

    if not all([app_id, app_secret, chat_id]):
        logger.warning("飞书 App 配置不完整，无法发送")
        return False

    token = _get_feishu_tenant_token(app_id, app_secret)
    if not token:
        return False

    # 发送消息
    try:
        payload = {
            "receive_id": chat_id,
            "msg_type": "interactive",
            "content": json.dumps({
                "header": {
                    "title": {"tag": "plain_text", "content": title},
                    "template": "orange",
                },
                "elements": [
                    {"tag": "markdown", "content": content}
                ],
            }),
        }
        resp = httpx.post(
            f"https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id",
            json=payload,
            headers={
                **HTTP_HEADERS,
                "Authorization": f"Bearer {token}",
            },
            timeout=HTTP_TIMEOUT,
        )
        data = resp.json()
        if data.get("code") == 0:
            logger.info("飞书 App 消息发送成功")
            return True
        else:
            logger.error("飞书 App 发送失败: %s", data)
            return False
    except Exception as e:
        logger.error("飞书 App 发送异常: %s", e)
        return False


# ═══════════════════════════════════════════════════════════
# Telegram Bot 通知
# ═══════════════════════════════════════════════════════════

def send_telegram(
    content: str,
    bot_token: str = "",
    chat_id: str = "",
    parse_mode: str = "HTML",
    disable_notification: bool = False,
) -> bool:
    """通过 Telegram Bot API 发送消息

    Args:
        content: 消息内容（支持 HTML 或 MarkdownV2）
        bot_token: Bot Token
        chat_id: 目标 Chat ID
        parse_mode: 解析模式 (HTML / MarkdownV2)
        disable_notification: 静默发送

    Returns:
        是否发送成功
    """
    bot_token = bot_token or os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = chat_id or os.environ.get("TELEGRAM_STOCK_CHAT_ID", "")

    if not all([bot_token, chat_id]):
        logger.warning("Telegram Bot 配置不完整，无法发送")
        return False

    try:
        payload = {
            "chat_id": chat_id,
            "text": content,
            "parse_mode": parse_mode,
            "disable_notification": disable_notification,
        }
        resp = httpx.post(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            json=payload,
            headers=HTTP_HEADERS,
            timeout=HTTP_TIMEOUT,
        )
        data = resp.json()
        if data.get("ok"):
            logger.info("Telegram 消息发送成功")
            return True
        else:
            logger.error("Telegram 发送失败: %s", data)
            return False
    except Exception as e:
        logger.error("Telegram 发送异常: %s", e)
        return False


# ═══════════════════════════════════════════════════════════
# 统一发送入口
# ═══════════════════════════════════════════════════════════

def send_notification(
    content: str,
    title: str = "📊 持仓预警",
    channel: str = "auto",
    config: Optional[NotifierConfig] = None,
) -> dict[str, bool]:
    """统一通知发送入口

    Args:
        content: 消息内容（Markdown 格式）
        title: 消息标题
        channel: 发送渠道 ("feishu" / "telegram" / "all" / "auto")
        config: 通知配置（默认从环境变量加载）

    Returns:
        {channel: success_bool} 字典
    """
    if config is None:
        config = load_notifier_config()

    results: dict[str, bool] = {}

    # 自动模式下用配置里的 enabled_channels
    channels = (
        config.enabled_channels
        if channel == "auto"
        else ["feishu", "telegram"] if channel == "all"
        else [channel]
    )

    for ch in channels:
        if ch == "feishu":
            # 优先用 App API（更稳定），降级到 Webhook
            if config.feishu.app_id and config.feishu.app_secret:
                ok = send_feishu_app(
                    content=content,
                    chat_id=config.feishu.chat_id,
                    title=title,
                    app_id=config.feishu.app_id,
                    app_secret=config.feishu.app_secret,
                )
            elif config.feishu.webhook_url:
                ok = send_feishu_webhook(
                    content=content,
                    webhook_url=config.feishu.webhook_url,
                    title=title,
                )
            else:
                ok = False
            results["feishu"] = ok

        elif ch == "telegram":
            ok = send_telegram(
                content=_md_to_html(content),
                bot_token=config.telegram.bot_token,
                chat_id=config.telegram.chat_id,
            )
            results["telegram"] = ok

    return results


def _md_to_html(md: str) -> str:
    """简单的 Markdown 转 HTML（用于 Telegram 发送）"""
    import re
    # 粗体: **text** → <b>text</b>
    md = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', md)
    # 斜体: *text* → <i>text</i>
    md = re.sub(r'(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)', r'<i>\1</i>', md)
    # 代码块: ```code``` → <code>code</code>
    md = re.sub(r'```(\w*)\n(.*?)```', r'<code>\2</code>', md, flags=re.DOTALL)
    # 行内代码: `code` → <code>code</code>
    md = re.sub(r'`([^`]+)`', r'<code>\1</code>', md)
    # 链接: [text](url) → <a href="url">text</a>
    md = re.sub(r'\[(.+?)\]\((.+?)\)', r'<a href="\2">\1</a>', md)
    # 换行: \n → <br/>
    md = md.replace('\n', '<br/>')
    return md
