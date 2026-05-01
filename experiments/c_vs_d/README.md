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

For backward compatibility, the same scenario and primer data is mirrored under
`src/philosophy_bench/data/` so wheel installs can still run the default
benchmark without needing the repo checkout. Source checkouts prefer this
experiment directory as the default path.

Run it with:

```bash
philosophy-bench prime \
  --model opus-4.7 \
  --conditions baseline,c_direct,d_direct \
  --root experiments/c_vs_d/data/scenarios \
  --output experiments/c_vs_d/results
```
