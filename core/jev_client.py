"""
Jev (TypeSafe System One) decisions client — for stock-mcp calibration decisions

Jev is NOT an OpenAI-compatible model: it exposes a /decisions endpoint
(via OpenRouter at /api/alpha/decisions), not chat/completions.
Question types: choice (categorical + probabilities), score (ordinal 0-10 + probs),
noul (natural output, 0..1 probability of Yes + explanation).

Config: OpenRouter key read from ~/.hermes/scripts/secrets.json (OPENROUTER_API_KEY).

Measured 2026-09-18: latency ~0.3s/call (4 questions in 0.3s),
cost $0.000016-0.000026/call, OpenRouter paid quota (not :free tier).
"""
from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

import httpx

logger = logging.getLogger("stock-mcp.jev")

_SECRETS_PATH = "/home/admin/.hermes/scripts/secrets.json"
_JEV_ENDPOINT = "https://openrouter.ai/api/alpha/decisions"
_JEV_MODEL = "typesafe/jev-1.13"


def _load_openrouter_key() -> str:
    """Read OpenRouter key from central secrets (600 perms, single source of truth)."""
    try:
        with open(_SECRETS_PATH) as f:
            return json.load(f).get("OPENROUTER_API_KEY", "")
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("jev: failed to load OPENROUTER_API_KEY from %s: %s", _SECRETS_PATH, e)
        return ""


_JEV_KEY = _load_openrouter_key()


def jev_decide(
    state: str,
    questions: dict[str, dict[str, Any]],
    model: str = _JEV_MODEL,
    timeout_s: float = 30.0,
    retries: int = 2,
) -> dict:
    """
    Call Jev decisions endpoint with one or more questions.

    Args:
        state: Context text (public stock data, market state, etc.). Keep facts clean
            — irrelevant detail degrades accuracy (jaggedness doc), but irrelevant
            *state* is tolerable; irrelevant *instructions* are not.
        questions: {name: question} where question is one of:
            - {"type": "choice", "instructions": "...", "criteria": {cat: desc, ...}}
            - {"type": "score", "instructions": "...", "criteria": [0-desc, 1-desc, ...]}
            - {"type": "noul", "instructions": "...", "description": "..." }
        model: OpenRouter model id for Jev.
        timeout_s: HTTP timeout per attempt.
        retries: retry count on 5xx/timeouts (NOT on 4xx — quota/400 won't recover).

    Returns:
        {"ok": True, "answers": {...}, "latency_s": float, "cost_usd": float, "usage": {...},
         "raw": {...}} on success;
        {"ok": False, "error": str, "http_code": int|None, "raw": str} on failure.
    """
    if not _JEV_KEY:
        return {"ok": False, "error": "OPENROUTER_API_KEY missing in secrets.json", "http_code": None, "raw": ""}

    payload = {"model": model, "state": state, "questions": questions}
    headers = {
        "Authorization": f"Bearer {_JEV_KEY}",
        "Content-Type": "application/json",
    }

    last_err = ""
    last_code: int | None = None
    for attempt in range(retries + 1):
        t0 = time.time()
        try:
            resp = httpx.post(_JEV_ENDPOINT, json=payload, headers=headers, timeout=timeout_s)
            if resp.status_code == 200:
                d = resp.json()
                return {
                    "ok": True,
                    "answers": d.get("answers", {}),
                    "latency_s": round(time.time() - t0, 3),
                    "cost_usd": d.get("usage", {}).get("cost"),
                    "usage": d.get("usage", {}),
                    "raw": d,
                }
            last_code = resp.status_code
            last_err = resp.text[:400]
            # 4xx is not recoverable without changing the request (quota exceeded,
            # bad question shape). Only retry 5xx / timeouts.
            if resp.status_code < 500 and resp.status_code != 429:
                return {"ok": False, "error": last_err, "http_code": last_code, "raw": ""}
        except httpx.TimeoutException:
            last_code = 408
            last_err = f"timeout after {timeout_s}s (attempt {attempt+1})"
        except httpx.HTTPError as e:
            last_code = None
            last_err = f"http error: {e}"
        time.sleep(1.0 * (attempt + 1))

    return {"ok": False, "error": last_err, "http_code": last_code, "raw": ""}


def jev_answer_summary(result: dict) -> dict:
    """Flatten a successful jev_decide() result into a compact per-question summary.

    For choice: winning category + probabilities. For score: score + probabilities.
    For noul: noul probability + explanation.
    """
    if not result.get("ok"):
        return {"error": result.get("error")}
    out: dict[str, Any] = {}
    for name, ans in result["answers"].items():
        t = ans.get("type")
        if t == "choice":
            out[name] = {
                "choice": ans.get("choice"),
                "confidence": ans.get("confidence"),
                "probabilities": ans.get("probabilities"),
            }
        elif t == "score":
            out[name] = {
                "score": ans.get("score"),
                "confidence": ans.get("confidence"),
                "probabilities": ans.get("probabilities"),
            }
        elif t == "noul":
            out[name] = {
                "noul": ans.get("noul"),
                "explanation": ans.get("explanation"),
            }
        else:
            out[name] = ans
    return out
