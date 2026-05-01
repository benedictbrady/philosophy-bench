"""Bundled-data path resolution.

Use `importlib.resources.files()` so paths work both in editable installs
(repo checkout) and in wheel installs from PyPI. Imported by both `cli.py`
and the analysis modules; kept separate from `cli.py` so analysis scripts
don't pull in click + rich just to get a path constant.
"""

from __future__ import annotations

from importlib.resources import files

_DATA_ROOT = files("philosophy_bench") / "data"

DEFAULT_SCENARIO_ROOT = str(_DATA_ROOT / "scenarios")
PRIMING_DIR = _DATA_ROOT / "primers"
ASK_POLES = _DATA_ROOT / "ask_poles.yaml"
