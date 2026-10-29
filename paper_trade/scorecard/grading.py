"""Grade calls against what the price actually did, ignoring our stops, targets and time limits.

A call is graded ``horizon`` seconds after it landed: the price then against the price when it landed. A buy is right if the
price rose, a sell if it fell; a move smaller than FLAT_BPS counts as no move and is left out of the right/wrong percentage.
Three simple guesses are graded on the very same calls: always sell, always buy, and TradingView's own rating from the evening
before. A Hold is not graded, but its calls are counted and so is how far the price moved after them.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from paper_trade.scorecard import settings
from paper_trade.scorecard.calls import Call


class Prices:
    """One pair's recorded minute closes, looked up by epoch seconds."""

    def __init__(self, closes: pd.Series):
        closes = closes.sort_index()
        self.seconds = closes.index.values.astype("datetime64[s]").astype("int64")      # minutes are recorded in UTC
        self.values = closes.values.astype(float)

    @property
    def newest(self) -> float:
        return float(self.seconds[-1]) if len(self.seconds) else float("-inf")

    def at(self, when: float) -> float | None:
        """The close of the last recorded minute at or before ``when``, if it is recent enough."""
        i = int(np.searchsorted(self.seconds, when, side="right")) - 1
        if i < 0 or when - self.seconds[i] > settings.PRICE_TOLERANCE_SECONDS:
            return None
        return float(self.values[i])


def move_bps(prices: Prices, at: float, seconds: float) -> float | None:
    """How far the price moved from ``at`` to ``seconds`` later, in basis points; None until that time has been recorded."""
    if at + seconds > prices.newest + settings.PRICE_TOLERANCE_SECONDS:
        return None
    start, end = prices.at(at), prices.at(at + seconds)
    if start is None or end is None or start <= 0:
        return None
    return (end / start - 1) * 1e4


def verdict(signed_bps: float) -> str:
    return "right" if signed_bps > settings.FLAT_BPS else "wrong" if signed_bps < -settings.FLAT_BPS else "flat"


def _tv_side(rating: float | None) -> int:
    return 0 if rating is None or abs(rating) <= settings.TV_BAND else 1 if rating > 0 else -1


def _empty() -> dict:
    return {"right": 0, "wrong": 0, "flat": 0, "bps": 0.0}


def _add(bucket: dict, signed_bps: float) -> None:
    bucket[verdict(signed_bps)] += 1
    bucket["bps"] += signed_bps


def _share(bucket: dict) -> dict:
    decided = bucket["right"] + bucket["wrong"]
    graded = decided + bucket["flat"]
    return {"n": graded, "right": bucket["right"], "wrong": bucket["wrong"], "flat": bucket["flat"],
            "right_pct": round(100 * bucket["right"] / decided, 1) if decided else None,
            "avg_bps": round(bucket["bps"] / graded, 2) if graded else None}


def grade(calls: list[Call], prices: dict[str, Prices], horizons: dict | None = None) -> dict:
    """The scorecard for a list of calls. ``prices`` maps each call's ticker to its recorded minutes."""
    horizons = horizons or settings.HORIZONS
    out = {"calls": len(calls), "holds": sum(1 for c in calls if c.rating == "Hold"),
           "unreadable": sum(1 for c in calls if c.rating not in settings.KNOWN_RATINGS), "horizons": {}, "pairs": {}}
    for name, seconds in horizons.items():
        buckets = {key: _empty() for key in ("calls", "sell", "buy", "tv")}
        held, held_move = 0, 0.0
        for call in calls:
            series = prices.get(call.ticker)
            move = move_bps(series, call.at, seconds) if series else None
            if move is None:
                continue
            if call.side == 0:
                held, held_move = held + (call.rating == "Hold"), held_move + (abs(move) if call.rating == "Hold" else 0.0)
                continue
            _add(buckets["calls"], move * call.side)
            _add(buckets["sell"], -move)
            _add(buckets["buy"], move)
            tv = _tv_side(call.tv_before)
            if tv:
                _add(buckets["tv"], move * tv)
            pair = out["pairs"].setdefault(call.ticker, {}).setdefault(name, _empty())
            _add(pair, move * call.side)
        row = _share(buckets["calls"])
        row.update(enough=row["n"] >= settings.MIN_SAMPLE, holds_graded=held, hold_avg_move_bps=round(held_move / held, 2) if held else None,
                   baselines={key: _share(buckets[key]) for key in ("sell", "buy", "tv")})
        out["horizons"][name] = row
    out["pairs"] = {t: {h: _share(b) for h, b in by.items()} for t, by in sorted(out["pairs"].items())}
    return out
