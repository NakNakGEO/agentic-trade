"""Settings of the exit what-if replay: which exit rules are tried and how many trades are enough to judge them."""

MIN_TRADES = 30                                  # fewer trades than this and a table is noise, not evidence
STOP_MULTS = (1.0, 1.5, 2.0, 3.0)                # stop distance in average 1-hour ranges
REWARD_RISKS = (1.0, 1.5, 2.0, 3.0)              # target distance in stops
MAX_HOURS = (4, 8, 12, 24, 48)                   # close at the market after this long
COVERAGE_SLACK_MINUTES = 5                       # the record must start within this long after a trade opened to replay it
MONEY_TOLERANCE = 0.005                         # dollars: a replayed profit this close to the traded one counts as the same
