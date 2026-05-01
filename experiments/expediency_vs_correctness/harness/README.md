# Harness

This experiment uses the shared `philosophy-bench` CLI directly. It does not
need experiment-specific runner or analysis code yet.

Run it with:

```bash
philosophy-bench run \
  --model opus-4.7 \
  --root experiments/expediency_vs_correctness/data/scenarios \
  --output experiments/expediency_vs_correctness/results
```
