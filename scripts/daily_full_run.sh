#!/usr/bin/env bash
# scripts/daily_full_run.sh — the once-a-day breadth run (FH-DAILY-FULL-RUN, owner 2026-11-08:
# "also on the daily launcher run we also need to run the full gates and fork tests"). Eternia's
# daily run (`tool/daily/full_run.dart`, row QA-DAILY-RUN-HERMES-STEPS) calls it, so one scheduled
# run covers both repos. It is a COMMAND, not a hook, and never pushes anything.
#
# Steps, in order, each its own log (`<out>/<step>.log`, ending `EXIT=<code>`) and timeout:
#   suite     the whole fork suite, every file once: `scripts/run_tests.sh`
#   gates     the prepush queue and text gates, in full (`scripts/prepush.sh --list-gates`)
#   doc-cite  `scripts/doc_cite_adjacency.py --exclude archive --exclude planned`
#   census    both name census gates whatever was touched (`scripts/prepush.sh --list-census`)
#   tooling   every whole-tree gate: `scripts/run_tests.sh tests/tooling`
# Every step runs even after a red. The run ends with a summary (`<out>/summary.txt` too) naming
# each red, its log, the red test files the log names, and the row it owes: every red is filed
# into its domain queue and fixed the same day, whether or not it was already on main.
#
# Usage:
#   scripts/daily_full_run.sh [--out=<dir>]          # default _lane_logs/daily-<UTC date>
#   scripts/daily_full_run.sh --dry-run [--out=<dir>]  # print the steps, run nothing
#   scripts/daily_full_run.sh --only=<step>[,<step>]   # a subset, same logs and summary
# Exit: 0 every step green · 1 any red or timeout · 2 usage.
#
# Environment:
#   DAILY_<STEP>_TIMEOUT  whole seconds (STEP = SUITE, GATES, DOC_CITE, CENSUS, TOOLING).
#   DAILY_JOBS            the runner's worker cap (default 24, the box's measured best).
#   DAILY_RUNNER / DAILY_PYTHON   the test runner (default scripts/run_tests.sh) and the
#                         doc-cite interpreter; both exist so the script's own test can drive it
#                         without running the suite.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT" || exit 2

STEPS=(suite gates doc-cite census tooling)
# A step's timeout (bash 3.2 has no associative arrays: macOS runs this too).
_timeout_of() {
  case "$1" in
    suite) echo "${DAILY_SUITE_TIMEOUT:-5400}" ;;
    gates) echo "${DAILY_GATES_TIMEOUT:-300}" ;;
    doc-cite) echo "${DAILY_DOC_CITE_TIMEOUT:-120}" ;;
    census) echo "${DAILY_CENSUS_TIMEOUT:-600}" ;;
    tooling) echo "${DAILY_TOOLING_TIMEOUT:-2400}" ;;
  esac
}
JOBS="${DAILY_JOBS:-24}"
OUT=""
DRY=0
ONLY=""
for arg in "$@"; do
  case "$arg" in
    --out=*) OUT="${arg#--out=}" ;;
    --dry-run) DRY=1 ;;
    --only=*) ONLY="${arg#--only=}" ;;
    -h|--help) sed -n '2,28p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *) echo "daily_full_run: unknown argument $arg (use --out=<dir>, --dry-run, --only=<steps>)" >&2; exit 2 ;;
  esac
done
[ -n "$OUT" ] || OUT="$REPO_ROOT/_lane_logs/daily-$(date -u +%Y-%m-%d)"
for step in "${STEPS[@]}"; do
  case "$(_timeout_of "$step")" in
    ''|*[!0-9]*|0) echo "daily_full_run: the $step timeout is not a positive whole number of seconds: '$(_timeout_of "$step")'" >&2; exit 2 ;;
  esac
done
case "$JOBS" in ''|*[!0-9]*|0) echo "daily_full_run: DAILY_JOBS is not a positive whole number: '$JOBS'" >&2; exit 2 ;; esac
SELECTED=("${STEPS[@]}")
if [ -n "$ONLY" ]; then
  SELECTED=()
  IFS=',' read -r -a wanted <<<"$ONLY"
  for step in "${wanted[@]}"; do
    case " ${STEPS[*]} " in
      *" $step "*) SELECTED+=("$step") ;;
      *) echo "daily_full_run: no such step '$step' (steps: ${STEPS[*]})" >&2; exit 2 ;;
    esac
  done
fi

