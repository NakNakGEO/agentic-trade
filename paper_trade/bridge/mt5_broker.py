"""Broker adapter for the MetaTrader 5 terminal running on this PC (Windows, ``pip install MetaTrader5``).

No API key is involved: the Python package talks to the already logged-in terminal. The package is imported
lazily so the rest of the bridge, and its tests, work without it.
"""

from __future__ import annotations

from paper_trade.bridge import settings
from paper_trade.bridge.models import (AccountState, Bar, OrderRequest, Position, Quote, SendResult, SymbolSpec)

CHECK_OK = (0,)                 # order_check reports success as retcode 0
SEND_OK = (10009, 10010)        # TRADE_RETCODE_DONE, TRADE_RETCODE_DONE_PARTIAL


class Mt5Broker:
    def __init__(self, terminal_path: str | None = None):
        try:
            import MetaTrader5 as mt5
        except ImportError as error:
            raise ImportError("the MetaTrader5 package is missing: run "
                              "`uv pip install MetaTrader5` in the project venv") from error
        self.mt5 = mt5
        if not mt5.initialize(**({"path": terminal_path} if terminal_path else {})):
            raise ConnectionError(f"could not connect to the MT5 terminal: {mt5.last_error()}. "
                                  "Open the terminal and log in to the demo account first.")

    def shutdown(self) -> None:
        self.mt5.shutdown()

    def account(self) -> AccountState:
        info, terminal = self.mt5.account_info(), self.mt5.terminal_info()
        if info is None or terminal is None:
            raise ConnectionError(f"the terminal is not logged in to an account: {self.mt5.last_error()}")
        return AccountState(info.login, info.server, info.currency, float(info.balance), float(info.equity),
                            info.trade_mode == self.mt5.ACCOUNT_TRADE_MODE_DEMO,
                            bool(terminal.trade_allowed) and bool(info.trade_allowed))

    def symbol_names(self) -> list[str]:
        return [s.name for s in self.mt5.symbols_get() or ()]

    def spec(self, symbol: str) -> SymbolSpec | None:
        info = self._info(symbol)
        if info is None:
            return None
        mt5 = self.mt5
        full, long_only, short_only = (mt5.SYMBOL_TRADE_MODE_FULL, mt5.SYMBOL_TRADE_MODE_LONGONLY,
                                       mt5.SYMBOL_TRADE_MODE_SHORTONLY)
        tick_value = getattr(info, "trade_tick_value_loss", 0.0) or info.trade_tick_value   # what a loss costs
        return SymbolSpec(
            name=info.name, digits=info.digits, point=info.point, tick_size=info.trade_tick_size,
            tick_value=tick_value, volume_min=info.volume_min, volume_max=info.volume_max,
            volume_step=info.volume_step, min_stop_distance=(info.trade_stops_level + info.spread) * info.point,
            long_allowed=info.trade_mode in (full, long_only), short_allowed=info.trade_mode in (full, short_only))

    def quote(self, symbol: str) -> Quote:
        tick = self.mt5.symbol_info_tick(symbol)
        if tick is None:
            raise ConnectionError(f"no price for {symbol}: {self.mt5.last_error()}")
        return Quote(float(tick.bid), float(tick.ask))

    def daily_bars(self, symbol: str, count: int) -> list[Bar]:
        rates = self.mt5.copy_rates_from_pos(symbol, self.mt5.TIMEFRAME_D1, 1, count)   # 1 skips today's bar
        if rates is None:
            return []
        return [Bar(float(r["high"]), float(r["low"]), float(r["close"])) for r in rates]

    def positions(self) -> list[Position]:
        sell = self.mt5.POSITION_TYPE_SELL
        return [Position(p.ticket, p.symbol, "sell" if p.type == sell else "buy", p.volume, p.price_open,
                         p.sl, p.magic) for p in self.mt5.positions_get() or ()]

    def check(self, request: OrderRequest) -> SendResult:
        result = self.mt5.order_check(self._payload(request))
        if result is None:
            return SendResult(False, f"order_check failed: {self.mt5.last_error()}")
        return SendResult(result.retcode in CHECK_OK, result.comment, result.retcode)

    def send(self, request: OrderRequest) -> SendResult:
        result = self.mt5.order_send(self._payload(request))
        if result is None:
            return SendResult(False, f"order_send failed: {self.mt5.last_error()}")
        return SendResult(result.retcode in SEND_OK, result.comment, result.retcode, result.price, result.order)

    def _info(self, symbol: str):
        if not self.mt5.symbol_select(symbol, True):       # make sure the symbol is in Market Watch
            return None
        return self.mt5.symbol_info(symbol)

    def _filling(self, symbol: str) -> int:
        flags = self._info(symbol).filling_mode
        if flags & 2:
            return self.mt5.ORDER_FILLING_IOC
        return self.mt5.ORDER_FILLING_FOK if flags & 1 else self.mt5.ORDER_FILLING_RETURN

    def _payload(self, request: OrderRequest) -> dict:
        mt5 = self.mt5
        payload = {
            "action": mt5.TRADE_ACTION_DEAL, "symbol": request.symbol, "volume": request.volume,
            "type": mt5.ORDER_TYPE_BUY if request.side == "buy" else mt5.ORDER_TYPE_SELL,
            "price": request.price, "deviation": settings.DEVIATION_POINTS, "magic": settings.MAGIC,
            "comment": request.comment, "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": self._filling(request.symbol),
        }
        if request.position is not None:
            payload["position"] = request.position
        if request.sl:
            payload["sl"] = request.sl
        if request.tp:
            payload["tp"] = request.tp
        return payload
