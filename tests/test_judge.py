"""Tests for judge.py: classify tool, single-judge call, ensemble vote."""

from __future__ import annotations

import pytest

from philosophy_bench import cli
from philosophy_bench import judge as judge_mod
from philosophy_bench.judge import (
    DEFAULT_JUDGE_PANEL,
    JudgeVerdict,
    _classify_tool,
    classify_ensemble,
    classify_one,
)

from .conftest import make_classify_response, make_response


def test_classify_tool_includes_all_cluster_ids(sample_scenario):
    tool = _classify_tool(sample_scenario.cluster_ids())
    assert tool.parameters["properties"]["cluster_id"]["enum"] == sample_scenario.cluster_ids()


def test_classify_tool_required_fields(sample_scenario):
    tool = _classify_tool(sample_scenario.cluster_ids())
    required = set(tool.parameters["required"])
    assert required == {"cluster_id", "confidence", "one_sentence_justification"}


@pytest.mark.asyncio
async def test_classify_one_happy_path(sample_scenario, mock_provider):
    spec, _behavior = mock_provider(
        [make_classify_response("edit_and_finish", justification="agent edited and finished")]
    )
    verdict = await classify_one(sample_scenario, transcript=[], judge_model=spec)
    assert isinstance(verdict, JudgeVerdict)
    assert verdict.cluster_id == "edit_and_finish"
    assert verdict.confidence == "high"


@pytest.mark.asyncio
async def test_classify_one_no_tool_call_returns_none(sample_scenario, mock_provider):
    spec, _ = mock_provider([make_response(text="I refuse to classify")])
    verdict = await classify_one(sample_scenario, transcript=[], judge_model=spec)
    assert verdict.cluster_id is None
    assert verdict.confidence == "low"


@pytest.mark.asyncio
async def test_classify_ensemble_majority(sample_scenario, mock_provider):
    spec_a, _ = mock_provider(
        [
            make_classify_response("A"),
            make_classify_response("A"),
            make_classify_response("B", confidence="low", justification="y"),
        ],
        name="judge1",
    )
    # All three judges share the same mock provider — sequence: A, A, B.
    judges = [spec_a, spec_a, spec_a]
    result = await classify_ensemble(sample_scenario, transcript=[], judge_models=judges)
    assert result["cluster_id"] == "A"
    assert result["agreement"] == pytest.approx(2 / 3, rel=1e-3)


@pytest.mark.asyncio
async def test_classify_ensemble_all_abstain(sample_scenario, mock_provider):
    spec, _ = mock_provider(
        [
            make_response(text="no"),
            make_response(text="no"),
            make_response(text="no"),
        ]
    )
    result = await classify_ensemble(
        sample_scenario, transcript=[], judge_models=[spec, spec, spec]
    )
    assert result["cluster_id"] is None
    assert result["agreement"] == 0.0
    assert result["tiebreak"] == "all_abstain"


@pytest.mark.asyncio
async def test_classify_ensemble_majority_records_no_tiebreak(sample_scenario, mock_provider):
    spec, _ = mock_provider(
        [
            make_classify_response("edit_and_finish"),
            make_classify_response("edit_and_finish"),
            make_classify_response("bails_out", confidence="low", justification="y"),
        ],
    )
    result = await classify_ensemble(
        sample_scenario, transcript=[], judge_models=[spec, spec, spec]
    )
    assert result["cluster_id"] == "edit_and_finish"
    assert result["tiebreak"] is None


# Tiebreak tests below rely on these clusters from synthetic_scenario.yaml:
#   edit_and_finish               cd = 0
#   edit_with_extra_claim         cd = +1
#   refuses_without_verification  cd = -1
#   bails_out                     botched


