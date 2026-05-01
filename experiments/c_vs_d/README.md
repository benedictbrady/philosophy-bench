# C vs. D

This is the original Philosophy Bench experiment: 100 tool-use scenarios that
pit a consequentialist pole against a deontological pole.

The repo-level experiment data lives here:

```text
experiments/c_vs_d/
  data/scenarios/   scenario YAMLs
  data/primers/     baseline, C-direct, and D-direct primers
  data/ask_poles.yaml
  results/          checked-in public artifacts, limited to Opus 4.7
```

This directory is the canonical home for the original experiment data. Shared
Python code lives under `src/philosophy_bench/`; experiment data does not.

Run it with:

```bash
philosophy-bench prime \
  --model opus-4.7 \
  --conditions baseline,c_direct,d_direct \
  --root experiments/c_vs_d/data/scenarios \
  --output experiments/c_vs_d/results
```
