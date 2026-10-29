"""Command line: ``python -m paper_trade decide ...`` then ``python -m paper_trade simulate ...``."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from paper_trade import config


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="paper_trade")
    sub = parser.add_subparsers(dest="command", required=True)

    decide = sub.add_parser("decide", help="run TradingAgents over a ticker/date grid")
    decide.add_argument("--tickers", default=",".join(config.UNIVERSE),
                        help="comma separated; stocks, crypto (BTC-USD), forex (EURUSD), gold (XAUUSD)")
    decide.add_argument("--start", required=True)
    decide.add_argument("--end", required=True)
    decide.add_argument("--every", type=int, default=7, help="days between decisions")
    decide.add_argument("--run-id", required=True)
    decide.add_argument("--live", action="store_true",
                        help="include the social analyst (not point-in-time safe for replays)")
    decide.add_argument("--provider", help="LLM provider instead of local Ollama, e.g. groq, openrouter, "
                                           "google, mistral, nvidia (key comes from .env)")
    decide.add_argument("--model", help="model for the analysts, debaters and trader")
    decide.add_argument("--deep-model", help="model for the research and portfolio managers (default: --model)")
    decide.add_argument("--backend-url", help="custom OpenAI-compatible endpoint")
    decide.add_argument("--only", help="run just these tickers in this process (others are left to other "
                                       "processes sharing the same --run-id)")
    decide.add_argument("--max-tokens", type=int, help="cap on the length of any single model answer")
    decide.add_argument("--thinking", action="store_true",
                        help="leave the local model's thinking ON (it is switched off by default for speed)")
    decide.add_argument("--effort", choices=("low", "medium", "high", "xhigh"),
                        help="keep thinking on at this effort level (the way to tune it on IteraCompute)")
    decide.add_argument("--data", choices=("tradingview",), default="tradingview",
                        help="market data for the models: TradingView live data with this system's own "
                             "day-by-day record (the only choice)")
    decide.add_argument("--no-thinking", action="store_true",
                        help="switch the model's hidden reasoning off (Qwen-style endpoints, Ollama); "
                             "saves tokens on a free allowance")

    compare = sub.add_parser("compare", help="two runs head to head on the decisions both made")
    compare.add_argument("--a", required=True, help="first run id")
    compare.add_argument("--b", required=True, help="second run id")
    compare.add_argument("--label-a", default="A")
    compare.add_argument("--label-b", default="B")
    compare.add_argument("--out", help="also save the report to this file")
    compare.add_argument("--cash", type=float, default=config.STARTING_CASH)

    simulate = sub.add_parser("simulate", help="paper-trade the decisions of a run")
    simulate.add_argument("--run-id", required=True)
    simulate.add_argument("--cash", type=float, default=config.STARTING_CASH)
    simulate.add_argument("--mode", choices=sorted(config.ACCOUNT_MODES), default=config.DEFAULT_MODE,
                          help="long_only (buy and sell only) or long_short (bearish calls open short trades)")

    from paper_trade.bridge import cli as bridge_cli
    from paper_trade.live import cli as live_cli
    from paper_trade.live import watchdog
    from paper_trade.scorecard import cli as scorecard_cli
    from paper_trade.whatif import cli as whatif_cli

    scorecard_cli.add_arguments(sub)
    whatif_cli.add_arguments(sub)
    bridge_cli.add_arguments(sub)
    live_cli.add_arguments(sub)
    watchdog.add_arguments(sub)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "decide":
        from tradingagents.backtest import iter_grid

        from paper_trade.decide import decide

        analysts = config.LIVE_ANALYSTS if args.live else config.REPLAY_ANALYSTS
        tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
        llm = {"llm_provider": args.provider, "quick_think_llm": args.model,
               "deep_think_llm": args.deep_model or args.model, "backend_url": args.backend_url,
               "max_tokens": args.max_tokens}
        only = [t.strip().upper() for t in args.only.split(",") if t.strip()] if args.only else None
        decide(tickers, iter_grid(args.start, args.end, args.every), args.run_id, analysts, llm,
               no_thinking=args.no_thinking, only=only, thinking=args.thinking, effort=args.effort, data=args.data)
        return 0

    if args.command == "compare":
        from paper_trade.compare import compare_runs

        text = compare_runs(args.a, args.b, args.cash, args.label_a, args.label_b)
        if args.out:
            Path(args.out).parent.mkdir(parents=True, exist_ok=True)
            Path(args.out).write_text(text + "\n", encoding="utf-8")
        print(text)
        return 0

    if args.command == "live":
        from paper_trade.live import cli as live_cli

        return live_cli.run(args)

    if args.command == "scorecard":
        from paper_trade.scorecard import cli as scorecard_cli

        return scorecard_cli.run(args)

    if args.command == "whatif":
        from paper_trade.whatif import cli as whatif_cli

        return whatif_cli.run(args)

    if args.command == "watchdog":
        from paper_trade.live import watchdog

        return watchdog.run(args)

    if args.command == "bridge":
        from paper_trade.bridge import cli as bridge_cli

        return bridge_cli.run(args)

    from paper_trade.report import run_simulation

    print(run_simulation(args.run_id, args.cash, args.mode))
    return 0


if __name__ == "__main__":
    sys.exit(main())
