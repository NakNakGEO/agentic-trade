"""A run's event log (events.jsonl) summed up per pair and day: when each pair's work started and last moved, which agents
spoke, and the tokens used. Shared by the dashboard (round progress) and the scorecard (when each call landed).

The log is read once and then only its new lines, because during a round it grows every few seconds.
"""

from __future__ import annotations

import json
from pathlib import Path

_logs: dict[Path, dict] = {}


def cells(path: Path) -> dict:
    """{cell label ("EURUSD 2026-10-29"): {first, last, nodes, node, tokens}}; ``last`` is the time of the cell's newest event,
    which for a finished pair is when its call landed. ``nodes`` lists each agent in the order it first spoke."""
    log = _logs.setdefault(path, {"offset": 0, "cells": {}})
    try:
        size = path.stat().st_size
    except OSError:
        return log["cells"]
    if size < log["offset"]:                                       # the file was replaced: start again
        log.update(offset=0, cells={})
    with open(path, "rb") as handle:
        handle.seek(log["offset"])
        chunk = handle.read()
    whole = chunk.rfind(b"\n") + 1                                 # a half-written last line waits for the next read
    log["offset"] += whole
    for line in chunk[:whole].decode("utf-8", errors="replace").splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        label = event.get("cell")
        if not label or "t" not in event:
            continue
        cell = log["cells"].setdefault(label, {"first": event["t"], "last": event["t"], "nodes": [], "node": None, "tokens": 0})
        cell["last"] = event["t"]
        if event.get("kind") == "llm":
            node = event.get("node")
            if node and node not in cell["nodes"]:
                cell["nodes"].append(node)
            cell["node"] = node
            cell["tokens"] += (event.get("tokens_in") or 0) + (event.get("tokens_out") or 0)
    return log["cells"]


def split(label: str) -> tuple[str, str] | None:
    """("EURUSD", "2026-10-29") from a cell label, or None for a label that is not a pair and a day."""
    ticker, _, day = label.rpartition(" ")
    return (ticker, day) if ticker and day else None
