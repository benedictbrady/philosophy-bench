#!/usr/bin/env bash
# Run the 4-model × 100-yaml stability experiment with baseline priming.
# Each model runs in parallel as a background job; default 3-judge panel is used.
set -u
cd "$(dirname "$0")/.."

set -a
source ../bench/.env
set +a

ROOT="$PWD/stability_pairs/scenarios"
OUT="$PWD/stability_pairs/results"
CLI="$PWD/.venv/bin/philosophy-bench"

LOG_DIR="$OUT/_logs"
mkdir -p "$LOG_DIR"

MODELS=(opus-4.7 gpt-5.5 gemini-3.1-pro grok-4.2)

echo "Launching ${#MODELS[@]} models in parallel..."
for m in "${MODELS[@]}"; do
  "$CLI" prime --model "$m" --conditions baseline --root "$ROOT" --output "$OUT" \
    > "$LOG_DIR/${m}.log" 2>&1 &
  echo "  $m → $LOG_DIR/${m}.log (pid $!)"
done

wait
echo "All models complete."
for m in "${MODELS[@]}"; do
  echo "=== $m ==="
  tail -3 "$LOG_DIR/${m}.log" | grep -E "cd_mean|error|Error" || echo "(no summary line)"
done
