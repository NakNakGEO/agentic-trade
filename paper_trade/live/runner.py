"""One live cycle: act on new decisions at live prices, check stops and targets, save. Plus the endless loop."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone

from paper_trade import assets, config
from paper_trade.live import book as livebook
from paper_trade.live import feeds, friction, keys, plan, schedule, settings

CREATE_NO_WINDOW = 0x08000000


def _now() -> datetime:
    return datetime.now(timezone.utc)


def new_decisions(book: livebook.Book, account: settings.Account) -> list:
    """Decisions in the account's decision logs (the daily run, and each round's run), for its own pairs, that the book has
    not acted on yet, oldest first. Each carries its ``slot`` ('' for the daily run) and its ``key`` in book.applied."""
    from types import SimpleNamespace

    from paper_trade.report import load_decisions

    done, mine, out = set(book.applied), {assets.canonical(t) for t in account.tickers}, []
    for run in schedule.all_runs(account):
        try:
            decisions, _ = load_decisions(run)
        except FileNotFoundError:
            continue
        slot = schedule.slot_of(run)
        for d in decisions:
            key = f"{d.ticker}|{d.date}|{slot}" if slot else f"{d.ticker}|{d.date}"
            if key not in done and assets.canonical(d.ticker) in mine:
                out.append(SimpleNamespace(ticker=d.ticker, date=d.date, rating=d.rating, slot=slot, key=key, run=run))
    return sorted(out, key=lambda d: (d.date, d.slot))


def _skip_old_calls(book: livebook.Book, account: settings.Account, today: str) -> None:
    """A new account trades from today's calls on: calls dated before today are marked done without trading them."""
    book.applied += [d.key for d in new_decisions(book, account) if d.date < today]


def update(book: livebook.Book, account: settings.Account, now: datetime | None = None) -> float:
    """Act on new decisions, close anything whose stop, target or time limit came, record the account value."""
    now = now or _now()
    stamp = now.strftime("%Y-%m-%dT%H:%M:%S+00:00")
    if not book.created:
        book.created = stamp
        _skip_old_calls(book, account, now.strftime("%Y-%m-%d"))
    if not config.READ_ONLY_DATA:               # a test copy never records: the live loops do
        feeds.record_minute(stamp)
        _record_day()
    prices = feeds.latest_prices(account.tickers)
    slip = friction.for_account(account)            # None unless the account switched slippage on
    for decision in new_decisions(book, account):
        price = prices.get(decision.ticker) or prices.get(assets.canonical(decision.ticker))
        if price is None:                       # no price right now: leave it for the next cycle
            continue
        hourly = account.style.stop_frame == "1h"
        average_range = feeds.hourly_range(decision.ticker) if hourly else feeds.daily_range(decision.ticker)
        if hourly and average_range is None:    # no hourly range right now, so no stop can be placed: try again next cycle
            continue
        tweaks = plan.tweaks_for(account.plan_options, decision.run, decision.ticker, decision.date, decision.rating)
        livebook.apply_decision(book, decision.ticker, decision.date, decision.rating, price,
                                [] if hourly else feeds.daily_bars(decision.ticker), stamp, prices, average_range, account.style, decision.slot,
                                tweaks, livebook.Policy(account.max_per_pair, account.hedge, account.risk_cap), slip)
    for ticker in {p.ticker for p in book.positions.values()}:
        livebook.step(book, ticker, feeds.intraday_bars(ticker), slip)
    livebook.wipe_out(book, prices, stamp, slip)
    value = livebook.record(book, prices, stamp)
    livebook.save(book, settings.book_path(account))
    return value


def _record_day() -> None:
    """Keep the day-by-day record current: the minute snapshot every cycle, TradingView's daily analysis when fresh."""
    from paper_trade import daybook
    from paper_trade.live import tradingview
    from paper_trade.tvdata import client

    for source, write in ((tradingview.snapshot, daybook.from_minute), (client.analysis, daybook.from_analysis)):
        try:
            write(source())
        except Exception as error:              # a missed record must never stop the trading cycle
            print(f"day record skipped ({source.__module__}): {type(error).__name__}: {str(error)[:160]}", flush=True)


def _state(account: settings.Account) -> dict:
    path = settings.state_path(account)
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _last_slot(account: settings.Account) -> datetime | None:
    stamp = _state(account).get("last_slot")
    return datetime.fromisoformat(stamp) if stamp else None


