import json

import pytest

from paper_trade import eventlog
from paper_trade.dashboard import rounds

DAY = "2026-10-30"
NOW = 10_000.0


def llm(cell, node, t, tokens=1000):
    return {"t": t, "cell": f"{cell} {DAY}", "kind": "llm", "node": node, "tokens_in": tokens * 3 // 4, "tokens_out": tokens // 4}


def write(path, events, partial=""):
    path.write_text("\n".join(json.dumps(e) for e in events) + "\n" + partial, encoding="utf-8")


def decision(ticker, rating="Sell"):
    return {"date": DAY, "ticker": ticker, "rating": rating}


def events_for_round():
    done = [llm("EURUSD", node, 1000 + i * 60) for i, node in enumerate(rounds.STAGES)]
    working = [llm("GBPUSD", node, NOW - 200 + i * 20) for i, node in enumerate(rounds.STAGES[:4])]        # first event 200 s ago, last 140 s ago
    stuck = [llm("AUDUSD", node, NOW - 900 + i * 10) for i, node in enumerate(rounds.STAGES[:2])]           # quiet for 890 s
    return done + working + stuck


def test_each_pair_is_done_working_paused_or_waiting(tmp_path):
    path = tmp_path / "events.jsonl"
    write(path, events_for_round())
    out = rounds.progress(path, [decision("EURUSD")], ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD"], parallel=False, now=NOW)
    rows = {r["ticker"]: r for r in out["rows"]}
    assert out["day"] == DAY and (out["done"], out["total"]) == (1, 4)
    assert rows["EURUSD"]["status"] == "done" and rows["EURUSD"]["steps"] == ["done"] * 11 and rows["EURUSD"]["rating"] == "Sell"
    assert rows["EURUSD"]["seconds"] == 600 and rows["EURUSD"]["tokens"] == 11_000
    assert rows["GBPUSD"]["status"] == "working" and rows["GBPUSD"]["now"] == "Bull Researcher"
    assert rows["GBPUSD"]["steps"] == ["done", "done", "done", "now"] + ["todo"] * 7
    assert rows["USDJPY"]["status"] == "waiting" and rows["USDJPY"]["steps"] == ["todo"] * 11
    assert rows["AUDUSD"]["status"] == "paused" and rows["AUDUSD"]["quiet"] == 890 and rows["AUDUSD"]["now"] == ""


def test_the_time_left_counts_pairs_still_to_start_only_for_a_model_that_goes_one_at_a_time(tmp_path):
    path = tmp_path / "events.jsonl"
    write(path, events_for_round())
    args = (path, [decision("EURUSD")], ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD"])
    one_at_a_time = rounds.progress(*args, parallel=False, now=NOW)
    together = rounds.progress(*args, parallel=True, now=NOW)
    assert together["left"] == 400                       # the working pair has run 200 s of an average 600 s; the paused one is ignored
    assert one_at_a_time["left"] == 400 + 600            # plus one average pair for the one still waiting


def test_a_finished_round_says_how_long_it_took_and_has_nothing_left(tmp_path):
    path = tmp_path / "events.jsonl"
    write(path, [llm("EURUSD", node, 1000 + i * 60) for i, node in enumerate(rounds.STAGES)])
    out = rounds.progress(path, [decision("EURUSD", "Hold")], ["EURUSD"], parallel=False, now=NOW)
    assert (out["done"], out["total"], out["left"], out["elapsed"]) == (1, 1, None, 600)


def test_the_log_is_read_once_and_then_only_its_new_lines_and_a_half_line_waits(tmp_path):
    path = tmp_path / "events.jsonl"
    first = llm("EURUSD", "Market Analyst", NOW - 30)
    write(path, [first], partial='{"t": 9990, "cell": "EURUSD 2026-10-30", "kind": "llm", "node": "News Ana')
    out = rounds.progress(path, [], ["EURUSD"], parallel=False, now=NOW)
    assert out["rows"][0]["steps"][:2] == ["now", "todo"]                    # the cut-off line is not counted yet
    with open(path, "a", encoding="utf-8") as handle:
        handle.write('lyst", "tokens_in": 10, "tokens_out": 5}\n')
    out = rounds.progress(path, [], ["EURUSD"], parallel=False, now=NOW)
    assert out["rows"][0]["steps"][:2] == ["done", "now"] and out["rows"][0]["tokens"] == 1000 + 15
    assert eventlog._logs[path]["offset"] == path.stat().st_size


def test_no_log_means_no_round_and_the_latest_day_is_the_one_shown(tmp_path):
    assert rounds.progress(tmp_path / "missing.jsonl", [], ["EURUSD"], parallel=False, now=NOW) is None
    path = tmp_path / "events.jsonl"
    write(path, [{**llm("EURUSD", "Market Analyst", 100), "cell": "EURUSD 2026-10-29"}, llm("EURUSD", "Market Analyst", NOW - 5)])
    assert rounds.progress(path, [], ["EURUSD"], parallel=False, now=NOW)["day"] == DAY


def test_a_round_lists_only_the_pairs_it_was_started_for():
    account = ["EURUSD", "GBPUSD", "BTC-USD", "XAUUSD"]
    assert rounds.pairs_of_round(account, ["GBPUSD"]) == ["GBPUSD"]                       # a one-pair test round: the rest were never asked
    assert rounds.pairs_of_round(account, ["btc-usd", "EURUSD"]) == ["EURUSD", "BTC-USD"]    # the account's own order, spelling-proof
    assert rounds.pairs_of_round(account, None) == account and rounds.pairs_of_round(account, []) == account     # no record: all of them
    assert rounds.pairs_of_round(account, ["AAPL"]) == account                            # nothing in common: do not show an empty round
