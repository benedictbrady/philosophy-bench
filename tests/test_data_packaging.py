"""Tests that the bundled data is reachable via importlib.resources.

Critical for catching the `pip install` vs editable-install path bug — the
old `Path(__file__).parent.parent.parent / "priming"` resolution worked
in the editable monorepo layout but pointed at a missing directory once
the package was installed from a wheel."""

from __future__ import annotations

from click.testing import CliRunner

from philosophy_bench.cli import cli
from philosophy_bench.engine import load_all_scenarios
from philosophy_bench.paths import ASK_POLES, DEFAULT_SCENARIO_ROOT, EXPERIMENT_ROOT, PRIMING_DIR


def test_scenarios_dir_resolvable():
    """DEFAULT_SCENARIO_ROOT must be a real, populated directory after install."""
    from pathlib import Path

    p = Path(DEFAULT_SCENARIO_ROOT)
    assert p.is_dir(), f"scenarios dir not resolvable: {DEFAULT_SCENARIO_ROOT}"
    yamls = list(p.rglob("*.yaml"))
    assert len(yamls) == 100, f"expected 100 scenarios, found {len(yamls)}"


def test_primer_files_resolvable():
    for label in ("baseline", "c_direct", "d_direct"):
        path = PRIMING_DIR / f"{label}_primer.txt"
        text = path.read_text()
        assert text.strip(), f"{label}_primer.txt is empty"


def test_ask_poles_resolvable():
    text = ASK_POLES.read_text()
    assert "c_asked" in text and "d_asked" in text and "neutral" in text


def test_expediency_correctness_experiment_resolvable():
    root = EXPERIMENT_ROOT / "expediency_vs_correctness"
    specs = load_all_scenarios(root)
    assert len(specs) == 100
    assert {s.category for s in specs} == {"shortcut_vs_rigor"}
    for spec in specs:
        scores = {c.cd_score for c in spec.response_clusters}
        assert {1, -1}.issubset(scores), spec.id


def test_cli_scenarios_command_loads_100():
    runner = CliRunner()
    result = runner.invoke(cli, ["scenarios"])
    assert result.exit_code == 0, result.output
    assert "Loaded 100 scenarios" in result.output


def test_cli_models_command_lists_providers():
    runner = CliRunner()
    result = runner.invoke(cli, ["models"])
    assert result.exit_code == 0
    # At least one model from each shipped provider
    for needle in ("opus-4.7", "gpt-5.4", "gemini-3.1-pro", "deepseek-v3.2"):
        assert needle in result.output, f"{needle} missing from `models` output"
