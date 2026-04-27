"""Every shipped scenario YAML parses and validates against ScenarioSpec.

`test_scenario_corpus.py` already loads the corpus at module-collection time
to power its parametrized authoring-rule tests, so a malformed file would
manifest as an opaque pytest collection error pointing at that file's import
rather than at the bad scenario. This test runs first (alphabetically) and
fails with a per-file message naming exactly which scenarios broke and why.
"""

from __future__ import annotations

from pathlib import Path

from philosophy_bench.engine import load_all_scenarios, load_scenario
from philosophy_bench.paths import DEFAULT_SCENARIO_ROOT

_ROOT = Path(DEFAULT_SCENARIO_ROOT)


def test_every_scenario_yaml_parses_and_validates():
    paths = sorted(_ROOT.rglob("*.yaml"))
    assert len(paths) == 100, f"expected 100 scenario files; found {len(paths)}"
    failures = []
    for p in paths:
        try:
            load_scenario(p)
        except Exception as e:  # noqa: BLE001
            failures.append(f"  {p.relative_to(_ROOT)}: {e}")
    assert not failures, "scenarios failed to load:\n" + "\n".join(failures)


def test_load_all_scenarios_returns_full_corpus():
    specs = load_all_scenarios(DEFAULT_SCENARIO_ROOT)
    assert len(specs) == 100
    assert len({s.id for s in specs}) == 100, "duplicate scenario ids"
