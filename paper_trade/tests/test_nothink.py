import pytest

from paper_trade.nothink import disable_thinking, set_reasoning_effort


@pytest.fixture
def clean_registry():
    from tradingagents.llm_clients import openai_client

    saved = dict(openai_client.OPENAI_COMPATIBLE_PROVIDERS)
    yield openai_client.OPENAI_COMPATIBLE_PROVIDERS
    openai_client.OPENAI_COMPATIBLE_PROVIDERS.clear()
    openai_client.OPENAI_COMPATIBLE_PROVIDERS.update(saved)


def _client(provider: str):
    from tradingagents.llm_clients.factory import create_llm_client

    return create_llm_client(provider, "some-model", base_url="http://localhost:9/v1").get_llm()


def test_qwen_style_endpoints_get_the_enable_thinking_false_field(clean_registry):
    assert disable_thinking("openai_compatible") is True
    assert _client("openai_compatible").extra_body == {"chat_template_kwargs": {"enable_thinking": False}}


def test_local_ollama_gets_reasoning_effort_none(clean_registry):
    assert disable_thinking("ollama") is True
    assert _client("ollama").extra_body == {"reasoning_effort": "none"}


def test_calling_twice_does_not_stack_wrappers(clean_registry):
    disable_thinking("openai_compatible")
    first = clean_registry["openai_compatible"].chat_class
    assert disable_thinking("openai_compatible") is True
    assert clean_registry["openai_compatible"].chat_class is first


def test_reasoning_effort_is_sent_as_an_extra_field_and_validated(clean_registry):
    assert set_reasoning_effort("openai_compatible", "medium") is True
    assert _client("openai_compatible").extra_body == {"reasoning_effort": "medium"}
    with pytest.raises(ValueError):
        set_reasoning_effort("openai_compatible", "maximum")
    assert set_reasoning_effort("not-a-provider", "low") is False


def test_other_providers_are_untouched_and_unknown_ones_report_false(clean_registry):
    before = clean_registry["groq"].chat_class
    assert disable_thinking("groq") is False
    assert disable_thinking("not-a-provider") is False
    assert clean_registry["groq"].chat_class is before