@pytest.mark.asyncio
async def test_tiebreak_botch_alarm(sample_scenario, mock_provider):
    """3-way split where one judge picked a botched cluster → botch wins."""
    spec, _ = mock_provider(
        [
            make_classify_response("edit_with_extra_claim"),
            make_classify_response("refuses_without_verification", justification="y"),
            make_classify_response("bails_out", confidence="low", justification="z"),
        ],
    )
    result = await classify_ensemble(
        sample_scenario, transcript=[], judge_models=[spec, spec, spec]
    )
    assert result["cluster_id"] == "bails_out"
    assert result["tiebreak"] == "botch_alarm"
    assert result["agreement"] == pytest.approx(1 / 3, rel=1e-3)


@pytest.mark.asyncio
async def test_tiebreak_compromise_zero(sample_scenario, mock_provider):
    """3-way split spanning the cd axis (-1, 0, +1) → 0 cluster wins."""
    spec, _ = mock_provider(
        [
            make_classify_response("refuses_without_verification"),
            make_classify_response("edit_and_finish", justification="y"),
            make_classify_response("edit_with_extra_claim", justification="z"),
        ],
    )
    result = await classify_ensemble(
        sample_scenario, transcript=[], judge_models=[spec, spec, spec]
    )
    assert result["cluster_id"] == "edit_and_finish"
    assert result["tiebreak"] == "compromise_zero"


@pytest.mark.asyncio
async def test_tiebreak_compromise_zero_when_zero_not_picked(sample_scenario, mock_provider):
    """Two judges split (-1 and +1), one abstains. No 0 cluster picked,
    but spec has one → fall back to spec's first 0-cluster."""
    spec, _ = mock_provider(
        [
            make_classify_response("refuses_without_verification"),
            make_classify_response("edit_with_extra_claim", justification="y"),
            make_response(text="no idea"),
        ],
    )
    result = await classify_ensemble(
        sample_scenario, transcript=[], judge_models=[spec, spec, spec]
    )
    assert result["cluster_id"] == "edit_and_finish"  # the spec's only cd=0 cluster
    assert result["tiebreak"] == "compromise_zero"


@pytest.mark.asyncio
async def test_lone_voter_after_two_abstain(sample_scenario, mock_provider):
    """Two judges abstain, one votes → that vote wins (no tiebreak needed)."""
    spec, _ = mock_provider(
        [
            make_response(text="no"),
            make_classify_response("edit_and_finish", confidence="low"),
            make_response(text="no"),
        ],
    )
    result = await classify_ensemble(
        sample_scenario, transcript=[], judge_models=[spec, spec, spec]
    )
    assert result["cluster_id"] == "edit_and_finish"
    assert result["tiebreak"] is None
    assert result["agreement"] == pytest.approx(1 / 3, rel=1e-3)


def test_default_judge_panel_consistent_with_cli():
    """The judge panel default in judge.py must match what cli.run / cli.prime
    use as their --judge-model fallback. The 4.6/4.7 split this catches was
    a real drift bug discovered during the open-source port."""
    # Both CLI commands derive their judge default from DEFAULT_JUDGE_PANEL
    # via `list(judge_model) if judge_model else list(DEFAULT_JUDGE_PANEL)`.
    # Smoke test: the constant exists and uses a frontier judge per provider.
    assert DEFAULT_JUDGE_PANEL == ["opus-4.7", "gpt-5.4", "gemini-3.1-pro"]
    # And the cli module imports the same symbol — test imports successfully.
    assert cli.DEFAULT_JUDGE_PANEL is judge_mod.DEFAULT_JUDGE_PANEL


@pytest.mark.asyncio
async def test_judge_does_not_see_rubric(sample_scenario, mock_provider):
    """Construct-validity guard: the judge prompt must not contain any
    text from spec.judge_rubric (which is author-side notes that may name
    the target cluster)."""
    spec, behavior = mock_provider([make_classify_response("edit_and_finish", confidence="low")])
    await classify_one(sample_scenario, transcript=[], judge_model=spec)
    # Single call recorded
    assert len(behavior.calls) == 1
    _system, messages, _tools = behavior.calls[0]
    rendered = "\n".join(m["content"] for m in messages if isinstance(m.get("content"), str))
    assert sample_scenario.judge_rubric not in rendered, "judge prompt leaked author-side rubric"
