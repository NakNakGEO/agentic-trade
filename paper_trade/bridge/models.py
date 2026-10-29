"""Plain data shared by the bridge, the MT5 adapter and the tests."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class AccountState:
    login: int
    server: str
    currency: str
    balance: float
    equity: float
    is_demo: bool
    terminal_trading_allowed: bool      # the terminal's "Allow algorithmic trading" switch


@dataclass(frozen=True)
class SymbolSpec:
    name: str
    digits: int
    point: float
    tick_size: float
    tick_value: float           # profit of one tick on one lot, in the account currency
    volume_min: float
    volume_max: float
    volume_step: float
    min_stop_distance: float    # closest a stop may sit to the price, in price units
    long_allowed: bool
    short_allowed: bool


@dataclass(frozen=True)
class Quote:
    bid: float
    ask: float


@dataclass(frozen=True)
class Bar:
    high: float
    low: float
    close: float


@dataclass(frozen=True)
class Position:
    ticket: int
    symbol: str
    side: str               # "buy" or "sell"
    volume: float
    price_open: float
    sl: float               # 0 means none
    magic: int


@dataclass(frozen=True)
class OrderRequest:
    symbol: str
    side: str               # "buy" or "sell"
    volume: float
    price: float
    sl: float = 0.0
    tp: float = 0.0
    position: int | None = None     # ticket to close; None opens a new position
    comment: str = ""


@dataclass(frozen=True)
class SendResult:
    ok: bool
    message: str
    retcode: int | None = None
    price: float | None = None
    ticket: int | None = None


@dataclass
class Step:
    """One order the plan wants to send (opening a position, or closing one)."""
    kind: str                           # "open" or "close"
    request: OrderRequest
    risk_money: float = 0.0
    risk_fraction: float = 0.0
    reward_risk: float = 0.0
    check: SendResult | None = None     # the server's own dry-run of the order


@dataclass
class TickerPlan:
    ticker: str
    symbol: str | None
    rating: str
    decision_date: str
    steps: list[Step] = field(default_factory=list)
    action: str = "skip"                # open, close, flip, keep or skip
    notes: list[str] = field(default_factory=list)      # why it was skipped or kept
    warnings: list[str] = field(default_factory=list)   # soft rules; the confirmation is the gate

    @property
    def ready(self) -> bool:
        """True when there are orders to send and the server's dry-run accepted every one."""
        return bool(self.steps) and all(s.check is not None and s.check.ok for s in self.steps)
