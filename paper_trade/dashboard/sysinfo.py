"""Local-model and GPU readings for the dashboard. Both degrade to empty on any failure."""

from __future__ import annotations

import os
import re
import subprocess
import time
from pathlib import Path

OLLAMA_LOG = Path(os.environ.get("LOCALAPPDATA", "")) / "Ollama" / "server.log"
_NO_WINDOW = 0x08000000   # CREATE_NO_WINDOW: no console pop-up on Windows
TAIL_BYTES = 2_000_000


def log_offset() -> int:
    """Where the Ollama log ends now, so calls can be counted from this moment."""
    try:
        return OLLAMA_LOG.stat().st_size
    except OSError:
        return 0


def parse_ollama_log(text: str) -> dict:
    """Request count, last prompt size and last generation speed from raw log text."""
    prompts = re.findall(r"init_sampler.*?text = (\d+)", text)
    speeds = re.findall(r"tg =\s+([\d.]+) t/s", text)
    return {
        "requests": text.count("init_sampler"),
        "last_prompt_tokens": int(prompts[-1]) if prompts else None,
        "tokens_per_second": float(speeds[-1]) if speeds else None,
    }


_memo: dict = {}


def _cached(key, ttl: float, read):
    """Reuse a reading for ``ttl`` seconds, so a page that updates every second does not spawn a process each time."""
    hit = _memo.get(key)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    value = read()
    _memo[key] = (time.time(), value)
    return value


def ollama_stats(since: int) -> dict:
    return _cached(("ollama", since), 3.0, lambda: _read_ollama(since))


def gpu_stats() -> dict:
    return _cached("gpu", 3.0, _read_gpu)


def _read_ollama(since: int) -> dict:
    try:
        size = OLLAMA_LOG.stat().st_size
        start = since if 0 <= since <= size else 0
        start = max(start, size - TAIL_BYTES)
        with open(OLLAMA_LOG, "rb") as handle:
            handle.seek(start)
            return parse_ollama_log(handle.read().decode("utf-8", errors="replace"))
    except OSError:
        return {}


def _read_gpu() -> dict:
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,utilization.gpu,memory.used,memory.total",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5, creationflags=_NO_WINDOW,
        ).stdout.strip().splitlines()[0]
        name, util, used, total = [part.strip() for part in out.split(",")]
        return {"name": name, "util": int(util), "mem_used_mb": int(used), "mem_total_mb": int(total)}
    except (OSError, subprocess.SubprocessError, IndexError, ValueError):
        return {}
