"""Strict pair-level audit for the stability_pairs corpus.

Runs eight checks against every stab_NNN_a / stab_NNN_b pair:

  1. Cluster axis well-formedness (exactly one axis=+1, one axis=-1, ≥1 axis=0,
     exactly one botched=null).
  2. Advocacy-pole correctness per file (A → pole=positive, axis=+1;
     B → pole=negative, axis=-1).
  3. Cluster-id stability across A/B (per-cluster diff with informative msg).
  4. False-symmetry lint on non-botched cluster descriptions.
  5. Botched-strictness lint on the botched cluster description.
  6. Direction-agnostic clusters (heuristic).
  7. Advocacy-text alignment (turn content references named cluster).
  8. Initial_state contradiction lint.

Errors are always fatal. Warnings are fatal only with --strict.

Categorizes each failing pair into:
  A: passes all checks (no fixes needed)
  B: needs turn rewrite only (advocacy / text-alignment / direction-agnostic)
  C: needs cluster restructuring (axis / false-symmetry / botched / contradiction)

Writes audit_report.json next to this script for programmatic use.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import yaml

EXP_ROOT = Path(__file__).resolve().parents[1]
SCEN = EXP_ROOT / "data" / "scenarios"
REPORT_PATH = Path(__file__).resolve().parent / "audit_report.json"

EXPECTED_SAME = [
    "category", "chassis", "initial_state", "system_prompt",
    "response_clusters", "judge_rubric",
]

POLICY_VIOLATION_PHRASES = [
    "violates policy", "violates the policy", "violates §",
    "prohibited", "subject to disciplinary",
    "in violation of", "breaches", "is a breach",
    "policy prohibiting", "audit log integrity is violated",
]

LOOSE_BOTCH_PHRASES = [
    "asks for clarification", "kicks back", "kick back",
    "drafts without sending", "drafts but does not send",
    "requests confirmation", "defers to human", "defers to user",
    "replies to the csm saying", "punts back", "asks the user to",
    "outputs questions", "hedges without",
]

STRICT_BOTCH_PHRASES = [
    "no tool call", "no relevant tool",
    "no response", "no substantive reply", "no reply",
    "silent", "silence",
    "no message", "no notification", "no escalation",
    "no publish", "no send_email", "no merge_pr",
    "no approve", "no edit", "no write", "no submit",
    "no update", "no log", "no draft",
    "user explicitly pre-empted",
]

CONTRADICTION_PAIRS = [
    ("in scope", "not in scope"),
    ("permitted", "prohibited"),
    ("is allowed", "is prohibited"),
    ("approved", "not approved"),
    ("on the roadmap", "not on the roadmap"),
]


def tokenize(s: str) -> set[str]:
    """Lowercase wordset, length>=4 to filter stopwords."""
    return {w for w in re.findall(r"[a-z0-9_]+", (s or "").lower()) if len(w) >= 4}


def find_phrase(text: str, phrases: list[str]) -> list[str]:
    t = (text or "").lower()
    return [p for p in phrases if p in t]


def cluster_by_id(spec: dict, cid: str) -> dict | None:
    for c in spec.get("response_clusters") or []:
        if c.get("id") == cid:
            return c
    return None


def botched_cluster(spec: dict) -> dict | None:
    for c in spec.get("response_clusters") or []:
        if c.get("botched"):
            return c
    return None


def axis_score(obj: dict) -> int | None:
    """Read the authored axis score, with legacy cd_score fallback."""
    return obj.get("axis_score", obj.get("cd_score"))


def check_cluster_axis(spec: dict, fname: str) -> tuple[list[str], list[str]]:
    """Returns (errors, warnings)."""
    errs, warns = [], []
    clusters = spec.get("response_clusters") or []
    axis_counts = {-1: 0, 0: 0, 1: 0, None: 0}
    botched_count = 0
    for c in clusters:
        score = axis_score(c)
        if score not in axis_counts:
            errs.append(f"{fname}: cluster '{c.get('id')}' has invalid axis_score {score}")
            continue
        axis_counts[score] += 1
        if c.get("botched"):
            botched_count += 1
            if score is not None:
                errs.append(f"{fname}: botched cluster '{c.get('id')}' must have axis_score: null, got {score}")
    if axis_counts[1] != 1:
        errs.append(f"{fname}: must have exactly 1 axis=+1 cluster, found {axis_counts[1]}")
    if axis_counts[-1] != 1:
        errs.append(f"{fname}: must have exactly 1 axis=-1 cluster, found {axis_counts[-1]}")
    if axis_counts[0] < 1:
        errs.append(f"{fname}: must have at least 1 axis=0 cluster, found {axis_counts[0]}")
    if botched_count != 1:
        errs.append(f"{fname}: must have exactly 1 botched cluster, found {botched_count}")
    return errs, warns


def check_advocacy_block(spec: dict, fname: str, expected_pole: str) -> tuple[list[str], list[str]]:
    errs, warns = [], []
    adv = spec.get("advocacy")
    if not adv:
        warns.append(f"{fname}: missing 'advocacy' block (required by new schema)")
        return errs, warns
    if not isinstance(adv, dict):
        errs.append(f"{fname}: 'advocacy' must be a mapping")
        return errs, warns
    if adv.get("pole") != expected_pole:
        errs.append(f"{fname}: advocacy.pole must be '{expected_pole}', got {adv.get('pole')!r}")
    expected_score = 1 if expected_pole == "positive" else -1
    if axis_score(adv) != expected_score:
        errs.append(f"{fname}: advocacy.axis_score must be {expected_score}, got {axis_score(adv)!r}")
    cid = adv.get("cluster_id")
    if not cid:
        errs.append(f"{fname}: advocacy.cluster_id required")
        return errs, warns
    cluster = cluster_by_id(spec, cid)
    if not cluster:
        errs.append(f"{fname}: advocacy.cluster_id {cid!r} not in response_clusters")
        return errs, warns
    if axis_score(cluster) != expected_score:
        errs.append(
            f"{fname}: advocacy points at cluster '{cid}' which has "
            f"axis_score={axis_score(cluster)}, expected {expected_score}"
        )
    if cluster.get("botched"):
        errs.append(f"{fname}: advocacy must not point at a botched cluster ({cid!r})")
    return errs, warns


def check_false_symmetry(spec: dict, fname: str) -> tuple[list[str], list[str]]:
    """A non-botched cluster's description should NOT openly call its own action
    a policy violation. That breaks the 'both poles defensible' bar."""
    errs, warns = [], []
    hinge = spec.get("hinge_axis") or {}
    allow_override = hinge.get("allow_policy_violation_pole") is True
    for c in spec.get("response_clusters") or []:
        if c.get("botched"):
            continue
        hits = find_phrase(c.get("description", ""), POLICY_VIOLATION_PHRASES)
        if hits and not allow_override:
            warns.append(
                f"{fname}: non-botched cluster '{c.get('id')}' contains policy-violation phrasing "
                f"({', '.join(repr(h) for h in hits)}); both poles must be defensible. "
                f"If intentional, set hinge_axis.allow_policy_violation_pole: true with justification."
            )
    return errs, warns


def check_botched_strictness(spec: dict, fname: str) -> tuple[list[str], list[str]]:
    errs, warns = [], []
    bc = botched_cluster(spec)
    if not bc:
        return errs, warns  # absence flagged in axis check
    desc = bc.get("description", "")
    loose = find_phrase(desc, LOOSE_BOTCH_PHRASES)
    strict = find_phrase(desc, STRICT_BOTCH_PHRASES)
    if loose and not strict:
        warns.append(
            f"{fname}: botched cluster '{bc.get('id')}' contains loose triggers "
            f"({', '.join(repr(h) for h in loose)}) without a strict 'no [verb] called' / "
            f"'no substantive reply' / 'silent' anchor. Asking for clarification, drafting "
            f"without sending, or kicking back to user are PRODUCTIVE behaviors and need their "
            f"own cluster, not the botched bucket."
        )
    return errs, warns


DIRECTION_BAKED_PHRASES = [
    "as requested", "as the principal", "as the user", "as the manager",
    "as the vp", "as the cfo", "as the cto", "as the director",
    "the requested edit", "the requested change", "the requested action",
    "the requested send", "the requested merge", "the requested approval",
    "decline to make the requested", "declines to make the requested",
    "comply with the request to", "complies with the request to",
    "as the boss", "as instructed", "follows the instruction",
    "the principal's ask", "the user's ask", "the principal's request",
]


def check_direction_agnostic(spec: dict, fname: str) -> tuple[list[str], list[str]]:
    """Cluster descriptions must not reference the direction of the principal's
    request shape. Phrases like 'as requested', 'declines to make the requested
    edit', 'comply with the request to X' bake in one direction's framing.
    Cluster outcomes should be described in terms of the agent's observable
    behavior, not in terms of compliance with the asker."""
    errs, warns = [], []
    for c in spec.get("response_clusters") or []:
        if c.get("botched"):
            continue
        hits = find_phrase(c.get("description", ""), DIRECTION_BAKED_PHRASES)
        if hits:
            warns.append(
                f"{fname}: cluster '{c.get('id')}' description uses direction-referencing "
                f"phrases ({', '.join(repr(h) for h in hits)}); rewrite in terms of agent's "
                f"observable behavior, not compliance with the asker."
            )
    return errs, warns


def check_advocacy_text_alignment(spec: dict, fname: str) -> tuple[list[str], list[str]]:
    """The principal turn should mention a signal substring from the named cluster.
    Permissive heuristic: any 4+ char token from any signal must appear in the turn."""
    errs, warns = [], []
    adv = spec.get("advocacy") or {}
    cid = adv.get("cluster_id")
    if not cid:
        return errs, warns
    cluster = cluster_by_id(spec, cid)
    if not cluster:
        return errs, warns
    turn = (spec.get("turns") or [{}])[0].get("content", "").lower()
    signals = cluster.get("signals") or []
    sig_tokens = set()
    for s in signals:
        sig_tokens |= tokenize(s)
    desc_tokens = tokenize(cluster.get("description", ""))
    keywords = (sig_tokens | desc_tokens) - {
        "with", "from", "into", "this", "that", "must", "have",
        "without", "where", "what", "when", "which", "would",
        "request", "requested", "asks", "asked", "called", "calls",
        "cluster", "agent", "user", "principal", "send", "sends",
    }
    if not keywords:
        return errs, warns
    overlap = keywords & tokenize(turn)
    if not overlap:
        warns.append(
            f"{fname}: turn does not textually align with advocacy cluster '{cid}' "
            f"(no shared keywords with cluster signals/description). Re-check advocacy tag."
        )
    return errs, warns


def check_contradiction(spec: dict, fname: str) -> tuple[list[str], list[str]]:
    errs, warns = [], []

    def walk(v):
        if isinstance(v, str):
            yield v
        elif isinstance(v, dict):
            for x in v.values():
                yield from walk(x)
        elif isinstance(v, list):
            for x in v:
                yield from walk(x)

    for s in walk(spec.get("initial_state") or {}):
        low = s.lower()
        for a, b in CONTRADICTION_PAIRS:
            if a in low and b in low:
                excerpt = re.search(rf".{{0,40}}{re.escape(a)}.{{0,80}}", low)
                ex = excerpt.group(0) if excerpt else ""
                warns.append(
                    f"{fname}: initial_state contains contradicting phrases "
                    f"'{a}' and '{b}'. Excerpt: {ex!r}"
                )
                break
    return errs, warns


def categorize(pair_errors: list[str], pair_warnings: list[str]) -> str:
    """Bucket a pair into A/B/C based on which checks failed."""
    if not pair_errors and not pair_warnings:
        return "A"
    text = " ".join(pair_errors + pair_warnings).lower()
    # Category C: structural defects in clusters or world
    c_signals = [
        "must have exactly", "must have at least",
        "policy-violation phrasing", "loose triggers", "direction-baked",
        "contradicting phrases", "must not point at a botched",
    ]
    if any(s in text for s in c_signals):
        return "C"
    # Otherwise: turn-only fixes (advocacy-pole, text-alignment, missing advocacy block)
    return "B"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenarios", type=Path, default=SCEN,
                    help="Scenario directory to audit.")
    ap.add_argument("--strict", action="store_true",
                    help="Treat warnings as fatal.")
    ap.add_argument("--quiet", action="store_true",
                    help="Skip per-pair detail output, just emit summary.")
    args = ap.parse_args()

    scen = args.scenarios
    report_path = scen.parent / "audit_report.json" if scen.name != "scenarios" else REPORT_PATH
    a_files = sorted(scen.glob("stab_*_a.yaml"))
    pair_ids = []
    by_pair: dict[str, dict] = {}
    structural_errors: list[str] = []

    for af in a_files:
        m = re.match(r"stab_(\d{3})_a", af.stem)
        if not m:
            structural_errors.append(f"unexpected name: {af.name}")
            continue
        pid = m.group(1)
        bf = scen / f"stab_{pid}_b.yaml"
        if not bf.exists():
            structural_errors.append(f"missing partner: {bf.name}")
            continue
        try:
            a = yaml.safe_load(af.read_text())
            b = yaml.safe_load(bf.read_text())
        except yaml.YAMLError as e:
            structural_errors.append(f"stab-{pid}: YAML parse error: {e}")
            continue

        errs: list[str] = []
        warns: list[str] = []

        for k in EXPECTED_SAME:
            if a.get(k) != b.get(k):
                # Be specific about which cluster differs if response_clusters
                if k == "response_clusters":
                    a_ids = [c.get("id") for c in a.get(k) or []]
                    b_ids = [c.get("id") for c in b.get(k) or []]
                    if a_ids != b_ids:
                        errs.append(f"stab-{pid}: cluster ids differ: A={a_ids} B={b_ids}")
                    else:
                        for ac, bc in zip(a.get(k), b.get(k)):
                            for f in ac:
                                if ac.get(f) != bc.get(f):
                                    errs.append(f"stab-{pid}: cluster '{ac.get('id')}' field '{f}' differs A vs B")
                else:
                    errs.append(f"stab-{pid}: shared field '{k}' differs between A and B")

        if a.get("turns", [{}])[0].get("content") == b.get("turns", [{}])[0].get("content"):
            errs.append(f"stab-{pid}: A and B turns are identical (no advocacy flip)")
        if a.get("id") != f"stab-{pid}-a":
            errs.append(f"{af.name}: id field is {a.get('id')!r}, expected 'stab-{pid}-a'")
        if b.get("id") != f"stab-{pid}-b":
            errs.append(f"{bf.name}: id field is {b.get('id')!r}, expected 'stab-{pid}-b'")

        for spec, fname, pole in [(a, af.name, "positive"), (b, bf.name, "negative")]:
            for fn, args_ in (
                (check_cluster_axis, (spec, fname)),
                (check_advocacy_block, (spec, fname, pole)),
                (check_false_symmetry, (spec, fname)),
                (check_botched_strictness, (spec, fname)),
                (check_advocacy_text_alignment, (spec, fname)),
                (check_contradiction, (spec, fname)),
                (check_direction_agnostic, (spec, fname)),
            ):
                e, w = fn(*args_)
                errs.extend(e); warns.extend(w)

        category = categorize(errs, warns)
        by_pair[pid] = {
            "errors": errs, "warnings": warns, "category": category,
            "category_label": {"A": "passes", "B": "turn-rewrite", "C": "cluster-rebuild"}[category],
        }
        pair_ids.append(pid)

    # orphan check
    for bf in sorted(scen.glob("stab_*_b.yaml")):
        m = re.match(r"stab_(\d{3})_b", bf.stem)
        if not m:
            structural_errors.append(f"unexpected name: {bf.name}")
            continue
        pid = m.group(1)
        if pid not in pair_ids:
            structural_errors.append(f"orphan B without A: {bf.name}")

    # Write report
    report = {
        "n_pairs": len(pair_ids),
        "structural_errors": structural_errors,
        "by_pair": by_pair,
        "category_counts": {
            cat: sum(1 for v in by_pair.values() if v["category"] == cat)
            for cat in "ABC"
        },
    }
    report_path.write_text(json.dumps(report, indent=2))

    # Print summary
    n_err = sum(len(v["errors"]) for v in by_pair.values()) + len(structural_errors)
    n_warn = sum(len(v["warnings"]) for v in by_pair.values())
    cats = report["category_counts"]
    print(f"Audited {len(pair_ids)} pairs.")
    print(f"  Category A (passes):         {cats['A']}")
    print(f"  Category B (turn-rewrite):   {cats['B']}")
    print(f"  Category C (cluster-rebuild):{cats['C']}")
    print(f"  Errors:   {n_err}")
    print(f"  Warnings: {n_warn}")
    print(f"Report written to {report_path.relative_to(Path.cwd()) if report_path.is_relative_to(Path.cwd()) else report_path}")

    if not args.quiet:
        for pid in pair_ids:
            v = by_pair[pid]
            if not v["errors"] and not v["warnings"]:
                continue
            print(f"\nstab-{pid}  [{v['category_label']}]")
            for e in v["errors"]:
                print(f"  ERROR:   {e}")
            for w in v["warnings"]:
                print(f"  WARNING: {w}")
        for e in structural_errors:
            print(f"\nSTRUCTURAL: {e}")

    if structural_errors or any(v["errors"] for v in by_pair.values()):
        sys.exit(1)
    if args.strict and any(v["warnings"] for v in by_pair.values()):
        sys.exit(2)


if __name__ == "__main__":
    main()
