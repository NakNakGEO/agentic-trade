"""``python -m paper_trade bridge``: plan (and, only when told to, send) a run's decisions on an MT5 demo account."""

from __future__ import annotations

import argparse

from paper_trade import config
from paper_trade.bridge import RealAccountError, build_session, execute, render, spreads, symbols
from paper_trade.bridge.broker import Broker
from paper_trade.bridge.mt5_broker import Mt5Broker

SPREAD_INTERVAL = 15.0      # seconds between looks when sampling


def add_arguments(sub) -> None:
    bridge = sub.add_parser("bridge", help="plan or send a run's latest decisions on an MT5 demo account")
    bridge.add_argument("--run-id", help="the run whose decisions to trade (needed unless --symbols)")
    bridge.add_argument("--send", action="store_true",
                        help="send the orders after a typed 'yes' (without it, only a dry run is printed)")
    bridge.add_argument("--symbols", action="store_true",
                        help="show the account and how each ticker maps to a symbol on it, then stop")
    bridge.add_argument("--spreads", action="store_true",
                        help="show each pair's live spread against its daily range, then stop")
    bridge.add_argument("--minutes", type=float, default=0.0,
                        help="with --spreads: keep sampling for this long and report the median and worst spread")
    bridge.add_argument("--tickers", default=",".join(config.UNIVERSE),
                        help="with --symbols or --spreads: which pairs to look at (comma separated)")
    bridge.add_argument("--terminal-path", help="full path to terminal64.exe if several MT5 terminals are installed")


def account_lines(broker: Broker) -> list[str]:
    account = broker.account()
    kind = "DEMO" if account.is_demo else "REAL - the bridge will refuse to trade on it"
    return [f"Account {account.login} on {account.server}: {kind}, {account.balance:,.2f} {account.currency}",
            f"Algorithmic trading allowed in the terminal: {'yes' if account.terminal_trading_allowed else 'NO'}", ""]


def show_spreads(broker: Broker, tickers: list[str], minutes: float, interval: float = SPREAD_INTERVAL) -> str:
    looks = max(1, int(minutes * 60 / interval) + 1) if minutes > 0 else 1
    if looks > 1:
        print(f"Sampling spreads every {interval:g}s for {minutes:g} minutes...", flush=True)
    rows = spreads.measure(broker, tickers, looks, interval)
    return "\n".join(account_lines(broker) + [spreads.render(rows, looks)])


def show_symbols(broker: Broker, tickers: list[str] = config.UNIVERSE) -> str:
    lines = account_lines(broker)
    available = broker.symbol_names()
    for ticker in tickers:
        name = symbols.resolve(ticker, available)
        if name is None:
            near = symbols.similar(ticker, available)
            lines.append(f"{ticker:<9} -> not found" + (f"   similar: {', '.join(near)}" if near else ""))
            continue
        spec = broker.spec(name)
        lines.append(f"{ticker:<9} -> {name:<10} min lot {spec.volume_min:g}, step {spec.volume_step:g}"
                     if spec else f"{ticker:<9} -> {name} (no details)")
    return "\n".join(lines)


def _ask() -> bool:
    try:
        return input("Type 'yes' to send these orders to the DEMO account: ").strip().lower() == "yes"
    except EOFError:
        return False


def run(args: argparse.Namespace) -> int:
    if not (args.symbols or args.spreads or args.run_id):
        print("bridge needs --run-id (or --symbols / --spreads to just look at the account)")
        return 2
    tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    try:
        broker = Mt5Broker(args.terminal_path)
    except (ImportError, ConnectionError) as error:
        print(error)
        return 2
    try:
        if args.symbols:
            print(show_symbols(broker, tickers))
            return 0
        if args.spreads:
            print(show_spreads(broker, tickers, args.minutes))
            return 0
        from paper_trade.decide import read_meta
        from paper_trade.report import load_decisions

        decisions, _ = load_decisions(args.run_id)
        try:
            session = build_session(broker, decisions, order=read_meta(args.run_id).get("tickers"))
        except RealAccountError as error:
            print(error)
            return 2
        print(render(session, args.send))
        if args.send:
            print("\n".join(execute(session, broker, _ask)))
        return 0
    finally:
        broker.shutdown()
