"""What each model provider needs, so the harness isn't tied to Sumopod.

Inspect names models `<provider>/<model>`. Sumopod is reached through
Inspect's OpenAI-compatible route, `openai-api/sumopod/<model>`; anyone
reproducing the results with their own key uses their provider's route
instead (e.g. `openai/gpt-5-mini` with `OPENAI_API_KEY`)."""

from typing import Any

SUMOPOD_PREFIX = "openai-api/sumopod/"


def model_args_for(model: str) -> dict[str, Any]:
    """Inspect model arguments for this model. The OpenAI-compatible route
    sends tools in OpenAI strict mode by default, which MCP-backbone's
    optional `api_key` tool parameter broke (a 400 before any tokens were
    spent); the native OpenAI provider doesn't set strict mode at all, so
    it needs nothing.

    MCP-backbone fixed its schemas in 107b079, but strict mode stays off:
    every published run had it off, and strict mode constrains how the
    model writes tool calls, so turning it on would change the agent
    under test. The reproduction stack also pins a server from before
    the fix, which strict mode would reject."""
    return {"strict_tools": False} if model.startswith("openai-api/") else {}


def required_env(model: str) -> list[str]:
    """Variables the harness itself must have for this model. Other
    providers' keys (OPENAI_API_KEY, ANTHROPIC_API_KEY, ...) are read by
    Inspect from the environment; the harness only passes .env through."""
    return ["SUMOPOD_AI_API_KEY", "SUMOPOD_BASE_URL"] if model.startswith(SUMOPOD_PREFIX) else []


def is_secret_name(name: str) -> bool:
    """Env names whose values must never appear in run records."""
    upper = name.upper()
    return any(word in upper for word in ("KEY", "TOKEN", "SECRET", "PASSWORD"))
