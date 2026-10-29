"""Live (forward) paper trading settings. Edit values here; the live modules hold no hardcoded numbers."""

from dataclasses import dataclass
from pathlib import Path

from paper_trade import config

TICKERS = ("EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "USDCHF", "NZDUSD", "BTC-USD", "ETH-USD", "XAUUSD",
           "AAPL", "NVDA", "MSFT")

UPDATE_SECONDS = 60                         # prices, stops and targets, and the forming M1 candle of every pair

# TradingView, through the tradingview-mcp package in its own environment (tvmcp/.venv). Forex and gold come from OANDA's
# feed on TradingView, crypto from Coinbase's, stocks from Nasdaq. canonical ticker -> "EXCHANGE:SYMBOL|screener"
TV_PYTHON = config.ROOT / "tvmcp" / ".venv" / "Scripts" / "python.exe"
TV_FEED = config.ROOT / "tvmcp" / "feed.py"
TV_SYMBOLS = {
    "EURUSD=X": "OANDA:EURUSD|forex", "GBPUSD=X": "OANDA:GBPUSD|forex", "USDJPY=X": "OANDA:USDJPY|forex",
    "AUDUSD=X": "OANDA:AUDUSD|forex", "USDCAD=X": "OANDA:USDCAD|forex", "USDCHF=X": "OANDA:USDCHF|forex",
    "NZDUSD=X": "OANDA:NZDUSD|forex", "GC=F": "OANDA:XAUUSD|cfd",
    "BTC-USD": "COINBASE:BTCUSD|crypto", "ETH-USD": "COINBASE:ETHUSD|crypto",
    "AAPL": "NASDAQ:AAPL|america", "NVDA": "NASDAQ:NVDA|america", "MSFT": "NASDAQ:MSFT|america",
}
TV_RECORD_EXTRA = {"SPY": "AMEX:SPY|america"}  # recorded for scoring decisions against SPY, never traded
TV_CANDLE_DIR = config.RUNS_DIR / "live" / "tv_candles"
TV_CANDLES_KEEP = 9000                      # recorded lines read back per pair (about three a minute: two days)
TV_SNAPSHOT_PATH = config.RUNS_DIR / "live" / "tv_snapshot.json"   # shared by both live loops and the dashboard
TV_CACHE_SECONDS = 55                       # TradingView is asked at most about once a minute (faster got us refused)
TV_COOLDOWN_PATH = config.RUNS_DIR / "live" / "tv_cooldown.txt"    # shared pause after TradingView refuses
TV_COOLDOWN_SECONDS = 30                    # first pause; it doubles for each refusal in a row
TV_COOLDOWN_MAX_SECONDS = 300
TV_TIMEOUT_SECONDS = 150                  # includes waiting for the shared gate (tvmcp/gate.py) while another fetch runs
TV_RETRY_SECONDS = 15                       # after a failed or timed-out fetch, this process waits this long before asking again
DECISION_AFTER_UTC = (0, 30)                # each day's decisions start after this UTC time (after the New York close)
STAGGER_SECONDS = 25                        # gap between the parallel decision workers of a hosted model

HISTORY_KEEP = 20_000                       # equity points kept in the book


LOT_STEP = 0.01                             # lots come in this step, and this is the smallest trade
MAX_LOT = 1.0


@dataclass(frozen=True)
class Style:
    """How an account places its stop and sizes and ends its trades. Every field left empty uses the bridge's rules
    (bridge/settings.py): the fixed lot, a stop of 2 daily ranges, a target 2 stops away, and no time limit."""
    stop_frame: str = "1d"                  # candle size whose 14-bar average range sets the stop: "1d" or "1h"
    stop_mult: float | None = None          # stop distance in average ranges
    reward_risk: float | None = None        # target distance in stops
    max_hours: float | None = None          # close at the market after this long
    risk_fraction: float | None = None      # size each trade to lose this share of the account at its stop (else the fixed lot)
    fixed_lot_tickers: tuple[str, ...] = ()  # these keep the fixed lot even when trades are sized by risk


DAILY = Style()
SHORT = Style(stop_frame="1h", stop_mult=1.5, reward_risk=2.0, max_hours=12, risk_fraction=0.02,
              fixed_lot_tickers=("XAUUSD",))
SHORT_TICKERS = tuple(t for t in TICKERS if t not in ("AAPL", "NVDA", "MSFT"))   # stocks trade 6.5 hours a day on 15-minute-late prices


@dataclass(frozen=True)
class Account:
    """One model trading its own fresh $100: a local model in one worker, or a hosted one with a worker per pair."""
    name: str
    run_id: str                             # the key the dashboard knows this account by
    label: str
    decide_args: tuple[str, ...] = ()       # model options for ``decide``
    parallel: bool = False                  # True: one worker per pair (hosted API), False: one worker for all pairs
    tickers: tuple[str, ...] = TICKERS
    style: Style = DAILY
    decisions_run_id: str | None = None     # the run folder its decisions are written to and read from (default: run_id)

    @property
    def decisions_run(self) -> str:
        return self.decisions_run_id or self.run_id


# Only the two short-term accounts trade now. They keep writing their calls into the run folders the first daily
# accounts used (live_gemma, live_qwen), so their decision history carries on. The daily accounts' books are archived
# under runs/archive/daily_accounts_2026-10-29.
ACCOUNTS = {
    "gemma_short": Account("gemma_short", "live_gemma_short", "short-term Gemma", ("--thinking",), parallel=False,
                           tickers=SHORT_TICKERS, style=SHORT, decisions_run_id="live_gemma"),
    "qwen_short": Account("qwen_short", "live_qwen_short", "short-term Qwen",
                          ("--provider", "openai_compatible", "--backend-url", "https://api.iteracompute.com/v1",
                           "--model", "qwen/qwen3.8-27b", "--effort", "medium", "--max-tokens", "8000"), parallel=True,
                          tickers=SHORT_TICKERS, style=SHORT, decisions_run_id="live_qwen"),
}


def book_path(account: Account) -> Path:
    return config.RUNS_DIR / "live" / account.name / "book.json"


def state_path(account: Account) -> Path:
    return config.RUNS_DIR / "live" / account.name / "state.json"
