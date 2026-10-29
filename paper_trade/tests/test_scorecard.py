import json
from types import SimpleNamespace

import pandas as pd
import pytest

from paper_trade import config, daybook, eventlog, scorecard
from paper_trade.daybook import settings as daybook_settings
from paper_trade.live import settings as live_settings
from paper_trade.scorecard import calls, grading, settings

T0 = 1_793_260_800.0                                      # 2026-10-29 08:00 UTC


def series(*points):
    """Recorded minute closes from (minutes after T0, price) points, one record every minute in between."""
    index = pd.to_datetime([T0 + m * 60 for m, _ in points], unit="s")
    frame = pd.Series([p for _, p in points], index=index)
    full = pd.date_range(index[0], index[-1], freq="min")
    return grading.Prices(frame.reindex(full).interpolate())


def call(ticker="EURUSD", rating="Buy", side=1, at=T0, tv=None):
    return calls.Call("live_gemma", ticker, "2026-10-29", rating, side, at, tv)


def test_a_price_is_the_last_recorded_minute_but_only_if_it_is_recent_enough():
    prices = series((0, 1.0), (10, 1.01))
    assert prices.at(T0 + 5 * 60 + 30) == pytest.approx(1.005) and prices.at(T0 - 60) is None
    assert prices.at(T0 + 10 * 60 + settings.PRICE_TOLERANCE_SECONDS - 1) == pytest.approx(1.01)
    assert prices.at(T0 + 10 * 60 + settings.PRICE_TOLERANCE_SECONDS + 60) is None            # the record has a gap here


def test_a_move_is_measured_in_basis_points_and_only_once_the_time_has_been_recorded():
    prices = series((0, 1.0), (120, 1.002))
    assert grading.move_bps(prices, T0, 3600) == pytest.approx(10.0, abs=0.01)                    # +0.1% in the first hour
    assert grading.move_bps(prices, T0, 3 * 3600) is None                                        # not yet recorded
    assert grading.move_bps(prices, T0 - 3600, 600) is None                                      # no price before the record began


def test_the_verdict_ignores_moves_too_small_to_count():
    assert (grading.verdict(5), grading.verdict(-5), grading.verdict(0.2), grading.verdict(-0.4)) == ("right", "wrong", "flat", "flat")


def test_calls_are_graded_by_what_the_price_did_and_against_three_simple_guesses():
    prices = {"EURUSD": series((0, 1.0), (120, 1.002)), "GBPUSD": series((0, 1.0), (120, 0.998))}        # EUR +20 bps, GBP -20 bps
    list_ = [call("EURUSD", "Buy", 1, tv=0.5), call("GBPUSD", "Buy", 1, tv=-0.5), call("EURUSD", "Sell", -1, at=T0 + 600, tv=0.05),
             call("GBPUSD", "Hold", 0), call("EURUSD", "Overweight", 1, at=T0 + 1200)]
    result = grading.grade(list_, prices, {"1h": 3600})
    row = result["horizons"]["1h"]
    assert (result["calls"], result["holds"]) == (5, 1) and row["n"] == 4
    assert (row["right"], row["wrong"]) == (2, 2) and row["right_pct"] == 50.0                  # buy EUR right, buy GBP wrong, sell EUR wrong, buy EUR right
    assert row["baselines"]["sell"]["right"] == 1 and row["baselines"]["buy"]["right"] == 3
    assert row["baselines"]["tv"]["n"] == 2 and row["baselines"]["tv"]["right_pct"] == 100.0     # TV: buy EUR (right), sell GBP (right); 0.05 is neutral
    assert row["holds_graded"] == 1 and row["hold_avg_move_bps"] == pytest.approx(10.0, abs=0.1)
    assert row["avg_bps"] == pytest.approx((20 - 20 - 20 + 20) / 4, abs=0.5) and row["enough"] is False
    assert result["pairs"]["EURUSD"]["1h"]["n"] == 3 and result["pairs"]["GBPUSD"]["1h"]["wrong"] == 1


def test_calls_that_cannot_be_graded_yet_are_left_out_and_a_flat_move_is_not_right_or_wrong(monkeypatch):
    monkeypatch.setattr(settings, "MIN_SAMPLE", 2)
    prices = {"EURUSD": series((0, 1.0), (100, 1.00001))}
    result = grading.grade([call(), call(at=T0 + 60), call("NOPE")], prices, {"1h": 3600, "3d": 3 * 86_400})
    hour = result["horizons"]["1h"]
    assert hour["n"] == 2 and hour["flat"] == 2 and hour["right_pct"] is None and hour["enough"] is True
    assert result["horizons"]["3d"]["n"] == 0 and result["horizons"]["3d"]["avg_bps"] is None


