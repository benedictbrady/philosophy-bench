# Opus 4.7 results

This directory contains the results that ship with v0.1.0 of philosophy-bench:
Claude Opus 4.7 (`claude-opus-4-7`) evaluated on all 100 scenarios under three
priming conditions. 100 transcripts per condition (300 total), all 100 with
judge verdicts.

## How these were produced

```bash
philosophy-bench prime \
  --model opus-4.7 \
  --conditions baseline,c_direct,d_direct \
  --judge-model opus-4.7 \
  --judge-model gpt-5.4 \
  --judge-model gemini-3.1-pro \
  --tier strong_100
```

- **Run date**: April 2026
- **Target model**: `opus-4.7` → `claude-opus-4-7` (Anthropic API alias)
- **Judge panel** (3-judge majority vote): `opus-4.7`, `gpt-5.4`, `gemini-3.1-pro`
- **Scenarios**: all 100 in `src/philosophy_bench/data/scenarios/`
- **Conditions**:
  - `baseline` — generic helpful-assistant primer
  - `c_direct` — short consequentialist primer ("outcomes over rules")
  - `d_direct` — short deontological primer ("duties over outcomes")

## Layout

```
opus-4.7/
├── baseline/
│   ├── runs/<scenario_id>.json   # 100 per-scenario raw transcripts
│   ├── judged.json               # 100 judge verdicts
│   └── summary.json              # cd_mean, cd_stdev, botch_rate, breakdowns
├── c_direct/   (same structure)
└── d_direct/   (same structure)
```

The parent directory also has `opus-4.7_comparison.json`, a side-by-side
roll-up of the three condition summaries.

## Headline numbers

```
                          baseline       c_direct       d_direct       Δ (c−d)
opus-4.7  cd_mean         -0.33          -0.15          -0.40          +0.25
          botch_rate       0.15           0.05           0.09
          engagement_w    -0.28          -0.14          -0.36
```

A ~150-word philosophical primer shifts Opus 4.7's mean action axis by
~0.25 cd_mean units — small but real. Botch rate drops sharply under the
consequentialist primer (0.15 → 0.05) and modestly under the deontological
one (0.15 → 0.09): philosophical framing makes the model more decisive
about hard cases either way.

## Reproducing

`philosophy-bench prime` is deterministic in cluster classification given
the same model snapshots, but model temperature is 0.7 and Anthropic does
not currently expose a seed parameter — so individual transcripts may
differ between runs. Aggregate `cd_mean` across 100 scenarios is generally
stable to within ±0.02 across re-runs in our experience. Per-scenario
cluster verdicts may flip on borderline cases.

Note: `claude-opus-4-7` is an Anthropic API alias. As Anthropic deprecates
or migrates the underlying snapshot, exact reproductions against the alias
will drift. The scenario corpus and harness are version-stable; only the
model side moves.
