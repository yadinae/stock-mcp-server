"""
Webshare Proxy Manager — 代理池管理与请求辅助

从 ~/.hermes/secrets/webshare.json 加载 10 个代理 IP，随机轮换。
data_sources 的 _http_get / _http_post 可通过 proxy_request() 走代理，
也可保持原有 urllib.request.urlopen 不变（直连）。

环境变量覆盖:
  WEBSHARE_ENABLED=false    → 禁用代理（全部直连）
  WEBSHARE_USERNAME=xxx     → 覆盖用户名
  WEBSHARE_PASSWORD=xxx     → 覆盖密码
"""
from __future__ import annotations

import json
import os
import random
import threading
import time
import urllib.request
from pathlib import Path
from typing import Optional

# ── Config ─────────────────────────────────────────────────────────────────
_SECRETS_PATH = Path.home() / ".hermes" / "secrets" / "webshare.json"
_PROXY_HOST = "p.webshare.io"
_PROXY_PORT = 80
_CACHE_TTL = 3600  # 1 hour — proxy list refresh interval

# ── State ──────────────────────────────────────────────────────────────────
_lock = threading.Lock()
_proxy_list: list[dict] = []  # [{ip, port, username, password, country, city}, ...]
_loaded_at: float = 0.0
_enabled: Optional[bool] = None  # None = not checked yet


def _is_enabled() -> bool:
    """Check if proxy is enabled via env or secrets file."""
    global _enabled
    if _enabled is not None:
        return _enabled

    env = os.environ.get("WEBSHARE_ENABLED", "").lower()
    if env in ("false", "0", "no", "off"):
        _enabled = False
        return _enabled

    # Check if credentials are available
    username = os.environ.get("WEBSHARE_USERNAME", "")
    password = os.environ.get("WEBSHARE_PASSWORD", "")
    if username and password:
        _enabled = True
        return _enabled

    # Check secrets file
    if _SECRETS_PATH.exists():
        try:
            data = json.loads(_SECRETS_PATH.read_text())
            if data.get("username") and data.get("password"):
                _enabled = True
                return _enabled
        except Exception:
            pass

    _enabled = False
    return _enabled


def _load_proxy_list() -> list[dict]:
    """Load proxy list from secrets file or env vars."""
    global _proxy_list, _loaded_at

    with _lock:
        now = time.time()
        if _proxy_list and (now - _loaded_at) < _CACHE_TTL:
            return _proxy_list

        # Try env vars first
        username = os.environ.get("WEBSHARE_USERNAME", "")
        password = os.environ.get("WEBSHARE_PASSWORD", "")
        if username and password:
            # Use API key to fetch fresh list, or fallback to secrets file
            api_key = os.environ.get("WEBSHARE_API_KEY", "")
            if api_key:
                _proxy_list = _fetch_from_api(api_key)
            if not _proxy_list:
                # Fallback: load from secrets file
                _proxy_list = _load_from_file()

            if not _proxy_list:
                # Create single proxy entry from env vars
                _proxy_list = [{
                    "ip": "31.59.20.176",  # Default known proxy
                    "port": 6754,
                    "username": username,
                    "password": password,
                    "country": "GB",
                    "city": "London",
                }]
            _loaded_at = now
            return _proxy_list

        # Load from secrets file
        _proxy_list = _load_from_file()
        _loaded_at = now
        return _proxy_list


def _load_from_file() -> list[dict]:
    """Load proxy list from secrets file."""
    if not _SECRETS_PATH.exists():
        return []
    try:
        data = json.loads(_SECRETS_PATH.read_text())
        username = data.get("username", "")
        password = data.get("password", "")
        proxies = []
        for p in data.get("proxies", []):
            proxies.append({
                "ip": p["ip"],
                "port": p["port"],
                "username": username,
                "password": password,
                "country": p.get("country", "?"),
                "city": p.get("city", "?"),
            })
        return proxies
    except Exception:
        return []


