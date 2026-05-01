# Expediency vs Correctness

This pack contains 100 task scenarios where the user gives an objective without
fully specifying the implementation details. The key measurement is whether the
agent takes the fast plausible route or the more correct route after inspecting
the state available through tools.

```bash
philosophy-bench scenarios --root experiments/expediency_vs_correctness/data/scenarios
philosophy-bench run \
  --model opus-4.7 \
  --root experiments/expediency_vs_correctness/data/scenarios \
  --output experiments/expediency_vs_correctness/results
```

Public results in this directory are limited to Opus 4.7 artifacts.
