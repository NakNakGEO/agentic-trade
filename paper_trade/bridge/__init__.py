"""Bridge from the paper-trade decisions to a MetaTrader 5 demo account. Demo only, dry run by default."""

from paper_trade.bridge.execute import execute
from paper_trade.bridge.guards import RealAccountError
from paper_trade.bridge.render import render
from paper_trade.bridge.session import Session, build_session

__all__ = ["RealAccountError", "Session", "build_session", "execute", "render"]
