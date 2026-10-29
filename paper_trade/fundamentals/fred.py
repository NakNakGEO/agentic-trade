"""Latest readings of FRED macro series (St. Louis Fed), as of a date, cached in the shared web cache."""

from __future__ import annotations

import os
from datetime import datetime, timedelta

from paper_trade import webcache
from paper_trade.fundamentals import settings


def _key() -> str:
    key = os.getenv("FRED_API_KEY", "").strip()
    if not key:
        raise RuntimeError("FRED_API_KEY is not set")
    return key


def observations(series: str, as_of: str, years: int = 2) -> list[tuple[str, float]]:
    """(date, value) pairs dated on or before ``as_of`` over ``years`` years, oldest first; missing values dropped."""
    start = (datetime.strptime(as_of, "%Y-%m-%d") - timedelta(days=366 * years)).strftime("%Y-%m-%d")
    body = webcache.get(settings.FRED_URL, settings.FRED_TTL, secret_params=("api_key",), params={
        "series_id": series, "api_key": _key(), "file_type": "json", "observation_start": start,
        "observation_end": as_of})
    rows = []
    for item in body.get("observations", []):
        try:
            rows.append((item["date"], float(item["value"])))
        except (KeyError, ValueError):          # FRED marks a missing reading with "."
            continue
    return rows


def reading(series: str, label: str, mode: str, as_of: str) -> dict | None:
    """{label, value, date, previous, series} for the latest reading, or None when there is none recent enough.

    ``mode="yoy"`` turns an index level (CPI) into its change over a year, in percent."""
    rows = observations(series, as_of)
    if mode == "yoy":
        by_date = dict(rows)
        rows = [(d, (v / by_date[f"{int(d[:4]) - 1}{d[4:]}"] - 1) * 100) for d, v in rows
                if f"{int(d[:4]) - 1}{d[4:]}" in by_date]
    if not rows:
        return None
    date, value = rows[-1]
    if datetime.strptime(as_of, "%Y-%m-%d") - datetime.strptime(date, "%Y-%m-%d") > timedelta(days=settings.FRED_STALE_DAYS):
        return None
    return {"label": label, "value": value, "date": date, "previous": rows[-2][1] if len(rows) > 1 else None,
            "series": series}


def currency_table(currency: str, as_of: str) -> list[dict]:
    out = []
    for series, label, mode in settings.FRED_SERIES.get(currency, []):
        try:
            found = reading(series, label, mode, as_of)
        except Exception as error:               # one series failing must not hide the rest
            found = {"label": label, "error": f"{type(error).__name__}", "series": series}
        if found:
            out.append(found)
    return out


def render(rows: list[dict], title: str) -> list[str]:
    lines = [f"### {title}", "| Reading | Latest | Previous | As of | FRED series |", "|---|---|---|---|---|"]
    for r in rows:
        if "error" in r:
            lines.append(f"| {r['label']} | unavailable ({r['error']}) | | | {r['series']} |")
        else:
            previous = f"{r['previous']:.2f}" if r["previous"] is not None else "n/a"
            lines.append(f"| {r['label']} | {r['value']:.2f} | {previous} | {r['date']} | {r['series']} |")
    return lines if rows else [f"### {title}", "No recent FRED readings."]
