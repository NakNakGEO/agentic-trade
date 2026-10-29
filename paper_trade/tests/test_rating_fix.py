import pytest
from tradingagents.agents import rating

from paper_trade.tvdata import rating_fix

QWEN_STYLE = """

## Rating

**Sell**

## Executive Summary

The SELL on AUDUSD is confirmed, but only in a modified form.
"""


@pytest.fixture
def patched():
    saved = rating.extract_rating
    rating_fix.install()
    yield
    rating.extract_rating = saved


def test_the_framework_alone_cannot_read_a_heading_style_rating():
    assert rating.parse_rating(QWEN_STYLE) == "REVIEW"


def test_a_heading_style_rating_is_read_once_installed(patched):
    assert rating.parse_rating(QWEN_STYLE) == "Sell"
    assert rating.parse_rating("# Final Rating:\n\n- Underweight\n\nbecause...") == "Underweight"
    assert rating.parse_rating("## Rating\n\n**Hold**") == "Hold"


def test_what_the_framework_already_reads_is_read_the_same(patched):
    assert rating.parse_rating("**Rating**: Buy\n\nBecause the trend is up.") == "Buy"
    assert rating.parse_rating("- **Rating**: Overweight") == "Overweight"


def test_nothing_that_is_not_a_call_becomes_one(patched):
    assert rating.parse_rating("## Rating Scale\n\nBuy: strongest\nSell: weakest") == "REVIEW"
    assert rating.parse_rating("## Rating\n\nThe desk could not decide.") == "REVIEW"
    assert rating.parse_rating("## Rating\n\n**Sell**\n\n## Final Rating\n\n**Buy**") == "REVIEW"   # two different calls
    assert rating.parse_rating("") == "REVIEW"


def test_installing_twice_does_not_stack(patched):
    first = rating.extract_rating
    rating_fix.install()
    assert rating.extract_rating is first
