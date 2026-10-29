"""Where the day-by-day record lives and how trading days are cut."""

from __future__ import annotations

from paper_trade import config

DIR = config.RUNS_DIR / "daybook"
BAR_FIELDS = ("open", "high", "low", "close", "volume")
NEW_YORK = "America/New_York"
FX_ROLL_HOURS = 7          # the forex and gold day rolls at 17:00 New York: adding 7 hours lands on the next date
WRITE_RETRIES = 5          # the two live loops share the files; a clash on replace is retried