RUNNER="${DAILY_RUNNER:-$SCRIPT_DIR/run_tests.sh}"
_default_python() {
  local venv="${HERMES_TEST_VENV:-$HOME/.venvs/hermes-test}" candidate
  for candidate in "$venv/Scripts/python.exe" "$venv/bin/python"; do
    [ -x "$candidate" ] && { echo "$candidate"; return; }
  done
  command -v python3 >/dev/null 2>&1 && { echo python3; return; }
  echo python
}
PY="${DAILY_PYTHON:-${HERMES_PYTHON:-$(_default_python)}}"

# The gate lists are prepush's own, so the daily run and every push run the same gates.
GATES=()
CENSUS=()
while IFS= read -r path; do [ -n "$path" ] && GATES+=("$path"); done < <(bash "$SCRIPT_DIR/prepush.sh" --list-gates)
while IFS= read -r path; do [ -n "$path" ] && CENSUS+=("$path"); done < <(bash "$SCRIPT_DIR/prepush.sh" --list-census)
if [ "${#GATES[@]}" -eq 0 ] || [ "${#CENSUS[@]}" -eq 0 ]; then
  echo "daily_full_run: scripts/prepush.sh named no gates (--list-gates / --list-census)" >&2
  exit 2
fi

_command() {
  case "$1" in
    suite) CMD=(bash "$RUNNER" -j "$JOBS") ;;
    gates) CMD=(bash "$RUNNER" -j "$JOBS" "${GATES[@]}") ;;
    doc-cite) CMD=("$PY" "$SCRIPT_DIR/doc_cite_adjacency.py" --exclude archive --exclude planned) ;;
    census) CMD=(bash "$RUNNER" -j "$JOBS" "${CENSUS[@]}") ;;
    tooling) CMD=(bash "$RUNNER" -j "$JOBS" tests/tooling) ;;
  esac
}

echo "daily_full_run — HEAD $(git rev-parse --short HEAD 2>/dev/null), logs in $OUT"
for step in "${SELECTED[@]}"; do
  _command "$step"
  echo "  step $step — timeout $(_timeout_of "$step")s — ${CMD[*]}"
done
[ "$DRY" = 1 ] && exit 0

mkdir -p "$OUT" || { echo "daily_full_run: cannot create $OUT" >&2; exit 2; }
if command -v timeout >/dev/null 2>&1; then
  HAVE_TIMEOUT=1
else
  HAVE_TIMEOUT=0
  echo "daily_full_run: no 'timeout' command here — the steps run without their timeouts" >&2
fi

REDS=()
SUMMARY=()
for step in "${SELECTED[@]}"; do
  _command "$step"
  log="$OUT/$step.log"
  started=$SECONDS
  echo "▶ $step (timeout $(_timeout_of "$step")s) → $log"
  {
    echo "# daily_full_run step $step — $(date -u +%Y-%m-%dT%H:%M:%SZ) — ${CMD[*]}"
    if [ "$HAVE_TIMEOUT" = 1 ]; then
      timeout --kill-after=30 "$(_timeout_of "$step")" "${CMD[@]}" </dev/null
    else
      "${CMD[@]}" </dev/null
    fi
  } >"$log" 2>&1
  rc=$?
  echo "EXIT=$rc" >>"$log"
  wall=$((SECONDS - started))
  if [ "$rc" -eq 0 ]; then
    SUMMARY+=("✔ $step ${wall}s")
    echo "✔ $step ${wall}s"
    continue
  fi
  if [ "$rc" -eq 124 ] || [ "$rc" -eq 137 ]; then
    what="timed out at $(_timeout_of "$step")s"
  else
    what="red (exit $rc)"
  fi
  REDS+=("$step")
  SUMMARY+=("✘ $step $what, ${wall}s — log $log — owes a row filed today in its domain queue (fork-hygiene for a gate or the runner)")
  echo "✘ $step $what, ${wall}s"
  # The red files the runner named, each a red to file and fix today.
  while IFS= read -r file; do
    [ -n "$file" ] && SUMMARY+=("    red: $file")
  done < <(grep -oE '^(  ║ )?FAILED [^: ]+' "$log" | sed -E 's/^(  ║ )?FAILED //' | sort -u)
done

{
  echo "daily_full_run summary — HEAD $(git rev-parse --short HEAD 2>/dev/null) — $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  for line in "${SUMMARY[@]}"; do echo "$line"; done
  if [ "${#REDS[@]}" -eq 0 ]; then
    echo "✔ daily_full_run: green (${#SELECTED[@]} step(s))"
  else
    echo "✘ daily_full_run: RED — ${REDS[*]} — file each red as a row the same day"
  fi
} | tee "$OUT/summary.txt"
[ "${#REDS[@]}" -eq 0 ]
