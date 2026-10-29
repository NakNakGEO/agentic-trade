"""Live (forward) paper trading settings. Edit values here; the live modules hold no hardcoded numbers."""

import dataclasses
import os
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
TV_CANDLE_DIR = config.DATA_DIR / "live" / "tv_candles"
TV_CANDLES_KEEP = 9000                      # recorded lines read back per pair (about three a minute: two days)
TV_SNAPSHOT_PATH = config.DATA_DIR / "live" / "tv_snapshot.json"   # shared by both live loops and the dashboard
TV_CACHE_DIR = config.DATA_DIR / "live" / "tv_cache"                # the shared analysis and screener replies
READ_ONLY_MAX_AGE_SECONDS = 600             # read-only copies treat a snapshot older than this as missing
TV_CACHE_SECONDS = 55                       # TradingView is asked at most about once a minute (faster got us refused)
TV_COOLDOWN_PATH = config.DATA_DIR / "live" / "tv_cooldown.txt"    # shared pause after TradingView refuses
TV_COOLDOWN_SECONDS = 30                    # first pause; it doubles for each refusal in a row
TV_COOLDOWN_MAX_SECONDS = 300
TV_TIMEOUT_SECONDS = 150                  # includes waiting for the shared gate (tvmcp/gate.py) while another fetch runs
TV_RETRY_SECONDS = 15                       # after a failed or timed-out fetch, this process waits this long before asking again
DECISION_AFTER_UTC = (0, 30)                # each day's decisions start after this UTC time (after the New York close)
STAGGER_SECONDS = 25                        # gap between the parallel decision workers of a hosted model

HISTORY_KEEP = 20_000                       # equity points kept in the book

# Optional uses of the agent's full answer, switched on per account (AGENTIC_PLAN_<ACCOUNT NAME>=levels,wait,mild; see plan.py).
PLAN_LEVELS, PLAN_WAIT, PLAN_MILD = "levels", "wait", "mild"
PLAN_OPTIONS = (PLAN_LEVELS, PLAN_WAIT, PLAN_MILD)
PLAN_STOP_MIN = 0.5                         # the agent's stop is used only when its distance is within this many ...
PLAN_STOP_MAX = 3.0                         # ... to this many of the account's own stop distances (else the own stop is kept)
MILD_SIZE = 0.75                            # Overweight / Underweight trade this share of the usual size
MILD_RATINGS = ("Overweight", "Underweight")
# A call that puts a condition on entering ("do not enter until", "wait for", "stand aside" ...) in its summary line.
WAIT_PATTERN = (r"do not (?:enter|initiate|open|add)|don't (?:enter|initiate|open)|wait (?:for|until|one|a|to)|hold off|stand aside|"
                r"no new (?:short|long)|avoid (?:entering|initiating|new)|defer(?:red)? (?:the )?entry|enter only (?:after|if|once)")


LOT_STEP = 0.01                             # lots come in this step, and this is the smallest trade
MAX_LOT = 1.0

# Slippage, for accounts that switch it on (see friction.py): asset class -> (market order, stop-loss), in basis points of the
# price. These are assumptions, not measured fills: about 0.2 and 0.5 pips on EURUSD, 3 and 12 cents on an ounce of gold,
# and 1 and 3 basis points on crypto. Edit them here.
SLIPPAGE_BPS = {"forex": (0.2, 0.5), "gold": (0.3, 1.0), "crypto": (1.0, 3.0)}


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
    call_every_minutes: int | None = None   # None: one round of calls a day (the old behaviour); else a round on this clock grid
    api_key_env: str | None = None          # the key variable of an online model; further keys are NAME_2, NAME_3 ... (see keys.py)
    plan_options: tuple[str, ...] = ()      # which parts of the agent's full answer the account uses (PLAN_OPTIONS); none: the rating only
    max_per_pair: int = 1                   # trades in the same direction one pair may hold at once
    hedge: bool = False                     # True: a call against an open trade opens the opposite trade too instead of closing it
    risk_cap: float | None = None           # most open risk as a share of the account; None: no limit (the account may be wiped out)
    slippage: bool = False                  # True: fills land a little worse than the price, stops most of all (SLIPPAGE_BPS)

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
                          tickers=SHORT_TICKERS, style=SHORT, decisions_run_id="live_qwen", api_key_env="OPENAI_COMPATIBLE_API_KEY"),
}


def apply_overrides(accounts: dict, environ) -> dict:
    """The accounts with switches set from the environment, so a part can be turned on, and off again, without changing code:
    AGENTIC_CALL_EVERY_<ACCOUNT NAME>=<minutes> (0 or empty switches it off), AGENTIC_PLAN_<ACCOUNT NAME>=levels,wait,mild
    (any of the PLAN_OPTIONS; anything else is ignored), AGENTIC_MAX_PER_PAIR_<ACCOUNT NAME>=<trades per direction>,
    AGENTIC_HEDGE_<ACCOUNT NAME>=on|off, AGENTIC_RISK_CAP_<ACCOUNT NAME>=<percent of the account>|off and
    AGENTIC_SLIPPAGE_<ACCOUNT NAME>=on|off."""
    out = {}
    for name, account in accounts.items():
        def setting(prefix: str) -> str:
            return (environ.get(f"{prefix}_{name.upper()}") or "").strip().lower()

        if setting("AGENTIC_CALL_EVERY").isdigit():
            account = dataclasses.replace(account, call_every_minutes=int(setting("AGENTIC_CALL_EVERY")) or None)
        chosen = setting("AGENTIC_PLAN").replace(" ", "").split(",")
        if any(option in PLAN_OPTIONS for option in chosen):
            account = dataclasses.replace(account, plan_options=tuple(o for o in PLAN_OPTIONS if o in chosen))
        if setting("AGENTIC_MAX_PER_PAIR").isdigit() and int(setting("AGENTIC_MAX_PER_PAIR")) >= 1:
            account = dataclasses.replace(account, max_per_pair=int(setting("AGENTIC_MAX_PER_PAIR")))
        if setting("AGENTIC_HEDGE") in ("on", "off"):
            account = dataclasses.replace(account, hedge=setting("AGENTIC_HEDGE") == "on")
        if setting("AGENTIC_SLIPPAGE") in ("on", "off"):
            account = dataclasses.replace(account, slippage=setting("AGENTIC_SLIPPAGE") == "on")
        cap = setting("AGENTIC_RISK_CAP").rstrip("%")
        if cap == "off":
            account = dataclasses.replace(account, risk_cap=None)
        elif cap.replace(".", "", 1).isdigit() and float(cap) > 0:
            account = dataclasses.replace(account, risk_cap=float(cap) / 100)
        out[name] = account
    return out


ACCOUNTS = apply_overrides(ACCOUNTS, os.environ)


def book_path(account: Account) -> Path:
    return config.RUNS_DIR / "live" / account.name / "book.json"


def state_path(account: Account) -> Path:
    return config.RUNS_DIR / "live" / account.name / "state.json"
