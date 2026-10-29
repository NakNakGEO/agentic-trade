"""Live push to the page (Server-Sent Events): a fresh state the moment a run's files change.

The page listens with ``EventSource``, which reconnects on its own. A heartbeat goes out every second,
and a full state at least every few seconds even when nothing changed, so the page can always tell a
quiet run from a dead connection.
"""

from __future__ import annotations

import json
import time

from paper_trade.dashboard.state import build_state
from paper_trade.decide import run_dir

TICK = 1.0               # seconds between checks
FULL_EVERY = 4.0         # send the whole state at least this often
WATCHED = ("events.jsonl", "trading_memory.md", "progress.log", "meta.json")


def signature(run: str) -> tuple:
    """Changes whenever any file the page is built from changes."""
    folder = run_dir(run)
    parts = []
    for name in WATCHED:
        try:
            info = (folder / name).stat()
            parts.append((info.st_mtime_ns, info.st_size))
        except OSError:
            parts.append(None)
    return tuple(parts)


def message(run: str, mode: str) -> bytes:
    try:
        payload = {"ok": True, "data": build_state(run, mode), "sent": time.time()}
    except Exception as exc:                        # keep the stream alive on a bad read
        payload = {"ok": False, "error": str(exc)[:300], "sent": time.time()}
    return f"event: state\ndata: {json.dumps(payload, default=str)}\n\n".encode()


def serve(wfile, run: str, mode: str) -> None:
    """Write events to ``wfile`` until the browser goes away."""
    last_sig, last_sent = None, 0.0
    try:
        while True:
            now, sig = time.time(), signature(run)
            if sig != last_sig or now - last_sent >= FULL_EVERY:
                wfile.write(message(run, mode))
                last_sig, last_sent = sig, now
            else:
                wfile.write(b": keep-alive\n\n")
            wfile.flush()
            time.sleep(TICK)
    except (BrokenPipeError, ConnectionError, OSError):
        return                                       # the page was closed or reloaded
