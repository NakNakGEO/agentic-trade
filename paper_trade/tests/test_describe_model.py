from paper_trade.dashboard.state import describe_model


def test_runs_without_a_provider_are_local_ollama_runs():
    info = describe_model({"model": "ta-gemma12b", "thinking": False})      # older runs had no provider field
    assert info["local"] is True
    assert "your GPU" in info["provider_label"]
    assert info["monthly_tokens"] is None


def test_online_api_run_is_labelled_by_provider_and_has_its_free_allowance():
    info = describe_model({"provider": "openai_compatible", "backend_url": "https://api.iteracompute.com/v1",
                           "model": "qwen/qwen3.8-27b", "thinking": False})
    assert info["local"] is False
    assert info["provider_label"] == "IteraCompute (online API)"
    assert info["monthly_tokens"] == 30_000_000
    assert info["model"] == "qwen/qwen3.8-27b"


def test_unknown_online_endpoint_is_still_not_called_local():
    info = describe_model({"provider": "groq", "model": "m"})
    assert info["local"] is False
    assert "groq" in info["provider_label"]
    assert info["monthly_tokens"] is None
