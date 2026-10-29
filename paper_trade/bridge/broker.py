"""The broker interface the bridge talks to. MT5 implements it; the tests use a fake."""

from __future__ import annotations

from typing import Protocol

from paper_trade.bridge.models import (AccountState, Bar, OrderRequest, Position, Quote, SendResult, SymbolSpec)


class Broker(Protocol):
    def account(self) -> AccountState: ...

    def symbol_names(self) -> list[str]: ...

    def spec(self, symbol: str) -> SymbolSpec | None: ...

    def quote(self, symbol: str) -> Quote: ...

    def daily_bars(self, symbol: str, count: int) -> list[Bar]:
        """The last ``count`` completed daily bars, oldest first (today's unfinished bar is left out)."""
        ...

    def positions(self) -> list[Position]: ...

    def check(self, request: OrderRequest) -> SendResult:
        """Ask the server whether it would accept the order. Places nothing."""
        ...

    def send(self, request: OrderRequest) -> SendResult: ...
