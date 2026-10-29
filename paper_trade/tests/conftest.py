import pytest

from paper_trade.bridge import settings


@pytest.fixture
def risk_sized(monkeypatch):
    """Size bridge orders by the 2% risk rule (the shipped default is a fixed 0.01 lot)."""
    monkeypatch.setattr(settings, "FIXED_LOT", None)
