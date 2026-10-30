#!/usr/bin/env bash
# scripts/prepush.sh — the checks every push to `main` owes, as ONE command
# (CLAUDE.md § Git discipline: "Every push to `main` is a landing", owner
# 2026-10-29, adopting the launcher's `dart tool/prepush/run.dart`). It is a
# COMMAND, not a hook: there is still no pre-push gate.
#
# Steps, in order — each declares a BUDGET and a DEADLINE (seconds):
#   gates    the queue gates (row grammar, row-history guard — ADR 0038) and the
#            cheap whole-tree text gates, in one `scripts/run_tests.sh` run;
#   doc-cite `scripts/doc_cite_adjacency.py` over the ruled scope;
#   touched  the pusher's touched tests (every `tests/**/test_*.py` that differs
#            from merge-base(HEAD, origin/main), committed, staged, unstaged or
#            untracked) plus any test paths given as arguments — pass here every
#            test that references a shared symbol you changed (`grep -rl <name>
#            tests/`), which no diff can find for you. This is the named SLOWER
#            lane: its cost is the pusher's own tests, so it carries its own
#            budget instead of counting against the default path's few seconds.
#
# It prints its plan first. A step past its budget prints a heartbeat naming
# it every few seconds and raises one desktop notification; a step at its
# deadline is killed (its whole process group) and the run fails naming it. A
# red or a kill raises a notification at the end. A green run inside budget
# raises nothing and probes nothing (row FH-PREPUSH-PROGRESS-BUDGET, owner
# 2026-10-30; the launcher's PREPUSH-PROGRESS-BUDGET is the same contract).
# Every step runs even after a red: one push, the whole answer.
#
# Usage:
#   scripts/prepush.sh                      # plan, then run
#   scripts/prepush.sh tests/foo/test_x.py  # plus the tests that use your symbol
#   scripts/prepush.sh --plan               # print the plan and exit 0
#   scripts/prepush.sh -j 4 ...             # worker cap (default 8)
#
# Environment:
#   PREPUSH_NOTIFY        `off`, or a command run as `<cmd> <title> <body>`
#                         instead of the OS adapter (notify-send, osascript,
#                         the Windows toast).
#   PREPUSH_<STEP>_BUDGET / PREPUSH_<STEP>_DEADLINE   (STEP = GATES, DOC_CITE,
#                         TOUCHED; whole seconds) override one step's numbers.
#   PREPUSH_HEARTBEAT     seconds between heartbeats past budget (default 5).
#   PREPUSH_RUNNER / PREPUSH_PYTHON   the test runner (default
#                         scripts/run_tests.sh) and the doc-cite interpreter;
#                         both exist so the script's own test can drive it
#                         without running the suite.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT" || exit 2

PREPUSH_QUEUE_GATES=(
  tests/tooling/test_work_queue_row_grammar.py
  tests/tooling/test_queue_row_guard.py
)

# Whole-tree text and claims gates that each finish in a few seconds. A gate
# joins only when its own run is cheap; the slow claims walkers stay on the
# landing gate.
PREPUSH_TEXT_GATES=(
  tests/test_line_endings.py
  tests/test_byte_pinned_fixture_families.py
  tests/tooling/test_gate_directory_current.py
  tests/tooling/test_upstream_reds_rows_resolve.py
  tests/test_docket_stage_claims.py
  tests/scripts/test_no_machine_paths_in_fork_scripts.py
  tests/scripts/test_check_no_tmp_literals.py
)

# The budgets, measured 2026-10-30 on nekwo-ubuntu24 (52 cores), each step run
# alone: gates 5.5 s wall (test_line_endings.py 4.0 s and the row guard 3.2 s
# with four rows deleted are its longest files; the runner's own start is
# ~1.3 s), doc-cite 1.7 s. The default path (gates + doc-cite) is therefore
# ~7 s against a 14 s budget. The touched lane is whatever the pusher touched.
BUDGET_GATES="${PREPUSH_GATES_BUDGET:-10}"
DEADLINE_GATES="${PREPUSH_GATES_DEADLINE:-120}"
BUDGET_DOC_CITE="${PREPUSH_DOC_CITE_BUDGET:-4}"
DEADLINE_DOC_CITE="${PREPUSH_DOC_CITE_DEADLINE:-60}"
BUDGET_TOUCHED="${PREPUSH_TOUCHED_BUDGET:-60}"
DEADLINE_TOUCHED="${PREPUSH_TOUCHED_DEADLINE:-900}"
HEARTBEAT="${PREPUSH_HEARTBEAT:-5}"

PLAN_ONLY=0
JOBS=8
EXTRA=()
while [ $# -gt 0 ]; do
  case "$1" in
    --plan) PLAN_ONLY=1 ;;
    -j|--jobs) shift; JOBS="${1:?-j needs a number}" ;;
    -h|--help) sed -n '2,44p' "${BASH_SOURCE[0]}"; exit 0 ;;
    -*) echo "prepush: unknown option $1" >&2; exit 2 ;;
    *) EXTRA+=("$1") ;;
  esac
  shift
