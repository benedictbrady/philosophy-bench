"""Aggregate per-model summary tables across priming conditions.

Reads each model's `<root>/<model>/<cond>/summary.json` (produced by
`philosophy-bench prime`) and prints two tables:

  1. Action `cd_mean` per (model, condition) plus per-model Δ across
     conditions — measures how much the priming primer shifts behavior.
  2. Reasoning-trace lean per (model, condition) — only printed if the
     classifier output exists at `<root>/_reasoning_analysis/<model>_<cond>.json`
     (produced by `philosophy-bench-classify-reasoning`).

Default `--root` is `results`.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

CONDS = ["baseline", "d_direct", "c_direct"]
DEFAULT_ROOT = Path("results")


def action_stats(root: Path, model: str, cond: str) -> dict | None:
    p = root / model / cond / "summary.json"
    if not p.exists():
        return None
    d = json.loads(p.read_text())
    ps = d.get("per_scenario") or []
    cds = [e["cd"]["cd_score"] for e in ps if e["cd"] and e["cd"]["cd_score"] is not None]
    botched = sum(1 for e in ps if e["cd"] and e["cd"]["botched"])
    n = len(ps)
    if not n:
        return None
    cd_mean = round(sum(cds) / len(cds), 3) if cds else None
    br = round(botched / n, 3)
    w = round(cd_mean * (1 - br), 3) if cd_mean is not None else None
    return {"cd_mean": cd_mean, "botch_rate": br, "weighted": w, "n": n}


def reasoning_stats(root: Path, model: str, cond: str) -> dict | None:
    p = root / "_reasoning_analysis" / f"{model}_{cond}.json"
    if not p.exists():
        return None
    rows = json.loads(p.read_text())
    c = sum(1 for r in rows if r["label"] == "C")
    d = sum(1 for r in rows if r["label"] == "D")
    n = sum(1 for r in rows if r["label"] == "N")
    total = c + d + n or 1
    return {"C": c, "D": d, "N": n, "cd_lean": round((c - d) / total, 3)}


def discover_models(root: Path) -> list[str]:
    return sorted(d for d in os.listdir(root) if (root / d).is_dir() and not d.startswith("_"))


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--root", default=str(DEFAULT_ROOT), help=f"Results dir (default: {DEFAULT_ROOT})"
    )
    parser.add_argument(
        "--skip-reasoning", action="store_true", help="Skip the reasoning-classifier table."
    )
    args = parser.parse_args()
    root = Path(args.root)
    if not root.is_dir():
        sys.exit(f"results dir not found: {root}")

    models = discover_models(root)
    print(f"# {root}\n")
    print("# Action: cd_mean / botch_rate / engagement_weighted_cd_mean\n")
    hdr = f"{'model':<24}" + "".join(f"{c:>22}" for c in CONDS) + f"{'Δ cd_mean':>12}"
    print(hdr)
    print("-" * len(hdr))
    for m in models:
        vals = {c: action_stats(root, m, c) for c in CONDS}
        if not all(vals.values()):
            print(f"{m:<24}  partial")
            continue
        means = [vals[c]["cd_mean"] for c in CONDS]
        delta = round(max(means) - min(means), 3)
        row = f"{m:<24}"
        for c in CONDS:
            v = vals[c]
            row += f"  {v['cd_mean']:+.2f}/{v['botch_rate']:.2f}/{v['weighted']:+.2f}"
        row += f"   {delta:+.2f}"
        print(row)

    if args.skip_reasoning:
        return
    print("\n# Reasoning lean (C - D) / n — from philosophy-bench-classify-reasoning\n")
    hdr2 = f"{'model':<24}" + "".join(f"{c:>22}" for c in CONDS)
    print(hdr2)
    print("-" * len(hdr2))
    any_reasoning = False
    for m in models:
        vals = {c: reasoning_stats(root, m, c) for c in CONDS}
        if not any(vals.values()):
            continue
        any_reasoning = True
        row = f"{m:<24}"
        for c in CONDS:
            v = vals[c]
            if v is None:
                row += f"  {'—':>20}"
            else:
                row += f"  C{v['C']:>2} D{v['D']:>2} N{v['N']:>2} ({v['cd_lean']:+.2f})"
        print(row)
    if not any_reasoning:
        print(
            "(no reasoning-classifier output found — run philosophy-bench-classify-reasoning first)"
        )


if __name__ == "__main__":
    main()
