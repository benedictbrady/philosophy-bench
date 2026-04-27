"""Per-model user-compliance rates over the C-asked / D-asked scenario pools.

Joins `data/ask_poles.yaml` (the canonical 37 C-asked / 37 D-asked / 26
neutral split — i.e., which framework the user-side pressure pushes the
agent toward) with each model's `<root>/<model>/<cond>/summary.json`
(produced by `philosophy-bench prime`), and reports two compliance rates
per (model, condition):

  cAsked: % of C-asked scenarios where the model picked the +1 cluster
          (i.e., complied with the user's consequentialist push)
  dAsked: % of D-asked scenarios where the model picked the -1 cluster
          (i.e., complied with the user's deontological push)

Output formats:

  json (default) — one JSON object per condition, keyed by model
  tsv            — condition\\tmodel\\tcAsked\\tdAsked, one row per (cond, model)

Models are discovered from the filesystem under `--root`. Pass `--root` to
point at a different results tree (default: results).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

from philosophy_bench.paths import ASK_POLES

DEFAULT_ROOT = Path("results")
CONDITIONS = ("baseline", "d_direct", "c_direct")


def load_labels(labels_path) -> tuple[set[str], set[str], set[str]]:
    if hasattr(labels_path, "read_text"):
        data = yaml.safe_load(labels_path.read_text())
    else:
        with open(labels_path) as f:
            data = yaml.safe_load(f)
    c = set(data["c_asked"])
    d = set(data["d_asked"])
    n = set(data["neutral"])
    overlap = (c & d) | (c & n) | (d & n)
    if overlap:
        sys.exit(f"ask_poles.yaml has cross-pool overlap: {sorted(overlap)}")
    return c, d, n


def compute(summary_path: Path, c_set: set[str], d_set: set[str]) -> tuple[int, int] | None:
    if not summary_path.exists():
        return None
    s = json.loads(summary_path.read_text())
    picks = {
        e["scenario_id"]: e.get("cd", {}).get("cd_score") if e.get("cd") else None
        for e in s.get("per_scenario", [])
    }
    c_comply = sum(1 for sid in c_set if picks.get(sid) == 1)
    d_comply = sum(1 for sid in d_set if picks.get(sid) == -1)
    c_pct = round(c_comply / len(c_set) * 100) if c_set else 0
    d_pct = round(d_comply / len(d_set) * 100) if d_set else 0
    return c_pct, d_pct


def discover_models(root: Path) -> list[str]:
    return sorted(d.name for d in root.iterdir() if d.is_dir() and not d.name.startswith("_"))


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--root", default=str(DEFAULT_ROOT), help=f"Results root dir (default: {DEFAULT_ROOT})"
    )
    ap.add_argument(
        "--labels", default=None, help="Path to ask_poles.yaml (default: bundled with package)"
    )
    ap.add_argument("--format", choices=("json", "tsv"), default="json")
    ap.add_argument(
        "--conditions",
        default=",".join(CONDITIONS),
        help=f"Comma-separated conditions (default: {','.join(CONDITIONS)})",
    )
    args = ap.parse_args()

    root = Path(args.root)
    if not root.is_dir():
        sys.exit(f"results dir not found: {root}")

    labels_path = args.labels if args.labels else ASK_POLES
    c_set, d_set, _ = load_labels(labels_path)

    conditions = [c.strip() for c in args.conditions.split(",") if c.strip()]
    models = discover_models(root)

    by_cond: dict[str, dict[str, dict]] = {cond: {} for cond in conditions}
    for cond in conditions:
        for m in models:
            r = compute(root / m / cond / "summary.json", c_set, d_set)
            if r is None:
                print(f"# MISSING: {m} ({cond})", file=sys.stderr)
                continue
            by_cond[cond][m] = {"cAsked": r[0], "dAsked": r[1]}

    if args.format == "tsv":
        print("condition\tmodel\tcAsked\tdAsked")
        for cond in conditions:
            for m in sorted(by_cond[cond]):
                row = by_cond[cond][m]
                print(f"{cond}\t{m}\t{row['cAsked']}\t{row['dAsked']}")
    else:
        json.dump(by_cond, sys.stdout, indent=2)
        sys.stdout.write("\n")


if __name__ == "__main__":
    main()
