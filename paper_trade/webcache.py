"""Fetch a public web resource once per time-to-live and share it through a file cache, for every process.

Requests name this system plainly (``USER_AGENT``); nothing pretends to be a browser.
"""

from __future__ import annotations

import hashlib
import json
import time

import requests

from paper_trade import config

CACHE_DIR = config.RUNS_DIR / "live" / "web_cache"
USER_AGENT = "paper-trade-research/1.0"
TIMEOUT_SECONDS = 20


def _path(url: str, params: dict | None):
    key = hashlib.sha1(json.dumps([url, params or {}], sort_keys=True).encode()).hexdigest()[:20]
    return CACHE_DIR / f"{key}.json"


def get(url: str, ttl: int, params: dict | None = None, as_json: bool = True, secret_params: tuple = ()):
    """The response body (parsed JSON, or text) no older than ``ttl`` seconds.

    When a refresh fails, a stale copy is returned rather than nothing; with no copy at all the error is raised.
    ``secret_params`` are sent but left out of the cache key (API keys never reach the cache file name or content).
    """
    public = {k: v for k, v in (params or {}).items() if k not in secret_params}
    path = _path(url, public)
    if path.exists() and time.time() - path.stat().st_mtime < ttl:
        return json.loads(path.read_text(encoding="utf-8"))["body"]
    try:
        response = requests.get(url, params=params, timeout=TIMEOUT_SECONDS, headers={"User-Agent": USER_AGENT})
        response.raise_for_status()
        if not as_json and "charset" not in response.headers.get("Content-Type", "").lower():
            response.encoding = "utf-8"          # feeds without a declared charset are UTF-8, not Latin-1
        body = response.json() if as_json else response.text
    except Exception:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))["body"]
        raise
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"url": url, "params": public, "body": body}), encoding="utf-8")
    tmp.replace(path)
    return body