done

for value in "$BUDGET_GATES" "$DEADLINE_GATES" "$BUDGET_DOC_CITE" "$DEADLINE_DOC_CITE" \
    "$BUDGET_TOUCHED" "$DEADLINE_TOUCHED" "$HEARTBEAT"; do
  case "$value" in
    ''|*[!0-9]*|0) echo "prepush: a budget, deadline or heartbeat is not a positive whole number of seconds: '$value'" >&2; exit 2 ;;
  esac
done

BASE="$(git merge-base HEAD origin/main 2>/dev/null)" || {
  echo "prepush: no merge-base with origin/main — run 'git fetch origin' first" >&2
  exit 2
}

# The pusher's touched tests: changed since the base, plus untracked.
TOUCHED=()
while IFS= read -r path; do
  [ -n "$path" ] || continue
  case "$path" in
    tests/*/test_*.py|tests/test_*.py) [ -f "$path" ] && TOUCHED+=("$path") ;;
  esac
done < <( { git diff --name-only "$BASE" --; git ls-files --others --exclude-standard -- tests; } | sort -u)

for path in ${EXTRA[@]+"${EXTRA[@]}"}; do
  [ -e "$path" ] || { echo "prepush: no such test path: $path" >&2; exit 2; }
done

# Each file once, in plan order: a gate is never re-run in the touched lane.
GATES=()
LANE=()
SEEN=$'\n'
for path in "${PREPUSH_QUEUE_GATES[@]}" "${PREPUSH_TEXT_GATES[@]}"; do
  SEEN="$SEEN$path"$'\n'
  GATES+=("$path")
done
for path in ${TOUCHED[@]+"${TOUCHED[@]}"} ${EXTRA[@]+"${EXTRA[@]}"}; do
  case "$SEEN" in *$'\n'"$path"$'\n'*) continue ;; esac
  SEEN="$SEEN$path"$'\n'
  LANE+=("$path")
done

_list() { local label="$1"; shift; echo "  $label ($#):"; for p in "$@"; do echo "    $p"; done; }
echo "prepush — base $(git rev-parse --short "$BASE") (merge-base with origin/main)"
echo "  default path: gates + doc-cite, budget $((BUDGET_GATES + BUDGET_DOC_CITE))s"
echo "  step gates — budget ${BUDGET_GATES}s, deadline ${DEADLINE_GATES}s"
_list "queue gates" "${PREPUSH_QUEUE_GATES[@]}"
_list "text gates" "${PREPUSH_TEXT_GATES[@]}"
echo "  step doc-cite — budget ${BUDGET_DOC_CITE}s, deadline ${DEADLINE_DOC_CITE}s"
echo "    scripts/doc_cite_adjacency.py --exclude archive --exclude planned"
if [ "${#LANE[@]}" -gt 0 ]; then
  echo "  step touched (the slower lane) — budget ${BUDGET_TOUCHED}s, deadline ${DEADLINE_TOUCHED}s"
else
  echo "  step touched (the slower lane) — nothing touched or named, skipped"
fi
_list "touched tests" ${TOUCHED[@]+"${TOUCHED[@]}"}
_list "named by you" ${EXTRA[@]+"${EXTRA[@]}"}
echo "  not run: the landing gate (scripts/run_tests_bundled.sh tests) and the importers of a"
echo "    symbol you changed unless you named them above"
[ "$PLAN_ONLY" = 1 ] && exit 0

RUNNER="${PREPUSH_RUNNER:-$SCRIPT_DIR/run_tests.sh}"
PY="${PREPUSH_PYTHON:-${HERMES_PYTHON:-python}}"

# ── the notification adapter: one function, three OSes, never waited on ─────
# Each notifier is started in its own process group, detached from every
# stream, so it outlives the watchdog that raised it and never holds a pipe
# the caller is reading.
_notify() {
  local title="$1" body="$2"
  case "${PREPUSH_NOTIFY:-auto}" in
    off) return 0 ;;
    auto) ;;
    *) ( set -m; "$PREPUSH_NOTIFY" "$title" "$body" >/dev/null 2>&1 </dev/null & ); return 0 ;;
  esac
  if command -v notify-send >/dev/null 2>&1; then
    ( set -m; notify-send -a "hermes prepush" "$title" "$body" >/dev/null 2>&1 </dev/null & )
  elif command -v osascript >/dev/null 2>&1; then
    ( set -m; osascript -e 'on run argv' -e 'display notification (item 2 of argv) with title (item 1 of argv)' \
        -e 'end run' "$title" "$body" >/dev/null 2>&1 </dev/null & )
  elif command -v powershell.exe >/dev/null 2>&1; then
    ( set -m; PREPUSH_TITLE="$title" PREPUSH_BODY="$body" powershell.exe -NoProfile -NonInteractive -Command '
      [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null
      $x = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02)
      $t = $x.GetElementsByTagName("text")
      $t.Item(0).AppendChild($x.CreateTextNode($env:PREPUSH_TITLE)) > $null
      $t.Item(1).AppendChild($x.CreateTextNode($env:PREPUSH_BODY)) > $null
      $app = "{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe"
      [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($app).Show([Windows.UI.Notifications.ToastNotification]::new($x))
    ' >/dev/null 2>&1 </dev/null & )
  fi
  return 0
}

_now_ms() {
  if [ -n "${EPOCHREALTIME:-}" ]; then
    local t="${EPOCHREALTIME/[.,]/}"
    echo $((10#$t / 1000))
  else
    echo $((SECONDS * 1000))
  fi
}

_secs() { echo "$(($1 / 1000)).$((($1 % 1000) / 100))s"; }

# The watchdog: silent until the budget, then a heartbeat and one notification,
# then at the deadline it kills the step's process group and exits 124.
_watch() {
  local name="$1" budget="$2" deadline="$3" pgid="$4" elapsed nap
  sleep "$budget" >/dev/null 2>&1 </dev/null
  elapsed="$budget"
  echo "… prepush: $name still running past its ${budget}s budget (deadline ${deadline}s)"
  _notify "prepush: $name over budget" "still running past ${budget}s; killed at ${deadline}s"
  while [ "$elapsed" -lt "$deadline" ]; do
    nap=$((deadline - elapsed < HEARTBEAT ? deadline - elapsed : HEARTBEAT))
    sleep "$nap" >/dev/null 2>&1 </dev/null
    elapsed=$((elapsed + nap))
    if [ "$elapsed" -lt "$deadline" ]; then
      echo "… prepush: $name still running (${elapsed}s, budget ${budget}s, deadline ${deadline}s)"
    fi
  done
  echo "✘ prepush: $name hit its ${deadline}s deadline — killing it"
  kill -TERM -- "-$pgid" 2>/dev/null
  for _ in 1 2 3 4 5 6 7 8 9 10; do
    kill -0 -- "-$pgid" 2>/dev/null || exit 124
    sleep 0.2 >/dev/null 2>&1 </dev/null
  done
  kill -KILL -- "-$pgid" 2>/dev/null
  exit 124
}

STEP_PGID=""
WATCH_PGID=""
_abort() {
  [ -n "$STEP_PGID" ] && kill -TERM -- "-$STEP_PGID" 2>/dev/null
  [ -n "$WATCH_PGID" ] && kill -TERM -- "-$WATCH_PGID" 2>/dev/null
  echo "✘ prepush: interrupted"
  exit 130
}
trap _abort INT TERM

RED_STEPS=()
# _step NAME BUDGET DEADLINE CMD... — the step and its watchdog each lead their
# own process group (job control is on only while they start), so a kill takes
# the step's whole tree and nothing else.
_step() {
  local name="$1" budget="$2" deadline="$3" started rc wd_rc ms
  shift 3
  echo "▶ $name (budget ${budget}s)"
  started="$(_now_ms)"
  set -m
  "$@" &
  STEP_PGID=$!
  _watch "$name" "$budget" "$deadline" "$STEP_PGID" &
  WATCH_PGID=$!
  set +m
  wait "$STEP_PGID"
  rc=$?
  kill -TERM -- "-$WATCH_PGID" 2>/dev/null
  wait "$WATCH_PGID" 2>/dev/null
  wd_rc=$?
  STEP_PGID="" WATCH_PGID=""
  ms=$(( $(_now_ms) - started ))
  # The step usually dies on the watchdog's TERM before the watchdog itself exits 124, so a
  # non-zero exit at or past the deadline is the deadline's kill as well.
  if [ "$wd_rc" -eq 124 ] || { [ "$rc" -ne 0 ] && [ "$ms" -ge $((deadline * 1000)) ]; }; then
    echo "✘ prepush: $name killed at its ${deadline}s deadline"
    RED_STEPS+=("$name (killed at its ${deadline}s deadline)")
  elif [ "$rc" -ne 0 ]; then
    echo "✘ prepush: $name red (exit $rc, $(_secs "$ms"))"
    RED_STEPS+=("$name (exit $rc)")
  else
    echo "✔ $name $(_secs "$ms") (budget ${budget}s)"
  fi
}

_step gates "$BUDGET_GATES" "$DEADLINE_GATES" bash "$RUNNER" -j "$JOBS" "${GATES[@]}"
_step doc-cite "$BUDGET_DOC_CITE" "$DEADLINE_DOC_CITE" \
  "$PY" "$SCRIPT_DIR/doc_cite_adjacency.py" --exclude archive --exclude planned
if [ "${#LANE[@]}" -gt 0 ]; then
  _step touched "$BUDGET_TOUCHED" "$DEADLINE_TOUCHED" bash "$RUNNER" -j "$JOBS" "${LANE[@]}"
fi

if [ "${#RED_STEPS[@]}" -ne 0 ]; then
  echo "✘ prepush: RED — ${RED_STEPS[*]} — fix before pushing"
  _notify "prepush: RED" "${RED_STEPS[*]}"
  exit 1
fi
echo "✔ prepush: green"
