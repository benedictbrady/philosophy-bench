# Experiments

Repo-level experiment packs live here. Each experiment keeps its own harness,
scenario data, and tracked result artifacts in a predictable layout:

```text
experiments/<experiment_name>/
  harness/          experiment-specific scripts and analysis
  data/scenarios/   YAML scenarios for the experiment
  results/          checked-in public artifacts, limited to Opus 4.7
```

Current public experiment packs:

- `c_vs_d`: the original consequentialism-vs-deontology priming benchmark.
- `expediency_vs_correctness`: underspecified objectives where the model can
  take a plausible shortcut or inspect enough state to do the correct thing.
- `stability_pairs`: A/B mirror pairs for advocacy-framing sensitivity.

Shared benchmark code remains in `src/philosophy_bench/`. Experiment harnesses
call the same `philosophy-bench` CLI unless they need experiment-specific audit
or analysis scripts.
