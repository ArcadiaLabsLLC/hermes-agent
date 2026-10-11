#!/usr/bin/env bash
# The idle-box lane: the files on scripts/test_idle_box_files.txt, one worker,
# on a box nothing else is running a suite on.
#
#   scripts/run_tests_idle.sh            # refuse if a suite is running; else run the list and record it
#   scripts/run_tests_idle.sh --check    # only say whether the box is idle (exit 0 idle, 3 busy)
#
# Owner ruling 2026-10-10: the turn-cost / timing files keep their absolute
# budgets and run only on an idle box, serial, never inside a parallel gate
# (docs/agent-runtime-harness/planned/design-sweep-d3-2026-10-10.md § D3.01).
# Their tests skip unless HERMES_TEST_IDLE_BOX=1 (tests/_downstream/idle_box.py)
# and the bundled gate does not select them; this script is the only runner
# that sets it.
#
# The environment is not re-spelled here: like run_tests_bundled.sh, this
# script SOURCES run_tests.sh and intercepts only its final
# `exec env -i … "$PYTHON" "$RUNNER_PATH" "$@"`, adding HERMES_TEST_IDLE_BOX=1
# to the hermetic environment. The run then appends one line,
# {"kind": "idle", …}, to .pytest_cache/hermes_bundled_runs.jsonl; quote it in
# the landing report.

set -euo pipefail

if shopt -oq posix; then
  echo "error: run_tests_idle.sh needs bash outside POSIX mode (a function must shadow 'exec')" >&2
  exit 2
fi

__IDLE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
__IDLE_REPO="$(cd "$__IDLE_DIR/.." && pwd)"
__IDLE_ENV="HERMES_TEST_IDLE_BOX"

# Every live process running pytest or a suite runner, as "<pid> <command line>",
# this lane's own processes excepted.
busy_processes() {
  if command -v powershell.exe >/dev/null 2>&1; then
    powershell.exe -NoProfile -NonInteractive -Command \
      "Get-CimInstance Win32_Process | Where-Object { \$_.ProcessId -ne \$PID -and \$_.CommandLine -match 'pytest|run_tests' -and \$_.CommandLine -notmatch 'run_tests_idle' } | ForEach-Object { '{0} {1}' -f \$_.ProcessId, \$_.CommandLine }" \
      | tr -d '\r'
  else
    ps -eo pid=,args= | grep -E 'pytest|run_tests' | grep -v -E 'run_tests_idle|grep -E' || true
  fi
}

# The hermetic run of the given files, HERMES_TEST_IDLE_BOX=1 added after `env -i`.
run_listed() {
  exec() {
    # run_tests.sh re-executes ITSELF under run-in-hermes-env when the checkout's
    # environment is stale; re-enter this script instead (inner pass: no busy
    # check, no record — the outer pass owns both).
    if [ "$#" -ge 3 ] && [ "$1" = "$__IDLE_DIR/run-in-hermes-env" ]; then
      export __HERMES_IDLE_INNER=1
      builtin exec "$1" "$2" "$__IDLE_DIR/run_tests_idle.sh" "${@:4}"
    fi
    if [ "$#" -ge 3 ] && [ "$1" = env ] && [ "$2" = -i ]; then
      builtin exec env -i "$__IDLE_ENV=1" "${@:3}"
    fi
    echo "error: run_tests.sh's exec is no longer \`env -i …\` — run_tests_idle.sh is out of date" >&2
    builtin exit 2
  }
  export HERMES_TEST_WORKERS=1
  # shellcheck source=run_tests.sh
  source "$__IDLE_DIR/run_tests.sh" "$@"
  echo "error: run_tests.sh returned without exec'ing a runner — run_tests_idle.sh is out of date" >&2
  exit 2
}

if [ "${__HERMES_IDLE_INNER:-}" = 1 ]; then
  run_listed "$@"
fi

busy="$(busy_processes)"
if [ -n "$busy" ]; then
  echo "refusing: the box is not idle — timing files run on an idle box only (owner ruling 2026-10-10)." >&2
  echo "running suite processes:" >&2
  printf '  %s\n' "$busy" >&2
  exit 3
fi
if [ "${1:-}" = "--check" ]; then
  echo "idle: no pytest or suite runner process is alive"
  exit 0
fi

files=()
while IFS= read -r line; do
  entry="${line%%#*}"
  entry="$(printf '%s' "$entry" | tr -d '\r' | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')"
  [ -n "$entry" ] && files+=("$entry")
done < "$__IDLE_DIR/test_idle_box_files.txt"
if [ "${#files[@]}" -eq 0 ]; then
  echo "error: scripts/test_idle_box_files.txt names no file" >&2
  exit 2
fi

mkdir -p "$__IDLE_REPO/.pytest_cache"
log="$__IDLE_REPO/.pytest_cache/hermes_idle_last.log"
started="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
t0="$(date +%s)"
set +e
( run_listed "${files[@]}" ) 2>&1 | tee "$log"
rc="${PIPESTATUS[0]}"
set -e
seconds="$(( $(date +%s) - t0 ))"

json_str() { printf '"%s"' "$(printf '%s' "$1" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g')"; }
summary="$(grep -a '=== Summary' "$log" | tail -n 1 | tr -d '\r' || true)"
listed=""
for f in "${files[@]}"; do listed="${listed:+$listed, }$(json_str "$f")"; done
record="{\"kind\": \"idle\", \"t\": \"$started\", \"seconds\": $seconds, \"rc\": $rc, \"workers\": 1, \"files\": [$listed], \"summary\": $(json_str "$summary")}"
printf '%s\n' "$record" >> "$__IDLE_REPO/.pytest_cache/hermes_bundled_runs.jsonl"
echo "▶ idle-box record: $record"
exit "$rc"
