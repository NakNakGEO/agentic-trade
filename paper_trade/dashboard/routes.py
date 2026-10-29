"""The dashboard's JSON endpoints, as plain functions of (run, query)."""

from __future__ import annotations

from paper_trade import config
from paper_trade.dashboard import chart, market
from paper_trade.dashboard.state import build_state, read_decisions
from paper_trade.decide import logged_cells, memory_log, read_meta


def tickers_of(run: str) -> list[str]:
    from paper_trade.dashboard import live_view

    account = live_view.account_for(run)
    if account is not None:
        return list(account.tickers)
    return read_meta(run).get("tickers") or list(config.UNIVERSE)


def mode_of(query: dict) -> str:
    """The account rules the page asked for: long_only or long_short (the default)."""
    mode = query.get("mode", [config.DEFAULT_MODE])[0]
    return mode if mode in config.ACCOUNT_MODES else config.DEFAULT_MODE


def chart_for(run: str, query: dict) -> dict:
    from paper_trade.dashboard import live_view

    ticker = query.get("ticker", [tickers_of(run)[0]])[0]
    account = live_view.account_for(run)
    if account is not None:
        return live_view.live_chart(account, ticker)
    return chart.chart_state(run, ticker, len(read_decisions(memory_log(run))), mode_of(query))


def list_runs() -> list[dict]:
    """Every run that has a record, most recently active first, for the page's run picker."""
    root = config.RUNS_DIR / "backtest"
    rows = []
    for folder in (root.iterdir() if root.exists() else []):
        meta = read_meta(folder.name) if folder.is_dir() else {}
        if not meta:
            continue
        touched = [p.stat().st_mtime for p in (folder / "events.jsonl", folder / "progress.log",
                                              folder / "trading_memory.md") if p.exists()]
        rows.append({"run": folder.name, "model": meta.get("model"), "provider": meta.get("provider") or "ollama",
                     "decisions": logged_cells(folder.name),
                     "planned": meta.get("planned_cells") or len(meta.get("tickers", [])) * len(meta.get("dates", [])),
                     "last_active": max(touched, default=0)})
    from paper_trade import assets
    from paper_trade.live import settings as live

    by_run = {r["run"]: r for r in rows}
    accounts = []                                # the live accounts: shown under their own names, and the only runs listed
    for account in live.ACCOUNTS.values():
        source = by_run.get(account.decisions_run)
        if source:
            mine = {assets.canonical(t) for t in account.tickers}
            made = sum(1 for d in read_decisions(memory_log(account.decisions_run)) if assets.canonical(d["ticker"]) in mine)
            accounts.append({**source, "run": account.run_id, "decisions": made, "planned": len(account.tickers)})
    if accounts:
        return sorted(accounts, key=lambda r: -r["last_active"])
    return sorted(rows, key=lambda r: -r["last_active"])


def candles_for(run: str, query: dict) -> dict:
    from paper_trade.dashboard import candles

    if "ticker" not in query:
        return {"symbols": candles.symbols()}
    return candles.chart(query["ticker"][0], query.get("tf", ["1m"])[0])


ROUTES = {
    "/api/candles": candles_for,
    "/api/runs": lambda run, query: list_runs(),
    "/api/state": lambda run, query: build_state(run, mode_of(query)),
    "/api/market": lambda run, query: market.live_quotes(tickers_of(run)),
    "/api/chart": chart_for,
}
