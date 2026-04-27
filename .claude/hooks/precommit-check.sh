#!/usr/bin/env bash
# Pre-commit CI gate. Runs the same checks as .github/workflows/ci.yml.
# If any fail, emits a PreToolUse `deny` decision so the commit is blocked
# and the failure surfaces in the model's transcript.
#
# Wired up by .claude/settings.json as a PreToolUse hook on
# `Bash(git commit *)`. Invoked by Claude Code; not meant for manual use,
# but you can run it directly to sanity-check the gate.

set -uo pipefail

cd "$(dirname "$0")/../.." || exit 1

OUT=$(uv run ruff format --check src tests 2>&1 \
   && uv run ruff check src tests 2>&1 \
   && uv run pytest -q --strict-markers -m "not integration" 2>&1)
RC=$?

if [ "$RC" -ne 0 ]; then
  jq -nc \
    --arg reason "Pre-commit CI gate failed (exit $RC). Fix locally before committing.

$OUT" \
    '{hookSpecificOutput:{hookEventName:"PreToolUse",permissionDecision:"deny",permissionDecisionReason:$reason}}'
fi
