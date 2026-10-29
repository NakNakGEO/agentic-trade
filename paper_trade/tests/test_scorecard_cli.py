from types import SimpleNamespace

from paper_trade import cli, scorecard
from paper_trade.scorecard import cli as scorecard_cli


def test_the_command_prints_each_accounts_scorecard_or_just_one(monkeypatch, capsys):
    monkeypatch.setattr(scorecard, "for_account", lambda account: None)
    assert scorecard_cli.run(SimpleNamespace(account=None)) == 0
    out = capsys.readouterr().out
    assert "short-term Gemma: no calls" in out and "short-term Qwen: no calls" in out
    scorecard_cli.run(SimpleNamespace(account="qwen_short"))
    out = capsys.readouterr().out
    assert "short-term Qwen" in out and "Gemma" not in out


def test_the_command_is_reachable_from_the_main_program(monkeypatch, capsys):
    monkeypatch.setattr(scorecard, "for_account", lambda account: None)
    assert cli.main(["scorecard", "--account", "gemma_short"]) == 0
    assert "short-term Gemma: no calls" in capsys.readouterr().out
