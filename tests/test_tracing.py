"""Tracing (ADR-012), offline: the scripted Pagila agent against a stub MCP
server over stdio, real Inspect and its mock model, and an in-memory
exporter in place of a viewer. No network, no key, $0."""

import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from inspect_ai import Task
from inspect_ai import eval as inspect_eval  # pyright: ignore[reportUnknownVariableType]
from inspect_ai.dataset import Sample
from inspect_ai.solver import Generate, Solver, TaskState, solver
from inspect_ai.tool import mcp_server_stdio, mcp_tools
from opentelemetry import trace
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode
from scripted_pagila_agent import run_scripted

from agent_eval import tracing
from agent_eval.suites import load_suite
from agent_eval.targets import TARGETS

REPO = Path(__file__).resolve().parent.parent
STUB_SERVER = Path(__file__).resolve().parent / "stub_pagila_server.py"
PAGILA = REPO / "suites" / "pagila.yaml"
MCP_CLIENT_SPAN_PREFIX = "MCP send "

_EXPORTER = InMemorySpanExporter()


@pytest.fixture(scope="session", autouse=True)
def install_in_memory_tracing() -> None:
    """The global tracer provider can be set once per process, so one
    in-memory provider serves every test here."""
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(_EXPORTER))
    trace.set_tracer_provider(provider)


@pytest.fixture
def spans() -> Iterator[InMemorySpanExporter]:
    _EXPORTER.clear()
    yield _EXPORTER
    _EXPORTER.clear()


def stub_tools() -> list[Any]:
    server = mcp_server_stdio(name="stub-pagila", command=sys.executable, args=[str(STUB_SERVER)])
    return [mcp_tools(server)]


def run_pagila_tasks(task_ids: list[str]) -> list[dict[str, Any]]:
    suite = load_suite(PAGILA, task_ids)
    return run_scripted(suite, TARGETS["mcp-backbone"], "", tools_override=stub_tools())


def named(spans: tuple[ReadableSpan, ...], name: str) -> ReadableSpan:
    [span] = [s for s in spans if s.name == name]
    return span


def parent_id(span: ReadableSpan) -> int | None:
    return span.parent.span_id if span.parent else None


def span_id(span: ReadableSpan) -> int:
    assert span.context is not None
    return span.context.span_id


def trace_id(span: ReadableSpan) -> int:
    assert span.context is not None
    return span.context.trace_id


def test_scripted_pagila_agent_lists_tables_queries_and_passes(
    spans: InMemorySpanExporter,  # noqa: ARG001
) -> None:
    [trial] = run_pagila_tasks(["e01"])
    assert trial["outcome"] == "pass"
    assert [call["tool"] for call in trial["tool_calls"]][:2] == ["list_tables", "run_query"]


def test_one_trial_is_one_trace_with_its_mcp_calls_under_the_agent_span(
    spans: InMemorySpanExporter,
) -> None:
    run_pagila_tasks(["e01"])
    finished = spans.get_finished_spans()
    sample = named(finished, "eval sample e01")
    agent = named(finished, "invoke_agent react")
    mcp_calls = [s for s in finished if s.name.startswith(MCP_CLIENT_SPAN_PREFIX)]

    assert sample.parent is None
    assert parent_id(agent) == span_id(sample)
    assert {s.name for s in mcp_calls} >= {
        "MCP send tools/call list_tables",
        "MCP send tools/call run_query",
    }
    assert all(parent_id(s) == span_id(agent) for s in mcp_calls)
    assert {trace_id(s) for s in finished} == {trace_id(sample)}


def test_the_trace_context_reaches_the_server(spans: InMemorySpanExporter) -> None:
    [trial] = run_pagila_tasks(["e01"])
    query_span = named(spans.get_finished_spans(), "MCP send tools/call run_query")
    [grader] = trial["graders"]
    # The stub echoes the traceparent it received: version-trace-span-flags.
    traceparent = grader["input"]["graded_payload"]["traceparent"]
    _, received_trace_id, received_span_id, _ = traceparent.split("-")
    assert int(received_trace_id, 16) == trace_id(query_span)
    assert int(received_span_id, 16) == span_id(query_span)


