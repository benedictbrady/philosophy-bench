# Philosophy Bench

[![ci](https://github.com/benedictbrady/philosophy-bench/actions/workflows/ci.yml/badge.svg)](https://github.com/benedictbrady/philosophy-bench/actions/workflows/ci.yml)
[![license: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![data: CC-BY-4.0](https://img.shields.io/badge/data-CC--BY--4.0-orange.svg)](LICENSE-DATA)
[![python: 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](pyproject.toml)

A behavioral benchmark for how LLM agents resolve **consequentialist** vs
**deontological** trade-offs in realistic tool-use settings.

## What it is

100 scenarios where the outcome-maximizing action breaks a rule and the
rule-honoring action sacrifices the outcome. Each scenario runs in a mocked
tool environment (CRM, code repo, support, warehouse), and a 3-judge majority
panel classifies the agent's transcript into one of 3–5 authored response
clusters. Clusters carry a signed `cd_score ∈ {-1, 0, +1}` (deontological /
compromise / consequentialist) plus a `botched` flag for refusal/evasion.

Aggregating cluster picks across scenarios gives a per-model `cd_mean`
(framework lean), `botch_rate` (how often the model refuses), and
`engagement_weighted_cd_mean = cd_mean × (1 − botch_rate)` (which punishes
models that look "cleaner" only by refusing hard cases). See `SCORING.md`
for the full rubric.

## Results

This repo ships public Opus 4.7 artifacts under each experiment's `results/`
directory. The original C-vs-D run lives at
`experiments/c_vs_d/results/opus-4.7/`. For data on other models, reach out to
Benedict Brady.

## Install

```bash
uv pip install philosophy-bench
cp .env.example .env       # add at least one provider key
```

You only need keys for providers you actually plan to call. Missing keys
produce a clear error at the first API call, not at import time.

## Quickstart

```bash
philosophy-bench models                    # list registered models (29)
philosophy-bench scenarios                 # validate the default C-vs-D corpus
philosophy-bench run -m opus-4.7 --limit 5 # smoke test (5 scenarios)
```

For development:

```bash
git clone https://github.com/benedictbrady/philosophy-bench
cd philosophy-bench
uv sync --extra dev
uv run pytest                              # 672 tests, ~2s
```

## Methodology

See `SCORING.md` for the canonical rubric. In brief:

- **`cd_score`** (`-1`, `0`, `+1`): a signed label on each authored response
  cluster. `+1` is consequentialist (outcome-maximizing, rule-breaking);
  `-1` is deontological (rule-honoring, outcome-sacrificing); `0` is a
  compromise both frameworks can endorse.
- **`botched: true`**: refuse / evade / incompetent — neither framework
  endorses it. Botched clusters have `cd_score: null` and feed the
  `botch_rate`, not the `cd_mean`.
- **Authoring rule** (enforced in CI by `tests/test_scenario_corpus.py`):
  every scenario has at least one `cd_score=+1` cluster AND at least one
  `cd_score=-1` cluster. Without that pair, it is not a real C/D dilemma.
- **Judge panel**: by default 3 judges run in parallel
  (`opus-4.7`, `gpt-5.4`, `gemini-3.1-pro`) and majority-vote. The judge
  sees the cluster descriptions and behavioral signals only — never the
  `cd_score` labels and never the author's `judge_rubric` field, both of
  which would prime the verdict.
- **Aggregates**: `cd_mean`, `cd_stdev`, `botch_rate`,
  `engagement_weighted_cd_mean`, plus per-category breakdowns.

## Adding a model or scenario

`philosophy-bench` ships with 29 models across 4 providers. To add a model
from a registered provider, edit `MODEL_REGISTRY` in
`src/philosophy_bench/providers.py`. To add a scenario to the original C-vs-D
experiment, copy `tests/fixtures/synthetic_scenario.yaml` into
`experiments/c_vs_d/data/scenarios/<category>/<your-id>.yaml`, mirror it under
`src/philosophy_bench/data/scenarios/` for wheel compatibility, and follow the
authoring rule above. Validate with `philosophy-bench scenarios` and
`pytest tests/test_scenario_corpus.py`.

## Results format

`philosophy-bench prime` produces:

```
experiments/c_vs_d/results/<model>/<condition>/
  ├── runs/<scenario_id>.json   # per-scenario raw transcripts (checkpointed)
  ├── judged.json               # judge verdicts merged into runs
  └── summary.json              # cd_mean, cd_stdev, botch_rate + breakdowns
```

The authoritative `summary.json` shape is in
`src/philosophy_bench/scoring.py:score_run`.

## Reproducing the shipped Opus 4.7 results

```bash
philosophy-bench prime \
  --model opus-4.7 \
  --conditions baseline,c_direct,d_direct \
  --judge-model opus-4.7 \
  --judge-model gpt-5.4 \
  --judge-model gemini-3.1-pro \
  --output experiments/c_vs_d/results
```

Note: `claude-opus-4-7` is an Anthropic API alias — exact transcript-level
reproduction will drift as the underlying snapshot migrates.

## Citation

```bibtex
@software{philosophy_bench_2026,
  author  = {Brady, Benedict and Mandel, Matt},
  title   = {Philosophy Bench},
  year    = {2026},
  version = {0.1.0},
  url     = {https://www.philosophybench.com/}
}
```

## License

- **Code**: MIT — see `LICENSE`
- **Data** (experiment scenarios/results in `experiments/` plus the bundled
  compatibility mirror in `src/philosophy_bench/data/`): CC-BY-4.0 — see
  `LICENSE-DATA`
