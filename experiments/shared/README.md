# Shared Harness

Shared experiment infrastructure is the package CLI and engine:

- `philosophy-bench scenarios --root experiments/<name>/data/scenarios`
- `philosophy-bench run --model opus-4.7 --root experiments/<name>/data/scenarios --output experiments/<name>/results`
- `philosophy-bench prime --model opus-4.7 --conditions baseline --root experiments/<name>/data/scenarios --output experiments/<name>/results`

Keep reusable code in `src/philosophy_bench/`. Keep experiment-only scripts in
the experiment's own `harness/` directory.

Default CLI paths point at the repo-level C-vs-D data under
`experiments/c_vs_d/data`.
