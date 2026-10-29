"""Scorecard settings. Edit values here; the scorecard modules hold no hardcoded numbers."""

HORIZONS = {"1h": 3600, "4h": 4 * 3600, "12h": 12 * 3600, "1d": 86_400, "3d": 3 * 86_400}   # how long after a call it is graded
FLAT_BPS = 0.5                      # a move smaller than this (in basis points, 1 bp = 0.01%) counts as no move
MIN_SAMPLE = 30                     # fewer graded calls than this: the card says there are too few to judge
PRICE_TOLERANCE_SECONDS = 600       # a price must come from a recorded minute at most this long before the time asked for
TV_BAND = 0.1                       # TradingView's rating counts as buy above +0.1 and sell below -0.1
CACHE_SECONDS = 60                  # the dashboard recomputes the scorecard at most this often
KNOWN_RATINGS = ("Buy", "Overweight", "Hold", "Underweight", "Sell")
