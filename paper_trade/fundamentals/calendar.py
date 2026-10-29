"""This week's scheduled economic releases (ForexFactory's weekly calendar feed), filtered to some currencies."""

from __future__ import annotations

from datetime import datetime, timezone

from paper_trade import webcache
from paper_trade.fundamentals import settings


def events(currencies: list[str], impacts: tuple[str, ...] = settings.CALENDAR_IMPACTS) -> list[dict]:
    """[{when (UTC datetime), currency, title, impact, forecast, previous}] for the week, soonest first."""
    out = []
    for item in webcache.get(settings.CALENDAR_URL, settings.CALENDAR_TTL):
        if item.get("country") not in currencies or item.get("impact") not in impacts:
            continue
        try:
            when = datetime.fromisoformat(item["date"]).astimezone(timezone.utc)
        except (KeyError, ValueError):
            continue
        out.append({"when": when, "currency": item["country"], "title": item.get("title", ""),
                    "impact": item["impact"], "forecast": item.get("forecast") or "", "previous": item.get("previous") or ""})
    return sorted(out, key=lambda e: e["when"])


def render(currencies: list[str], now: datetime | None = None) -> list[str]:
    now = now or datetime.now(timezone.utc)
    try:
        found = events(currencies)
    except Exception as error:
        return ["### Economic calendar this week", f"Unavailable: {type(error).__name__}"]
    title = f"### Economic calendar this week ({', '.join(currencies)}; high and medium impact, ForexFactory)"
    if not found:
        return [title, "No high or medium impact releases scheduled."]
    lines = [title, "| When (UTC) | Currency | Release | Impact | Forecast | Previous | Status |", "|---|---|---|---|---|---|---|"]
    for e in found:
        status = "already out" if e["when"] < now else "upcoming"
        lines.append(f"| {e['when']:%a %d %b %H:%M} | {e['currency']} | {e['title']} | {e['impact']} | "
                     f"{e['forecast']} | {e['previous']} | {status} |")
    return lines
