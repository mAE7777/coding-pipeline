#!/bin/bash
# Runs every deterministic test of the pipeline (scripts, hooks, fixtures) and the static checks.
# Prints PASS/FAIL per suite and exits nonzero if any suite fails. Re-run after any change to any
# pipeline file, not only the file that changed.
# Usage: tests/pipeline-selftest.sh [--static-only]

set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(dirname "$HERE")"
FAILS=0

suite() {
  local name="$1"; shift
  local out
  if out=$("$@" 2>&1); then
    printf 'PASS   %-34s %s\n' "$name" "$(printf '%s\n' "$out" | tail -1)"
  else
    printf 'FAIL   %-34s\n' "$name"
    printf '%s\n' "$out" | tail -25 | sed 's/^/       /'
    FAILS=$((FAILS + 1))
  fi
}

if [ "${1:-}" != "--static-only" ]; then
  for t in "$HERE"/test_*.py; do
    suite "$(basename "$t" .py)" python3 "$t"
  done
  # The local overlay (never published) carries its own tests when it is present.
  for t in "$ROOT"/private/tests/test_*.py; do
    [ -f "$t" ] && suite "private/$(basename "$t" .py)" python3 "$t"
  done
fi

suite "static-checks" python3 "$HERE/static_checks.py" "$ROOT"

echo
if [ $FAILS -eq 0 ]; then
  echo "pipeline-selftest: PASS"
else
  echo "pipeline-selftest: FAIL ($FAILS suite(s))"
fi
[ $FAILS -eq 0 ]
