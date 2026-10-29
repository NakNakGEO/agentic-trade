# Switches

Every new part is switched by an environment variable **per account**, set before the account's loop is started. Nothing here changes a running account until its loop is restarted with the variable set. `<ACCOUNT>` is `GEMMA_SHORT` or `QWEN_SHORT`.

| Variable | Default | What it does |
|---|---|---|
| `AGENTIC_CALL_EVERY_<ACCOUNT>=<minutes>` | unset: one round a day at 00:30 UTC | Calls on a UTC clock grid (`120` = 00:30, 02:30, ...). One round at a time; if a round is still working when the next slot arrives, only the newest slot starts afterwards. Each round has its own run folder. Setting this also gives that account's agents the short-term desk rules, 1-hour and 4-hour candle tables built from our own minute record, and their own latest calls on the pair. |
| `AGENTIC_PLAN_<ACCOUNT>=levels,wait,mild` | none (the rating alone) | Use more of what the agent wrote. `levels`: the agent's stop, when it is on the right side of the price and 0.5 to 3 times our own stop distance. `wait`: a call that puts a condition on entering ("do not enter until ...") does not trade now. `mild`: Overweight and Underweight trade 75% of the usual size. |
| `AGENTIC_MAX_PER_PAIR_<ACCOUNT>=<n>` | `1` | Trades in the same direction one pair may hold at once. A repeat call in the same direction opens another trade until the pair holds `n`. |
| `AGENTIC_HEDGE_<ACCOUNT>=on\|off` | `off` | `on`: a call against an open trade opens the opposite trade beside it instead of closing it. |
| `AGENTIC_RISK_CAP_<ACCOUNT>=<percent>\|off` | `off` | The most open risk, as a share of the account (`50` = half). With it off the account can lose everything. |
| `AGENTIC_SLIPPAGE_<ACCOUNT>=on\|off` | `off` | Fills land a little worse than the price, stops most of all (numbers in `settings.SLIPPAGE_BPS`; they are assumptions, not measured fills). |

More keys for an online model: add `OPENAI_COMPATIBLE_API_KEY_2` ... `_9` to `.env`; the workers use them in turn. There is no spend limit.

Two guards are always on, whatever the switches say: no new trade once the account value is zero or below, and when it falls to zero every open trade is closed at its price ("Wiped out"). The dashboard always shows the open risk as a share of the account.

## Read-only tools

```
python -m paper_trade scorecard [--account gemma_short]   are the calls right? (1h, 4h, 12h, 1d, 3d after landing, against always-sell, always-buy and TradingView)
python -m paper_trade whatif    [--account gemma_short]   the same trades under other stops, targets and time limits, with a built-in exactness check
python -m paper_trade watchdog  check|run                 restart a stopped loop or dashboard (refuses in the test copy)
```

## Test-copy variables

| Variable | Meaning |
|---|---|
| `AGENTIC_LIVE_DATA_DIR` | the live `runs` folder; the test copy then reads the live snapshot, candles and daily record and never fetches or records |
| `AGENTIC_ALLOW_TEST_ROUNDS=1` | lets a test copy start model calls (otherwise a test copy never does) |

## What promotion would change

- **Call schedule (C, with the short-term rules and candle tables from E):** the agents' prompt changes for an account once its interval is set. Promote Gemma first and watch one full day of the scorecard before Qwen.
- **Risk cap (F):** the accounts in the test copy default to **no cap**, as decided. The live accounts have the 50% cap today, so promoting F removes it unless `AGENTIC_RISK_CAP_<ACCOUNT>=50` is set. Decide that at promotion.
- **Everything else** is off until its variable is set, and promoting it does not touch the books.
