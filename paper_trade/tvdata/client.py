"""Calls tvmcp/engine_feed.py (in the tradingview-mcp environment) and caches its replies in shared files.

Every decision worker reads the same cache, so TradingView is asked once per CACHE_SECONDS however many workers run.
"""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

from paper_trade import config
from paper_trade.live import settings as live
from paper_trade.live import tv_guard

CREATE_NO_WINDOW = 0x08000000
ENGINE_FEED = config.ROOT / "tvmcp" / "engine_feed.py"
CACHE_DIR = live.TV_CACHE_DIR
ANALYSIS_SECONDS = 15 * 60
INTERVALS = ("1h", "4h", "1d", "1W")
TIMEOUT_SECONDS = 180


def _run(request: dict) -> dict:
    tv_guard.check()
    try:
        reply = subprocess.run([str(live.TV_PYTHON), str(ENGINE_FEED)], input=json.dumps(request), capture_output=True,
                               text=True, timeout=TIMEOUT_SECONDS, creationflags=CREATE_NO_WINDOW)
    except subprocess.TimeoutExpired:            # waited too long behind other requests: not TradingView refusing us
        raise RuntimeError("TradingView request timed out waiting its turn") from None
    if reply.returncode != 0:
        tv_guard.failed()
        raise RuntimeError(f"TradingView request failed: {tv_guard.why(reply.stderr)}")
    tv_guard.succeeded()
    return json.loads(reply.stdout.strip().splitlines()[-1])


def _cached(name: str, seconds: int, fetch) -> dict:
    """A shared cached reply; when a refresh fails (or TradingView is cooling down) the last reply is used."""
    path = CACHE_DIR / f"{name}.json"
    if config.READ_ONLY_DATA:                # a test copy only reads what the live system fetched, however old
        if not path.exists():
            raise RuntimeError(f"read-only data mode: the live system has no '{name}' reply yet")
        return json.loads(path.read_text(encoding="utf-8"))
    if path.exists() and time.time() - path.stat().st_mtime < seconds:
        return json.loads(path.read_text(encoding="utf-8"))
    try:
        data = fetch()
    except Exception:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        raise
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data), encoding="utf-8")
    tmp.replace(path)
    return data


def analysis() -> dict:
    """{ticker: {interval: {indicator: value}}} for every live pair and SPY (all TradingView indicators, ATR daily)."""
    symbols = {**{t: live.TV_SYMBOLS[c] for t, c in _canonical_live().items()}, **live.TV_RECORD_EXTRA}
    return _cached("analysis", ANALYSIS_SECONDS,
                   lambda: _run({"mode": "analysis", "symbols": symbols, "intervals": list(INTERVALS)}))


SCREENER_SECONDS = 6 * 3600          # company figures and names change slowly
STOCK_FIELDS = (
    "name", "description", "sector", "industry", "exchange", "country", "number_of_employees", "market_cap_basic",
    "price_earnings_ttm", "earnings_per_share_diluted_ttm", "earnings_per_share_diluted_yoy_growth_ttm",
    "earnings_per_share_forecast_next_fq", "earnings_release_date", "earnings_release_next_date", "total_revenue_ttm",
    "total_revenue_yoy_growth_ttm", "net_income_ttm", "gross_margin_ttm", "operating_margin_ttm", "net_margin_ttm",
    "return_on_equity", "debt_to_equity", "current_ratio", "total_debt", "cash_n_short_term_invest_fq",
    "free_cash_flow_ttm", "dividends_yield_current", "price_book_fq", "price_sales_current",
    "enterprise_value_ebitda_ttm", "beta_1_year", "price_target_average", "recommendation_mark",
)


def screener() -> dict:
    """{ticker: {field: value}}: name and description for every live pair, company figures for stocks."""
    symbols = {t: live.TV_SYMBOLS[c] for t, c in _canonical_live().items()}
    return _cached("screener", SCREENER_SECONDS,
                   lambda: _run({"mode": "screener", "symbols": symbols, "stock_fields": list(STOCK_FIELDS)}))


def _canonical_live() -> dict[str, str]:
    from paper_trade.assets import canonical

    return {t: canonical(t) for t in live.TICKERS if canonical(t) in live.TV_SYMBOLS}


def cache_path(name: str) -> Path:
    return CACHE_DIR / f"{name}.json"
