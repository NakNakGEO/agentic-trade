"""Paper-trade settings. Edit values here; logic modules hold no hardcoded numbers."""

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUNS_DIR = ROOT / "runs"
CACHE_DIR = ROOT / "cache"

# A test copy sets AGENTIC_LIVE_DATA_DIR to the live system's runs folder. It then READS the live prices, minute candles,
# daily record and TradingView caches from there and never records or fetches any of it (docs/RELEASING.md).
LIVE_DATA_DIR = os.environ.get("AGENTIC_LIVE_DATA_DIR") or None
READ_ONLY_DATA = LIVE_DATA_DIR is not None
DATA_DIR = Path(LIVE_DATA_DIR) if READ_ONLY_DATA else RUNS_DIR
ALLOW_TEST_ROUNDS = os.environ.get("AGENTIC_ALLOW_TEST_ROUNDS") == "1"     # a test copy only starts model calls when told to
IS_TEST_COPY = (ROOT / ".test_copy").exists()                             # marker file in the test copy: it never starts live loops

# Local Ollama model with a raised context window (see Modelfile notes in the README).
LLM_SETTINGS = {
    "llm_provider": "ollama",
    "deep_think_llm": "ta-gemma12b",
    "quick_think_llm": "ta-gemma12b",
}

HOSTED_LLM_RETRIES = 8      # retry budget for hosted providers, which rate-limit free plans

# What the dashboard shows for known online endpoints, keyed by the endpoint's host name.
# monthly_tokens is the provider's published free allowance (shared by every run this month).
PROVIDER_INFO: dict[str, dict] = {
    "api.iteracompute.com": {"label": "IteraCompute (online API)", "monthly_tokens": 30_000_000},
}

# Analysts used when replaying past dates. The social feed (StockTwits/Reddit) is not
# archived, so replaying it would leak today's chatter into a past decision.
REPLAY_ANALYSTS = ("market", "news", "fundamentals")
LIVE_ANALYSTS = ("market", "social", "news", "fundamentals")

# Hidden reasoning pass of the local model: most of the runtime. See nothink.py.
DISABLE_THINKING = True

# One mixed universe: stocks, crypto, forex and gold. The framework resolves each symbol.
UNIVERSE = ("AAPL", "GOOGL", "AMZN", "BTC-USD", "ETH-USD", "EURUSD", "XAUUSD")

STARTING_CASH = 100.0       # split equally across tickers into independent sleeves
COST_BPS = 5.0              # commission + slippage, charged on each side of every trade
MIN_TRADE_FRACTION = 0.01   # ignore rebalances smaller than this share of sleeve equity
BENCHMARK = "SPY"

# (floor, cap) on the share of a ticker's sleeve held after each rating; the position is
# clamped into this range, so a rating never moves it the wrong way:
#   Buy          exactly 100%             Overweight   at least 75%, never cut (adds only)
#   Hold         unchanged                Underweight  at most 25%, never added to (trims only)
#   Sell         0%
# Long-only: the framework's "Sell" means exit or avoid entry, never go short.
RATING_BOUNDS: dict[str, tuple[float, float]] = {
    "Buy": (1.0, 1.0),
    "Overweight": (0.75, 1.0),
    "Hold": (0.0, 1.0),
    "Underweight": (0.0, 0.25),
    "Sell": (0.0, 0.0),
}

# Long and short: the account may also bet on a fall (sell first, buy back later), like a Sell order in MT5.
# Negative numbers are short positions as a share of the sleeve. Mirror image of the long side:
#   Buy +100%   Overweight at least +75% (adds, never cuts)   Hold unchanged
#   Underweight at most -75% (adds to a short, never covers)  Sell -100%
# The framework defines its ratings for a long-only fund, so reading Sell / Underweight as shorts is this
# harness's assumption. No borrow fees or margin interest are modelled, which flatters shorts a little.
RATING_BOUNDS_LONG_SHORT: dict[str, tuple[float, float]] = {
    "Buy": (1.0, 1.0),
    "Overweight": (0.75, 1.0),
    "Hold": (-1.0, 1.0),
    "Underweight": (-1.0, -0.75),
    "Sell": (-1.0, -1.0),
}

# Full size: the same long and short account, but Overweight and Underweight also commit 100% of the sleeve
# (the base rules use 75%). Only the position size changes; the decisions are the same.
RATING_BOUNDS_FULL_SIZE: dict[str, tuple[float, float]] = {
    "Buy": (1.0, 1.0),
    "Overweight": (1.0, 1.0),
    "Hold": (-1.0, 1.0),
    "Underweight": (-1.0, -1.0),
    "Sell": (-1.0, -1.0),
}

# Fixed-lot account: trades the bridge's fixed lot with its stop and take-profit instead of sizing by rating, so the
# paper result mirrors what the MT5 demo would do (see lots.py). It is leveraged: 0.01 lot of EURUSD is about $1,100.
# Units in one 1.00 lot; these are standard contract sizes and the crypto and gold ones should be checked on the account.
LOT_CONTRACT_UNITS = {"forex": 100_000, "crypto": 1, "gold": 100, "stock": 1}   # stock CFDs: one share per lot
LOT_COST_BPS = {"forex": 1.0, "gold": 1.0}   # per side, as a share of the position's value; other assets use COST_BPS
# (gold's 1 bp is about $0.40 on an ounce at $4,000, a little above a real spread; 5 bps would be $2 a side)
LOT_MODES = ("fixed_lot",)
LOT_HISTORY_DAYS = 45       # price history before the first decision: the stop needs 15 daily bars, holidays included
HISTORY_DAYS = 7            # the same for every other account

# The bounds are unused by the fixed-lot account; the entry only keeps the mode in the list of valid modes.
ACCOUNT_MODES = {"long_only": RATING_BOUNDS, "long_short": RATING_BOUNDS_LONG_SHORT,
                 "full_size": RATING_BOUNDS_FULL_SIZE, "fixed_lot": RATING_BOUNDS_LONG_SHORT}
MODE_LABELS = {"long_only": "Long only", "long_short": "Long and short", "full_size": "Long and short, full size",
               "fixed_lot": "Fixed lot with stops (like the MT5 demo)"}
DEFAULT_MODE = "long_short"
