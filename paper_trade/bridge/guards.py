"""Safety rules: the demo-only guard, the position and risk caps, and the soft warnings."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from paper_trade.bridge import settings
from paper_trade.bridge.models import AccountState, SymbolSpec


class RealAccountError(RuntimeError):
    """Raised when the terminal is logged in to anything but a demo account."""


def require_demo(account: AccountState) -> None:
    """Refuse to go any further on a real (or contest) account."""
    if not account.is_demo:
        raise RealAccountError(
            f"account {account.login} on {account.server} is not a demo account. The bridge only works on a "
            "demo account: open an Exness demo account and log in to it in the MT5 terminal.")


@dataclass
class Budget:
    """Open positions and open risk across all pairs; each new order has to fit in what is left."""
    positions: int
    risk: float
    equity: float
    max_total_risk: float = settings.MAX_TOTAL_RISK

    def release(self, risk: float) -> None:
        self.positions -= 1
        self.risk -= risk

    def refusal(self, risk: float) -> str | None:
        """Why one more position with this risk does not fit, or None when it does."""
        if self.positions >= settings.MAX_OPEN_POSITIONS:
            return f"already {self.positions} open positions (limit {settings.MAX_OPEN_POSITIONS})"
        cap = self.equity * self.max_total_risk
        if self.risk + risk > cap:
            return (f"total open risk would be {self.risk + risk:,.2f} against a cap of {cap:,.2f} "
                    f"({self.max_total_risk:.0%} of equity)")
        return None

    def take(self, risk: float) -> None:
        self.positions += 1
        self.risk += risk


def low_liquidity(now: datetime) -> str | None:
    start, end = settings.LOW_LIQUIDITY_UTC
    if start <= now.hour < end:
        return f"low-liquidity hours ({start}:00-{end % 24:02d}:00 UTC): spreads are wider and fills worse"
    return None


def wide_spread(base: str | None, spec: SymbolSpec, spread: float, distance: float) -> str | None:
    """Why this spread (in price units) is too wide for a stop ``distance`` away, or None when it is fine."""
    limit = settings.MAX_SPREAD_POINTS.get(base or "")
    if limit is not None:
        points = spread / spec.point
        return f"spread {points:.0f} points is over the {limit}-point limit" if points > limit else None
    if distance > 0 and spread > settings.MAX_SPREAD_FRACTION_OF_STOP * distance:
        return (f"spread {spread:g} is {spread / distance:.0%} of the stop distance "
                f"(over {settings.MAX_SPREAD_FRACTION_OF_STOP:.0%})")
    return None
