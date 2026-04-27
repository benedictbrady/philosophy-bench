"""Tests for runner.py: end-to-end run with the mock provider."""

from __future__ import annotations

import json

import pytest

from philosophy_bench.runner import run_scenario, run_suite

from .conftest import make_response, make_tool_call


@pytest.mark.asyncio
async def test_run_scenario_end_to_end(sample_scenario, mock_provider):
    """Mock emits: text → edit tool call → finish_task. Expect a transcript
    with all events in order, finished_explicitly=True."""
    spec, behavior = mock_provider(
        [
            make_response(
                text="Editing the file.",
                tool_calls=[
                    make_tool_call(
                        "edit",
                        {
                            "path": "deploy_log.txt",
                            "content": "previous deploys: v1.2.3 (passing)\nv1.2.4",
                        },
                        call_id="t1",
                    )
                ],
            ),
            make_response(
                tool_calls=[
                    make_tool_call("finish_task", {"summary": "added v1.2.4"}, call_id="t2")
                ]
            ),
        ]
    )
    result = await run_scenario(sample_scenario, spec)
    assert result["scenario_id"] == sample_scenario.id
    assert result["finished_explicitly"] is True
    roles = [t["role"] for t in result["transcript"]]
    assert "user" in roles
    assert "assistant_text" in roles
    assert "tool_call" in roles
    # Mock was called twice
    assert len(behavior.calls) == 2


@pytest.mark.asyncio
async def test_run_scenario_priming_before(sample_scenario, mock_provider):
    spec, behavior = mock_provider(
        [
            make_response(
                tool_calls=[make_tool_call("finish_task", {"summary": "ok"}, call_id="t1")]
            ),
        ]
    )
    await run_scenario(sample_scenario, spec, priming="PRIMER_TEXT", priming_label="C")
    system_seen = behavior.calls[0][0]
    assert system_seen.startswith("PRIMER_TEXT")
    assert "engineer triaging" in system_seen  # original system prompt is still present


@pytest.mark.asyncio
async def test_run_scenario_priming_after(sample_scenario, mock_provider):
    spec, behavior = mock_provider(
        [
            make_response(
                tool_calls=[make_tool_call("finish_task", {"summary": "ok"}, call_id="t1")]
            ),
        ]
    )
    await run_scenario(
        sample_scenario, spec, priming="PRIMER_TEXT", priming_label="C", priming_position="after"
    )
    system_seen = behavior.calls[0][0]
    assert system_seen.rstrip().endswith("PRIMER_TEXT")


@pytest.mark.asyncio
async def test_run_scenario_max_steps_respected(sample_scenario, mock_provider):
    """Mock that always returns a tool_call but never finish_task should
    stop after max_agent_steps invocations."""
    looping = make_response(
        tool_calls=[
            make_tool_call("read", {"path": "deploy_log.txt"}, call_id="x"),
        ]
    )
    # 20 copies — far more than max_agent_steps (default 8)
    spec, behavior = mock_provider([looping] * 20)
    await run_scenario(sample_scenario, spec)
    assert len(behavior.calls) == sample_scenario.max_agent_steps


@pytest.mark.asyncio
async def test_run_suite_writes_checkpoint(sample_scenario, mock_provider, tmp_path):
    spec, _ = mock_provider(
        [
            make_response(
                tool_calls=[make_tool_call("finish_task", {"summary": "ok"}, call_id="t1")]
            ),
        ]
    )
    await run_suite([sample_scenario], spec, tmp_path)
    ckpt = tmp_path / spec.name / "baseline" / "runs" / f"{sample_scenario.id}.json"
    assert ckpt.exists()
    data = json.loads(ckpt.read_text())
    assert data["scenario_id"] == sample_scenario.id


@pytest.mark.asyncio
async def test_run_suite_resumes_from_checkpoint(sample_scenario, mock_provider, tmp_path):
    """If a checkpoint already exists, the runner should not call the model."""
    ckpt_dir = tmp_path / "mock-test" / "baseline" / "runs"
    ckpt_dir.mkdir(parents=True)
    sentinel = {
        "scenario_id": sample_scenario.id,
        "category": sample_scenario.category,
        "model": "mock-test",
        "priming": "",
        "transcript": [{"role": "user", "content": "from-checkpoint"}],
        "chassis_snapshot": {},
        "elapsed": 0.0,
        "finished_explicitly": True,
    }
    (ckpt_dir / f"{sample_scenario.id}.json").write_text(json.dumps(sentinel))

    spec, behavior = mock_provider([])  # empty — will assert no calls below
    results = await run_suite([sample_scenario], spec, tmp_path)
    assert behavior.calls == []
    assert results[0]["transcript"][0]["content"] == "from-checkpoint"
