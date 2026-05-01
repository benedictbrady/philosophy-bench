"""Bundled-data path resolution.

Use `importlib.resources.files()` so paths work both in editable installs
(repo checkout) and in wheel installs from PyPI. Imported by both `cli.py`
and the analysis modules; kept separate from `cli.py` so analysis scripts
don't pull in click + rich just to get a path constant.
"""

from __future__ import annotations

from importlib.resources import files
from pathlib import Path

_DATA_ROOT = files("philosophy_bench") / "data"


def _repo_c_vs_d_data_root() -> Path | None:
    """Return the repo-level C-vs-D experiment data root when running from source.

    Wheels still use the bundled package-data mirror below. This keeps default
    commands backward-compatible for installed users while making the source
    checkout's first-class experiment layout the default during development.
    """
    repo_root = Path(__file__).resolve().parents[2]
    root = repo_root / "experiments" / "c_vs_d" / "data"
    return root if (root / "scenarios").is_dir() else None


_C_VS_D_DATA_ROOT = _repo_c_vs_d_data_root()

if _C_VS_D_DATA_ROOT is not None:
    DEFAULT_SCENARIO_ROOT = str(_C_VS_D_DATA_ROOT / "scenarios")
    PRIMING_DIR = _C_VS_D_DATA_ROOT / "primers"
    ASK_POLES = _C_VS_D_DATA_ROOT / "ask_poles.yaml"
else:
    DEFAULT_SCENARIO_ROOT = str(_DATA_ROOT / "scenarios")
    PRIMING_DIR = _DATA_ROOT / "primers"
    ASK_POLES = _DATA_ROOT / "ask_poles.yaml"
