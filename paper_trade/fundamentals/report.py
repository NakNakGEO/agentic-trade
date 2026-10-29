"""The fundamentals analyst's tools, one answer per asset class, with the framework's arguments.

Stocks: TradingView's company figures, plus SEC EDGAR filings for the statements and insider trades.
Forex: both currencies' rates, inflation, jobs and yields (FRED), speculator positioning (CFTC), this week's releases.
Gold: real and nominal US yields, the dollar and inflation (FRED), positioning (CFTC), US releases.
Crypto: market size, supply, volume and network money (CoinGecko, DefiLlama), positioning in CME futures (CFTC).
"""

from __future__ import annotations

from datetime import datetime, timezone

from paper_trade import assets
from paper_trade.fundamentals import calendar, cot, crypto, fred, settings, stocks


def _today(as_of: str | None) -> str:
    return (as_of or datetime.now(timezone.utc).strftime("%Y-%m-%d"))[:10]


def _pair(ticker: str) -> tuple[str, str]:
    symbol = assets.canonical(ticker)
    return symbol[:3], symbol[3:6]


def _forex(ticker: str, as_of: str) -> list[str]:
    base, quote = _pair(ticker)
    lines = [f"## Fundamentals for the {base}/{quote} exchange rate (as of {as_of})",
             f"The pair rises when {base} strengthens against {quote}. Compare the two economies: a higher interest rate "
             "or yield, or a rate expected to rise, tends to support a currency."]
    for currency in (base, quote):
        lines += [""] + fred.render(fred.currency_table(currency, as_of), f"{currency} economy (FRED)")
    for currency in (base, quote):
        if currency != "USD" or base == "USD":
            lines += [""] + cot.render(currency, as_of)
    return lines + [""] + calendar.render([base, quote])


def _gold(as_of: str) -> list[str]:
    usd = {r["series"]: r for r in fred.currency_table("USD", as_of)}
    rows = [usd[s] for s in settings.GOLD_SERIES if s in usd]
    return ([f"## Fundamentals for gold (XAUUSD, as of {as_of})",
             "Gold pays no interest: it tends to fall when real (after-inflation) US yields and the dollar rise, "
             "and to rise when they fall or when inflation fears grow.", ""]
            + fred.render(rows, "US rates, inflation and the dollar (FRED)") + [""] + cot.render("GOLD", as_of)
            + [""] + calendar.render(["USD"]))


def _crypto(ticker: str, as_of: str) -> list[str]:
    coin = assets.canonical(ticker).split("-")[0]
    usd = {r["series"]: r for r in fred.currency_table("USD", as_of)}
    rows = [usd[s] for s in ("DFF", "DFII10", "DTWEXBGS") if s in usd]
    return ([f"## Fundamentals for {ticker} (as of {as_of})",
             "A crypto asset has no company behind it; these are its network and market measures, plus US rates "
             "and the dollar, which move risk appetite.", ""] + crypto.render(ticker) + [""] + cot.render(coin, as_of)
            + [""] + fred.render(rows, "US rates and the dollar (FRED)"))


def get_fundamentals(ticker: str, curr_date: str | None = None, *args, **kwargs) -> str:
    as_of = _today(curr_date)
    kind = assets.asset_class(ticker)
    if kind == "forex":
        lines = _forex(ticker, as_of)
    elif kind == "gold":
        lines = _gold(as_of)
    elif kind == "crypto":
        lines = _crypto(ticker, as_of)
    else:
        lines = [f"## Fundamentals for {ticker} (as of {as_of})", ""] + stocks.render(ticker)
        lines += ["", "Use get_balance_sheet, get_income_statement and get_cashflow for the filed statements (SEC EDGAR)."]
    return "\n".join(lines)


def _statement(name: str):
    def tool(ticker: str, freq: str = "quarterly", curr_date: str | None = None, *args, **kwargs) -> str:
        if assets.asset_class(ticker) != "stock":
            return (f"NOT_APPLICABLE: {ticker} is not a company, so it has no {name.replace('_', ' ')}. "
                    "Its fundamentals (economy, positioning, network data) come from get_fundamentals.")
        from tradingagents.dataflows.vendors import sec_edgar

        return getattr(sec_edgar, f"get_{name}")(ticker, freq, _today(curr_date))
    tool.__name__ = f"get_{name}"
    return tool


get_balance_sheet = _statement("balance_sheet")
get_income_statement = _statement("income_statement")
get_cashflow = _statement("cashflow")


def get_insider_transactions(ticker: str, *args, **kwargs) -> str:
    if assets.asset_class(ticker) != "stock":
        return f"NOT_APPLICABLE: {ticker} is a currency, gold or crypto pair; insider trades do not exist for it."
    try:
        return stocks.insider_filings(ticker, _today(kwargs.get("curr_date")))
    except Exception as error:
        return f"NO_DATA_AVAILABLE: SEC EDGAR insider filings could not be read ({type(error).__name__})."
