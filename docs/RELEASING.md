# Environments, releasing and rolling back

The rule: **nothing is built or edited in the live folder.** Everything is built and proven in the test copy first, then promoted one small part at a time. If a part misbehaves it can be switched off or rolled back in a minute.

## The two copies

| | LIVE copy | TEST copy |
|---|---|---|
| Folder | `D:\turic trading agent` | `D:\agentic-trade-test` |
| Branch | `prod` (only ever receives promotions) | `test` (all building happens here) |
| Runs | the two real paper accounts (`gemma_short`, `qwen_short`), the loops, the phone-monitor job | unit tests, replays, and test accounts that only read the live data |
| Data folder (`runs/`, `logs/`) | the real record: books, minute candles, daily record, decisions | its own, empty at the start; never writes into the live one |
| Dashboard port | 8765 | 8766 |
| Shared, read-only | the pinned original agent framework and the TradingView helper environment are linked into the test copy (never copied, never edited) | |

Direct commits to `main`, `qa` and `prod` are refused by a git hook. Only `test` accepts commits.

## The path of a change

```
test  ->  qa  ->  main  ->  prod
build    prove     approve   run live
```

1. **test**: the change is built behind a switch that is **off by default**, with its own tests. The whole suite must pass and coverage must not go down (baseline on 2026-10-29: 70%).
2. **qa**: the change is run in the test copy on paper against the live data (read-only), for as long as the change needs: at least one full round of calls for anything that touches the agents, and a check of the scorecard.
3. **main**: approved. The merge gets a release tag, `release-YYYYMMDD-N`.
4. **prod**: the live folder takes that tag and the loops are restarted **between rounds**, never while a round of calls is running. The tag is written in `docs/DEPLOYED.md`.

One part per release. A release never bundles two parts, so a problem always points at one change.

## Promoting (live folder)

```bash
cd "D:/turic trading agent"
git fetch origin
git merge --ff-only release-YYYYMMDD-N      # moves prod to the tag, nothing else
# then restart the two loops (see README "Running it"), outside the 00:30 UTC round
```

## Rolling back

Two ways, fastest first:

1. **Turn the part off.** Every new part has a switch in `paper_trade/live/settings.py`. Set it back to off and restart the loops. No code changes.
2. **Go back to the previous release.**
   ```bash
   cd "D:/turic trading agent"
   git checkout -B prod <previous-release-tag>
   # restart the two loops
   ```
   The data folders are not in git, so books, candles and decisions stay exactly as they were.

## Safety rules for the test copy

- It never records live data: it reads what the live loops record (the read-only data mode is built first, in Phase A).
- It never starts the live accounts and never uses the live accounts' names.
- A test round of calls (which uses the model) is started by hand, for a few pairs, at a time when the live round is not running.
- Real money is never involved anywhere. The MetaTrader connector in `paper_trade/bridge` is manual and demo-only.

## Decisions made

- **Token cost does not matter**; spare API keys can be swapped in (a key list per model will be added). No spend limit.
- **The 50% open-risk limit is a switch, off by default.** With it off, several trades per pair are allowed. The account can be wiped out; that is accepted for paper money. Two guards stay: no new trades once the account value is zero or below, and the dashboard shows the open risk as a share of the account whether the limit is on or not.
- **Calls are made as often as each model can manage**, set per model: Gemma every 2 hours and Qwen every 1 hour to start with.
