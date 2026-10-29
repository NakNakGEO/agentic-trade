import json

from paper_trade.dashboard import state, sysinfo


def test_token_totals_sum_calls_tokens_and_agents(tmp_path):
    path = tmp_path / "events.jsonl"
    rows = [
        {"kind": "llm", "node": "Market Analyst", "seconds": 4.0, "tokens_in": 1000, "tokens_out": 50},
        {"kind": "llm", "node": "Market Analyst", "seconds": 6.0, "tokens_in": 2000, "tokens_out": 150},
        {"kind": "llm", "node": "Trader", "seconds": 2.0, "tokens_in": 500, "tokens_out": 100},
        {"kind": "tool", "node": "Market Analyst", "tool": "get_stock_data"},
        {"kind": "error", "node": "Trader", "text": "boom"},
    ]
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n{half written", encoding="utf-8")

    totals = state.token_totals(path)

    assert (totals["calls"], totals["tool_calls"], totals["errors"]) == (3, 1, 1)
    assert (totals["tokens_in"], totals["tokens_out"]) == (3500, 300)
    assert totals["llm_seconds"] == 12.0
    assert totals["by_node"][0] == {"node": "Market Analyst", "calls": 2, "tokens": 3200}


def test_response_times_use_exact_ms_and_fall_back_to_seconds_for_older_events(tmp_path):
    path = tmp_path / "events.jsonl"
    rows = [
        {"kind": "llm", "node": "A", "ms": 1200, "seconds": 1.2, "tokens_in": 1, "tokens_out": 1},
        {"kind": "llm", "node": "A", "seconds": 61.9, "tokens_in": 1, "tokens_out": 1},          # recorded before ms existed
        {"kind": "llm", "node": "B", "ms": 400, "seconds": 0.4, "tokens_in": 1, "tokens_out": 1},
    ]
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")

    totals = state.token_totals(path)

    assert (totals["ms_last"], totals["ms_max"], totals["ms_median"]) == (400, 61900, 1200)
    assert totals["ms_avg"] == round((1200 + 61900 + 400) / 3)
    assert totals["slow_calls"] == 1


def test_no_calls_means_no_latency_numbers(tmp_path):
    path = tmp_path / "events.jsonl"
    path.write_text(json.dumps({"kind": "tool", "node": "A", "tool": "x"}) + "\n", encoding="utf-8")
    totals = state.token_totals(path)
    assert totals["ms_last"] is None and totals["ms_avg"] is None and totals["slow_calls"] == 0


def test_token_totals_refresh_when_the_file_grows(tmp_path):
    path = tmp_path / "events.jsonl"
    path.write_text(json.dumps({"kind": "llm", "node": "A", "tokens_in": 1, "tokens_out": 1}) + "\n", encoding="utf-8")
    assert state.token_totals(path)["calls"] == 1
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps({"kind": "llm", "node": "A", "tokens_in": 1, "tokens_out": 1}) + "\n")
    assert state.token_totals(path)["calls"] == 2


def test_missing_feed_is_empty_not_an_error(tmp_path):
    assert state.token_totals(tmp_path / "nope.jsonl") == {}
    assert state.read_feed(tmp_path / "nope.jsonl") == []


def test_decisions_parse_settled_and_pending_tags(tmp_path):
    path = tmp_path / "trading_memory.md"
    path.write_text(
        "[2026-09-02 | AAPL | Overweight | +1.2% | +2.4% | 5d | resolved:2026-09-11]\n\nDECISION:\nx\n"
        "<!-- ENTRY_END -->\n[2026-09-02 | EURUSD | Underweight | pending]\n\nDECISION:\ny\n", encoding="utf-8")

    rows = {r["ticker"]: r for r in state.read_decisions(path)}

    assert rows["AAPL"]["raw"] == "+1.2%" and rows["AAPL"]["alpha"] == "+2.4%"
    assert rows["EURUSD"]["raw"] is None and rows["EURUSD"]["rating"] == "Underweight"


def test_ollama_log_parsing():
    text = ("slot init_sampler: id 0 | task 1 | tokens: text = 3128, total = 3128\n"
            "slot print_timing: id 0 | n_gen = 160, tg =  52.48 t/s\n"
            "slot init_sampler: id 0 | task 2 | tokens: text = 900, total = 900\n")
    assert sysinfo.parse_ollama_log(text) == {
        "requests": 2, "last_prompt_tokens": 900, "tokens_per_second": 52.48}
    assert sysinfo.parse_ollama_log("nothing here")["requests"] == 0
