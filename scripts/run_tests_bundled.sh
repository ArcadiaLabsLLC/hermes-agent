#!/usr/bin/env bash
# Bundled variant of scripts/run_tests.sh: the SAME hermetic environment, with
# scripts/run_tests_bundled.py (N test files per pytest process) as the runner.
#
#   scripts/run_tests_bundled.sh tests/agent_runtime tests/hermes_cli tests/hermes_state  # landing gate: --scope fork (default)
#   scripts/run_tests_bundled.sh --scope full tests/agent_runtime tests/hermes_cli tests/hermes_state  # weekly upstream merge lane
#   scripts/run_tests_bundled.sh --bundle-size 10 tests/hermes_cli -q
#
# --scope fork runs the files absent from tests/fixtures/upstream_manifest.txt
# plus the inherited files the change (git diff <--since, default origin/main>...HEAD)
# reaches; --scope full runs every discovered file.
#
# The environment is not re-spelled here. This script SOURCES run_tests.sh —
# venv probe, `env -i` allowlist, Windows location variables, the fence's real
# store root, bytecode pre-compile — and intercepts only its final
# `exec env -i … "$PYTHON" "$RUNNER_PATH" "$@"`, swapping the runner path for
# the bundled one. So an env var added to run_tests.sh's allowlist reaches the
# bundled runner with no edit here.
#
# Fails loud rather than silently running the per-file runner: if run_tests.sh
# stops ending in that exec, or the exec no longer names $RUNNER_PATH, this
# script exits 2 and says so.

set -euo pipefail

if shopt -oq posix; then
  echo "error: run_tests_bundled.sh needs bash outside POSIX mode (a function must shadow 'exec')" >&2
  exit 2
fi

__BUNDLED_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

exec() {
  if [ -z "${RUNNER_PATH:-}" ]; then
    echo "error: run_tests.sh reached exec without setting RUNNER_PATH — the bundled wrapper is out of date" >&2
    builtin exit 2
  fi
  local bundled="${RUNNER_PATH%run_tests_parallel.py}run_tests_bundled.py"
  if [ "$bundled" = "$RUNNER_PATH" ]; then
    echo "error: RUNNER_PATH ($RUNNER_PATH) no longer names run_tests_parallel.py — the bundled wrapper is out of date" >&2
    builtin exit 2
  fi
  local swapped=0
  local argv=()
  local arg
  for arg in "$@"; do
    if [ "$swapped" = 0 ] && [ "$arg" = "$RUNNER_PATH" ]; then
      argv+=("$bundled")
      swapped=1
    else
      argv+=("$arg")
    fi
  done
  if [ "$swapped" = 0 ]; then
    echo "error: run_tests.sh's exec no longer passes \$RUNNER_PATH — the bundled wrapper is out of date" >&2
    builtin exit 2
  fi
  echo "▶ bundled runner: $bundled"
  builtin exec "${argv[@]}"
}

# shellcheck source=run_tests.sh
source "$__BUNDLED_DIR/run_tests.sh" "$@"

echo "error: run_tests.sh returned without exec'ing a runner — the bundled wrapper is out of date" >&2
exit 2