def _fetch_from_api(api_key: str) -> list[dict]:
    """Fetch proxy list from Webshare API."""
    try:
        req = urllib.request.Request(
            "https://proxy.webshare.io/api/v2/proxy/list/?mode=direct",
            headers={"Authorization": f"Token {api_key}", "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            proxies = []
            for p in data.get("results", []):
                proxies.append({
                    "ip": p.get("proxy_address", ""),
                    "port": p.get("port", 0),
                    "username": p.get("username", ""),
                    "password": p.get("password", ""),
                    "country": p.get("country_code", "?"),
                    "city": p.get("city_name", "?"),
                })
            return proxies
    except Exception:
        return []


# ── Public API ─────────────────────────────────────────────────────────────

def get_proxy_url(proxy: Optional[dict] = None) -> Optional[str]:
    """Build a proxy URL string. Returns None if proxy is disabled."""
    if not _is_enabled():
        return None

    if proxy is None:
        proxies = _load_proxy_list()
        if not proxies:
            return None
        proxy = random.choice(proxies)

    return f"http://{proxy['username']}:{proxy['password']}@{proxy['ip']}:{proxy['port']}"


def get_proxy_opener(proxy: Optional[dict] = None) -> urllib.request.OpenerDirector:
    """Build a urllib opener with proxy. Falls back to direct if proxy disabled."""
    proxy_url = get_proxy_url(proxy)
    if not proxy_url:
        # Direct opener (no proxy)
        opener = urllib.request.build_opener()
        opener.addheaders = [("User-Agent", _DEFAULT_UA)]
        return opener

    handler = urllib.request.ProxyHandler({"http": proxy_url, "https": proxy_url})
    opener = urllib.request.build_opener(handler)
    opener.addheaders = [("User-Agent", _DEFAULT_UA)]
    return opener


_DEFAULT_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"


def proxy_request(
    url: str,
    data: Optional[bytes] = None,
    headers: Optional[dict] = None,
    method: Optional[str] = None,
    timeout: float = 12.0,
    referer: Optional[str] = None,
    use_proxy: bool = True,
) -> str:
    """
    Make an HTTP request through the proxy pool (or direct if disabled).

    Returns response body as string. Raises on HTTP errors.

    This is the recommended way to make HTTP requests in data_sources.
    Replace urllib.request.urlopen() calls with this function.
    """
    merged_headers = {"User-Agent": _DEFAULT_UA}
    if headers:
        merged_headers.update(headers)
    if referer:
        merged_headers["Referer"] = referer

    opener = get_proxy_opener() if use_proxy else urllib.request.build_opener()
    opener.addheaders = list(merged_headers.items())

    req = urllib.request.Request(url, data=data, method=method)
    with opener.open(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", "replace")


def proxy_urlopen(
    url: str,
    data: Optional[bytes] = None,
    timeout: float = 12.0,
    headers: Optional[dict] = None,
    use_proxy: bool = True,
):
    """
    Like urllib.request.urlopen but routes through proxy pool.

    Returns the response object (call .read() / .read().decode() on it).
    Use this as a drop-in replacement for urllib.request.urlopen.
    """
    merged_headers = {"User-Agent": _DEFAULT_UA}
    if headers:
        merged_headers.update(headers)

    opener = get_proxy_opener() if use_proxy else urllib.request.build_opener()
    opener.addheaders = list(merged_headers.items())

    req = urllib.request.Request(url, data=data)
    for k, v in merged_headers.items():
        req.add_header(k, v)

    return opener.open(req, timeout=timeout)


def proxy_status() -> dict:
    """Return current proxy status for health checks."""
    enabled = _is_enabled()
    proxies = _load_proxy_list() if enabled else []
    return {
        "enabled": enabled,
        "proxy_count": len(proxies),
        "secrets_file": str(_SECRETS_PATH),
        "secrets_exists": _SECRETS_PATH.exists(),
        "countries": list(set(p.get("country", "?") for p in proxies)),
    }
