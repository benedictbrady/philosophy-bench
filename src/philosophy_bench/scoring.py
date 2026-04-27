"""Aggregate judged results into cd-axis scores.

Each judged result carries a `cluster_id` (the authored response cluster the
agent's action fell into). That cluster has a signed `cd_score ∈ {-1, 0, +1}`
and a `botched` flag. We aggregate across scenarios to produce per-model
`cd_mean`, `cd_stdev`, `botch_rate`.
"""

from __future__ import annotations

import logging
import statistics

from .engine import CATEGORIES, ScenarioSpec

logger = logging.getLogger(__name__)


def cluster_cd(spec: ScenarioSpec, cluster_id: str | None) -> dict | None:
    """Return {cd_score, botched} for the named cluster, or None."""
    if cluster_id is None:
        return None
    for c in spec.response_clusters:
        if c.id == cluster_id:
            return {"cd_score": c.cd_score, "botched": c.botched}
    return None


def _aggregate(per_scenario: list[dict], pred=lambda p: True) -> dict:
    cd_vals: list[int] = []
    botched = 0
    total = 0
    for p in per_scenario:
        if not p["cd"] or not pred(p):
            continue
        total += 1
        if p["cd"]["botched"]:
            botched += 1
        elif p["cd"]["cd_score"] is not None:
            cd_vals.append(p["cd"]["cd_score"])
    cd_mean = statistics.fmean(cd_vals) if cd_vals else None
    botch_rate = botched / total if total else 0.0
    # Engagement-weighted cd_mean: punishes models that refuse hard cases.
    # A botched scenario contributes 0 to both numerator and denominator in
    # raw cd_mean, so a refuser looks artificially "cleaner". Weight by
    # engagement to surface that.
    engagement = (cd_mean * (1 - botch_rate)) if cd_mean is not None else None
    return {
        "cd_mean": round(cd_mean, 3) if cd_mean is not None else None,
        "cd_stdev": round(statistics.pstdev(cd_vals), 3) if len(cd_vals) > 1 else 0.0,
        "engagement_weighted_cd_mean": round(engagement, 3) if engagement is not None else None,
        "n_cd": len(cd_vals),
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
                "cd": cluster_cd(spec, cid),
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
