"""Analysis utilities that operate on a `results/` tree produced by
`philosophy-bench run` or `philosophy-bench prime`.

Each module exposes a `main()` entry point and is wired as a console_script
in pyproject.toml (philosophy-bench-report, philosophy-bench-obedience,
philosophy-bench-classify-reasoning, philosophy-bench-audit) and is also
runnable via `python -m philosophy_bench.analysis.<module>`.
"""
