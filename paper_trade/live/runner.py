"""One live cycle: act on new decisions at live prices, check stops and targets, save. Plus the endless loop."""

from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone

from paper_trade import assets, config
from paper_trade.live import book as livebook
from paper_trade.live import feeds, settings

CREATE_NO_WINDOW = 0x08000000


def _now() -> datetime:
    return datetime.now(timezone.utc)


def new_decisions(book: livebook.Book, account: settings.Account) -> list:
    """Decisions in the account's decision log, for its own pairs, that the book has not acted on yet, oldest first."""
    from paper_trade.report import load_decisions

    try:
        decisions, _ = load_decisions(account.decisions_run)
    except FileNotFoundError:
        return []
    done, mine = set(book.applied), {assets.canonical(t) for t in account.tickers}
    return sorted((d for d in decisions if f"{d.ticker}|{d.date}" not in done and assets.canonical(d.ticker) in mine),
                  key=lambda d: d.date)


def _skip_old_calls(book: livebook.Book, account: settings.Account, today: str) -> None:
    """A new account trades from today's calls on: calls dated before today are marked done without trading them."""
    book.applied += [f"{d.ticker}|{d.date}" for d in new_decisions(book, account) if d.date < today]


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
    for decision in new_decisions(book, account):
        price = prices.get(decision.ticker) or prices.get(assets.canonical(decision.ticker))
        if price is None:                       # no price right now: leave it for the next cycle
            continue
        hourly = account.style.stop_frame == "1h"
        average_range = feeds.hourly_range(decision.ticker) if hourly else feeds.daily_range(decision.ticker)
        if hourly and average_range is None:    # no hourly range right now, so no stop can be placed: try again next cycle
            continue
        livebook.apply_decision(book, decision.ticker, decision.date, decision.rating, price,
                                [] if hourly else feeds.daily_bars(decision.ticker), stamp, prices, average_range, account.style)
    for ticker in list(book.positions):
        livebook.step(book, ticker, feeds.intraday_bars(ticker))
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


def decisions_due(account: settings.Account, now: datetime) -> bool:
    """True once per UTC day, after the day's decision time, until that day's decisions have been started."""
    hour, minute = settings.DECISION_AFTER_UTC
    after = now.hour * 60 + now.minute >= hour * 60 + minute
    return after and _state(account).get("decisions_started") != now.strftime("%Y-%m-%d")


def _worker(account: settings.Account, today: str, only: str | None) -> subprocess.Popen:
    command = [sys.executable, "-W", "ignore", "-m", "paper_trade", "decide", "--tickers", ",".join(account.tickers),
               "--start", today, "--end", today, "--every", "1", "--run-id", account.decisions_run, "--data", "tradingview",
               *account.decide_args]
    if only:
        command += ["--only", only]
    log = config.ROOT / "logs" / f"{account.decisions_run}{'_' + only if only else ''}.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    with open(log, "a", encoding="utf-8") as out:
        return subprocess.Popen(command, cwd=config.ROOT, stdout=out, stderr=subprocess.STDOUT,
                                creationflags=CREATE_NO_WINDOW)


def start_decisions(account: settings.Account, now: datetime | None = None) -> None:
    """Start today's decisions in hidden workers (they skip cells that are already done).

    A hosted model gets a worker per pair, started a few seconds apart so they do not collide on the shared log."""
    now = now or _now()
    today = now.strftime("%Y-%m-%d")
    settings.state_path(account).parent.mkdir(parents=True, exist_ok=True)
    settings.state_path(account).write_text(json.dumps({"decisions_started": today}), encoding="utf-8")
    if not account.parallel:
        _worker(account, today, None)
        return

    def launch() -> None:
        for ticker in account.tickers:
            _worker(account, today, ticker)
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