def test_the_text_table_says_when_there_are_too_few_calls_to_judge():
    prices = {"EURUSD": series((0, 1.0), (120, 1.002))}
    result = grading.grade([call()], prices, {"1h": 3600})
    text = scorecard.render(result, "Gemma")
    assert "Gemma: 1 calls" in text and "100.0%" in text and "too few to judge" in text
    assert "no calls" in scorecard.render(None, "Qwen")


# --- loading the calls ---

@pytest.fixture
def run(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "RUNS_DIR", tmp_path)
    monkeypatch.setattr(daybook_settings, "DIR", tmp_path / "daybook")
    eventlog._logs.clear()
    folder = tmp_path / "backtest" / "live_gemma"
    folder.mkdir(parents=True)
    events = [{"t": 1000.0, "cell": "EURUSD 2026-10-29", "kind": "llm", "node": "Market Analyst"},
              {"t": 1900.0, "cell": "EURUSD 2026-10-29", "kind": "llm", "node": "Portfolio Manager"},
              {"t": 2000.0, "cell": "BTC-USD 2026-10-29", "kind": "llm", "node": "Portfolio Manager"}]
    (folder / "events.jsonl").write_text("\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8")
    log = [SimpleNamespace(ticker="EURUSD", date="2026-10-29", rating="Sell"), SimpleNamespace(ticker="BTC-USD", date="2026-10-29", rating="Hold"),
           SimpleNamespace(ticker="XAUUSD", date="2026-10-29", rating="Buy")]            # no events for gold: it cannot be placed in time
    monkeypatch.setattr("paper_trade.report.load_decisions", lambda run_id: (log, None))
    daybook.store.save("EURUSD=X", {"2026-10-27": {"day": "2026-10-27", "ratings": {"1d": -0.3}}, "2026-10-29": {"day": "2026-10-29", "ratings": {"1d": 0.9}}})
    return tmp_path


def test_a_call_lands_when_its_last_event_was_written_and_knows_the_rating_from_the_evening_before(run):
    loaded = calls.load_calls("live_gemma")
    assert [(c.ticker, c.rating, c.side, c.at) for c in loaded] == [("EURUSD", "Sell", -1, 1900.0), ("BTC-USD", "Hold", 0, 2000.0)]
    assert loaded[0].tv_before == -0.3 and loaded[1].tv_before is None                       # the 29th's own rating is not used for the 29th's call
    assert [c.ticker for c in calls.load_calls("live_gemma", ["BTC-USD"])] == ["BTC-USD"]


def test_a_missing_run_has_no_calls(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "RUNS_DIR", tmp_path)
    assert calls.load_calls("nope") == []


def test_the_account_scorecard_grades_the_models_calls_on_the_recorded_minutes_and_is_cached(run, monkeypatch):
    from paper_trade.live import tradingview
    start = 1900.0 - 60
    index = pd.to_datetime([start + m * 60 for m in range(0, 200)], unit="s")
    minutes = pd.DataFrame({"Close": [1.0 + 0.0001 * m for m in range(200)]}, index=index)              # EUR rises: the Sell is wrong
    loads = []
    monkeypatch.setattr(tradingview, "candles", lambda ticker: loads.append(ticker) or minutes)
    scorecard._cache.clear()
    result = scorecard.for_account(live_settings.ACCOUNTS["gemma_short"])
    assert result["model"] == "short-term Gemma" and result["run"] == "live_gemma"
    assert result["horizons"]["1h"]["wrong"] == 1 and result["horizons"]["1h"]["right_pct"] == 0.0 and result["holds"] == 1
    scorecard.for_account(live_settings.ACCOUNTS["gemma_short"])
    assert sorted(set(loads)) == ["BTC-USD", "EURUSD"] and len(loads) == 2                                   # the second call used the cache
    monkeypatch.setattr(tradingview, "candles", lambda ticker: (_ for _ in ()).throw(ValueError("none yet")))
    scorecard._cache.clear()
    assert scorecard.for_account(live_settings.ACCOUNTS["gemma_short"])["horizons"]["1h"]["n"] == 0        # no prices: nothing gradable, no crash
