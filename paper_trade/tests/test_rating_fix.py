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


QWEN_LONE_WORD = """

**Hold**

**Executive Summary**

Do not open a short on AUDUSD at the current live price this cycle. The bias is bearish, but the entry is compromised.
"""


def test_a_lone_rating_word_that_opens_the_answer_is_read(patched):
    assert rating.parse_rating(QWEN_LONE_WORD) == "Hold"
    assert rating.parse_rating("Sell\n\nBecause the trend is down.") == "Sell"
    assert rating.parse_rating("## **Underweight**\n\nThe summary.") == "Underweight"


def test_a_word_that_is_not_alone_on_the_first_line_is_not_a_call(patched):
    assert rating.parse_rating("Hold the line on costs.\n\nSell later.") == "REVIEW"
    assert rating.parse_rating("The call is below.\n\n**Hold**") == "REVIEW"            # only the opening line counts
    assert rating.parse_rating("**Hold** or sell, the desk is split.") == "REVIEW"
    assert rating.parse_rating("**Rating**: Buy\n\n**Hold**") == "Buy"                  # the framework's own reading still comes first
