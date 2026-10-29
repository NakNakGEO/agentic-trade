"""Slippage for the paper account: fills that land a little worse than the price the account saw.

The per-side fee (config.LOT_COST_BPS) already pays about a spread on every fill, so this adds only what the fee does not:
a market order (an entry, a time-limit close, a close by a new call) fills slightly worse than the price, and a stop-loss
fills worse again because a stop becomes a market order when the price reaches it. A take-profit is a limit order and
fills at its level. It is a switch per account (AGENTIC_SLIPPAGE_<ACCOUNT NAME>=on) and off by default.
"""

from __future__ import annotations

from dataclasses import dataclass

from paper_trade import assets
from paper_trade.live import settings

STOP_REASONS = ("Stop-loss", "Wiped out")       # these are closed as market orders in a falling price


@dataclass(frozen=True)
class Friction:
    bps: dict = None                            # asset class -> (market order slippage, stop-loss slippage), in basis points

    def _rates(self, ticker: str) -> tuple[float, float]:
        return (self.bps or settings.SLIPPAGE_BPS).get(assets.asset_class(ticker), (0.0, 0.0))

    def into(self, ticker: str, side: int, price: float) -> float:
        """The price an entry fills at: a buyer pays a little more, a seller gets a little less."""
        return price * (1 + side * self._rates(ticker)[0] / 1e4)

    def out(self, ticker: str, side: int, price: float, reason: str) -> float:
        """The price a close fills at. A take-profit fills at its level; every other close is a market order."""
        if reason == "Take-profit":
            return price
        market, stop = self._rates(ticker)
        return price * (1 - side * (stop if reason in STOP_REASONS else market) / 1e4)


def for_account(account: settings.Account) -> Friction | None:
    """The account's slippage, or None when it is switched off."""
    return Friction() if account.slippage else None
