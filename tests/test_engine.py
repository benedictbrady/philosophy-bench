"""Tests for engine.py: scenario schema, loader, transcript builder."""

from __future__ import annotations

import textwrap

import pytest
from pydantic import ValidationError

from philosophy_bench.engine import (
    ScenarioSpec,
    UserTurn,
    build_transcript_for_judge,
    load_all_scenarios,
    load_scenario,
    should_fire_turn,
)
from philosophy_bench.paths import DEFAULT_SCENARIO_ROOT


def _write_yaml(tmp_path, content: str):
    p = tmp_path / "scn.yaml"
    p.write_text(textwrap.dedent(content))
    return p


def test_load_synthetic_scenario(sample_scenario):
    assert isinstance(sample_scenario, ScenarioSpec)
    assert sample_scenario.id == "synth-test-01"
    assert sample_scenario.chassis == "mock_repo"


def test_load_all_scenarios_smoke(all_scenarios):
    assert len(all_scenarios) == 100


def test_invalid_yaml_raises(tmp_path):
    p = _write_yaml(tmp_path, "this: is: not: valid: yaml:\n  - {")
    with pytest.raises(Exception):
        load_scenario(p)


def test_missing_required_field_raises(tmp_path):
    p = _write_yaml(
        tmp_path,
        """
        id: x
        category: honesty_under_pressure
        chassis: mock_repo
        # missing system_prompt, turns, hinge_description, response_clusters
    """,
    )
    with pytest.raises(ValueError):
        load_scenario(p)


def test_invalid_category_raises(tmp_path):
    p = _write_yaml(
        tmp_path,
        """
        id: x
        category: bogus_category
        chassis: mock_repo
        system_prompt: hi
        turns: [{content: hello}]
        hinge_description: t
        response_clusters:
          - {id: a, description: b, cd_score: 1, botched: false}
          - {id: c, description: d, cd_score: -1, botched: false}
    """,
    )
    with pytest.raises(ValueError):
        load_scenario(p)


def test_invalid_chassis_raises(tmp_path):
    p = _write_yaml(
        tmp_path,
        """
        id: x
        category: honesty_under_pressure
        chassis: not_a_real_chassis
        system_prompt: hi
        turns: [{content: hello}]
        hinge_description: t
        response_clusters:
          - {id: a, description: b, cd_score: 1, botched: false}
          - {id: c, description: d, cd_score: -1, botched: false}
    """,
    )
    with pytest.raises(ValueError):
        load_scenario(p)


def test_cd_score_out_of_range_raises():
    with pytest.raises(ValidationError):
        ScenarioSpec(
            id="x",
            category="honesty_under_pressure",
            chassis="mock_repo",
            system_prompt="hi",
            turns=[UserTurn(content="hi")],
            hinge_description="t",
            response_clusters=[{"id": "a", "description": "b", "cd_score": 2}],
        )


def test_legacy_cd_score_migrates_to_axis_score():
    spec = ScenarioSpec(
        id="x",
        category="honesty_under_pressure",
        chassis="mock_repo",
        system_prompt="hi",
        turns=[UserTurn(content="hi")],
        hinge_description="t",
        response_clusters=[{"id": "a", "description": "b", "cd_score": 1}],
    )
    cluster = spec.response_clusters[0]
    assert cluster.axis_score == 1
    assert cluster.cd_score == 1


def test_axis_score_loads_without_cd_score():
    spec = ScenarioSpec(
        id="x",
        category="honesty_under_pressure",
        chassis="mock_repo",
        system_prompt="hi",
        turns=[UserTurn(content="hi")],
        hinge_description="t",
        response_clusters=[{"id": "a", "description": "b", "axis_score": -1}],
    )
    cluster = spec.response_clusters[0]
    assert cluster.axis_score == -1
    assert cluster.cd_score == -1


def test_cluster_ids_method(sample_scenario):
    ids = sample_scenario.cluster_ids()
    assert ids == [c.id for c in sample_scenario.response_clusters]
    assert len(ids) == 4


def test_should_fire_turn_no_when():
    assert should_fire_turn(UserTurn(content="x"), [])


def test_should_fire_turn_always():
    assert should_fire_turn(UserTurn(content="x", when={"always": True}), [])


def test_should_fire_turn_requires_tool_present():
    t = UserTurn(content="x", when={"requires_tool": "edit"})
    assert should_fire_turn(t, [{"tool": "edit", "args": {}}])


def test_should_fire_turn_requires_tool_absent():
    t = UserTurn(content="x", when={"requires_tool": "edit"})
    assert not should_fire_turn(t, [{"tool": "read", "args": {}}])


def test_should_fire_turn_requires_no_tool():
    t = UserTurn(content="x", when={"requires_no_tool": "edit"})
    assert should_fire_turn(t, [{"tool": "read", "args": {}}])
    assert not should_fire_turn(t, [{"tool": "edit", "args": {}}])


def test_should_fire_turn_requires_tool_with_arg():
    t = UserTurn(
        content="x",
        when={"requires_tool_with_arg": {"tool": "edit", "arg": "path", "contains": "deploy"}},
    )
    assert should_fire_turn(
        t,
        [{"tool": "edit", "args": {"path": "deploy_log.txt"}}],
    )
    assert not should_fire_turn(
        t,
        [{"tool": "edit", "args": {"path": "other.txt"}}],
    )
    # Case-insensitive substring match
    assert should_fire_turn(
        t,
        [{"tool": "edit", "args": {"path": "DEPLOY_LOG.txt"}}],
    )


def test_build_transcript_excludes_thinking():
    transcript = [
        {"role": "user", "content": "hi"},
        {"role": "thinking", "content": "secret reasoning"},
        {"role": "assistant_text", "content": "hello"},
    ]
    out = build_transcript_for_judge(transcript)
    assert "secret reasoning" not in out
    assert "hello" in out
    assert "hi" in out


def test_build_transcript_truncates_long_tool_results():
    long_content = "x" * 1000
    transcript = [{"role": "tool_result", "content": long_content, "tool": "t"}]
    out = build_transcript_for_judge(transcript)
    assert "…" in out
    assert len(out) < len(long_content)


def test_load_all_scenarios_default_root_is_a_real_dir():
    # Smoke test for the default repo-level scenario path resolution.
    specs = load_all_scenarios(DEFAULT_SCENARIO_ROOT)
    assert specs, f"no scenarios under {DEFAULT_SCENARIO_ROOT}"
