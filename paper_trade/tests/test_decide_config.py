from paper_trade import config
from paper_trade.decide import build_config


def test_default_is_the_local_model_without_retry_changes():
    settings = build_config()
    assert settings["llm_provider"] == "ollama"
    assert settings["quick_think_llm"] == config.LLM_SETTINGS["quick_think_llm"]
    assert settings["llm_max_retries"] != config.HOSTED_LLM_RETRIES


def test_hosted_provider_overrides_models_and_raises_the_retry_budget():
    settings = build_config({"llm_provider": "groq", "quick_think_llm": "m-small",
                             "deep_think_llm": "m-big", "backend_url": None})
    assert (settings["llm_provider"], settings["quick_think_llm"], settings["deep_think_llm"]) == (
        "groq", "m-small", "m-big")
    assert settings["llm_max_retries"] == config.HOSTED_LLM_RETRIES
    assert settings["backend_url"] is None          # unset flags never clobber the defaults


def test_empty_flags_are_ignored():
    settings = build_config({"llm_provider": None, "quick_think_llm": "", "deep_think_llm": None})
    assert settings["llm_provider"] == "ollama"
    assert settings["quick_think_llm"] == config.LLM_SETTINGS["quick_think_llm"]
