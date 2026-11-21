#!/usr/bin/env bash
# scripts/daily_full_run.sh — the once-a-day breadth run (FH-DAILY-FULL-RUN, owner 2026-11-08:
# "also on the daily launcher run we also need to run the full gates and fork tests"). Eternia's
# daily run (`tool/daily/full_run.dart`, row QA-DAILY-RUN-HERMES-STEPS) calls it, so one scheduled
# run covers both repos. It is a COMMAND, not a hook, and never pushes anything.
#
# Steps, in order, each its own log (`<out>/<step>.log`, ending `EXIT=<code>`) and timeout:
#   suite     the whole fork suite, every file once: `scripts/run_tests.sh`, minus the upstream skip
#             list (`tests/fixtures/upstream_skip_list.txt`: P0 freeze files, proven reds, ADR 0015
#             unused features), which no scope runs unnamed — `scripts/daily_suite_files.py` writes
#             `<out>/suite.files` (`--files-from`) and a `--deselect` per node row
#   gates     the prepush queue and text gates, in full (`scripts/prepush.sh --list-gates`)
#   doc-cite  `scripts/doc_cite_adjacency.py --exclude archive --exclude planned`
#   census    both name census gates whatever was touched (`scripts/prepush.sh --list-census`)
#   tooling   every whole-tree gate: `scripts/run_tests.sh tests/tooling`
# Every pytest step (suite, gates, census, tooling) also times each test: `<out>/<step>.timings.json`
# holds every test's node id, seconds and outcome, slowest first, and every test that started but never
# finished (hung, or killed at a timeout); the summary names those, every test over
# `SLOW_TEST_SECONDS` and the slowest few (`scripts/daily_test_timings.py`).
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
#                         doc-cite, suite-list and timings interpreter; both exist so the script's own test can drive it
#                         without running the suite; DAILY_PM_PYTHON, the managed node/pnpm resolver's.

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
    -h|--help) sed -n '2,35p' "${BASH_SOURCE[0]}"; exit 0 ;;
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

