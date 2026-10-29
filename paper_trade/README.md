# paper_trade

Everything in this package was built for this project; the original agent framework lives in `../TradingAgents` and is never edited. The big picture, setup and the branch model are in the [repository README](../README.md).

| Folder or file | What it does |
|---|---|
| `live/` | the live paper accounts. `settings.py` holds every number (accounts, stop and target rules, lot sizes); `book.py` holds the trades and the money; `runner.py` is the endless loop; `feeds.py`, `tradingview.py`, `tv_guard.py` fetch live prices politely |
| `tvdata/` | gives the agents TradingView data in the form they expect (`vendor.py`), plus our desk rules, company profile and a fix for oddly formatted ratings |
| `daybook/` | our own day-by-day record of prices and indicators |
| `fundamentals/`, `news/` | extra data sources for the agents |
| `dashboard/` | the local web page (`server.py`, `state.py`, `blotter.py` orders panel, `rounds.py` round progress, `static/` page files) |
| `bridge/` | a separate, demo-only MetaTrader 5 connector for manual use; the live accounts never import its broker code |
| `decide.py` | runs the agent teams for a list of instruments and dates |
| `lots.py`, `simulator.py`, `portfolio.py`, `compare.py`, `report.py` | the older day-by-day paper ledger and reports |
| `tests/` | the pytest suite: `python -m pytest paper_trade/tests` |

Rules of this codebase: one job per file, at most 300 lines per file, numbers live in `settings.py` / `config.py`, and every module should have tests (the audit lists the current gaps).
