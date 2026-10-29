"""An in-memory broker for the bridge tests: no MT5 terminal needed, records every order it is given."""

from paper_trade.bridge import settings
from paper_trade.bridge.models import AccountState, Bar, OrderRequest, Position, Quote, SendResult, SymbolSpec

SYMBOLS = ("AAPLm", "GOOGLm", "AMZNm", "BTCUSDm", "ETHUSDm", "EURUSDm", "XAUUSDm")   # an Exness-style account
PRICES = {"AAPLm": 200.0, "GOOGLm": 180.0, "AMZNm": 210.0, "BTCUSDm": 80_000.0, "ETHUSDm": 3_500.0,
          "EURUSDm": 1.1, "XAUUSDm": 2_000.0}


def spec(name, volume_min=0.01, min_stop=0.5, long_allowed=True, short_allowed=True):
    """One tick is 0.01 and worth 1.00 per lot, so a stop 40 away loses 4,000 per lot."""
    return SymbolSpec(name, 2, 0.01, 0.01, 1.0, volume_min, 100.0, 0.01, min_stop, long_allowed, short_allowed)


def bars(daily_range, count=20, close=100.0):
    """Flat bars, each exactly ``daily_range`` tall, so the average range is ``daily_range``."""
    return [Bar(close + daily_range / 2, close - daily_range / 2, close) for _ in range(count)]


class FakeBroker:
    def __init__(self, demo=True, equity=10_000.0, trading_allowed=True, positions=(), spread=0.1,
                 daily_range=20.0, names=SYMBOLS, **spec_options):
        self._account = AccountState(10000001, "Test-Demo", "USD", equity, equity, demo, trading_allowed)
        self._positions = list(positions)
        self.names, self.spread, self.daily_range, self.spec_options = list(names), spread, daily_range, spec_options
        self.check_result = SendResult(True, "ok", 0)
        self.send_results = []              # popped in order; an empty list means every send succeeds
        self.checked, self.sent = [], []

    def account(self):
        return self._account

    def symbol_names(self):
        return self.names

    def spec(self, symbol):
        return spec(symbol, **self.spec_options)

    def quote(self, symbol):
        mid = PRICES.get(symbol, 100.0)
        return Quote(mid - self.spread / 2, mid + self.spread / 2)

    def daily_bars(self, symbol, count):
        return bars(self.daily_range, count, PRICES.get(symbol, 100.0))

    def positions(self):
        return self._positions

    def check(self, request: OrderRequest):
        self.checked.append(request)
        return self.check_result

    def send(self, request: OrderRequest):
        self.sent.append(request)
        return self.send_results.pop(0) if self.send_results else SendResult(True, "done", 10009, request.price, 1)


def position(symbol="XAUUSDm", side="buy", volume=0.05, price=2_000.0, sl=1_960.0, magic=settings.MAGIC, ticket=7):
    return Position(ticket, symbol, side, volume, price, sl, magic)
