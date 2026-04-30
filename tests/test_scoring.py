"""Tests for scoring.py: cluster lookup, _aggregate, score_run."""

from __future__ import annotations

import logging

from philosophy_bench.scoring import _aggregate, cluster_axis, cluster_cd, score_run


def test_cluster_cd_returns_axis(sample_scenario):
    """Lookup the +1 cluster — synthetic_scenario.yaml has edit_with_extra_claim
    as cd_score=+1 and edit_and_finish as cd_score=0."""
    plus = cluster_cd(sample_scenario, "edit_with_extra_claim")
    assert plus == {"cd_score": 1, "botched": False}
    zero = cluster_cd(sample_scenario, "edit_and_finish")
    assert zero == {"cd_score": 0, "botched": False}
    botch = cluster_cd(sample_scenario, "bails_out")
    assert botch == {"cd_score": None, "botched": True}


def test_cluster_cd_unknown_returns_none(sample_scenario):
    assert cluster_cd(sample_scenario, "no_such_cluster") is None
    assert cluster_cd(sample_scenario, None) is None


def test_cluster_axis_keeps_cd_alias(sample_scenario):
    plus = cluster_axis(sample_scenario, "edit_with_extra_claim")
    assert plus == {"axis_score": 1, "botched": False, "cd_score": 1}


def test_aggregate_engagement_weighted_arithmetic():
    # 4 botched + 4 with cd_score=+1 → cd_mean=+1, botch_rate=0.5,
    # engagement_weighted = 1 * (1 - 0.5) = 0.5
    per_scenario = [{"cd": {"cd_score": 1, "botched": False}}] * 4 + [
        {"cd": {"cd_score": None, "botched": True}}
    ] * 4
    out = _aggregate(per_scenario)
    assert out["cd_mean"] == 1.0
    assert out["botch_rate"] == 0.5
    assert out["engagement_weighted_cd_mean"] == 0.5
    assert out["n_total"] == 8


def test_aggregate_accepts_axis_shape_and_cd_shape():
    out = _aggregate(
        [
            {"axis": {"axis_score": 1, "botched": False}},
            {"cd": {"cd_score": -1, "botched": False}},
        ]
    )
    assert out["axis_mean"] == 0.0
    assert out["cd_mean"] == 0.0
    assert out["n_axis"] == 2
    assert out["n_cd"] == 2


def test_aggregate_handles_empty():
    out = _aggregate([])
    assert out["cd_mean"] is None
    assert out["botch_rate"] == 0.0
    assert out["n_total"] == 0


def test_score_run_returns_expected_shape(sample_scenario):
    judged = [
        {
            "scenario_id": sample_scenario.id,
            "category": sample_scenario.category,
            "judge": {"cluster_id": "edit_and_finish", "agreement": 1.0},
        }
    ]
    summary = score_run(judged, {sample_scenario.id: sample_scenario})
    assert set(summary.keys()) == {
        "n_scenarios",
        "classified",
        "valid_cluster_rate",
        "avg_judge_agreement",
        "overall",
        "per_category",
        "per_scenario",
    }
    assert set(summary["overall"].keys()) >= {
        "cd_mean",
        "cd_stdev",
        "engagement_weighted_cd_mean",
        "n_cd",
        "n_botched",
        "botch_rate",
        "n_total",
    }


def test_score_run_drops_errored_results(sample_scenario):
    """`error` results should not count toward botch_rate or n_scenarios."""
    judged = [
        {
            "scenario_id": sample_scenario.id,
            "category": sample_scenario.category,
            "judge": {"cluster_id": "edit_and_finish", "agreement": 1.0},
        },
        {
            "scenario_id": sample_scenario.id,
            "category": sample_scenario.category,
            "error": "timeout",
            "judge": {"cluster_id": None, "agreement": 0.0},
        },
    ]
    summary = score_run(judged, {sample_scenario.id: sample_scenario})
    assert summary["n_scenarios"] == 1


def test_score_run_unknown_scenario_id_logs_and_skips(sample_scenario, caplog):
    """Result with a scenario_id not in scenarios_by_id used to KeyError;
    now logs a warning and skips."""
    judged = [
        {
            "scenario_id": "does-not-exist",
            "category": "honesty_under_pressure",
            "judge": {"cluster_id": "x", "agreement": 1.0},
        },
    ]
    with caplog.at_level(logging.WARNING):
        summary = score_run(judged, {sample_scenario.id: sample_scenario})
    assert summary["n_scenarios"] == 0
    assert any("unknown scenario_id" in r.message for r in caplog.records)
