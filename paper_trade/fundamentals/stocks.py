"""Company fundamentals for stocks: TradingView's current company figures, and insider filings listed by SEC EDGAR."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from paper_trade.fundamentals import settings
from paper_trade.tvdata import client

# TradingView field -> (what it is, how to show it)
FIELDS = [
    ("description", "Company", "text"), ("sector", "Sector", "text"), ("industry", "Industry", "text"),
    ("exchange", "Exchange", "text"), ("country", "Country", "text"), ("number_of_employees", "Employees", "count"),
    ("market_cap_basic", "Market value", "money"), ("price_earnings_ttm", "Price / earnings (last 12 months)", "ratio"),
    ("earnings_per_share_diluted_ttm", "Earnings per share (12 months)", "price"),
    ("earnings_per_share_diluted_yoy_growth_ttm", "Earnings per share growth over a year %", "pct"),
    ("earnings_per_share_forecast_next_fq", "Analysts' earnings forecast, next quarter", "price"),
    ("earnings_release_date", "Last earnings report", "date"), ("earnings_release_next_date", "Next earnings report", "date"),
    ("total_revenue_ttm", "Revenue (12 months)", "money"), ("total_revenue_yoy_growth_ttm", "Revenue growth over a year %", "pct"),
    ("net_income_ttm", "Net income (12 months)", "money"), ("gross_margin_ttm", "Gross margin %", "pct"),
    ("operating_margin_ttm", "Operating margin %", "pct"), ("net_margin_ttm", "Net margin %", "pct"),
    ("return_on_equity", "Return on equity %", "pct"), ("debt_to_equity", "Debt / equity", "ratio"),
    ("current_ratio", "Current ratio", "ratio"), ("total_debt", "Total debt", "money"),
    ("cash_n_short_term_invest_fq", "Cash and short-term investments", "money"),
    ("free_cash_flow_ttm", "Free cash flow (12 months)", "money"), ("dividends_yield_current", "Dividend yield %", "pct"),
    ("price_book_fq", "Price / book", "ratio"), ("price_sales_current", "Price / sales", "ratio"),
    ("enterprise_value_ebitda_ttm", "Enterprise value / EBITDA", "ratio"), ("beta_1_year", "Beta (1 year)", "ratio"),
    ("price_target_average", "Analysts' average price target", "price"),
    ("recommendation_mark", "Analysts' rating (1 strong buy ... 5 strong sell)", "ratio"),
]


def _show(value, kind: str) -> str:
    if kind == "text":
        return str(value)
    if kind == "date":
        return datetime.fromtimestamp(float(value), timezone.utc).strftime("%Y-%m-%d")
    value = float(value)
    if kind == "money":
        for size, unit in ((1e12, "trillion"), (1e9, "billion"), (1e6, "million")):
            if abs(value) >= size:
                return f"${value / size:,.2f} {unit}"
        return f"${value:,.0f}"
    if kind == "count":
        return f"{value:,.0f}"
    if kind == "price":
        return f"${value:,.2f}"
    return f"{value:,.2f}"


def company_figures(ticker: str) -> dict:
    return client.screener().get("rows", {}).get(ticker, {})


def render(ticker: str) -> list[str]:
    try:
        figures = company_figures(ticker)
    except Exception as error:
        return [f"### {ticker} company figures (TradingView)", f"Unavailable: {type(error).__name__}"]
    if not figures:
        return [f"### {ticker} company figures (TradingView)", "TradingView returned no figures."]
    lines = [f"### {ticker} company figures (TradingView, current)", "| Measure | Value |", "|---|---|"]
    lines += [f"| {label} | {_show(figures[key], kind)} |" for key, label, kind in FIELDS if figures.get(key) is not None]
    return lines


def insider_filings(ticker: str, as_of: str) -> str:
    """Form 4 filings (insiders reporting a trade) filed in the ``INSIDER_DAYS`` before ``as_of``, by SEC EDGAR."""
    from tradingagents.dataflows.vendors import sec_edgar

    cik = sec_edgar.cik_for(ticker)
    if not cik:
        return f"NO_DATA_AVAILABLE: SEC EDGAR has no filer for {ticker}."
    recent = sec_edgar._fetch_json(settings.SEC_SUBMISSIONS_URL.format(cik=cik)).get("filings", {}).get("recent", {})
    since = (datetime.strptime(as_of, "%Y-%m-%d") - timedelta(days=settings.INSIDER_DAYS)).strftime("%Y-%m-%d")
    dates = [d for f, d in zip(recent.get("form", []), recent.get("filingDate", [])) if f == "4" and since <= d <= as_of]
    lines = [f"## Insider trade filings for {ticker} (SEC EDGAR Form 4, {since} to {as_of})",
             f"{len(dates)} Form 4 filings: each is an officer, director or large holder reporting a trade in the stock.",
             "The filings are counted by date here; whether each was a purchase or a sale is not read."]
    if dates:
        by_week: dict = {}
        for d in dates:
            week = datetime.strptime(d, "%Y-%m-%d")
            key = (week - timedelta(days=week.weekday())).strftime("%Y-%m-%d")
            by_week[key] = by_week.get(key, 0) + 1
        lines += ["| Week starting | Filings |", "|---|---|"] + [f"| {w} | {n} |" for w, n in sorted(by_week.items())]
    return "\n".join(lines)
