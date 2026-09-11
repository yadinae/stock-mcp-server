#!/usr/bin/env python3
"""Methodology Cache — 本地研报/策略知识缓存，供 LLM 分析注入上下文

纯代码 + 本地文件缓存，零外部依赖。

核心功能：
1. 策略文档缓存（本地 JSON 文件）
2. 按关键词检索相关文档
3. 上下文注入（为 LLM 分析提供历史策略参考）
4. 增量更新
"""
from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime
from typing import Optional


# ─── 配置 ──────────────────────────────────────────────────────
_CACHE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "methodology"
)
_MAX_CACHE_SIZE = 50 * 1024 * 1024  # 50MB 上限
_MAX_DOCS = 200                     # 最大文档数
_INDEX_FILE = "index.json"
_MAX_CONTEXT_CHARS = 8000           # 注入上下文最大字符数


def _ensure_dir():
    os.makedirs(_CACHE_DIR, exist_ok=True)


def _index_path() -> str:
    return os.path.join(_CACHE_DIR, _INDEX_FILE)


def _load_index() -> dict:
    """加载文档索引"""
    _ensure_dir()
    path = _index_path()
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"version": 1, "documents": [], "updated_at": None}


def _save_index(index: dict):
    """保存文档索引"""
    _ensure_dir()
    index["updated_at"] = datetime.now().isoformat()
    with open(_index_path(), "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)


def add_strategy(
    title: str,
    content: str,
    tags: Optional[list[str]] = None,
    source: str = "",
    doc_type: str = "strategy",
) -> dict:
    """添加策略文档到缓存

    Args:
        title: 策略名称
        content: 策略正文
        tags: 标签（如 ["趋势跟踪", "均线", "止损"]）
        source: 来源
        doc_type: 文档类型 (strategy/methodology/research/memo)

    Returns:
        {"id": ..., "title": ..., "stored": True}
    """
    index = _load_index()

    doc_id = f"doc_{len(index['documents'])}_{int(time.time())}"
    tags = tags or []

    # 提取关键词
    keywords = _extract_keywords(title + " " + content)

    entry = {
        "id": doc_id,
        "title": title,
        "tags": tags,
        "source": source,
        "doc_type": doc_type,
        "keywords": keywords,
        "content_length": len(content),
        "created_at": datetime.now().isoformat(),
    }

    # 保存内容文件
    _ensure_dir()
    content_path = os.path.join(_CACHE_DIR, f"{doc_id}.json")
    with open(content_path, "w", encoding="utf-8") as f:
        json.dump({"title": title, "content": content, "tags": tags, "source": source}, f, ensure_ascii=False)

    index["documents"].append(entry)
    _save_index(index)

    return {"id": doc_id, "title": title, "stored": True}


def search_strategies(
    query: str,
    limit: int = 5,
    doc_type: Optional[str] = None,
) -> list[dict]:
    """搜索策略文档

    Args:
        query: 搜索关键词
        limit: 最大返回数
        doc_type: 限定文档类型

    Returns:
        [{id, title, tags, relevance_score, preview}]
    """
    index = _load_index()
    query_keywords = set(_extract_keywords(query))
    query_lower = query.lower()

    scored = []
    for doc in index.get("documents", []):
        if doc_type and doc.get("doc_type") != doc_type:
            continue

        # 计算相关性得分
        score = 0
        title_lower = doc["title"].lower()
        doc_keywords = set(doc.get("keywords", []))
        doc_tags = set(t.lower() for t in doc.get("tags", []))

        # 标题匹配
        if query_lower in title_lower:
            score += 100

        # 关键词重叠（精确）
        overlap = query_keywords & doc_keywords
        score += len(overlap) * 20

        # 标签匹配（精确）
        tag_overlap = query_keywords & doc_tags
        score += len(tag_overlap) * 15

        # 子串匹配：query 词在 doc 关键词/标签中
        for qk in query_keywords:
            if len(qk) < 2:
                continue
            for dk in doc_keywords:
                if qk in dk or dk in qk:
                    score += 5
                    break
            for dt in doc_tags:
                if qk in dt or dt in qk:
                    score += 8
                    break

        # 标题子串匹配
        for qk in query_keywords:
            if len(qk) >= 2 and qk in title_lower:
                score += 10

        if score > 0:
            scored.append({**doc, "relevance_score": score})

    scored.sort(key=lambda x: x["relevance_score"], reverse=True)
    return scored[:limit]


def get_strategy_content(doc_id: str) -> dict:
    """获取策略文档完整内容"""
    content_path = os.path.join(_CACHE_DIR, f"{doc_id}.json")
    if not os.path.exists(content_path):
        return {"error": f"文档 {doc_id} 不存在"}
    with open(content_path, "r", encoding="utf-8") as f:
        return json.load(f)


def build_context(
    query: str,
    max_chars: int = _MAX_CONTEXT_CHARS,
    doc_type: Optional[str] = None,
) -> str:
    """为 LLM 构建策略上下文

    根据查询关键词检索相关策略文档，拼接为上下文注入。

    Args:
        query: 当前分析查询
        max_chars: 最大字符数
        doc_type: 限定文档类型

    Returns:
        策略上下文文本（供注入 system prompt）
    """
    docs = search_strategies(query, limit=3, doc_type=doc_type)
    if not docs:
        return ""

    parts = []
    total = 0
    for doc in docs:
        content = get_strategy_content(doc["id"])
        if "error" in content or "content" not in content:
            continue
        text = content["content"]
        header = f"## {doc['title']}"
        if doc.get("tags"):
            header += f" [{', '.join(doc['tags'][:3])}]"

        block = f"\n{header}\n{text[:2000]}\n"
        if total + len(block) > max_chars:
            # 截断最后一篇
            remaining = max_chars - total
            if remaining > 200:
                block = f"\n{header}\n{text[:remaining - 50]}\n..."
            else:
                break
        parts.append(block)
        total += len(block)

    if not parts:
        return ""

    return (
        "\n---\n以下内容来自本地策略知识库，属于历史研究材料，不是实时数据。\n"
        "回答时应注明来源并保持批判性。\n" + "".join(parts) + "\n---"
    )


def list_strategies(doc_type: Optional[str] = None) -> list[dict]:
    """列出所有策略文档"""
    index = _load_index()
    docs = index.get("documents", [])
    if doc_type:
        docs = [d for d in docs if d.get("doc_type") == doc_type]
    return [
        {"id": d["id"], "title": d["title"], "tags": d.get("tags", []),
         "doc_type": d.get("doc_type"), "content_length": d.get("content_length"),
         "created_at": d.get("created_at")}
        for d in docs
    ]


def remove_strategy(doc_id: str) -> dict:
    """删除策略文档"""
    index = _load_index()
    index["documents"] = [d for d in index["documents"] if d["id"] != doc_id]
    _save_index(index)

    content_path = os.path.join(_CACHE_DIR, f"{doc_id}.json")
    if os.path.exists(content_path):
        os.remove(content_path)

    return {"id": doc_id, "removed": True}


def _extract_keywords(text: str) -> list[str]:
    """从文本中提取关键词（2-gram + 单字过滤）"""
    # 提取中文 2-gram（滑动窗口，比长串更匹配）
    cn_chars = re.findall(r'[\u4e00-\u9fff]', text)
    cn_bigrams = [cn_chars[i] + cn_chars[i+1] for i in range(len(cn_chars)-1)]
    # 提取英文词
    en_words = re.findall(r'[a-zA-Z_]{2,}', text)
    # 去重
    seen = set()
    keywords = []
    for w in cn_bigrams + en_words:
        wl = w.lower()
        if wl not in seen:
            seen.add(wl)
            keywords.append(wl)
    return keywords[:100]
