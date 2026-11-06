"""Local models through Ollama, at sql-analyst-env's baseline settings
(step 1c of MCP-backbone's accuracy-benchmark-plan.md). No Ollama server
is needed: its API is faked with httpx's mock transport."""

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from agent_eval import REPO_ROOT
from agent_eval.budget import load_prices, price_for
from agent_eval.ollama import (
    CONTEXT_LENGTH,
    MAX_REPLY_TOKENS,
    SAMPLING,
    OllamaError,
    generation_settings,
    served_model_info,
)


def test_an_ollama_model_gets_its_model_card_sampling_and_the_reply_cap() -> None:
    assert generation_settings("ollama/qwen3.5:4b") == {
        "temperature": 1.0,
        "top_p": 0.95,
        "presence_penalty": 1.5,
        "max_tokens": MAX_REPLY_TOKENS,
    }


def test_an_ollama_model_without_settings_is_refused() -> None:
    with pytest.raises(OllamaError, match="no sampling settings for ollama/mistral"):
        generation_settings("ollama/mistral")


def test_other_models_keep_their_providers_defaults() -> None:
    """Every published run used the provider's defaults."""
    assert generation_settings("openai-api/sumopod/gpt-5-mini") == {}


def test_every_ollama_model_is_priced_at_zero_as_running_locally() -> None:
    prices = load_prices(REPO_ROOT / "prices.yaml")
    for name in SAMPLING:
        price = price_for(f"ollama/{name}", prices)
        assert price is not None, name
        assert (price["input"], price["output"], price["source"]) == (0, 0, "runs locally")


def _fake_ollama(context_length: int) -> httpx.Client:
    def handle(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/api/show":
            details = {"format": "gguf", "quantization_level": "Q4_K_M", "parameter_size": "4B"}
            return httpx.Response(200, json={"details": details, "parameters": "stop <x>"})
        if path == "/api/ps":
            loaded = {"name": "qwen3.5:4b", "context_length": context_length}
            return httpx.Response(200, json={"models": [loaded]})
        if path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "qwen3.5:4b", "digest": "d1"}]})
        if path == "/api/version":
            return httpx.Response(200, json={"version": "0.40.11"})
        assert path == "/api/generate" and json.loads(request.content) == {"model": "qwen3.5:4b"}
        return httpx.Response(200, json={"done": True})

    return httpx.Client(base_url="http://ollama", transport=httpx.MockTransport(handle))


def test_the_served_model_is_recorded_with_its_digest_and_context() -> None:
    info: dict[str, Any] = served_model_info("ollama/qwen3.5:4b", _fake_ollama(CONTEXT_LENGTH))
    assert info["digest"] == "d1"
    assert info["context_length"] == CONTEXT_LENGTH
    assert info["runtime"] == "Ollama 0.40.11"
    assert info["quantization"] == "Q4_K_M"


def test_a_server_with_the_wrong_context_says_how_to_restart_it() -> None:
    with pytest.raises(OllamaError, match="OLLAMA_CONTEXT_LENGTH=24576 OLLAMA_NUM_PARALLEL=1"):
        served_model_info("ollama/qwen3.5:4b", _fake_ollama(4096))


def test_no_ollama_server_says_so(tmp_path: Path) -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    client = httpx.Client(base_url="http://ollama", transport=httpx.MockTransport(refuse))
    with pytest.raises(OllamaError, match="is Ollama running"):
        served_model_info("ollama/qwen3.5:4b", client)
