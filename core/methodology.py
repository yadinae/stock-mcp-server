#!/usr/bin/env python3
"""Methodology 知识缓存 — 研报/策略摘要本地存储 + 关键词检索

灵感来自 easy-stock (https://github.com/jundizhou/easy-stock) methodology，但适配 stock-mcp-server 的 MCP 工具场景。

功能：
1. 本地存储研报摘要、策略文档、交易方法论
2. 关键词检索（TF-IDF 简化版：词频匹配 + 位置加权）
3. TTL 过期（默认 7 天）
4. 供 LLM 分析时注入上下文

数据存储：SQLite（复用 core/store.py 的 DB_PATH）。
"""
from __future__ import annotations

import json
import math
import os
import re
import sqlite3
import threading
from datetime import datetime, timedelta
from typing import Optional

DB_PATH = os.environ.get(
    "STOCK_MCP_DB", os.path.expanduser("~/.stock-mcp/stock_mcp.db")
)

# ── Schema ──────────────────────────────────────────────────
_SCHEMA = """
CREATE TABLE IF NOT EXISTS methodology_docs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  title TEXT NOT NULL,
  source TEXT,
  category TEXT DEFAULT 'general',
  tags TEXT DEFAULT '[]',
  content TEXT NOT NULL,
  summary TEXT,
  author TEXT,
  published_at TEXT,
  content_hash TEXT,
  expires_at TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_method_category ON methodology_docs(category);
CREATE INDEX IF NOT EXISTS idx_method_source ON methodology_docs(source);
CREATE INDEX IF NOT EXISTS idx_method_hash ON methodology_docs(content_hash);
"""

_conn: Optional[sqlite3.Connection] = None
_lock = threading.Lock()

DEFAULT_TTL_DAYS = 7
MAX_CONTENT_CHARS = 50_000  # 单文档最大 50K 字符


# ── 连接管理 ──────────────────────────────────────────────────
def _get_conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        _conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.executescript(_SCHEMA)
    return _conn


def _content_hash(content: str) -> str:
    """简单内容哈希（去重用）"""
    import hashlib
    return hashlib.md5(content.strip().encode("utf-8")).hexdigest()[:16]


# ── 写入 ──────────────────────────────────────────────────────
def add_document(
    title: str,
    content: str,
    source: Optional[str] = None,
    category: str = "general",
    tags: Optional[list[str]] = None,
    summary: Optional[str] = None,
    author: Optional[str] = None,
    published_at: Optional[str] = None,
    ttl_days: int = DEFAULT_TTL_DAYS,
    force: bool = False,
) -> dict:
    """添加研报/策略文档到缓存

    Args:
        title: 文档标题
        content: 文档内容
        source: 来源（URL/机构名）
        category: 分类（strategy/report/newsletter/research）
        tags: 标签列表
        summary: 摘要（可选，用于快速预览）
        author: 作者
        published_at: 发布日期
        ttl_days: 过期天数（默认7天）
        force: 强制覆盖同内容文档

    Returns:
        {"id": ..., "title": ..., "saved": True, "duplicate": False}
    """
    if not content or not content.strip():
        return {"error": "内容不能为空"}

    content = content.strip()[:MAX_CONTENT_CHARS]
    h = _content_hash(content)
    conn = _get_conn()

    # 去重检查
    if not force:
        existing = conn.execute(
            "SELECT id, title FROM methodology_docs WHERE content_hash = ?",
            (h,),
        ).fetchone()
        if existing:
            return {
                "id": existing["id"],
                "title": existing["title"],
                "saved": False,
                "duplicate": True,
                "message": "内容已存在",
            }

    expires_at = (datetime.now() + timedelta(days=ttl_days)).isoformat()
    tags_json = json.dumps(tags or [], ensure_ascii=False)

    result = conn.execute("""
        INSERT INTO methodology_docs
        (title, source, category, tags, content, summary, author,
         published_at, content_hash, expires_at)
        VALUES (?,?,?,?,?,?,?,?,?,?)
    """, (
        title, source, category, tags_json, content,
        summary, author, published_at, h, expires_at,
    ))
    conn.commit()

    return {"id": result.lastrowid, "title": title, "saved": True, "duplicate": False}


def add_batch(documents: list[dict]) -> dict:
    """批量添加文档

    Args:
        documents: [{"title": ..., "content": ..., "source": ..., ...}, ...]

    Returns:
        {"total": N, "saved": M, "duplicates": D, "errors": E}
    """
    saved, duplicates, errors = 0, 0, 0
    for doc in documents:
        try:
            r = add_document(**doc)
            if r.get("saved"):
                saved += 1
            elif r.get("duplicate"):
                duplicates += 1
            else:
                errors += 1
        except Exception:
            errors += 1
    return {"total": len(documents), "saved": saved, "duplicates": duplicates, "errors": errors}


# ── 检索 ──────────────────────────────────────────────────────
def _tokenize(text: str) -> list[str]:
    """简单中文分词（基于正则 + 字符类型切分）"""
    text = text.lower()
    # 英文词
    en_words = re.findall(r"[a-z0-9]+", text)
    # 中文连续字符（2-4字组合）
    cn_segments = []
    cn_chars = re.findall(r"[\u4e00-\u9fff]+", text)
    for seg in cn_chars:
        for size in (2, 3, 4):
            for i in range(len(seg) - size + 1):
                cn_segments.append(seg[i:i + size])
    return en_words + cn_segments


