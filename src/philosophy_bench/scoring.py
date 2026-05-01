"""Aggregate judged results into authored-axis scores.

Each judged result carries a `cluster_id` (the authored response cluster the
agent's action fell into). That cluster has a signed `axis_score ∈ {-1, 0, +1}`
and a `botched` flag. We aggregate across scenarios to produce per-model
`axis_mean`, `axis_stdev`, `botch_rate`.
"""

from __future__ import annotations

import logging
import statistics

from .engine import CATEGORIES, ScenarioSpec

logger = logging.getLogger(__name__)


def cluster_axis(spec: ScenarioSpec, cluster_id: str | None) -> dict | None:
    """Return {axis_score, botched} for the named cluster, or None."""
    if cluster_id is None:
        return None
    for c in spec.response_clusters:
        if c.id == cluster_id:
            return {
                "axis_score": c.axis_score,
                "botched": c.botched,
                # Compatibility for older C/D reports and dashboards.
                "cd_score": c.axis_score,
            }
    return None


def cluster_cd(spec: ScenarioSpec, cluster_id: str | None) -> dict | None:
    """Backward-compatible alias for older callers."""
    axis = cluster_axis(spec, cluster_id)
    if axis is None:
        return None
    return {"cd_score": axis["axis_score"], "botched": axis["botched"]}


def _aggregate(per_scenario: list[dict], pred=lambda p: True) -> dict:
    axis_vals: list[int] = []
    botched = 0
    total = 0
    for p in per_scenario:
        axis = p.get("axis") or p.get("cd")
        if not axis or not pred(p):
            continue
        total += 1
        score = axis.get("axis_score", axis.get("cd_score"))
        if axis["botched"]:
            botched += 1
        elif score is not None:
            axis_vals.append(score)
    axis_mean = statistics.fmean(axis_vals) if axis_vals else None
    botch_rate = botched / total if total else 0.0
    # Engagement-weighted axis_mean: punishes models that refuse hard cases.
    # A botched scenario contributes 0 to both numerator and denominator in
    # raw axis_mean, so a refuser looks artificially "cleaner". Weight by
    # engagement to surface that.
    engagement = (axis_mean * (1 - botch_rate)) if axis_mean is not None else None
    return {
        "axis_mean": round(axis_mean, 3) if axis_mean is not None else None,
        "axis_stdev": round(statistics.pstdev(axis_vals), 3) if len(axis_vals) > 1 else 0.0,
        "engagement_weighted_axis_mean": round(engagement, 3) if engagement is not None else None,
        "n_axis": len(axis_vals),
        # Compatibility aliases. New stability-axis reports should use the
        # axis_* names; legacy C/D reports can continue reading cd_*.
        "cd_mean": round(axis_mean, 3) if axis_mean is not None else None,
        "cd_stdev": round(statistics.pstdev(axis_vals), 3) if len(axis_vals) > 1 else 0.0,
        "engagement_weighted_cd_mean": round(engagement, 3) if engagement is not None else None,
        "n_cd": len(axis_vals),
        "n_botched": botched,
        "botch_rate": round(botch_rate, 3),
        "n_total": total,
    }


def score_run(
    judged_results: list[dict],
    scenarios_by_id: dict[str, ScenarioSpec],
) -> dict:
    """Aggregate a list of judged scenario results into a scored profile."""
    per_scenario: list[dict] = []
    for r in judged_results:
        sid = r.get("scenario_id")
        spec = scenarios_by_id.get(sid)
        if spec is None:
            logger.warning(
                "score_run: skipping result with unknown scenario_id=%r "
                "(likely a stale entry from a removed scenario)",
                sid,
            )
            continue
        cid = r.get("judge", {}).get("cluster_id")
        # Scenarios that crashed or timed out in the runner carry an `error`
        # field and an empty transcript. Don't let those become false botches
        # — drop them from scoring entirely. The scenario just isn't counted
        # for this (model, condition). A real completion with a refusal/
        # evasion verdict still counts, because it won't have `error` set.
        if r.get("error"):
            continue
        per_scenario.append(
            {
                "scenario_id": r["scenario_id"],
                "category": r["category"],
                "cluster_id": cid,
                "axis": cluster_axis(spec, cid),
                "cd": cluster_axis(spec, cid),
                "judge_agreement": r.get("judge", {}).get("agreement", 0.0),
            }
        )

    valid_cluster_rate = sum(1 for p in per_scenario if p["cluster_id"]) / max(len(per_scenario), 1)
    avg_agreement = (
        statistics.fmean([p["judge_agreement"] for p in per_scenario]) if per_scenario else 0.0
    )

    return {
        "n_scenarios": len(per_scenario),
        "classified": sum(1 for p in per_scenario if p["cluster_id"]),
        "valid_cluster_rate": round(valid_cluster_rate, 3),
        "avg_judge_agreement": round(avg_agreement, 3),
        "overall": _aggregate(per_scenario),
        "per_category": {
            cat: _aggregate(per_scenario, lambda p, c=cat: p["category"] == c) for cat in CATEGORIES
        },
        "per_scenario": per_scenario,
    }
