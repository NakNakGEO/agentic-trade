import dataclasses
import json
from datetime import datetime, timezone

import pytest

from paper_trade import config
from paper_trade.live import book as lb
from paper_trade.live import plan, runner, settings

SHORT = settings.SHORT
PLAN_TEXT = "**Action**: Sell\n\n**Entry Price**: 1.1143\n\n**Stop Loss**: 1.1256\n\n**Position Sizing**: 0.01 lot"
WAITING = "**Rating**: Underweight\n\n**Executive Summary**: Short EURUSD, but only on a confirmed post-ECB 1-hour close. Wait for the cluster.\n\n**Investment Thesis**: x"
PLAIN = "**Rating**: Sell\n\n**Executive Summary**: Short EURUSD now at the market.\n\n**Investment Thesis**: later we wait for nothing"


def test_the_stop_is_read_from_the_trader_plan_in_its_usual_spellings():
    assert plan.stop_of(PLAN_TEXT) == pytest.approx(1.1256)
    assert plan.stop_of("**Stop Loss:** $67,250.50 (below the swing)") == pytest.approx(67250.5)
    assert plan.stop_of("**Stop Loss**: 0.713182\n**Position Sizing**: 0.01 lot") == pytest.approx(0.713182)
    assert plan.stop_of("**Action**: Hold") is None and plan.stop_of(None) is None and plan.stop_of("**Stop Loss**: n/a") is None


def test_a_condition_on_entering_is_found_in_the_summary_only():
    assert "only on a confirmed post-ECB" in plan.wait_of(WAITING) or "Wait for the cluster" in plan.wait_of(WAITING)
    assert plan.wait_of(PLAIN) == "" and plan.wait_of(None) == ""        # "wait" after the thesis heading does not count


@pytest.fixture
def runs(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "RUNS_DIR", tmp_path)

    def save(run, ticker, date, trader=PLAN_TEXT, final=WAITING):
        folder = tmp_path / "backtest" / run / ticker / "TradingAgentsStrategy_logs"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"full_states_log_{date}.json").write_text(json.dumps({"trader_investment_plan": trader, "final_trade_decision": final}), encoding="utf-8")
    return save


def test_a_plan_is_read_from_the_agents_saved_state_and_a_missing_or_broken_one_is_none(runs, tmp_path):
    runs("live_gemma_s202610300030", "EURUSD", "2026-10-30")
    found = plan.read_plan("live_gemma_s202610300030", "EURUSD", "2026-10-30")
    assert found.stop == pytest.approx(1.1256) and found.wait
    assert plan.read_plan("live_gemma_s202610300030", "GBPUSD", "2026-10-30") is None
    (tmp_path / "backtest" / "live_gemma_s202610300030" / "EURUSD" / "TradingAgentsStrategy_logs" / "full_states_log_2026-10-31.json").write_text("{half", encoding="utf-8")
    assert plan.read_plan("live_gemma_s202610300030", "EURUSD", "2026-10-31") is None


def test_each_switch_takes_only_its_own_part_and_no_switch_takes_nothing(runs, monkeypatch):
    runs("r", "EURUSD", "2026-10-30")
    assert plan.tweaks_for((), "r", "EURUSD", "2026-10-30", "Sell") is None
    levels = plan.tweaks_for(("levels",), "r", "EURUSD", "2026-10-30", "Underweight")
    assert levels == lb.Tweaks(stop=pytest.approx(1.1256), scale=1.0, hold="")
    wait = plan.tweaks_for(("wait",), "r", "EURUSD", "2026-10-30", "Underweight")
    assert wait.stop is None and wait.scale == 1.0 and wait.hold
    mild = plan.tweaks_for(("mild",), "r", "EURUSD", "2026-10-30", "Underweight")
    assert mild == lb.Tweaks(stop=None, scale=settings.MILD_SIZE, hold="")
    assert plan.tweaks_for(("mild",), "r", "EURUSD", "2026-10-30", "Sell").scale == 1.0              # only the mild ratings
    assert plan.tweaks_for(("levels", "wait"), "r", "NOPAIR", "2026-10-30", "Sell") == lb.Tweaks()        # no saved answer: the usual rules
    monkeypatch.setattr(plan, "read_plan", lambda *args: pytest.fail("the saved state must not be read for sizing alone"))
    assert plan.tweaks_for(("mild",), "r", "EURUSD", "2026-10-30", "Overweight").scale == settings.MILD_SIZE


ARGS = dict(price=1.1143, daily_bars=[], when="2026-10-30T01:00:00+00:00", prices={"EURUSD": 1.1143}, average_range=0.001, style=SHORT)


def apply(tweaks, rating="Sell", ticker="EURUSD", **extra):
    book = lb.Book(created="2026-10-30T00:00:00+00:00")
    args = {**ARGS, **extra}
    lb.apply_decision(book, ticker, "2026-10-30", rating, tweaks=tweaks, **args)
    return book


def test_without_tweaks_the_trade_is_exactly_the_usual_one():
    pos = apply(None).positions["EURUSD"]
    assert pos.stop == pytest.approx(1.1143 + 0.0015) and pos.note == "" and apply(lb.Tweaks()).positions["EURUSD"] == pos


def test_a_sane_agent_stop_replaces_the_own_stop_and_the_size_follows_it():
    usual = apply(None, average_range=0.0005).positions["EURUSD"]                      # own stop: 1.5 ranges = 7.5 pips
    pos = apply(lb.Tweaks(stop=1.1143 + 0.0015), average_range=0.0005).positions["EURUSD"]      # 15 pips: 2 own stops, inside 0.5..3
    assert pos.stop == pytest.approx(1.1158) and pos.target == pytest.approx(1.1143 - 0.0030) and pos.note == "agent stop"
    assert (usual.lot, pos.lot) == (0.02, 0.01) and pos.risk == pytest.approx(usual.risk)              # a wider stop, a smaller lot, the same risk