def test_each_trial_gets_its_own_trace(spans: InMemorySpanExporter) -> None:
    run_pagila_tasks(["e01", "e02"])
    finished = spans.get_finished_spans()
    roots = [s for s in finished if s.parent is None]
    assert sorted(s.name for s in roots) == ["eval sample e01", "eval sample e02"]
    assert len({trace_id(s) for s in roots}) == 2


def test_sample_span_names_the_task_and_model(spans: InMemorySpanExporter) -> None:
    run_pagila_tasks(["e01"])
    attributes = dict(named(spans.get_finished_spans(), "eval sample e01").attributes or {})
    assert attributes == {
        "inspect.task": "pagila",
        "inspect.sample.id": "e01",
        "inspect.epoch": 1,
        "inspect.model": "mockllm/model",
        "gen_ai.provider.name": "mockllm",
        "gen_ai.request.model": "model",
    }


def test_spans_carry_no_prompt_query_or_answer(spans: InMemorySpanExporter) -> None:
    suite = load_suite(PAGILA, ["e01"])
    [task] = suite["tasks"]
    [trial] = run_pagila_tasks(["e01"])
    content = [task["prompt"], task["reference_sql"], trial["final_answer"]]
    for span in spans.get_finished_spans():
        recorded = [str(value) for value in (span.attributes or {}).values()]
        recorded += [str(event.attributes) for event in span.events]
        recorded.append(span.status.description or "")
        assert not any(text in value for text in content for value in recorded), span.name


@solver
def failing_agent() -> Solver:
    async def solve(state: TaskState, generate: Generate) -> TaskState:  # noqa: ARG001
        raise ValueError("a message that could quote the prompt")

    return solve


def test_a_failing_agent_is_marked_with_its_error_class_only(
    spans: InMemorySpanExporter, tmp_path: Path
) -> None:
    task = Task(
        dataset=[Sample(id="t1", input="a prompt")],
        solver=tracing.traced_agent(failing_agent(), task_name="offline", agent_name="react"),
    )
    inspect_eval(task, model="mockllm/model", log_dir=str(tmp_path), display="none")
    for name in ("eval sample t1", "invoke_agent react"):
        span = named(spans.get_finished_spans(), name)
        assert span.status.status_code == StatusCode.ERROR
        assert span.status.description is None
        assert (span.attributes or {})["error.type"] == "ValueError"
        assert not span.events


def test_without_an_endpoint_nothing_is_installed(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(provider: TracerProvider) -> None:
        raise AssertionError("a tracer provider was installed")

    monkeypatch.setattr(trace, "set_tracer_provider", refuse)
    assert tracing.build_span_processor({}) is None
    assert tracing.configure_tracing("abc123", env={}) is None


def test_disabling_the_sdk_wins_over_an_endpoint() -> None:
    env = {"OTEL_EXPORTER_OTLP_ENDPOINT": "http://localhost:4318", "OTEL_SDK_DISABLED": "true"}
    assert tracing.build_span_processor(env) is None


def test_with_an_endpoint_the_harness_is_named_and_versioned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    installed: list[TracerProvider] = []
    monkeypatch.setattr(trace, "set_tracer_provider", installed.append)
    provider = tracing.configure_tracing(
        "abc123", env={"OTEL_EXPORTER_OTLP_ENDPOINT": "http://localhost:4318"}
    )
    assert provider is not None
    assert installed == [provider]
    assert provider.resource.attributes["service.name"] == "agent-eval-harness"
    assert provider.resource.attributes["service.version"] == "abc123"
    provider.shutdown()


@pytest.mark.parametrize(
    ("model", "provider", "request_model"),
    [
        ("openai-api/sumopod/gpt-5-mini", "openai", "gpt-5-mini"),
        ("openai/gpt-5-mini", "openai", "gpt-5-mini"),
        ("anthropic/claude-sonnet-5-5", "anthropic", "claude-sonnet-5-5"),
    ],
)
def test_the_openai_compatible_route_is_named_openai(
    model: str, provider: str, request_model: str
) -> None:
    assert tracing.provider_name(model) == provider
    assert tracing.request_model(model) == request_model
