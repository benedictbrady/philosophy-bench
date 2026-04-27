"""Tests for the four mock chassis."""

from __future__ import annotations

import json

import pytest
from jsonschema import Draft202012Validator

from philosophy_bench.chassis import CHASSIS_REGISTRY


@pytest.fixture(params=sorted(CHASSIS_REGISTRY.keys()))
def chassis(request):
    cls = CHASSIS_REGISTRY[request.param]
    return cls(initial_state={})


def test_chassis_instantiates(chassis):
    assert chassis is not None


def test_chassis_tools_have_unique_names(chassis):
    names = [t.name for t in chassis.tools()]
    assert len(set(names)) == len(names), f"duplicate tool name in {names}"


def test_chassis_tool_schemas_validate(chassis):
    for tool in chassis.tools():
        # raises if the schema itself is invalid JSON Schema 2020-12
        Draft202012Validator.check_schema(tool.parameters)


def test_dispatch_unknown_tool_returns_error(chassis):
    result = chassis.dispatch("nonexistent_tool", {})
    assert result.error, "unknown tool should produce error result, not raise"


def test_tool_log_records_calls(chassis):
    # Pick a real tool name from this chassis and dispatch with empty args.
    # We don't care if the call succeeds — only that it lands in the log.
    tool_name = chassis.tools()[0].name
    chassis.dispatch(tool_name, {})
    assert len(chassis.tool_log) == 1
    assert chassis.tool_log[0]["tool"] == tool_name


def test_snapshot_is_json_serializable(chassis):
    chassis.dispatch(chassis.tools()[0].name, {})
    snap = chassis.snapshot()
    # Round-trip: serialise + deserialise must succeed and round-trip equal.
    s = json.dumps(snap, default=str)
    json.loads(s)


def test_chassis_registry_covers_all_scenario_chassis_names(all_scenarios):
    """Every scenario's `chassis` field must resolve in the registry."""
    used = {s.chassis for s in all_scenarios}
    missing = used - set(CHASSIS_REGISTRY)
    assert not missing, f"scenarios reference unknown chassis: {missing}"
