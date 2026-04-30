"""Scenario schema, loader, and transcript formatter.

A scenario is a YAML file binding a chassis, an initial world state, a
sequence of user turns, and a response-cluster rubric. Engine is pure data +
pure logic — no async, no LLM calls.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, ValidationError, model_validator

logger = logging.getLogger(__name__)

CATEGORIES = [
    "honesty_under_pressure",
    "scope_discipline",
    "authority_conflicts",
    "confidentiality",
    "shortcut_vs_rigor",
    "attribution",
    "uncertainty_disclosure",
    "harm_adjacent",
    "loyalty_conflicts",
    "self_continuity",
]


class ResponseCluster(BaseModel):
    model_config = {"extra": "ignore"}

    id: str
    description: str
    signals: list[str] = Field(default_factory=list)
    # Signed position on the scenario's authored ethical axis.
    # +1 is the A-framed pole, -1 is the B-framed pole, 0 is a compromise.
    # None means the cluster is botched/off-axis.
    axis_score: int | None = Field(default=None, ge=-1, le=1)
    # Off-axis: refuse/evasive/incompetent. axis_score is ignored when true.
    botched: bool = False

    @model_validator(mode="before")
    @classmethod
    def _migrate_legacy_cd_score(cls, data):
        if isinstance(data, dict) and "axis_score" not in data and "cd_score" in data:
            data = {**data, "axis_score": data["cd_score"]}
        return data

    @property
    def cd_score(self) -> int | None:
        """Backward-compatible alias for older analysis code."""
        return self.axis_score


class UserTurn(BaseModel):
    content: str
    # Optional condition on prior tool calls; see should_fire_turn.
    when: dict | None = None


class ScenarioSpec(BaseModel):
    model_config = {"extra": "ignore"}

    id: str
    category: Literal[
        "honesty_under_pressure",
        "scope_discipline",
        "authority_conflicts",
        "confidentiality",
        "shortcut_vs_rigor",
        "attribution",
        "uncertainty_disclosure",
        "harm_adjacent",
        "loyalty_conflicts",
        "self_continuity",
    ]
    chassis: Literal["mock_repo", "mock_support", "mock_crm", "mock_warehouse"]
    initial_state: dict = Field(default_factory=dict)
    system_prompt: str
    turns: list[UserTurn]
    max_agent_steps: int = 8
    hinge_description: str
    response_clusters: list[ResponseCluster]
    judge_rubric: str = ""
    control_variant_of: str | None = None

    def cluster_ids(self) -> list[str]:
        return [c.id for c in self.response_clusters]


def load_scenario(path: str | Path) -> ScenarioSpec:
    raw = yaml.safe_load(Path(path).read_text())
    try:
        return ScenarioSpec(**raw)
    except ValidationError as e:
        raise ValueError(f"{path}: {e}") from e


def load_all_scenarios(root: str | Path) -> list[ScenarioSpec]:
    root = Path(root)
    paths = sorted(root.rglob("*.yaml"))
    scenarios = []
    errors = []
    for p in paths:
        try:
            scenarios.append(load_scenario(p))
        except Exception as e:  # noqa: BLE001
            errors.append(f"{p}: {e}")
    if errors:
        logger.error("Scenario load errors:\n" + "\n".join(errors))
        raise ValueError(f"{len(errors)} scenario(s) failed to load")
    return scenarios


# ---------------------------------------------------------------------------
# Turn-gating predicates
# ---------------------------------------------------------------------------


def should_fire_turn(turn: UserTurn, tool_log: list[dict]) -> bool:
    if not turn.when:
        return True
    w = turn.when
    if w.get("always"):
        return True
    if "requires_tool" in w:
        return any(t["tool"] == w["requires_tool"] for t in tool_log)
    if "requires_no_tool" in w:
        return not any(t["tool"] == w["requires_no_tool"] for t in tool_log)
    if "requires_tool_with_arg" in w:
        spec = w["requires_tool_with_arg"]
        tname = spec.get("tool")
        key = spec.get("arg")
        contains = spec.get("contains", "")
        return any(
            t["tool"] == tname and contains.lower() in str(t["args"].get(key, "")).lower()
            for t in tool_log
        )
    return True


# ---------------------------------------------------------------------------
# Transcript snapshot for the judge
# ---------------------------------------------------------------------------


def build_transcript_for_judge(transcript: list[dict]) -> str:
    lines = []
    for entry in transcript:
        role = entry["role"]
        if role == "user":
            lines.append(f"[USER]\n{entry['content']}\n")
        elif role == "assistant_text":
            lines.append(f"[AGENT TEXT]\n{entry['content']}\n")
        elif role == "tool_call":
            args_str = ", ".join(f"{k}={_short(v)}" for k, v in entry["args"].items())
            lines.append(f"[AGENT TOOL] {entry['tool']}({args_str})")
        elif role == "tool_result":
            lines.append(f"[TOOL RESULT] {_short(entry['content'], 400)}")
        elif role == "thinking":
            pass  # judge sees the action, not the stated reasoning
    return "\n".join(lines)


def _short(v, limit: int = 200) -> str:
    s = str(v)
    return s if len(s) <= limit else s[:limit] + "…"
