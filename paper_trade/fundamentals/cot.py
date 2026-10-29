"""CFTC Commitments of Traders: how large speculators are positioned in a currency, gold or crypto future."""

from __future__ import annotations

from paper_trade import webcache
from paper_trade.fundamentals import settings


def weeks(code: str, as_of: str) -> list[dict]:
    """The latest ``COT_WEEKS`` reports dated on or before ``as_of``, newest first."""
    rows = webcache.get(settings.COT_URL, settings.COT_TTL, params={
        "$where": f"cftc_contract_market_code='{code}' AND report_date_as_yyyy_mm_dd <= '{as_of}T23:59:59'",
        "$order": "report_date_as_yyyy_mm_dd DESC", "$limit": str(settings.COT_WEEKS)})
    out = []
    for r in rows:
        long_, short = float(r.get("noncomm_positions_long_all", 0)), float(r.get("noncomm_positions_short_all", 0))
        out.append({"date": r["report_date_as_yyyy_mm_dd"][:10], "market": r.get("market_and_exchange_names", ""),
                    "long": long_, "short": short, "net": long_ - short,
                    "open_interest": float(r.get("open_interest_all", 0) or 0)})
    return out


def render(asset: str, as_of: str) -> list[str]:
    code = settings.COT_CODES.get(asset)
    if not code:
        return []
    try:
        rows = weeks(code, as_of)
    except Exception as error:
        return [f"### Speculator positioning ({asset} futures, CFTC)", f"Unavailable: {type(error).__name__}"]
    if not rows:
        return [f"### Speculator positioning ({asset} futures, CFTC)", "No report found."]
    lines = [f"### Speculator positioning: {rows[0]['market']} (CFTC Commitments of Traders)",
             "Large speculators' futures contracts. Net = long minus short; a rising net means they are adding longs.",
             "| Report date | Long | Short | Net | Net % of open interest |", "|---|---|---|---|---|"]
    for r in rows:
        share = r["net"] / r["open_interest"] * 100 if r["open_interest"] else 0.0
        lines.append(f"| {r['date']} | {r['long']:,.0f} | {r['short']:,.0f} | {r['net']:+,.0f} | {share:+.1f}% |")
    return lines
