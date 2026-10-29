"""A list of API keys per online model, so the load (and any one key's limit) is spread over several.

The first key is the provider's usual variable (for example OPENAI_COMPATIBLE_API_KEY); further keys are the same name with
_2, _3 ... added, read from the environment or from the .env file. Keys are only ever handed to a worker process through
its environment: they are never printed or logged.
"""

from __future__ import annotations

import os
from pathlib import Path

from paper_trade import config

MAX_KEYS = 9


def env_file_values(path: Path) -> dict[str, str]:
    values = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return values
    for line in lines:
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            name, _, value = line.partition("=")
            values[name.strip()] = value.strip().strip('"').strip("'")
    return values


def load_keys(name: str, environ=None, env_file: Path | None = None) -> list[str]:
    """Every distinct non-empty key set for ``name``, ``name_2`` ... ``name_9``, in that order."""
    environ = os.environ if environ is None else environ
    file_values = env_file_values(env_file or config.ROOT / ".env")
    keys = []
    for variable in [name] + [f"{name}_{n}" for n in range(2, MAX_KEYS + 1)]:
        value = (environ.get(variable) or file_values.get(variable) or "").strip()
        if value and value not in keys:
            keys.append(value)
    return keys


def pick(keys: list[str], index: int) -> str | None:
    """The key for the ``index``-th worker: they are used in turn, so a round is spread over all of them."""
    return keys[index % len(keys)] if keys else None
