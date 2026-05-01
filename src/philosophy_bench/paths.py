"""Default repo-level experiment paths.

Experiment data lives under ``experiments/``. This module is imported by both
``cli.py`` and analysis modules; keeping it separate avoids importing click and
rich just to get path constants.
"""

from __future__ import annotations

from pathlib import Path


def _repo_root() -> Path:
    """Find the checkout root that owns the experiment packs."""
    candidates = [Path.cwd(), *Path.cwd().parents, Path(__file__).resolve().parents[2]]
    for candidate in candidates:
        if (candidate / "experiments" / "c_vs_d" / "data" / "scenarios").is_dir():
            return candidate
    return Path.cwd()


EXPERIMENT_ROOT = _repo_root() / "experiments"
C_VS_D_DATA_ROOT = EXPERIMENT_ROOT / "c_vs_d" / "data"

DEFAULT_SCENARIO_ROOT = str(C_VS_D_DATA_ROOT / "scenarios")
PRIMING_DIR = C_VS_D_DATA_ROOT / "primers"
ASK_POLES = C_VS_D_DATA_ROOT / "ask_poles.yaml"
