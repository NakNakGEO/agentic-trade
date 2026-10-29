"""Broker-bridge settings. Edit values here; the bridge modules hold no hardcoded numbers."""

from paper_trade import config

LOG_PATH = config.ROOT / "logs" / "bridge_orders.jsonl"   # one JSON line per order sent or refused

# --- risk rules (from the account's trading rules) -------------------------------------------------
RISK_FRACTION = 0.02            # most of the account equity one trade may lose if its stop is hit
MIN_REWARD_RISK = 1.5           # a plan below this ratio is refused
REWARD_RISK = 2.0               # take-profit sits this many stop-distances from the entry
MAX_POSITIONS_PER_SYMBOL = 3
MAX_OPEN_POSITIONS = len(config.UNIVERSE)   # one slot per pair
MAX_TOTAL_RISK = 0.10           # open risk of every position, as a share of equity

# A fixed lot replaces the risk-based sizing: every order uses this volume, and a symbol whose minimum lot is
# larger is skipped. None sizes each trade by RISK_FRACTION instead. The stop stays mandatory, so every trade
# still has a known worst case; with a fixed lot the open-risk cap below replaces MAX_TOTAL_RISK.
FIXED_LOT: float | None = 0.01
FIXED_LOT_MAX_TOTAL_RISK = 0.50

# --- stop placement: the model's own stop is not used (it can sit on the wrong side of the entry) ---
ATR_PERIOD = 14                 # daily bars
ATR_STOP_MULT = 2.0             # stop distance = this many average daily ranges

# Share of the risk budget used per rating (the simulator also sizes Overweight/Underweight at 75%).
CONVICTION = {"Buy": 1.0, "Overweight": 0.75, "Sell": 1.0, "Underweight": 0.75}
LONG_RATINGS = ("Buy", "Overweight")
SHORT_RATINGS = ("Sell", "Underweight")

# --- warnings (shown in the plan; the typed confirmation is the gate) -----------------------------
MAX_SPREAD_POINTS = {"XAUUSD": 30}      # gold: warn above 30 points
MAX_SPREAD_FRACTION_OF_STOP = 0.15      # every other symbol: warn if the spread is over 15% of the stop
LOW_LIQUIDITY_UTC = (21, 24)            # hours [from, to)
NEWS_REMINDER = "Check the calendar for NFP, CPI or FOMC within the next hour before confirming."

# --- decisions are only acted on while fresh, so a replayed (past-dated) run is never traded -------
MAX_DECISION_AGE_DAYS = 1

# --- order details ----------------------------------------------------------------------------------
MAGIC = 26102801                # tags the bridge's own positions so they can be told from manual ones
COMMENT = "paper_trade"
DEVIATION_POINTS = 30           # slippage the order tolerates

# --- symbol names: Yahoo-style ticker -> the base name at the broker, then tried with each suffix ---
BROKER_BASE_NAMES = {
    "AAPL": "AAPL", "GOOGL": "GOOGL", "AMZN": "AMZN",
    "BTC-USD": "BTCUSD", "ETH-USD": "ETHUSD",
    "EURUSD=X": "EURUSD", "GC=F": "XAUUSD",
}
SYMBOL_SUFFIXES = ("", "m", "z", "c", "b")      # Exness account types add one (XAUUSDm, EURUSDz, ...)
SYMBOL_OVERRIDES: dict[str, str] = {}           # exact names to force, e.g. {"AAPL": "AAPL.US"}
