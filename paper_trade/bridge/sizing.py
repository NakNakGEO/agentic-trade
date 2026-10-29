"""Stop placement and lot sizing. Pure arithmetic: no broker calls, so it is easy to test."""

from __future__ import annotations

import math

from paper_trade.bridge import settings
from paper_trade.bridge.models import Bar, Position, SymbolSpec


def atr(bars: list[Bar], period: int = settings.ATR_PERIOD) -> float | None:
    """Average true range of the last ``period`` completed bars; None without enough history."""
    if len(bars) < period + 1:
        return None
    window = bars[-(period + 1):]
    ranges = [max(bar.high - bar.low, abs(bar.high - prev.close), abs(bar.low - prev.close))
              for prev, bar in zip(window, window[1:])]
    return sum(ranges) / period


def stop_distance(spec: SymbolSpec, average_range: float) -> float:
    """How far the stop sits from the entry: ATR-based, never closer than the broker allows."""
    return max(average_range * settings.ATR_STOP_MULT, spec.min_stop_distance)


def loss_per_lot(spec: SymbolSpec, distance: float) -> float:
    """Money lost on one lot when the price moves ``distance`` against the position."""
    return distance / spec.tick_size * spec.tick_value


def lots_for_risk(spec: SymbolSpec, risk_money: float, distance: float) -> float:
    """Largest volume (rounded down to the broker's step) that loses at most ``risk_money`` at the stop.

    Returns 0.0 when even the smallest allowed volume would lose more than that.
    """
    per_lot = loss_per_lot(spec, distance)
    if per_lot <= 0:
        return 0.0
    steps = math.floor(risk_money / per_lot / spec.volume_step + 1e-9)
    lots = round(min(steps * spec.volume_step, spec.volume_max), 8)
    return lots if lots >= spec.volume_min else 0.0


def fixed_lots(spec: SymbolSpec, lot: float) -> float:
    """``lot`` rounded down to the broker's step; 0.0 when it is below the symbol's minimum volume."""
    steps = math.floor(lot / spec.volume_step + 1e-9)
    lots = round(min(steps * spec.volume_step, spec.volume_max), 8)
    return lots if lots >= spec.volume_min else 0.0


def levels(spec: SymbolSpec, side: str, entry: float, distance: float) -> tuple[float, float]:
    """(stop, target) prices: the stop one distance against the entry, the target REWARD_RISK distances for it."""
    sign = 1 if side == "buy" else -1
    stop = round(entry - sign * distance, spec.digits)
    target = round(entry + sign * distance * settings.REWARD_RISK, spec.digits)
    return stop, target


def position_risk(spec: SymbolSpec, position: Position, equity: float) -> float:
    """Money an open position loses at its stop; a position with no stop is charged one full risk budget."""
    if position.sl == 0:
        return equity * settings.RISK_FRACTION
    return loss_per_lot(spec, abs(position.price_open - position.sl)) * position.volume
