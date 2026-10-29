import json

from paper_trade import config
from paper_trade.decide import read_meta


def _write_meta(tmp_path, raw: bytes):
    run = tmp_path / "backtest" / "r1"
    run.mkdir(parents=True)
    (run / "meta.json").write_bytes(raw)


def test_meta_with_a_windows_byte_order_mark_is_still_read(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "RUNS_DIR", tmp_path)
    _write_meta(tmp_path, b"\xef\xbb\xbf" + json.dumps({"provider": "openai_compatible"}).encode())
    assert read_meta("r1") == {"provider": "openai_compatible"}


def test_missing_or_broken_meta_is_empty_not_an_error(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "RUNS_DIR", tmp_path)
    assert read_meta("nope") == {}
    _write_meta(tmp_path, b"{not json")
    assert read_meta("r1") == {}
