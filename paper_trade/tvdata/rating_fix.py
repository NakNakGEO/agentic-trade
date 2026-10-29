"""Read a rating written as a heading with the value on the next line, or as a lone word that opens the answer.

The framework reads only "Rating: Sell" on one line, so a Portfolio Manager that writes "## Rating" and then "**Sell**" on the
next line, or opens with just "**Hold**" and then its summary, is logged as REVIEW (unreadable) and its decision is lost,
although it plainly says what it decided. Qwen does this now and then (a lone "**Hold**" lost a real test call).
This adds those two shapes, and only when the framework found no rating, so everything it already reads is read exactly as
before. A heading that merely introduces the scale ("Rating Scale") is not a rating line.
"""

from __future__ import annotations

import re
import unicodedata

from tradingagents.agents import rating

_QUALIFIER = r"(?:(?:final|our|overall|my|recommended|updated|revised|new|current)\s+)*"
_HEADING = re.compile(r"^[\s*_#>\-]*" + _QUALIFIER + r"rating[\s*_:#\-]*$", re.IGNORECASE)
_VALUE = re.compile(r"^[\s*_#>\-]*(\w+)")


def heading_rating(text: str) -> str | None:
    """The 5-tier rating named on the line after a lone "Rating" heading, or None (several differing ones are no call)."""
    lines = [line for line in unicodedata.normalize("NFKC", text or "").splitlines() if line.strip()]
    found = []
    for line, following in zip(lines, lines[1:]):
        value = _VALUE.match(following) if _HEADING.match(line) else None
        if value and value.group(1).lower() in rating._RATING_SET:
            found.append(value.group(1).capitalize())
    return found[0] if found and len(set(found)) == 1 else None


_LONE_WORD = re.compile(r"^[\s*_#>\-]*(\w+)[\s*_.:#\-]*$")


def lone_rating(text: str) -> str | None:
    """The 5-tier rating when the answer opens with nothing but that word on its own line ("**Hold**" then the summary)."""
    lines = [line for line in unicodedata.normalize("NFKC", text or "").splitlines() if line.strip()]
    word = _LONE_WORD.match(lines[0]) if lines else None
    return word.group(1).capitalize() if word and word.group(1).lower() in rating._RATING_SET else None


def install() -> None:
    """Make the framework's rating reader accept heading-style ratings (safe to call more than once)."""
    original = rating.extract_rating
    if getattr(original, "heading_aware", False):
        return

    def extract_rating(text: str) -> str | None:
        return original(text) or heading_rating(text) or lone_rating(text)

    extract_rating.heading_aware = True
    rating.extract_rating = extract_rating
