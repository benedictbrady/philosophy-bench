#!/usr/bin/env bash
# Run the stability-pairs experiment with baseline priming.
# Defaults to Opus 4.7 so the public repo only ships one model's result artifacts.
set -u
EXP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
REPO_ROOT="$(cd "$EXP_DIR/../.." && pwd)"
cd "$REPO_ROOT"

ENV_FILE="${PHIL_BENCH_ENV:-}"
if [[ -z "$ENV_FILE" ]]; then
  if [[ -f "$REPO_ROOT/.env" ]]; then
    ENV_FILE="$REPO_ROOT/.env"
  elif [[ -f "$REPO_ROOT/../bench/.env" ]]; then
    ENV_FILE="$REPO_ROOT/../bench/.env"
  fi
fi
if [[ -n "$ENV_FILE" && -f "$ENV_FILE" ]]; then
  set -a
  source "$ENV_FILE"
  set +a
fi

ROOT="$EXP_DIR/data/scenarios"
OUT="$EXP_DIR/results"
CLI="$PWD/.venv/bin/philosophy-bench"

LOG_DIR="$OUT/_logs"
mkdir -p "$LOG_DIR"

MODEL_LIST="${MODEL_LIST:-opus-4.7}"
IFS=',' read -r -a MODELS <<< "$MODEL_LIST"

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
  tail -3 "$LOG_DIR/${m}.log" | grep -E "axis_mean|error|Error" || echo "(no summary line)"
done