def _score_document(query_tokens: list[str], doc_content: str,
                    doc_title: str = "") -> float:
    """计算文档与查询的相关性得分

    基于简化 TF-IDF：词频 × 位置权重
    """
    if not query_tokens:
        return 0

    content_lower = doc_content.lower()
    title_lower = doc_title.lower()
    total_score = 0.0

    for token in query_tokens:
        # 标题匹配权重 ×3
        title_count = title_lower.count(token)
        total_score += title_count * 3.0

        # 内容匹配权重 ×1
        content_count = content_lower.count(token)
        if content_count > 0:
            # TF 用 log(1+count) 压缩
            tf = math.log(1 + content_count)
            total_score += tf

    return round(total_score, 2)


def search(
    query: str,
    category: Optional[str] = None,
    limit: int = 5,
    include_expired: bool = False,
) -> list[dict]:
    """关键词检索文档

    Args:
        query: 搜索关键词
        category: 限定分类
        limit: 返回条数
        include_expired: 是否包含过期文档

    Returns:
        [{ id, title, source, category, summary, score, ... }, ...]
    """
    conn = _get_conn()

    # 先缩小范围
    sql = "SELECT * FROM methodology_docs WHERE 1=1"
    params: list = []
    if category:
        sql += " AND category = ?"
        params.append(category)
    if not include_expired:
        sql += " AND (expires_at IS NULL OR expires_at > ?)"
        params.append(datetime.now().isoformat())

    rows = conn.execute(sql, params).fetchall()

    # 计算得分
    query_tokens = _tokenize(query)
    scored = []
    for row in rows:
        d = dict(row)
        score = _score_document(
            query_tokens,
            d.get("content", ""),
            d.get("title", ""),
        )
        if score > 0:
            d["score"] = score
            # 解析 tags
            try:
                d["tags"] = json.loads(d.get("tags") or "[]")
            except Exception:
                d["tags"] = []
            # 截断 content
            if "content" in d:
                d["content_preview"] = d["content"][:500]
                del d["content"]
            scored.append(d)

    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:limit]


def get_document(doc_id: int) -> Optional[dict]:
    """获取完整文档"""
    conn = _get_conn()
    row = conn.execute(
        "SELECT * FROM methodology_docs WHERE id = ?", (doc_id,)
    ).fetchone()
    if not row:
        return None
    d = dict(row)
    try:
        d["tags"] = json.loads(d.get("tags") or "[]")
    except Exception:
        d["tags"] = []
    return d


def get_context_for_prompt(query: str, max_chars: int = 8000) -> str:
    """为 LLM prompt 检索相关上下文

    从知识库中找到与查询最相关的文档，组装成 prompt 注入格式。
    如果无匹配返回空字符串。

    Args:
        query: 用户查询或分析主题
        max_chars: 最大字符数

    Returns:
        格式化的上下文字符串，或空字符串
    """
    docs = search(query, limit=3)
    if not docs:
        return ""

    parts = [
        "以下内容来自本地知识库（研报/策略摘要），属于历史分析材料，不是实时行情。"
        "回答时应注明来源并保持批判性。\n"
    ]

    total = len(parts[0])
    for doc in docs:
        preview = doc.get("content_preview", "")
        if not preview:
            continue
        header = f"\n## {doc.get('title', '未知')}\n来源: {doc.get('source', '本地')}\n"
        entry = f"{header}\n{preview}\n"
        if total + len(entry) > max_chars:
            break
        parts.append(entry)
        total += len(entry)

    return "".join(parts)


# ── 管理 ──────────────────────────────────────────────────────
def cleanup_expired() -> int:
    """清理过期文档，返回清理数量"""
    conn = _get_conn()
    now = datetime.now().isoformat()
    result = conn.execute(
        "DELETE FROM methodology_docs WHERE expires_at IS NOT NULL AND expires_at < ?",
        (now,),
    )
    conn.commit()
    return result.rowcount


def list_documents(
    category: Optional[str] = None,
    limit: int = 20,
) -> list[dict]:
    """列出文档（摘要模式）"""
    conn = _get_conn()
    sql = "SELECT id, title, source, category, tags, summary, author, published_at, created_at FROM methodology_docs"
    params: list = []
    if category:
        sql += " WHERE category = ?"
        params.append(category)
    sql += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)

    rows = conn.execute(sql, params).fetchall()
    result = []
    for row in rows:
        d = dict(row)
        try:
            d["tags"] = json.loads(d.get("tags") or "[]")
        except Exception:
            d["tags"] = []
        result.append(d)
    return result


def get_stats() -> dict:
    """知识库统计"""
    conn = _get_conn()
    total = conn.execute("SELECT COUNT(*) as cnt FROM methodology_docs").fetchone()["cnt"]
    active = conn.execute(
        "SELECT COUNT(*) as cnt FROM methodology_docs "
        "WHERE expires_at IS NULL OR expires_at > ?",
        (datetime.now().isoformat(),),
    ).fetchone()["cnt"]
    by_category = conn.execute(
        "SELECT category, COUNT(*) as cnt FROM methodology_docs GROUP BY category"
    ).fetchall()

    return {
        "total_documents": total,
        "active_documents": active,
        "expired_documents": total - active,
        "by_category": {r["category"]: r["cnt"] for r in by_category},
    }
