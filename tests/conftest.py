"""Shared pytest fixtures.

Notable: the `mock_provider` fixture installs a fake provider into the
package-level `_PROVIDER_CALLERS` dispatch dict. This keeps "mock" out of
the production registry while letting tests drive the runner end-to-end
without API keys."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from philosophy_bench import providers
from philosophy_bench.engine import ScenarioSpec, load_all_scenarios, load_scenario
from philosophy_bench.paths import DEFAULT_SCENARIO_ROOT
from philosophy_bench.providers import GenericTool, ModelResponse, ModelSpec

FIXTURES_DIR = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# Scenario fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_scenario() -> ScenarioSpec:
    """The synthetic scenario in tests/fixtures/synthetic_scenario.yaml."""
    return load_scenario(FIXTURES_DIR / "synthetic_scenario.yaml")


@pytest.fixture(scope="session")
def all_scenarios() -> list[ScenarioSpec]:
    """Every scenario in the bundled corpus, loaded once per session."""
    return load_all_scenarios(DEFAULT_SCENARIO_ROOT)


# ---------------------------------------------------------------------------
# Mock provider — drives the runner without an API key
# ---------------------------------------------------------------------------


class MockBehavior:
    """Scripted responses for the mock provider.

    Build with a list of `ModelResponse` objects; each call to the provider
    pops the next one. Tests can also pass callables that receive
    (system, messages, tools) for assertions about what was sent.
    """

    def __init__(self, responses: list):
        self._responses = list(responses)
        self.calls: list[tuple[str, list, list]] = []

    async def __call__(self, spec, system, messages, tools):
        self.calls.append((system, list(messages), list(tools)))
        if not self._responses:
            return ModelResponse(
                tool_calls=[], text="(no scripted response)", thinking="", raw_assistant=None
            )
        nxt = self._responses.pop(0)
        if callable(nxt):
            return (
                await nxt(spec, system, messages, tools)
                if hasattr(nxt, "__await__")
                else nxt(spec, system, messages, tools)
            )
        return nxt


@pytest.fixture
def mock_provider(monkeypatch) -> Iterator[callable]:
    """Returns a factory: pass scripted ModelResponse list, get a ModelSpec
    that will be dispatched through the mock provider."""

    installed: list[MockBehavior] = []

    def _make(responses, name: str = "mock-test", model_id: str = "mock-id"):
        behavior = MockBehavior(responses)
        installed.append(behavior)

        async def caller(spec, system, messages, tools):
            return await behavior(spec, system, messages, tools)

        # Install into the dispatch dict; remove after the test
        monkeypatch.setitem(providers._PROVIDER_CALLERS, "mock", caller)
        spec = ModelSpec(name=name, provider="mock", model_id=model_id)
        return spec, behavior

    yield _make

    # monkeypatch unwinds providers._PROVIDER_CALLERS automatically.


# ---------------------------------------------------------------------------
# Convenience helpers for building tool calls in tests
# ---------------------------------------------------------------------------


def make_response(
    *, text: str = "", thinking: str = "", tool_calls: list | None = None, raw_assistant=None
) -> ModelResponse:
    return ModelResponse(
        tool_calls=tool_calls or [],
        text=text,
        thinking=thinking,
        raw_assistant=raw_assistant or [],
    )


def make_tool_call(name: str, args: dict, call_id: str = "tc1") -> dict:
    return {"name": name, "args": args, "id": call_id}


def make_classify_response(
    cluster_id: str,
    confidence: str = "high",
    justification: str = "x",
) -> ModelResponse:
    """Build a ModelResponse containing a single `classify` tool call."""
    return make_response(
        tool_calls=[
            make_tool_call(
                "classify",
                {
                    "cluster_id": cluster_id,
                    "confidence": confidence,
                    "one_sentence_justification": justification,
                },
            )
        ]
    )


__all__ = [
    "FIXTURES_DIR",
    "GenericTool",
    "ModelResponse",
    "ModelSpec",
    "make_classify_response",
    "make_response",
    "make_tool_call",
]
