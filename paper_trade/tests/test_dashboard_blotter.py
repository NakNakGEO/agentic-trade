import pandas as pd
import pytest

from paper_trade.bridge import settings as rules
from paper_trade.dashboard import blotter
from paper_trade.live import book as lb
from paper_trade.live import settings

NOW = "2026-10-29T10:00:00+00:00"
LATER = "2026-10-29T10:05:00+00:00"
SHORT = settings.SHORT


@pytest.fixture(autouse=True)
def fixed_lot(monkeypatch):
    monkeypatch.setattr(rules, "FIXED_LOT", 0.01)
    monkeypatch.setattr(rules, "FIXED_LOT_MAX_TOTAL_RISK", 100.0)


def hourly(*rows):
    return pd.DataFrame([(o, h, low, o) for _, o, h, low in rows], columns=["Open", "High", "Low", "Close"],
                        index=[pd.Timestamp(f"2026-10-29 {hour}:00") for hour, *_ in rows])


def open_trade(book, ticker, rating, when=NOW, price=1.1):
    lb.apply_decision(book, ticker, "2026-10-29", rating, price, [], when, {ticker: price}, 0.001, SHORT)


def test_an_open_trade_has_one_order_with_its_levels_and_what_it_makes_or_loses_at_each():
    book = lb.Book(created=NOW)
    open_trade(book, "EURUSD", "Sell")
    out = blotter.build(book, {"EURUSD": 1.0995})
    (order,) = out["orders"]
    win, lose = lb.outcomes(book.positions["EURUSD"])
    assert (order["kind"], order["side"], order["status"], order["fill"]) == ("open", "Sell", "Filled", 1.1)
    assert (order["tp"], order["sl"]) == (pytest.approx(1.097), pytest.approx(1.1015))
    assert (order["win"], order["lose"]) == (round(win, 2), round(lose, 2)) and win > 0 > lose
    assert (order["win_move"], order["lose_move"]) == ("30.0 pips", "15.0 pips")
    assert (order["result"], order["pnl"]) == ("open", pytest.approx(0.5))                     # 1,000 units x 0.0005, floating
    pos = out["positions"][0]
    assert (pos["pnl"], pos["to_target"], pos["to_stop"], pos["expiry"]) == (pytest.approx(0.5), "30.0 pips", "15.0 pips", "2026-10-29 22:00")
    assert out["history"] == []


def test_two_trades_on_one_pair_show_as_two_rows_and_a_hedge_is_one_buy_and_one_sell():
    book = lb.Book(created=NOW)
    open_trade(book, "XAUUSD", "Buy", price=4029.0)
    sell = lb.Position("XAUUSD", -1, 4028.6, 4040.0, 4005.0, LATER, "2026-10-29", "Sell", 11.4, 0.4, None, "")
    book.positions["XAUUSD#2"] = sell                      # the book keeps one trade per pair today: a second key stands in for it
    out = blotter.build(book, {"XAUUSD": 4029.1})
    assert [(p["trade"], p["ticker"], p["side"]) for p in out["positions"]] == [(2, "XAUUSD", "short"), (1, "XAUUSD", "long")]
    assert sorted(o["side"] for o in out["orders"]) == ["Buy", "Sell"]


def test_a_closed_trade_has_an_opening_and_a_closing_order_and_both_say_whether_it_won():
    book = lb.Book(created=NOW)
    open_trade(book, "EURUSD", "Sell")
    lb.step(book, "EURUSD", hourly((11, 1.1, 1.1001, 1.0900)))                      # reaches the take profit
    out = blotter.build(book, {})
    closing, opening = out["orders"]                                                 # newest first
    assert (closing["kind"], closing["side"], closing["fill"], closing["result"]) == ("close", "Buy", pytest.approx(1.097), "win")
    assert (opening["kind"], opening["side"], opening["result"]) == ("open", "Sell", "win")
    assert closing["pnl"] == opening["pnl"] == out["history"][0]["pnl"] > 0
    assert out["history"][0]["reason"] == "Take-profit" and out["history"][0]["move"] == "+30.0 pips"
    assert out["positions"] == []


def test_a_losing_trade_says_loss_and_a_time_limit_close_is_listed_with_its_reason():
    book = lb.Book(created=NOW)
    open_trade(book, "EURUSD", "Sell")
    lb.step(book, "EURUSD", hourly((22, 1.1020, 1.1030, 1.1015)))
    out = blotter.build(book, {})
    assert [o["result"] for o in out["orders"]] == ["loss", "loss"] and out["orders"][0]["pnl"] < 0
    assert out["history"][0]["reason"] == "Time limit" and out["history"][0]["minutes"] == 720
    assert out["history"][0]["move"] == "-20.0 pips"


def test_when_a_call_flips_the_old_trade_is_closed_and_the_new_one_opened_in_the_same_minute():
    book = lb.Book(created=NOW)
    lb.apply_decision(book, "AAPL", "2026-10-28", "Buy", 345.0, [], NOW, {"AAPL": 345.0}, 1.0, SHORT)
    lb.apply_decision(book, "AAPL", "2026-10-29", "Sell", 343.0, [], LATER, {"AAPL": 343.0}, 1.0, SHORT)
    out = blotter.build(book, {"AAPL": 343.0})
    assert [(o["kind"], o["trade"], o["side"], o["time"]) for o in out["orders"]] == [
        ("open", 2, "Sell", "2026-10-29 10:05"), ("close", 1, "Sell", "2026-10-29 10:05"), ("open", 1, "Buy", "2026-10-29 10:00")]


def test_trades_closed_before_their_levels_were_kept_still_list_their_orders():
    book = lb.Book(created=NOW)
    book.closed.append(lb.Closed("AAPL", -1, 343.0, 344.0, NOW, LATER, "New call", -0.02, "2026-10-28", "Sell"))
    out = blotter.build(book, {})
    assert [o["kind"] for o in out["orders"]] == ["close", "open"] and out["orders"][1]["tp"] is None
    assert out["history"][0]["pnl"] == -0.02
