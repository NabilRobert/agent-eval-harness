"""Local models through Ollama (Inspect's `ollama/<model>`), run at the
settings sql-analyst-env's baselines use, so the accuracy benchmark's
local rows are comparable with them (MCP-backbone's
accuracy-benchmark-plan.md, D4, D6 and step 1c). The values are copied
from sql-analyst-env's analyst_env/baselines.py (branch feat/baselines,
2026-11-04), with that file's reasons.

Ollama's OpenAI-compatible API can't set the context per request, so the
server must be started with it, and `served_model_info` checks what the
server actually gives the model before a run, and records it."""

import os
from typing import Any

import httpx

PREFIX = "ollama/"
# Room for a full rollout plus a capped reply: sql-analyst-env measured a
# 14,271-token prompt by turn 16, so 16,384 was too tight.
CONTEXT_LENGTH = 24576
# Without a cap, a looping reply runs on (one rollout wrote 163,840 tokens
# over 2.5 hours); 4,096 is about twice the longest normal reply.
MAX_REPLY_TOKENS = 4096
SERVE_COMMAND = f"OLLAMA_CONTEXT_LENGTH={CONTEXT_LENGTH} OLLAMA_NUM_PARALLEL=1 ollama serve"
DEFAULT_SERVER = "http://127.0.0.1:11434"
# A first load reads the model from disk; generous so a cold start isn't an error.
SERVER_TIMEOUT_S = 300

# Each model's own recommended sampling, sent with every request, and where
# it comes from. Only the benchmark's model is listed: Arthur chose
# qwen3.5:4b alone (2026-11-05).
SAMPLING: dict[str, tuple[dict[str, float], str]] = {
    "qwen3.5:4b": (
        {"temperature": 1.0, "top_p": 0.95, "presence_penalty": 1.5},
        "Qwen3.5 model card, thinking mode, general tasks",
    ),
}


class OllamaError(Exception):
    """A local model can't run as the benchmark needs. Exit 2, nothing run."""


def is_ollama(model: str) -> bool:
    return model.startswith(PREFIX)


def generation_settings(model: str) -> dict[str, float]:
    """Inspect generation settings for this model: an Ollama model's sampling
    and reply cap; nothing for other providers, so their runs stay as
    published."""
    if not is_ollama(model):
        return {}
    name = model.removeprefix(PREFIX)
    if name not in SAMPLING:
        raise OllamaError(
            f"no sampling settings for {model}: add its model card's settings to "
            "agent_eval/ollama.py: SAMPLING (and ask Arthur before pulling a new model)"
        )
    sampling, _source = SAMPLING[name]
    return {**sampling, "max_tokens": MAX_REPLY_TOKENS}


def server_url() -> str:
    """Where Inspect will reach Ollama: OLLAMA_BASE_URL without its /v1."""
    return os.environ.get("OLLAMA_BASE_URL", DEFAULT_SERVER).removesuffix("/").removesuffix("/v1")


def _get(client: httpx.Client, path: str) -> dict[str, Any]:
    return client.get(path).raise_for_status().json()


def _post(client: httpx.Client, path: str, body: dict[str, Any]) -> dict[str, Any]:
    return client.post(path, json=body).raise_for_status().json()


def served_model_info(model: str, client: httpx.Client) -> dict[str, Any]:
    """What Ollama serves under this name, for the run's provenance. Loads
    the model first (no prompt, so nothing is generated) so the context
    it's given can be read back and checked."""
    name = model.removeprefix(PREFIX)
    try:
        show = _post(client, "/api/show", {"model": name})
        _post(client, "/api/generate", {"model": name})
        loaded = _get(client, "/api/ps")["models"]
        tags = _get(client, "/api/tags")["models"]
        version = _get(client, "/api/version")["version"]
    except httpx.HTTPError as exc:
        raise OllamaError(f"couldn't ask Ollama about {name} ({exc}); is Ollama running?") from exc
    context = next(int(m["context_length"]) for m in loaded if m["name"] == name)
    if context != CONTEXT_LENGTH:
        raise OllamaError(
            f"Ollama gives {name} a {context}-token context, not {CONTEXT_LENGTH}: "
            f"restart it as `{SERVE_COMMAND}`"
        )
    details = show["details"]
    return {
        "name": name,
        "digest": next(t["digest"] for t in tags if t["name"] == name),
        "format": details["format"],
        "quantization": details["quantization_level"],
        "parameter_size": details["parameter_size"],
        "runtime": f"Ollama {version}",
        "context_length": context,
        "packaged_parameters": show.get("parameters", ""),
        "sampling_source": SAMPLING[name][1] if name in SAMPLING else None,
    }
