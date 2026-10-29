"""A shared pause on TradingView requests after it refuses one, so the loops and the dashboard back off together.

When TradingView answers with errors (it limits how often one client may ask), every process waits out the same
cool-down instead of retrying each cycle, which would only keep the limit in force. Prices then come from the
fallback sources (feeds.py) until the pause ends.
"""

from __future__ import annotations

import time

from paper_trade.live import settings


class CoolingDown(RuntimeError):
    pass


def why(stderr: str) -> str:
    """The useful part of a failed feed's error output: what TradingView answered, then how it ended."""
    lines = [line.strip() for line in (stderr or "").splitlines() if line.strip()]
    answers = [line for line in lines if "transient" in line or "HTTP" in line or "status" in line.lower()][:2]
    return " | ".join((answers + lines[-1:])[:3])[:500] or "no error text"


def _until() -> float:
    try:
        return float(settings.TV_COOLDOWN_PATH.read_text(encoding="utf-8").split()[0])
    except (OSError, ValueError, IndexError):
        return 0.0


def seconds_left() -> int:
    """Seconds until requests are allowed again (0 when there is no pause)."""
    return max(0, round(_until() - time.time()))


def check() -> None:
    """Raise ``CoolingDown`` while a pause set by any process is still running."""
    left = seconds_left()
    if left > 0:
        raise CoolingDown(f"TradingView asked us to slow down; next request in {left} s")


def failed() -> None:
    """Start (or lengthen) the pause: each refusal in a row doubles it, up to the maximum."""
    try:
        streak = int(settings.TV_COOLDOWN_PATH.read_text(encoding="utf-8").split()[1]) + 1
    except (OSError, ValueError, IndexError):
        streak = 1
    pause = min(settings.TV_COOLDOWN_SECONDS * 2 ** (streak - 1), settings.TV_COOLDOWN_MAX_SECONDS)
    settings.TV_COOLDOWN_PATH.parent.mkdir(parents=True, exist_ok=True)
    settings.TV_COOLDOWN_PATH.write_text(f"{time.time() + pause} {streak}", encoding="utf-8")


def succeeded() -> None:
    settings.TV_COOLDOWN_PATH.unlink(missing_ok=True)
