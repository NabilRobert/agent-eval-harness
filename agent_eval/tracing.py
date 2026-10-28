"""Sends a trace of each trial to an OpenTelemetry viewer, if one is
configured (ADR-012). The MCP SDK already opens a client span for every
request the agent sends ("MCP send tools/call run_query") and puts the
trace context into the request's `_meta`, so the server's spans join the
same trace. This file installs the exporter that sends those spans
somewhere, and gives each trial one parent span, so all of a trial's MCP
calls share one trace instead of each starting its own.

Off unless OTEL_EXPORTER_OTLP_ENDPOINT (or the traces-only variant) is
set: then nothing is installed and every span is a no-op. A dead viewer
only loses spans; it never fails or slows a run by more than the capped
shutdown. No content goes into the spans this file opens: no prompts,
answers or tool arguments, only names, ids and the model (the conventions
in agent-observability's docs/conventions.md, rule 5).

`build_span_processor` and `shutdown_tracing` are MCP-backbone's
(app/tracing.py at 5f38bd2), copied because MCP-backbone is a server, not
a package this harness can depend on."""

import os
import threading
from collections.abc import Generator, Mapping
from contextlib import contextmanager

from inspect_ai.solver import Generate, Solver, TaskState, solver
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import SpanProcessor, TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import Span, StatusCode

SERVICE_NAME = "agent-eval-harness"

# Until a provider is installed this hands out no-op spans, so the solver
# below can open spans unconditionally.
tracer = trace.get_tracer(SERVICE_NAME)

# A dead viewer held up MCP-backbone's shutdown for 6.5 s with the
# exporter's default timeout (10 s plus retries); 2 s keeps it to about
# 1 s per batch, and the shutdown as a whole is capped at 2 s too.
DEFAULT_EXPORT_TIMEOUT_SECONDS = 2.0
SHUTDOWN_TIMEOUT_SECONDS = 2.0

# Inspect's OpenAI-compatible route ("openai-api/<service>/<model>") speaks
# OpenAI's API, so that's the provider the GenAI conventions name.
OPENAI_COMPATIBLE_PREFIX = "openai-api/"


def build_span_processor(env: Mapping[str, str] = os.environ) -> SpanProcessor | None:
    """The background exporter to install, or None when no endpoint is
    configured. Endpoint and timeout come from `env`, read the way the
    SDK reads the standard variables: the traces-only endpoint as given,
    the general one with /v1/traces added, and the timeout in seconds."""
    if env.get("OTEL_SDK_DISABLED", "").strip().lower() == "true":
        return None
    base = env.get("OTEL_EXPORTER_OTLP_ENDPOINT", "")
    endpoint = env.get("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT") or (
        f"{base.rstrip('/')}/v1/traces" if base else ""
    )
    if not endpoint:
        return None
    timeout = env.get("OTEL_EXPORTER_OTLP_TRACES_TIMEOUT") or env.get("OTEL_EXPORTER_OTLP_TIMEOUT")
    return BatchSpanProcessor(
        OTLPSpanExporter(
            endpoint=endpoint,
            timeout=float(timeout) if timeout else DEFAULT_EXPORT_TIMEOUT_SECONDS,
        )
    )


def configure_tracing(
    service_version: str, env: Mapping[str, str] = os.environ
) -> TracerProvider | None:
    """Installs the global tracer provider when an endpoint is configured,
    and returns it so the caller can flush it at the end. Returns None,
    installing nothing, when there's no endpoint."""
    processor = build_span_processor(env)
    if processor is None:
        return None
    resource = Resource.create(
        {
            "service.name": env.get("OTEL_SERVICE_NAME") or SERVICE_NAME,
            "service.version": service_version,
        }
    )
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(processor)
    trace.set_tracer_provider(provider)
    return provider


def shutdown_tracing(
    provider: TracerProvider, timeout_seconds: float = SHUTDOWN_TIMEOUT_SECONDS
) -> bool:
    """Flushes what's still queued and stops the exporter, waiting at most
    `timeout_seconds`, so a dead viewer can't hold up the end of a run.
    The SDK's own shutdown has no useful overall limit, so it runs in a
    daemon thread; spans still queued when time runs out are lost, which
    is acceptable: traces are a view, the run records are the evidence.
    Returns whether the flush finished in time."""
    flusher = threading.Thread(target=provider.shutdown, name="tracing-shutdown", daemon=True)
    flusher.start()
    flusher.join(timeout_seconds)
    if flusher.is_alive():
        print(f"note: tracing gave up flushing spans after {timeout_seconds:.0f} s")
        return False
    return True


@contextmanager
def tracing_if_configured(service_version: str) -> Generator[None]:
    """Tracing for the length of a run: installed on entry when an
    endpoint is set, flushed on exit. Does nothing otherwise."""
    provider = configure_tracing(service_version)
    try:
        yield
    finally:
        if provider is not None:
            shutdown_tracing(provider)


def provider_name(model: str) -> str:
    """`gen_ai.provider.name` for an Inspect model id: `openai` for the
    OpenAI-compatible route, otherwise Inspect's provider prefix
    (`openai`, `anthropic`, `mockllm`, ...)."""
    if model.startswith(OPENAI_COMPATIBLE_PREFIX):
        return "openai"
    return model.split("/", 1)[0]


def request_model(model: str) -> str:
    """`gen_ai.request.model`: the model's own name, without the route."""
    return model.rsplit("/", 1)[-1]


def _mark_failed(span: Span, exc: Exception) -> None:
    """Records only the exception's class: its message can quote a
    prompt or a tool result, which is content."""
    span.set_attribute("error.type", type(exc).__qualname__)
    span.set_status(StatusCode.ERROR)


@solver
def traced_agent(agent: Solver, task_name: str, agent_name: str) -> Solver:
    """Runs `agent` inside two spans per trial: `eval sample {id}`, named
    as agent-observability's replay of this harness's logs names it, and
    `invoke_agent {agent_name}` under it, the GenAI conventions' agent
    span. Every MCP call the agent makes becomes a child of the second."""

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        model = str(state.model)
        sample_attributes = {
            "inspect.task": task_name,
            "inspect.sample.id": str(state.sample_id),
            "inspect.epoch": state.epoch,
            "inspect.model": model,
            "gen_ai.provider.name": provider_name(model),
            "gen_ai.request.model": request_model(model),
        }
        with (
            tracer.start_as_current_span(
                f"eval sample {state.sample_id}",
                attributes=sample_attributes,
                record_exception=False,
                set_status_on_exception=False,
            ) as sample_span,
            tracer.start_as_current_span(
                f"invoke_agent {agent_name}",
                attributes={
                    "gen_ai.operation.name": "invoke_agent",
                    "gen_ai.agent.name": agent_name,
                },
                record_exception=False,
                set_status_on_exception=False,
            ) as agent_span,
        ):
            try:
                return await agent(state, generate)
            # Exception, not BaseException: a cancelled trial isn't a failure.
            except Exception as exc:
                _mark_failed(agent_span, exc)
                _mark_failed(sample_span, exc)
                raise

    return solve
