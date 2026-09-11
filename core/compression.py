"""
Result compression — prevent context overflow for large tool outputs.

Inspired by go-stock (https://github.com/ArvinLovegood/go-stock) compressMessages() + text_chunker.go pattern.
MCP tools return strings; when results exceed a threshold, compress them.
"""
from __future__ import annotations

import json
from typing import Any

# Thresholds (in characters)
COMPRESS_THRESHOLD = 8000   # Start compressing above this
AGGRESSIVE_THRESHOLD = 16000  # More aggressive truncation


def compress_result(result: str, max_chars: int = COMPRESS_THRESHOLD) -> str:
    """
    Compress a JSON tool result string if it exceeds the threshold.

    Strategy: keep head (60%) + tail (40%), annotate the middle.
    For very large results (>AGGRESSIVE_THRESHOLD), keep head only.
    """
    if len(result) <= max_chars:
        return result

    if len(result) > AGGRESSIVE_THRESHOLD:
        # Aggressive: keep first 60%
        cutoff = int(max_chars * 0.6)
        omitted = len(result) - cutoff
        return result[:cutoff] + f'\n\n... [省略 {omitted:,} 字符，结果过长] ...\n'

    # Moderate: head + tail
    head = int(max_chars * 0.6)
    tail = max_chars - head - 200
    omitted = len(result) - max_chars
    return (
        result[:head]
        + f'\n\n... [省略 {omitted:,} 字符] ...\n\n'
        + result[-tail:]
    )


def compress_dict_result(data: dict | list, max_chars: int = COMPRESS_THRESHOLD) -> str:
    """
    Convert a dict/list to JSON string, then compress if needed.
    This is the most common pattern: handler builds dict → json.dumps → return.
    """
    result = json.dumps(data, ensure_ascii=False, default=str)
    return compress_result(result, max_chars)


def aggregate_batch_results(items: list[dict], key_fields: list[str] | None = None) -> str:
    """
    Aggregate a list of dicts into a compact summary table.

    Args:
        items: list of result dicts (e.g., multiple stock quotes)
        key_fields: fields to include in summary. If None, auto-detect.

    Returns:
        Compact JSON string with summary + full data if small enough.
    """
    if not items:
        return json.dumps({"items": [], "count": 0}, ensure_ascii=False)

    # Auto-detect key fields from first item
    if key_fields is None:
        first = items[0] if items else {}
        # Common fields that make good summaries
        priority = ["code", "name", "price", "change_pct", "volume", "amount",
                     "industry", "net_inflow", "risk_level", "score"]
        key_fields = [f for f in priority if f in first]
        if not key_fields:
            key_fields = list(first.keys())[:5]

    # Build summary
    summary = []
    for item in items:
        row = {k: item.get(k) for k in key_fields if k in item}
        summary.append(row)

    result = {
        "summary": summary,
        "count": len(items),
        "key_fields": key_fields,
    }

    # If total result is small, include full data
    full_json = json.dumps(items, ensure_ascii=False, default=str)
    if len(full_json) <= COMPRESS_THRESHOLD:
        result["full_data"] = items

    return json.dumps(result, ensure_ascii=False, default=str)


def truncate_table(rows: list[dict], max_rows: int = 20, max_chars: int = COMPRESS_THRESHOLD) -> str:
    """
    Truncate a table (list of dicts) to max_rows and compress.

    Useful for industry rankings, fund flow lists, etc.
    """
    if not rows:
        return json.dumps([], ensure_ascii=False)

    total = len(rows)
    truncated = rows[:max_rows]
    result = json.dumps(truncated, ensure_ascii=False, default=str)

    if len(result) > max_chars:
        result = compress_result(result, max_chars)

    if total > max_rows:
        result = json.dumps({
            "items": truncated,
            "displayed": max_rows,
            "total": total,
            "note": f"显示前 {max_rows}/{total} 条",
        }, ensure_ascii=False, default=str)

    return result