def _last_started(account: settings.Account) -> datetime | None:
    stamp = _state(account).get("last_started")
    return datetime.fromisoformat(stamp) if stamp else None


def decisions_due(account: settings.Account, now: datetime) -> bool:
    """True when a round of calls should start now. An account with a call interval follows its clock grid (one round at a
    time, see schedule.py); any other account starts once per UTC day, after the day's decision time."""
    if account.call_every_minutes:
        return schedule.due(account, now, _last_slot(account), _last_started(account)) is not None
    hour, minute = settings.DECISION_AFTER_UTC
    after = now.hour * 60 + now.minute >= hour * 60 + minute
    return after and _state(account).get("decisions_started") != now.strftime("%Y-%m-%d")


def _worker_environment(account: settings.Account, only: str | None, run_id: str) -> dict:
    """What a worker needs beyond the shared environment: its account name (so its agents see the account's earlier calls) in
    a round-based account, and one key from the account's key list, used in turn (a different one for each pair)."""
    extra = {}
    if account.call_every_minutes:
        extra["AGENTIC_ACCOUNT"] = account.name
    if account.api_key_env:
        key = keys.pick(keys.load_keys(account.api_key_env), account.tickers.index(only) if only in account.tickers else _slot_number(run_id))
        if key:
            extra[account.api_key_env] = key
    return extra


def _slot_number(run_id: str) -> int:
    """A number that changes from round to round (minutes of the slot time), so a single worker also rotates through the keys."""
    slot = schedule.slot_of(run_id)
    return int(slot[-4:-2]) * 60 + int(slot[-2:]) if slot else 0


def _worker(account: settings.Account, today: str, only: str | None, run_id: str | None = None) -> subprocess.Popen:
    run_id = run_id or account.decisions_run
    command = [sys.executable, "-W", "ignore", "-m", "paper_trade", "decide", "--tickers", ",".join(account.tickers),
               "--start", today, "--end", today, "--every", "1", "--run-id", run_id, "--data", "tradingview",
               *account.decide_args]
    if only:
        command += ["--only", only]
    log = config.ROOT / "logs" / f"{run_id}{'_' + only if only else ''}.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    extra = _worker_environment(account, only, run_id)
    with open(log, "a", encoding="utf-8") as out:
        return subprocess.Popen(command, cwd=config.ROOT, stdout=out, stderr=subprocess.STDOUT,
                                creationflags=CREATE_NO_WINDOW, **({"env": {**os.environ, **extra}} if extra else {}))


def start_decisions(account: settings.Account, now: datetime | None = None) -> None:
    """Start today's decisions in hidden workers (they skip cells that are already done).

    A hosted model gets a worker per pair, started a few seconds apart so they do not collide on the shared log."""
    now = now or _now()
    today = now.strftime("%Y-%m-%d")
    state = {"decisions_started": today}
    run_id = None
    if account.call_every_minutes:                         # a round on the clock grid, in its own run folder
        slot = schedule.latest_slot(now, account.call_every_minutes)
        state["last_slot"], run_id, today = slot.isoformat(), schedule.slot_run_id(account.decisions_run, slot), slot.strftime("%Y-%m-%d")
        state["last_started"] = now.isoformat()
    settings.state_path(account).parent.mkdir(parents=True, exist_ok=True)
    settings.state_path(account).write_text(json.dumps(state), encoding="utf-8")
    if not account.parallel:
        _worker(account, today, None, run_id)
        return

    def launch() -> None:
        for ticker in account.tickers:
            _worker(account, today, ticker, run_id)
            time.sleep(settings.STAGGER_SECONDS)

    threading.Thread(target=launch, daemon=True).start()


def loop(account: settings.Account) -> None:
    """Forever: start each day's decisions when due, and update the book every few minutes."""
    book = livebook.load(settings.book_path(account))
    while True:
        now = _now()
        if decisions_due(account, now) and (not config.READ_ONLY_DATA or config.ALLOW_TEST_ROUNDS):
            start_decisions(account, now)
        try:
            update(book, account, now)
        except Exception as error:              # one bad cycle (network, a half-written log) must not end the loop
            print(f"{now:%H:%M:%S} update failed: {type(error).__name__}: {error}", flush=True)
        time.sleep(settings.UPDATE_SECONDS)
