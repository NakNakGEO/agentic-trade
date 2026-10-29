"""Let one process at a time ask TradingView, and share each answer for a short while.

Every caller (two live loops, the dashboard and up to 28 decision workers) starts its own copy of feed.py or
engine_feed.py. Without this gate, all of them refetch the moment a cache expires, a burst of requests that TradingView
answers by refusing everyone for several minutes. With it, the first caller fetches; the others wait their turn and then
read that same answer. It uses only the standard library and works across processes through a lock file.
"""

import hashlib
import json
import os
import time
from pathlib import Path

HERE = Path(__file__).parent
LOCK = HERE / "fetch.lock"
RECENT = HERE / "recent"
LOCK_STALE_SECONDS = 300           # a lock older than this belongs to a process that died
LOCK_WAIT_SECONDS = 240


def _acquire() -> None:
    deadline = time.time() + LOCK_WAIT_SECONDS
    while True:
        try:
            os.close(os.open(LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
            return
        except FileExistsError:
            try:
                if time.time() - LOCK.stat().st_mtime > LOCK_STALE_SECONDS:
                    LOCK.unlink()
                    continue
            except OSError:
                pass
            if time.time() > deadline:
                raise TimeoutError("another TradingView request is still running")
            time.sleep(0.5)


def serve(request: dict, ttl: int, compute) -> str:
    """The text ``compute()`` returns for ``request``, run by one process at a time and reused for ``ttl`` seconds."""
    path = RECENT / f"{hashlib.sha1(json.dumps(request, sort_keys=True).encode()).hexdigest()[:16]}.json"

    def recent():
        fresh = path.exists() and time.time() - path.stat().st_mtime < ttl
        return path.read_text(encoding="utf-8") if fresh else None

    found = recent()
    if found is not None:
        return found
    _acquire()
    try:
        found = recent()                         # the process ahead of us may have just fetched exactly this
        if found is not None:
            return found
        text = compute()
        RECENT.mkdir(exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(path)
        return text
    finally:
        LOCK.unlink(missing_ok=True)
