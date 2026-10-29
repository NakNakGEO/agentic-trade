"""Live event feed: one JSON line per LLM call and tool call, tagged with the agent's graph node.

Registered as a LangChain configure hook, so it reaches every call the framework makes
without editing the framework. The dashboard reads the file this writes.
"""

from __future__ import annotations

import json
import threading
import time
from contextvars import ContextVar
from pathlib import Path

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.tracers.context import register_configure_hook

_HANDLER: ContextVar[BaseCallbackHandler | None] = ContextVar("paper_trade_feed", default=None)
register_configure_hook(_HANDLER, inheritable=True)

SNIPPET_CHARS = 20_000     # effectively the full message; only a runaway answer is cut
TOOL_INPUT_CHARS = 600


def _timing(started: float) -> dict:
    """How long a call took: ``ms`` is exact, ``seconds`` is kept for older readers."""
    took = time.time() - started
    return {"seconds": round(took, 1), "ms": round(took * 1000)}


def _node(metadata: dict | None) -> str:
    """The agent's name. Analysts run as subgraphs whose inner nodes are just ``agent`` and
    ``tools``, so the outermost segment of the checkpoint namespace names the agent."""
    meta = metadata or {}
    namespace = meta.get("langgraph_checkpoint_ns") or ""
    outer = namespace.split("|")[0].split(":")[0]
    return outer or meta.get("langgraph_node") or "-"


class FeedHandler(BaseCallbackHandler):
    """Appends events to ``path``; never raises into the framework's run."""

    raise_error = False

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.cell = ""
        self._lock = threading.Lock()
        self._started: dict = {}

    def set_cell(self, ticker: str, date: str) -> None:
        self.cell = f"{ticker} {date}"

    def _write(self, record: dict) -> None:
        line = json.dumps({"t": time.time(), "cell": self.cell, **record}, ensure_ascii=False)
        with self._lock, open(self.path, "a", encoding="utf-8") as handle:
            handle.write(line + "\n")

    def on_chat_model_start(self, serialized, messages, *, run_id, metadata=None, **kwargs):
        self._started[run_id] = (time.time(), _node(metadata))

    def on_llm_start(self, serialized, prompts, *, run_id, metadata=None, **kwargs):
        self._started[run_id] = (time.time(), _node(metadata))

    def on_llm_end(self, response, *, run_id, **kwargs):
        started, node = self._started.pop(run_id, (time.time(), "-"))
        message = getattr(response.generations[0][0], "message", None) if response.generations else None
        text = (response.generations[0][0].text if response.generations else "") or ""
        usage = (getattr(message, "usage_metadata", None) or {}) if message else {}
        calls = [call.get("name") for call in (getattr(message, "tool_calls", None) or [])]
        self._write({"kind": "llm", "node": node, **_timing(started),
                     "tokens_in": usage.get("input_tokens"), "tokens_out": usage.get("output_tokens"),
                     "tool_calls": calls, "text": text[:SNIPPET_CHARS]})

    def on_llm_error(self, error, *, run_id, **kwargs):
        started, node = self._started.pop(run_id, (time.time(), "-"))
        self._write({"kind": "error", "node": node, **_timing(started),
                     "text": str(error)[:SNIPPET_CHARS]})

    def on_tool_start(self, serialized, input_str, *, run_id, metadata=None, **kwargs):
        self._write({"kind": "tool", "node": _node(metadata),
                     "tool": (serialized or {}).get("name") or kwargs.get("name") or "tool",
                     "text": str(input_str)[:TOOL_INPUT_CHARS]})


def install(path: Path) -> FeedHandler:
    """Start feeding ``path`` for everything this context runs from now on."""
    handler = FeedHandler(path)
    _HANDLER.set(handler)
    return handler
