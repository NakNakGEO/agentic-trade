"""Control a model's hidden reasoning without touching the cloned repo.

TradingAgents only forwards reasoning settings for native OpenAI providers, so there is no config
route for local or Qwen-style models. Their OpenAI-compatible endpoints accept extra request fields
that change the reasoning pass, which is most of the generated tokens in a run.

Measured on IteraCompute's Qwen3.8 (same prompt, one call each): ``reasoning_effort`` low / medium /
default gave 350 / 589 / 1,008 tokens, but ``enable_thinking: false`` still gave 500, so that "off"
switch is NOT honoured there. Use an effort level to turn thinking down on that endpoint.
"""

from __future__ import annotations

import copy
import dataclasses

# Extra request-body fields that try to turn thinking off, per TradingAgents provider name.
THINKING_OFF_BODY: dict[str, dict] = {
    "ollama": {"reasoning_effort": "none"},
    "openai_compatible": {"chat_template_kwargs": {"enable_thinking": False}},   # ignored by IteraCompute
}
EFFORTS = ("low", "medium", "high", "xhigh")
MARKER = "paper_trade_extra_body"     # records which fields a patched client class already sends


def _patch(provider: str, body: dict) -> bool:
    """Make every chat client of ``provider`` send ``body`` as extra request fields. Safe to call twice."""
    from tradingagents.llm_clients import openai_client

    spec = openai_client.OPENAI_COMPATIBLE_PROVIDERS.get(provider)
    if spec is None:
        return False
    base = spec.chat_class
    if getattr(base, MARKER, None) == body:
        return True

    class PatchedChat(base):                       # type: ignore[misc, valid-type]
        def __init__(self, **kwargs):
            merged = dict(kwargs.pop("extra_body", None) or {})
            for key, value in body.items():
                merged.setdefault(key, copy.deepcopy(value))
            super().__init__(extra_body=merged, **kwargs)

    # Set after the class exists: an underscore name inside the class body would become a pydantic private field.
    setattr(PatchedChat, MARKER, body)
    openai_client.OPENAI_COMPATIBLE_PROVIDERS[provider] = dataclasses.replace(spec, chat_class=PatchedChat)
    return True


def disable_thinking(provider: str) -> bool:
    """Send the provider's thinking-off field. False when this provider has no known switch."""
    body = THINKING_OFF_BODY.get(provider)
    return _patch(provider, body) if body else False


def set_reasoning_effort(provider: str, effort: str) -> bool:
    """Keep thinking on but at ``effort`` (low / medium / high / xhigh). False for an unknown provider."""
    if effort not in EFFORTS:
        raise ValueError(f"effort must be one of {EFFORTS}, got {effort!r}")
    return _patch(provider, {"reasoning_effort": effort})
