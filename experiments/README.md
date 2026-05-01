# Experiments

Repo-level experiment packs live here. Each experiment keeps its own harness,
scenario data, and tracked result artifacts in a predictable layout:

```text
experiments/<experiment_name>/
  harness/          experiment-specific scripts and analysis
  data/scenarios/   YAML scenarios for the experiment
  results/          checked-in public artifacts, limited to Opus 4.7
```

Shared benchmark code remains in `src/philosophy_bench/`. The experiment
harnesses call the same `philosophy-bench` CLI rather than maintaining separate
runners.
