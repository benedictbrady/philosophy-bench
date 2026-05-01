"""Smoke tests for repo-level experiment packs."""

from __future__ import annotations

from pathlib import Path

from philosophy_bench.engine import load_all_scenarios
from philosophy_bench.paths import ASK_POLES, DEFAULT_SCENARIO_ROOT, PRIMING_DIR

REPO_ROOT = Path(__file__).resolve().parents[1]
EXPERIMENT_ROOT = REPO_ROOT / "experiments"


def test_experiment_layout_is_consistent():
    for name in ("c_vs_d", "expediency_vs_correctness", "stability_pairs"):
        root = EXPERIMENT_ROOT / name
        assert (root / "harness").is_dir()
        assert (root / "data" / "scenarios").is_dir()
        assert (root / "results").is_dir()


def test_c_vs_d_pack_loads_and_is_default():
    root = EXPERIMENT_ROOT / "c_vs_d" / "data" / "scenarios"
    specs = load_all_scenarios(root)
    assert len(specs) == 100
    assert Path(DEFAULT_SCENARIO_ROOT) == root
    assert PRIMING_DIR == EXPERIMENT_ROOT / "c_vs_d" / "data" / "primers"
    assert ASK_POLES == EXPERIMENT_ROOT / "c_vs_d" / "data" / "ask_poles.yaml"


def test_expediency_correctness_pack_loads():
    root = EXPERIMENT_ROOT / "expediency_vs_correctness" / "data" / "scenarios"
    specs = load_all_scenarios(root)
    assert len(specs) == 100
    assert {s.category for s in specs} == {"shortcut_vs_rigor"}
    for spec in specs:
        scores = {c.axis_score for c in spec.response_clusters}
        assert {1, -1}.issubset(scores), spec.id


def test_stability_pairs_pack_loads():
    root = EXPERIMENT_ROOT / "stability_pairs" / "data" / "scenarios"
    specs = load_all_scenarios(root)
    assert len(specs) == 200
    assert {s.id.rsplit("-", 1)[-1] for s in specs} == {"a", "b"}
