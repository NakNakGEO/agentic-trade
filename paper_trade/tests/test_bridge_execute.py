import json

import pytest
from datetime import datetime, timezone

from fake_broker import FakeBroker, position

from paper_trade.bridge import build_session, execute, render
from paper_trade.bridge.models import SendResult
from paper_trade.simulator import Decision

pytestmark = pytest.mark.usefixtures("risk_sized")

NOW = datetime(2026, 10, 28, 10, 0, tzinfo=timezone.utc)
SELL = [Decision("XAUUSD", "2026-10-28", "Sell")]


def run(broker, confirmed=True, decisions=SELL, log=None):
    session = build_session(broker, decisions, NOW)
    asked = []
    lines = execute(session, broker, lambda: asked.append(1) or confirmed, log)
    return session, lines, asked


def test_nothing_is_sent_unless_the_user_confirms(tmp_path):
    broker = FakeBroker()
    _, lines, asked = run(broker, confirmed=False, log=tmp_path / "log.jsonl")
    assert broker.sent == [] and asked == [1] and "not confirmed" in lines[0]


def test_a_confirmed_plan_sends_its_orders_and_logs_them(tmp_path):
    broker, log = FakeBroker(), tmp_path / "log.jsonl"
    _, lines, _ = run(broker, log=log)
    assert [r.side for r in broker.sent] == ["sell"] and lines[0].startswith("sent")
    row = json.loads(log.read_text().splitlines()[0])
    assert row["ticker"] == "XAUUSD" and row["ok"] is True and row["request"]["sl"] > 0


def test_the_terminals_algo_trading_switch_blocks_sending_before_asking(tmp_path):
    broker = FakeBroker(trading_allowed=False)
    _, lines, asked = run(broker, log=tmp_path / "log.jsonl")
    assert broker.sent == [] and asked == [] and "Allow algorithmic trading" in lines[0]


def test_an_order_the_server_refused_in_the_dry_run_is_not_sent(tmp_path):
    broker = FakeBroker()
    broker.check_result = SendResult(False, "Market closed", 10018)
    _, lines, asked = run(broker, log=tmp_path / "log.jsonl")
    assert broker.sent == [] and asked == [] and lines == ["nothing to send"]


def test_a_failed_close_stops_the_plan_so_the_opposite_trade_is_not_opened(tmp_path):
    broker = FakeBroker(positions=[position(side="buy")])
    broker.send_results = [SendResult(False, "Requote", 10004)]
    _, lines, _ = run(broker, log=tmp_path / "log.jsonl")
    assert len(broker.sent) == 1 and lines[0].startswith("FAILED")


def test_the_report_names_the_account_as_demo_and_says_nothing_was_sent():
    session = build_session(FakeBroker(), SELL, NOW)
    text = render(session, sending=False)
    assert "DEMO" in text and "dry run" in text and "stop" in text and "XAUUSDm" in text
