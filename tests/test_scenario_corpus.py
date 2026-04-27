"""Dataset-quality regression tests, parametrized over every shipped scenario.

This is the file that encodes the SCORING.md authoring rule as CI: every
shipped scenario must present a real C-vs-D dilemma (at least one cd=+1
cluster AND at least one cd=-1 cluster), unique cluster ids, a real chassis
name, and a botched cluster wherever a botched flag is set."""

from __future__ import annotations

import pytest
import yaml

from philosophy_bench.chassis import CHASSIS_REGISTRY
from philosophy_bench.engine import load_all_scenarios
from philosophy_bench.paths import ASK_POLES, DEFAULT_SCENARIO_ROOT


def _ids():
    return [s.id for s in load_all_scenarios(DEFAULT_SCENARIO_ROOT)]


def _spec_by_id():
    return {s.id: s for s in load_all_scenarios(DEFAULT_SCENARIO_ROOT)}


SPECS = _spec_by_id()
ALL_IDS = sorted(SPECS.keys())


@pytest.mark.parametrize("sid", ALL_IDS)
def test_authoring_rule_real_tension(sid):
    """Every scenario must have at least one cd_score=+1 cluster AND at least
    one cd_score=-1 cluster. (SCORING.md: 'real tension')."""
    spec = SPECS[sid]
    has_plus = any(c.cd_score == 1 for c in spec.response_clusters)
    has_minus = any(c.cd_score == -1 for c in spec.response_clusters)
    assert has_plus and has_minus, (
        f"{sid}: missing C/D pole "
        f"(has_plus={has_plus}, has_minus={has_minus}) — "
        "see SCORING.md 'authoring rule'"
    )


@pytest.mark.parametrize("sid", ALL_IDS)
def test_cluster_ids_unique(sid):
    spec = SPECS[sid]
    ids = spec.cluster_ids()
    assert len(ids) == len(set(ids)), f"{sid}: duplicate cluster ids: {ids}"


@pytest.mark.parametrize("sid", ALL_IDS)
def test_chassis_name_in_registry(sid):
    spec = SPECS[sid]
    assert spec.chassis in CHASSIS_REGISTRY, (
        f"{sid}: chassis={spec.chassis!r} not in CHASSIS_REGISTRY"
    )


@pytest.mark.parametrize("sid", ALL_IDS)
def test_botched_implies_null_cd(sid):
    spec = SPECS[sid]
    for c in spec.response_clusters:
        if c.botched:
            assert c.cd_score is None, (
                f"{sid}: cluster {c.id} is botched but has cd_score={c.cd_score}"
            )


@pytest.mark.parametrize("sid", ALL_IDS)
def test_max_agent_steps_reasonable(sid):
    spec = SPECS[sid]
    assert 1 <= spec.max_agent_steps <= 16, (
        f"{sid}: max_agent_steps={spec.max_agent_steps} outside reasonable range"
    )


@pytest.mark.parametrize("sid", ALL_IDS)
def test_initial_state_yaml_round_trip(sid):
    spec = SPECS[sid]
    # Should not raise
    yaml.safe_dump(spec.initial_state)


def test_scenario_id_uniqueness(all_scenarios):
    ids = [s.id for s in all_scenarios]
    assert len(set(ids)) == len(ids), (
        f"duplicate scenario ids: {[i for i in set(ids) if ids.count(i) > 1]}"
    )


def test_per_category_count(all_scenarios):
    """Pin the corpus shape: 10 scenarios per category, 100 total."""
    from collections import Counter

    counts = Counter(s.category for s in all_scenarios)
    assert sum(counts.values()) == 100
    for cat, n in counts.items():
        assert n == 10, f"category {cat} has {n} scenarios, expected 10"


def test_no_initial_state_chassis_runtime_collision(all_scenarios):
    """A scenario's `initial_state` must not declare a top-level key that the
    chassis also uses as a runtime list (the keys the chassis appends tool
    outputs into). Squatting on those keys silently breaks tools at first
    write — `setdefault("reports", []).append(...)` throws if the scenario
    pre-seeded `reports` as a dict. The collision is invisible until a model
    actually calls the tool, at which point the run looks like a refusal.
    Caught us once on `confidentiality-05` and `self-continuity-06`; this
    test makes the next instance fail in CI instead of in production."""
    import inspect
    import re

    runtime_keys: dict[str, set[str]] = {}
    for name, cls in CHASSIS_REGISTRY.items():
        src = inspect.getsource(inspect.getmodule(cls))
        keys = set(re.findall(r'c\.state\.setdefault\(\s*"([^"]+)"\s*,\s*\[\]', src))
        runtime_keys[name] = keys

    collisions = []
    for s in all_scenarios:
        chassis_keys = runtime_keys.get(s.chassis, set())
        # A collision is only a bug if the YAML value isn't already a list —
        # `setdefault(k, []).append(...)` is fine on a pre-seeded list, but
        # crashes on a dict (or any non-list).
        bad = [
            k
            for k in s.initial_state
            if k in chassis_keys and not isinstance(s.initial_state[k], list)
        ]
        if bad:
            collisions.append((s.id, s.chassis, sorted(bad)))
    assert not collisions, (
        "scenarios collide with chassis runtime list-write keys "
        "(rename the YAML field, e.g. `reports` -> `existing_reports`):\n"
        + "\n".join(f"  {sid}: chassis={ch} keys={ks}" for sid, ch, ks in collisions)
    )


def test_ask_poles_partition_consistent(all_scenarios):
    """Every id in ask_poles.yaml is a real scenario id; the c/d/n partition
    is disjoint and covers exactly the corpus."""
    data = yaml.safe_load(ASK_POLES.read_text())
    c = set(data["c_asked"])
    d = set(data["d_asked"])
    n = set(data["neutral"])
    corpus = {s.id for s in all_scenarios}
    assert (c & d) == set()
    assert (c & n) == set()
    assert (d & n) == set()
    assert (c | d | n) == corpus, (
        f"ask_poles drift: corpus only={corpus - (c | d | n)}, poles only={(c | d | n) - corpus}"
    )
    assert len(c) == 37 and len(d) == 37 and len(n) == 26, (
        f"ask_poles split changed: c={len(c)} d={len(d)} n={len(n)}"
    )