# Every pytest step times each test (row FH-DAILY-RUN-TIMES-EVERY-TEST, owner 2026-11-20): the plugin
# rides after `--`, which both runners forward to every pytest process unvalidated, and appends a
# start and an end line per test to `<out>/<step>.timings.d/<pid>.jsonl`; after the step,
# `scripts/daily_test_timings.py` folds them into `<out>/<step>.timings.json` and the summary lines.
case "$OUT" in /*|[A-Za-z]:*) ;; *) OUT="$REPO_ROOT/$OUT" ;; esac
_native() {  # a path a native Windows python can open (Git Bash's /c/... is not one)
  if command -v cygpath >/dev/null 2>&1; then cygpath -m "$1"; else printf '%s\n' "$1"; fi
}
_timed() { case "$1" in suite|gates|census|tooling) return 0 ;; esac; return 1; }

_command() {
  local timing=(-- -p scripts.daily_test_timings "--daily-test-timings=$(_native "$OUT/$1.timings.d")")
  case "$1" in
    suite) CMD=(bash "$RUNNER" -j "$JOBS" --files-from="$OUT/suite.files" ${SUITE_DESELECTS[@]+"${SUITE_DESELECTS[@]}"} "${timing[@]}") ;;
    gates) CMD=(bash "$RUNNER" -j "$JOBS" "${GATES[@]}" "${timing[@]}") ;;
    doc-cite) CMD=("$PY" "$SCRIPT_DIR/doc_cite_adjacency.py" --exclude archive --exclude planned) ;;
    census) CMD=(bash "$RUNNER" -j "$JOBS" "${CENSUS[@]}" "${timing[@]}") ;;
    tooling) CMD=(bash "$RUNNER" -j "$JOBS" tests/tooling "${timing[@]}") ;;
  esac
}

# The step's timing lines into SUMMARY (a never-finished test is echoed at once too); the raw
# per-process files go once the JSON holds them.
_fold_timings() {
  local dir="$OUT/$1.timings.d" json="$OUT/$1.timings.json" line rc=0 report
  report="$("$PY" "$SCRIPT_DIR/daily_test_timings.py" "$(_native "$dir")" "$(_native "$json")")" || rc=$?
  if [ "$rc" -ne 0 ]; then
    SUMMARY+=("    timings: scripts/daily_test_timings.py failed (exit $rc); raw lines kept in $dir")
    return
  fi
  while IFS= read -r line; do
    [ -n "$line" ] || continue
    SUMMARY+=("$line")
    case "$line" in *"NEVER FINISHED"*) echo "$line" ;; esac
  done <<<"$report"
  rm -rf "$dir"
}

SUITE_DESELECTS=()
SUITE_PLAN_RC=0
echo "daily_full_run — HEAD $(git rev-parse --short HEAD 2>/dev/null), logs in $OUT"
for step in "${SELECTED[@]}"; do
  _command "$step"
  echo "  step $step — timeout $(_timeout_of "$step")s — ${CMD[*]}"
done
[ "$DRY" = 1 ] && exit 0

mkdir -p "$OUT" || { echo "daily_full_run: cannot create $OUT" >&2; exit 2; }

# The managed Node and pnpm on PATH (red-fix pass 2026-11-21): the suite's Node tests
# (tests/scripts/test_bundle_pnpm.py, tests/scripts/test_webapp_renderer_freshness.py,
# tests/plugins/platforms/photon/test_url_send_path.py) run `node`/`pnpm` off PATH, and the
# workstation runner's shared-venv route skips activation, the one thing that puts pm's tool dirs
# there; the runner hands its PATH to every pytest child. The dirs come from pm's own resolver
# (`pm.install.env_for`, what `pm env node pnpm` prints), run under the bootstrap interpreter
# activation itself composes with (`hermes_bootstrap_python`); a checkout whose pins the store
# does not hold resolves nothing, and PATH stays as it was. DAILY_PM_PYTHON replaces that
# interpreter so the script's own test can drive it.
_managed_node_path() {
  local python
  if [ -n "${DAILY_PM_PYTHON:-}" ]; then
    python="$DAILY_PM_PYTHON"
  else
    [ -f "$SCRIPT_DIR/_activation.sh" ] || return 1
    # shellcheck source=scripts/_activation.sh
    python="$(. "$SCRIPT_DIR/_activation.sh" && hermes_bootstrap_python "$REPO_ROOT")" || return 1
  fi
  PYTHONHOME= PYTHONPATH="$(_native "$REPO_ROOT")" "$python" -c \
    'from pm.install import env_for; print(env_for("node", "pnpm", base_env={}).get("PATH", ""))' 2>/dev/null
}
if managed_path="$(_managed_node_path)" && [ -n "$managed_path" ]; then
  # A native Windows python prints `C:\a;C:\b`; bash splits PATH on ':'.
  if command -v cygpath >/dev/null 2>&1; then managed_path="$(cygpath -u -p "$managed_path")"; fi
  PATH="$managed_path:$PATH"
  export PATH
  echo "▶ managed node/pnpm on PATH: $managed_path"
else
  echo "▶ no managed node/pnpm recorded for this checkout's pins — PATH unchanged"
fi
if command -v timeout >/dev/null 2>&1; then
  HAVE_TIMEOUT=1
else
  HAVE_TIMEOUT=0
  echo "daily_full_run: no 'timeout' command here — the steps run without their timeouts" >&2
fi

REDS=()
SUMMARY=()
case " ${SELECTED[*]} " in
  *" suite "*)
    # The suite list honours the skip list; a list that cannot be built reds the suite step
    # instead of falling back to every file (the P0 freeze files among them).
    plan_out="$("$PY" "$SCRIPT_DIR/daily_suite_files.py" "$OUT/suite.files")" || SUITE_PLAN_RC=$?
    while IFS= read -r arg; do [ -n "$arg" ] && SUITE_DESELECTS+=("$arg"); done <<<"$plan_out"
    [ -s "$OUT/suite.files" ] || [ "$SUITE_PLAN_RC" -ne 0 ] || SUITE_PLAN_RC=2
    ;;
esac
for step in "${SELECTED[@]}"; do
  _command "$step"
  log="$OUT/$step.log"
  if [ "$step" = suite ] && [ "$SUITE_PLAN_RC" -ne 0 ]; then
    echo "daily_full_run: scripts/daily_suite_files.py could not build the suite list (exit $SUITE_PLAN_RC); the suite did not run" >"$log"
    echo "EXIT=$SUITE_PLAN_RC" >>"$log"
    REDS+=("$step")
    SUMMARY+=("✘ suite red (no suite list, exit $SUITE_PLAN_RC) — log $log — owes a row filed today in its domain queue (fork-hygiene for a gate or the runner)")
    echo "✘ suite: no suite list"
    continue
  fi
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
    ! _timed "$step" || _fold_timings "$step"
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
  ! _timed "$step" || _fold_timings "$step"
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