@pytest.mark.parametrize("stop", [1.1143 + 0.0005, 1.1143 + 0.0090, 1.1143 - 0.0020, 1.1143])
def test_an_agent_stop_that_is_too_close_too_far_on_the_wrong_side_or_at_the_price_is_ignored(stop):
    pos = apply(lb.Tweaks(stop=stop)).positions["EURUSD"]
    assert pos.stop == pytest.approx(1.1143 + 0.0015) and pos.note == ""


def test_a_long_call_takes_the_agent_stop_below_the_price():
    pos = apply(lb.Tweaks(stop=1.1143 - 0.0020), rating="Buy").positions["EURUSD"]
    assert pos.side == 1 and pos.stop == pytest.approx(1.1123) and pos.note == "agent stop"


def test_a_mild_call_trades_a_smaller_lot_but_a_fixed_lot_pair_stays_as_it_is():
    big = apply(None, price=1.1143, average_range=0.0002).positions["EURUSD"]       # a tight stop: a bigger lot to compare against
    mild = apply(lb.Tweaks(scale=settings.MILD_SIZE), average_range=0.0002).positions["EURUSD"]
    assert (big.lot, mild.lot) == (0.06, 0.05) and mild.note == "mild size" and big.note == ""          # 2% -> $2 / $30 a lot; 75% -> $1.50
    gold = apply(lb.Tweaks(scale=settings.MILD_SIZE), ticker="XAUUSD", price=4000.0, prices={"XAUUSD": 4000.0}, average_range=10.0).positions["XAUUSD"]
    assert gold.lot is None and gold.note == ""


def test_a_waiting_call_changes_nothing_and_is_still_marked_done():
    book = lb.Book(created="2026-10-30T00:00:00+00:00")
    lb.apply_decision(book, "EURUSD", "2026-10-29", "Buy", tweaks=None, **ARGS)         # an open long
    lb.apply_decision(book, "EURUSD", "2026-10-30", "Sell", tweaks=lb.Tweaks(hold="wait for the post-ECB close"), **ARGS)
    assert book.positions["EURUSD"].side == 1 and book.closed == []                  # the long was not flipped
    assert book.applied == ["EURUSD|2026-10-29", "EURUSD|2026-10-30"]
    assert book.skipped[-1]["why"] == "the agent said to wait: wait for the post-ECB close" and book.skipped[-1]["rating"] == "Sell"


def test_the_environment_turns_the_switches_on_per_account_and_ignores_unknown_words():
    accounts = {"gemma_short": settings.ACCOUNTS["gemma_short"], "qwen_short": settings.ACCOUNTS["qwen_short"]}
    out = settings.apply_overrides(accounts, {"AGENTIC_PLAN_GEMMA_SHORT": " Mild, junk ,LEVELS", "AGENTIC_PLAN_QWEN_SHORT": "junk"})
    assert out["gemma_short"].plan_options == ("levels", "mild") and out["qwen_short"].plan_options == ()
    assert settings.apply_overrides(accounts, {"AGENTIC_PLAN_GEMMA_SHORT": ""})["gemma_short"].plan_options == ()
    both = settings.apply_overrides(accounts, {"AGENTIC_PLAN_GEMMA_SHORT": "wait", "AGENTIC_CALL_EVERY_GEMMA_SHORT": "120"})["gemma_short"]
    assert both.plan_options == ("wait",) and both.call_every_minutes == 120


def test_the_account_update_uses_the_agents_answer_only_when_its_switch_is_on(runs, monkeypatch, tmp_path):
    runs("live_gemma", "EURUSD", "2026-10-30", trader="**Stop Loss**: 1.1173", final=PLAIN)
    monkeypatch.setattr(config, "READ_ONLY_DATA", False)
    monkeypatch.setattr("paper_trade.report.load_decisions", lambda run_id: ([type("D", (), {"ticker": "EURUSD", "date": "2026-10-30", "rating": "Sell"})()], None) if run_id == "live_gemma" else ([], None))
    monkeypatch.setattr(runner.feeds, "latest_prices", lambda tickers: {"EURUSD": 1.1143})
    monkeypatch.setattr(runner.feeds, "hourly_range", lambda ticker: 0.001)
    monkeypatch.setattr(runner.feeds, "intraday_bars", lambda ticker: None)
    monkeypatch.setattr(runner.feeds, "record_minute", lambda stamp: None)
    monkeypatch.setattr(runner, "_record_day", lambda: None)
    monkeypatch.setattr(settings, "book_path", lambda account: tmp_path / "book.json")
    now = datetime(2026, 10, 30, 1, 0, tzinfo=timezone.utc)
    off = runner.livebook.Book(created="2026-10-30T00:00:00+00:00")
    runner.update(off, settings.ACCOUNTS["gemma_short"], now)
    on = runner.livebook.Book(created="2026-10-30T00:00:00+00:00")
    runner.update(on, dataclasses.replace(settings.ACCOUNTS["gemma_short"], plan_options=("levels",)), now)
    assert off.positions["EURUSD"].note == "" and off.positions["EURUSD"].stop == pytest.approx(1.1143 + 0.0015)
    assert on.positions["EURUSD"].note == "agent stop" and on.positions["EURUSD"].stop == pytest.approx(1.1173)
