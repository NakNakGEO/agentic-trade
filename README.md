# agentic-trade

An experiment: **teams of AI agents make trading calls, a rulebook turns those calls into paper trades on live prices, and a dashboard shows everything that happens.**

> **Paper money only.** Nothing in this project places a real trade. The live accounts are simulations. Results so far cover a few days and say nothing about whether the approach makes money. Not financial advice.

---

## The idea in plain words

1. **A call.** Every day each instrument (EURUSD, gold, Bitcoin, ...) is looked at by a team of 11 AI agents that work one after another: three analysts (prices and indicators, news, company or economic data), a bull and a bear researcher who argue, a research manager, a trader, three risk reviewers, and a portfolio manager who writes the final answer. The answer is one word: **Buy, Sell or Hold** (plus the mild versions Overweight and Underweight). That word is the **call**.
2. **The rulebook ("the account").** The agents do not place trades. Our code reads the call and applies fixed rules: how big the trade is, where the stop loss and take profit go, and when the trade is closed anyway.
3. **The trade.** The account opens a paper trade at the live price, watches it every minute, and closes it at the stop, the target, the time limit, or when a new opposite call arrives.
4. **The dashboard.** A local web page shows the agents working, every call, every trade and order, the account value, and live charts.

Two models are compared on the same instruments: **Gemma** (a model that runs on the local computer) and **Qwen** (an online model). Both start with $100 of paper money.

## How a day works

```
 live prices, indicators, news, economic numbers
                    |
                    v
   11 AI agents per instrument  ----->  the call: Buy / Sell / Hold
                                                |
                                                v
                              the account's rules (stop, target, size, time limit)
                                                |
                                                v
                                 paper trade, checked every minute
                                                |
                                                v
                              dashboard, orders, results
```

Calls are made once a day at 00:30 UTC. The plan in [docs/AUDIT_2026-10-29.md](docs/AUDIT_2026-10-29.md) makes the call frequency a setting per model.

## The two live accounts

Defined in `paper_trade/live/settings.py`. Nothing is hard-coded elsewhere.

| | short-term Gemma | short-term Qwen |
|---|---|---|
| Model | Gemma 4 12B on the local machine (Ollama) | Qwen 3.8 27B through an OpenAI-compatible API |
| Instruments | 7 forex pairs, gold, Bitcoin, Ethereum | the same |
| Start | $100 paper | $100 paper |
| Stop loss | 1.5 x the 1-hour average range | the same |
| Take profit | 2 stops away | the same |
| Time limit | closed at the market after 12 hours | the same |
| Size | gold: fixed 0.01 lot; others sized to lose about 2% of the account at the stop (smallest 0.01) | the same |
| Open-risk cap | 50% of the account | the same |
| Cost | 1 basis point per side on forex and gold, 5 on crypto | the same |

Known limits of the paper model: stops fill at the exact price (no spread or slippage), and one call a day means a pair trades about once a day.

## Where the data comes from

| Data | Source |
|---|---|
| Prices, indicators on 4 timeframes, company figures, news | TradingView (its screener), live only |
| Daily history | **our own record**, built day by day from what we saw (`runs/daybook`); no outside price history is used |
| Economic numbers (rates, inflation) | FRED |
| Positioning, economic calendar | CFTC and calendar sources (`paper_trade/fundamentals`) |
| Prediction-market odds | Polymarket (part of the original agent) |

## Repository map

```
paper_trade/            everything built here (Python package)
  live/                 the live accounts: settings, book (trades and money), runner (the loop), price feeds
  tvdata/               gives the agents TradingView data in the form they expect, plus our desk rules
  daybook/              our own day-by-day record
  fundamentals/ news/   extra data sources for the agents
  dashboard/            the local web page: server, state, orders panel, round progress, static files
  bridge/               a separate, demo-only MetaTrader 5 connector (manual use; the live accounts never use it)
  tests/                the pytest suite
tvmcp/                  a small helper that talks to TradingView, run in its own Python environment
TradingAgents/          the original agent framework (git submodule, pinned, never edited)
docs/                   audit and plan
snapshot_*.py watch_*.py *.ps1   helper scripts for the phone monitors and launching
```

The original agent framework is [TauricResearch/TradingAgents](https://github.com/TauricResearch/TradingAgents) (Apache-2.0), pinned to release 0.7.1. We add our behaviour around it without editing it.

## Running it (Windows)

You need: Python 3.12, [Ollama](https://ollama.com) for the local model, a copy of this repo with its submodule, and the keys below.

```bash
git clone --recurse-submodules https://github.com/NakNakGEO/agentic-trade.git
cd agentic-trade
```

1. **Python environments.** One environment for the agent framework and our code (`TradingAgents/.venv`, with the framework installed in it plus `pandas`, `pytest`, `stockstats`), and a separate one for the TradingView helper (`tvmcp/.venv`, with `tradingview-screener`).
2. **Keys.** Copy `.env.example` to `.env` and fill in `FRED_API_KEY` (free, from the FRED website) and `OPENAI_COMPATIBLE_API_KEY` (the online Qwen account). `.env` is ignored by git; never commit it.
3. **Local model.** Pull the model and give it our settings:
   ```
   ollama pull gemma4:12b
   # Modelfile:  FROM gemma4:12b / PARAMETER num_ctx 32768 / PARAMETER temperature 0.2
   ollama create ta-gemma12b -f Modelfile
   ```
4. **Start the two accounts** (each runs forever; run them hidden or in their own windows):
   ```
   TradingAgents/.venv/Scripts/python.exe -W ignore -m paper_trade live --account gemma_short loop
   TradingAgents/.venv/Scripts/python.exe -W ignore -m paper_trade live --account qwen_short loop
   ```
5. **Open the dashboard:**
   ```
   TradingAgents/.venv/Scripts/python.exe -m paper_trade.dashboard --run live_gemma_short --port 8765
   ```
   then visit http://localhost:8765
6. **Tests:**
   ```
   TradingAgents/.venv/Scripts/python.exe -m pytest paper_trade/tests
   ```

## Branches

| Branch | Purpose |
|---|---|
| `test` | where new work is built and unit-tested |
| `qa` | a candidate: passed the tests, now checked on paper with live data (a full day with the scorecard) |
| `main` | approved baseline |
| `prod` | exactly what the live accounts run; only ever updated from `main` |

Work moves one way: `test` -> `qa` -> `main` -> `prod`. New behaviour ships switched off by default and never changes the running accounts' books.

## Status and plan

Live on paper since 2026-10-29. The latest full review and the phased plan (scorecard, calls as often as each model can manage, use more of what the agents write, exit what-if, several trades per pair) are in [docs/AUDIT_2026-10-29.md](docs/AUDIT_2026-10-29.md).

## License

No license has been chosen yet, so by default all rights are reserved. The bundled framework keeps its own license (Apache-2.0).
