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
#   census   the two name census gates (`Running the tests.md` asks a lane that touched Python to
#            run them), when touched or named: their own step and budget, because together they
#            are ~55 s of whole-tree walk and sank the touched lane's 60 s on their own
#            (FH-PREPUSH-TOUCHED-BUDGET-VS-NAME-CENSUS);
#   touched  the pusher's touched tests (every `tests/**/test_*.py` that differs
#            from merge-base(HEAD, origin/main), committed, staged, unstaged or
#            untracked) plus any test paths given as arguments — pass here every
#            test that references a shared symbol you changed (`grep -rl <name>
#            tests/`), which no diff can find for you. This is the named SLOWER
#            lane: its cost is the pusher's own tests, so it carries its own
#            budget instead of counting against the default path's few seconds.
#            A file this tree last ran in PREPUSH_SHARD_MIN s or more (the runner's
#            own `test_durations.json`) runs as shards, side by side, split by node
#            id (`scripts/_bundle_plugin/hermes_shard.py`), unless it is listed in
#            `scripts/test_files_unsharded.txt` (FH-PREPUSH-CAP-TIGHT).
#
# It prints its plan first. A step past its budget prints a heartbeat naming
# it every few seconds and raises one desktop notification; a step at its
# deadline is killed (its whole process group) and the run fails naming it. A
# red or a kill raises a notification at the end. A green run inside budget
# raises nothing and probes nothing (row FH-PREPUSH-PROGRESS-BUDGET, owner
# 2026-10-30; the launcher's PREPUSH-PROGRESS-BUDGET is the same contract).
# Every step runs even after a red: one push, the whole answer.
#
# ONE whole-run cap (PREPUSH_CAP) bounds the run, whatever the steps' deadlines add up
# to: a step that would outlive it is killed when it is spent, the steps after it do not
# start, and the run exits 3 naming the step — so `prepush.sh && git push` never pushes
# (FH-PREPUSH-CAP-TIGHT, owner 2026-11-08: "make it performant").
#
# Every step past its budget, killed at its deadline or stopped by the cap appends ONE
# JSON line to the untracked overrun ledger (PREPUSH_LEDGER, default
# `_lane_logs/prepush_overruns.jsonl`): step, outcome, budget, deadline, measured wall,
# exit, load average, live lanes, HEAD, cap. The run ends with a summary naming each
# overrun and the fork-hygiene row it owes, so the lane's landing report carries it
# (FH-PREPUSH-OVERRUN-LEDGER; the launcher's QA-LAND-WAVE-PROMOTE-TO-MAIN ledger is the
# same contract).
#
# Exit: 0 green · 1 red (a red or a deadline kill) · 2 usage · 3 the whole-run cap ·
# 130 interrupted.
#
# Usage:
#   scripts/prepush.sh                      # plan, then run
#   scripts/prepush.sh tests/foo/test_x.py  # plus the tests that use your symbol
#   scripts/prepush.sh --plan               # print the plan and exit 0
#   scripts/prepush.sh -j 4 ...             # worker cap (default 8)
#   scripts/prepush.sh --list-gates         # the gates step's files, one per line (and
#   scripts/prepush.sh --list-census        #   the census gates): scripts/daily_full_run.sh reads them
#
# Environment:
#   PREPUSH_NOTIFY        `off`, or a command run as `<cmd> <title> <body>`
#                         instead of the OS adapter (notify-send, osascript,
#                         the Windows toast).
#   PREPUSH_<STEP>_BUDGET / PREPUSH_<STEP>_DEADLINE   (STEP = GATES, DOC_CITE, CENSUS,
#                         TOUCHED; whole seconds) override one step's numbers.
#   PREPUSH_HEARTBEAT     seconds between heartbeats past budget (default 5).
#   PREPUSH_CAP           the whole-run cap, whole seconds (default 240).
#   PREPUSH_LEDGER        the overrun ledger (default _lane_logs/prepush_overruns.jsonl).
#   PREPUSH_LIVE_LANES    the live lane count the ledger records (null when unset).
#   PREPUSH_SHARD_MIN / PREPUSH_SHARD_SECONDS   a touched file last run this many
#                         seconds or more is sharded, one shard per SHARD_SECONDS of
#                         its last run, at most 4 (defaults 20 and 10).
#   PREPUSH_RUNNER / PREPUSH_PYTHON   the test runner (default
#                         scripts/run_tests.sh) and the doc-cite interpreter;
#                         both exist so the script's own test can drive it
#                         without running the suite.
#   PREPUSH_GATES_RUNNER  the gates step's runner, called with `--small` (default
#                         scripts/run_tests_bundled.sh: one pytest process per test
#                         directory, not per file — FH-UPSTREAM-RUNNER-ONE-PROCESS-GROUP).

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
  # The upstream-footprint ledger gate (~4 s alone; the bundle runs it beside the others). Off this
  # path, an upstream test file edited with no ledger row sat red on main for two days unseen
  # (7939482ee8, FH-FOOTPRINT-LEDGER-LAUNCHER-PUBLICATION-TEST-UNLEDGERED).
  tests/scripts/test_upstream_footprint.py
  # The 800-code-line size ceiling (its census ~1 s in-process): off this path, the bundled runner
  # crossed it and main sat red unseen (FH-SIZE-CEILING-TWO-FILES-OVER-800). The import-layers gate
  # stays on the landing gate: it imports every fork module (63.6 s alone at load ~28).
  tests/tooling/test_downstream_size_ceiling.py
)

# The name census gates: a touched or named one runs in the census step, never the touched lane.
PREPUSH_CENSUS_GATES=(
  tests/tooling/test_no_ladder_routing.py
  tests/agent_runtime/test_duplicate_helper_bodies.py
)

# The budgets, first measured 2026-10-30 on nekwo-ubuntu24 (52 cores), each step run
# alone: gates 5.5 s wall (test_line_endings.py 4.0 s and the row guard 3.2 s
# with four rows deleted are its longest files; the runner's own start is
# ~1.3 s), doc-cite 1.7 s. The default path (gates + doc-cite) is therefore
# ~7 s against a 14 s budget. The touched lane is whatever the pusher touched.
# 2026-11-03 (w1103a-h1): test_line_endings.py reads a blob-keyed memo of git's
# --eol answer (0.6 s warm; 87 s was a cold whole-tree --eol, FH-LINE-ENDINGS-GATE-
# OVER-30S-COLD), and the row grammar and guard read the closed-row archive within
# the same budget: the current and previous month parsed, every month ID-scanned,
# the guard's sha check bounded to the archive lines the push adds (RT-QUEUE-
# ARCHIVE-GRAMMAR, launcher plan QUEUE_CLOSED_ROW_ARCHIVE_2026-11-02 D8).
BUDGET_GATES="${PREPUSH_GATES_BUDGET:-10}"
DEADLINE_GATES="${PREPUSH_GATES_DEADLINE:-120}"
BUDGET_DOC_CITE="${PREPUSH_DOC_CITE_BUDGET:-4}"
DEADLINE_DOC_CITE="${PREPUSH_DOC_CITE_DEADLINE:-60}"
# 2026-11-08 (w1108c-hm-prepush, FH-PREPUSH-CAP-TIGHT), nekwo-ubuntu24 under load, 12 live lanes:
# each DEADLINE is ~2x the step's measured wall under that load, never the old 6-15x of its budget
# (120 / 60 / 600 / 900 s let one hung step hold a push ~28 min). The numbers and their loads:
# `Harness_Brain/50 — Agent Handoffs/Running the tests.md` § prepush.
#   gates    4.6-4.9 s (load 22-31)            budget 10, deadline 20
#   doc-cite 1.9-2.1 s                         budget 4,  deadline 10
#   census   62.9 s before (load 29); 13.2 s (load 16) with the walks chunked over worker
#            processes (`scripts/census_pool.py`) budget 30, deadline 60
#   touched  the pusher's own tests            budget 60, deadline 120
# and ONE whole-run cap over them all: 240 s.
BUDGET_GATES="${PREPUSH_GATES_BUDGET:-10}"
DEADLINE_GATES="${PREPUSH_GATES_DEADLINE:-20}"
BUDGET_DOC_CITE="${PREPUSH_DOC_CITE_BUDGET:-4}"
DEADLINE_DOC_CITE="${PREPUSH_DOC_CITE_DEADLINE:-10}"
BUDGET_CENSUS="${PREPUSH_CENSUS_BUDGET:-30}"
DEADLINE_CENSUS="${PREPUSH_CENSUS_DEADLINE:-60}"
BUDGET_TOUCHED="${PREPUSH_TOUCHED_BUDGET:-60}"
DEADLINE_TOUCHED="${PREPUSH_TOUCHED_DEADLINE:-120}"
HEARTBEAT="${PREPUSH_HEARTBEAT:-5}"
CAP="${PREPUSH_CAP:-240}"
SHARD_MIN="${PREPUSH_SHARD_MIN:-20}"
SHARD_SECONDS="${PREPUSH_SHARD_SECONDS:-10}"
SHARD_MAX=4
LEDGER="${PREPUSH_LEDGER:-$REPO_ROOT/_lane_logs/prepush_overruns.jsonl}"

PLAN_ONLY=0
JOBS=8
EXTRA=()
while [ $# -gt 0 ]; do
  case "$1" in
    --plan) PLAN_ONLY=1 ;;
    --list-gates) printf '%s\n' "${PREPUSH_QUEUE_GATES[@]}" "${PREPUSH_TEXT_GATES[@]}"; exit 0 ;;
    --list-census) printf '%s\n' "${PREPUSH_CENSUS_GATES[@]}"; exit 0 ;;
    -j|--jobs) shift; JOBS="${1:?-j needs a number}" ;;
    -h|--help) sed -n '2,75p' "${BASH_SOURCE[0]}"; exit 0 ;;
    -*) echo "prepush: unknown option $1" >&2; exit 2 ;;
    *) EXTRA+=("$1") ;;
  esac
  shift
done

for value in "$BUDGET_GATES" "$DEADLINE_GATES" "$BUDGET_DOC_CITE" "$DEADLINE_DOC_CITE" \
    "$BUDGET_CENSUS" "$DEADLINE_CENSUS" "$BUDGET_TOUCHED" "$DEADLINE_TOUCHED" "$HEARTBEAT" "$CAP" \
    "$SHARD_MIN" "$SHARD_SECONDS"; do
  case "$value" in
    ''|*[!0-9]*|0) echo "prepush: a budget, deadline, cap, heartbeat or shard number is not a positive whole number of seconds: '$value'" >&2; exit 2 ;;
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
CENSUS=()
LANE=()
SEEN=$'\n'
for path in "${PREPUSH_QUEUE_GATES[@]}" "${PREPUSH_TEXT_GATES[@]}"; do
  SEEN="$SEEN$path"$'\n'
  GATES+=("$path")
done
for path in ${TOUCHED[@]+"${TOUCHED[@]}"} ${EXTRA[@]+"${EXTRA[@]}"}; do
  case "$SEEN" in *$'\n'"$path"$'\n'*) continue ;; esac
  SEEN="$SEEN$path"$'\n'
  case " ${PREPUSH_CENSUS_GATES[*]} " in
    *" $path "*) CENSUS+=("$path") ;;
    *) LANE+=("$path") ;;
  esac
done

# The touched lane's shards. A file this tree last ran (the runner's own `test_durations.json`) in
# SHARD_MIN s or more runs as k = min(SHARD_MAX, ceil(last / SHARD_SECONDS)) node-id shards side by
# side, unless `scripts/test_files_unsharded.txt` lists it (its tests depend on each other's order).
_last_seconds() {
  local record="$REPO_ROOT/test_durations.json"
  [ -f "$record" ] || { echo 0; return; }
  # A Windows run keys the record `tests\\a\\test_x.py` (JSON-escaped backslashes): both separators
  # are read as `/`, or no file ever shards on Windows (FH-PREPUSH-TOUCHED-NAMED-HEAVY-OVER-BUDGET).
  # MUTATION: drop the sed and test_a_windows_keyed_duration_record_still_shards reddens.
  sed 's#\\\\#/#g' "$record" 2>/dev/null | grep -o "\"${1//./\\.}\": *[0-9.]*" 2>/dev/null |
    awk -F': *' 'NR == 1 { v = $2 + 0; printf "%d\n", (v == int(v)) ? v : int(v) + 1; found = 1 } END { if (!found) print 0 }'
}
_unsharded() {
  [ -f "$REPO_ROOT/scripts/test_files_unsharded.txt" ] &&
    awk -v p="$1" '$1 == p { found = 1 } END { exit !found }' "$REPO_ROOT/scripts/test_files_unsharded.txt"
}
PLAIN=()
SHARD_FILES=()
SHARD_COUNTS=()
for path in ${LANE[@]+"${LANE[@]}"}; do
  last="$(_last_seconds "$path")"
  shards=$(( (last + SHARD_SECONDS - 1) / SHARD_SECONDS ))
  [ "$shards" -gt "$SHARD_MAX" ] && shards="$SHARD_MAX"
  if [ "$last" -ge "$SHARD_MIN" ] && [ "$shards" -ge 2 ] && ! _unsharded "$path"; then
    SHARD_FILES+=("$path")
    SHARD_COUNTS+=("$shards")
  else
    PLAIN+=("$path")
  fi
done

_list() { local label="$1"; shift; echo "  $label ($#):"; for p in "$@"; do echo "    $p"; done; }
echo "prepush — base $(git rev-parse --short "$BASE") (merge-base with origin/main)"
echo "  default path: gates + doc-cite, budget $((BUDGET_GATES + BUDGET_DOC_CITE))s"
echo "  whole-run cap ${CAP}s: past it the running step is killed, the rest do not start, exit 3"
echo "  overrun ledger: ${LEDGER#"$REPO_ROOT"/}"
# The gates run BUNDLED (FH-UPSTREAM-RUNNER-ONE-PROCESS-GROUP, owner 2026-11-10: fork-side, no
# upstream change): `run_tests.sh` starts one pytest per file, and on Windows each start is
# ~3 s of interpreter, plugins and the root conftest before its first test — nine of them were
# most of the step's wall. The bundled runner's `--small` path (named files: no scope, skip list,
# gate store or leftovers scan) puts a test directory's files in one process and
# keeps the per-file guarantee where it matters: a bundle that reds re-runs every member that
# did not pass ONE FILE PER PROCESS, and a member red bundled but green alone is reported as an
# isolation leak (`scripts/run_tests_bundled.py`). It runs with ETERNIA_HEAVY_SLOTS=off: a bundled
# run otherwise waits for the launcher's machine-wide heavy-run slot (two per box), which a lane's
# full-tier run can hold for minutes — measured 2026-11-10 at 139 s and 300 s+ of waiting for a
# 14 s step. The per-file runner this replaces never claimed a slot, so the cap loses nothing.
GATES_RUNNER="${PREPUSH_GATES_RUNNER:-$SCRIPT_DIR/run_tests_bundled.sh}"
echo "  step gates — budget ${BUDGET_GATES}s, deadline ${DEADLINE_GATES}s"
echo "    runner: ${GATES_RUNNER#"$REPO_ROOT"/}"
_list "queue gates" "${PREPUSH_QUEUE_GATES[@]}"
_list "text gates" "${PREPUSH_TEXT_GATES[@]}"
echo "  step doc-cite — budget ${BUDGET_DOC_CITE}s, deadline ${DEADLINE_DOC_CITE}s"
echo "    scripts/doc_cite_adjacency.py --exclude archive --exclude planned"
if [ "${#CENSUS[@]}" -gt 0 ]; then
  echo "  step census — budget ${BUDGET_CENSUS}s, deadline ${DEADLINE_CENSUS}s"
  _list "name census gates" "${CENSUS[@]}"
fi
if [ "${#LANE[@]}" -gt 0 ]; then
  echo "  step touched (the slower lane) — budget ${BUDGET_TOUCHED}s, deadline ${DEADLINE_TOUCHED}s"
  for index in "${!SHARD_FILES[@]}"; do
    echo "    sharded: ${SHARD_FILES[$index]} into ${SHARD_COUNTS[$index]} (last run $(_last_seconds "${SHARD_FILES[$index]}")s)"
  done
else
  echo "  step touched (the slower lane) — nothing touched or named, skipped"
fi
_list "touched tests" ${TOUCHED[@]+"${TOUCHED[@]}"}
_list "named by you" ${EXTRA[@]+"${EXTRA[@]}"}
echo "  not run: the landing gate (scripts/run_tests_bundled.sh tests) and the importers of a"
echo "    symbol you changed unless you named them above"
[ "$PLAN_ONLY" = 1 ] && exit 0

RUNNER="${PREPUSH_RUNNER:-$SCRIPT_DIR/run_tests.sh}"
# The doc-cite interpreter: an explicit one, else the shared test venv the runners already find
# (`_fork_test_env.sh`: HERMES_TEST_VENV, else ~/.venvs/hermes-test), else python3, else python.
# A bare `python` is absent on the Linux box, which redded every push `exit 127`
# (FH-PREPUSH-BARE-PYTHON-LINUX).
# The venv default is the door's (fork_default_test_venv: the real user home, so a temp HOME
# still finds it — FH-PREPUSH-TEMP-HOME-NO-VENV).
# shellcheck source=scripts/_fork_test_env.sh
. "$SCRIPT_DIR/_fork_test_env.sh"
_default_python() {
  local venv candidate
  venv="$(fork_default_test_venv)"
  for candidate in "$venv/Scripts/python.exe" "$venv/bin/python"; do
    [ -x "$candidate" ] && { echo "$candidate"; return; }
  done
  command -v python3 >/dev/null 2>&1 && { echo python3; return; }
  echo python
}
PY="${PREPUSH_PYTHON:-${HERMES_PYTHON:-$(_default_python)}}"

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
# then at the deadline it kills the step's process group and exits 124. A step whose
# deadline is the whole-run cap's remainder is told so (WHY = "the whole-run cap").
_watch() {
  local name="$1" budget="$2" deadline="$3" pgid="$4" why="$5" elapsed=0 nap
  if [ "$budget" -lt "$deadline" ]; then
    sleep "$budget" >/dev/null 2>&1 </dev/null
    elapsed="$budget"
    echo "… prepush: $name still running past its ${budget}s budget (deadline ${deadline}s)"
    _notify "prepush: $name over budget" "still running past ${budget}s; killed at ${deadline}s"
  fi
  while [ "$elapsed" -lt "$deadline" ]; do
    nap=$((deadline - elapsed < HEARTBEAT ? deadline - elapsed : HEARTBEAT))
    sleep "$nap" >/dev/null 2>&1 </dev/null
    elapsed=$((elapsed + nap))
    if [ "$elapsed" -lt "$deadline" ] && [ "$elapsed" -gt "$budget" ]; then
      echo "… prepush: $name still running (${elapsed}s, budget ${budget}s, deadline ${deadline}s)"
    fi
  done
  echo "✘ prepush: $name hit ${why} (${deadline}s) — killing it"
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

# ── the overrun ledger (FH-PREPUSH-OVERRUN-LEDGER) ──────────────────────────
_load_average() {
  local one=""
  if [ -r /proc/loadavg ]; then
    read -r one _ </proc/loadavg
  elif command -v sysctl >/dev/null 2>&1; then
    one="$(sysctl -n vm.loadavg 2>/dev/null | awk '{ print $2 }')"
  fi
  case "$one" in ''|*[!0-9.]*) echo null ;; *) echo "$one" ;; esac
}
# Live lanes only when the caller knows them (a wave's orchestrator exports the count): a
# clone's lock reasons outlive their lanes and miss the other repos' lanes, so a guess is null.
_live_lanes() {
  case "${PREPUSH_LIVE_LANES:-}" in ''|*[!0-9]*) echo null ;; *) echo "$PREPUSH_LIVE_LANES" ;; esac
}
_json_str() { local v="${1//\\/\\\\}"; v="${v//\"/\\\"}"; printf '"%s"' "$v"; }
OVERRUNS=()
# _ledger STEP OUTCOME BUDGET DEADLINE MS EXIT — one JSON line, then one summary entry.
_ledger() {
  local step="$1" outcome="$2" budget="$3" deadline="$4" ms="$5" rc="$6" wall load lanes head
  wall="$(($5 / 1000)).$(( ($5 % 1000) / 100 ))"
  load="$(_load_average)"
  lanes="$(_live_lanes)"
  head="$(git rev-parse --short HEAD 2>/dev/null)"
  mkdir -p "$(dirname "$LEDGER")" 2>/dev/null
  printf '{"ts":%s,"step":%s,"outcome":%s,"budget_s":%s,"deadline_s":%s,"wall_s":%s,"exit":%s,"load":%s,"live_lanes":%s,"head":%s,"cap_s":%s}\n' \
    "$(_json_str "$(date -u +%Y-%m-%dT%H:%M:%SZ)")" "$(_json_str "$step")" "$(_json_str "$outcome")" \
    "$budget" "$deadline" "$wall" "$rc" "$load" "$lanes" "$(_json_str "$head")" "$CAP" >>"$LEDGER" ||
    echo "✘ prepush: could not append to the overrun ledger $LEDGER" >&2
  local row
  row="FH-PREPUSH-$(printf '%s' "$step" | tr '[:lower:]-' '[:upper:]-')-OVER-BUDGET"
  OVERRUNS+=("$step $outcome: ${wall}s against budget ${budget}s (deadline ${deadline}s, load $load, live lanes $lanes) — owes row $row")
}

RUN_STARTED="$(_now_ms)"
RED_STEPS=()
CAPPED=""
# _step NAME BUDGET DEADLINE CMD... — the step and its watchdog each lead their
# own process group (job control is on only while they start), so a kill takes
# the step's whole tree and nothing else. The deadline is the step's own or what is
# left of the whole-run cap, whichever is sooner; once the cap is spent no step starts.
_step() {
  local name="$1" budget="$2" deadline="$3" started rc wd_rc ms left why="its deadline" outcome=""
  shift 3
  if [ -n "$CAPPED" ]; then
    echo "✘ prepush: $name not started — the ${CAP}s whole-run cap is spent ($CAPPED)"
    RED_STEPS+=("$name (not started: the whole-run cap)")
    return
  fi
  left=$(( CAP - ( $(_now_ms) - RUN_STARTED ) / 1000 ))
  if [ "$left" -le 0 ]; then
    CAPPED="before $name"
    echo "✘ prepush: $name not started — the ${CAP}s whole-run cap is spent"
    RED_STEPS+=("$name (not started: the whole-run cap)")
    _ledger "$name" capped "$budget" "$deadline" 0 124
    return
  fi
  if [ "$left" -lt "$deadline" ]; then
    deadline="$left"
    why="the whole-run cap"
  fi
  echo "▶ $name (budget ${budget}s)"
  started="$(_now_ms)"
  set -m
  "$@" &
  STEP_PGID=$!
  _watch "$name" "$budget" "$deadline" "$STEP_PGID" "$why" &
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
    if [ "$why" = "the whole-run cap" ]; then
      outcome=capped
      CAPPED="during $name"
      echo "✘ prepush: $name killed at the ${CAP}s whole-run cap"
      RED_STEPS+=("$name (killed at the ${CAP}s whole-run cap)")
    else
      outcome=killed
      echo "✘ prepush: $name killed at its ${deadline}s deadline"
      RED_STEPS+=("$name (killed at its ${deadline}s deadline)")
    fi
  elif [ "$rc" -ne 0 ]; then
    echo "✘ prepush: $name red (exit $rc, $(_secs "$ms"))"
    RED_STEPS+=("$name (exit $rc)")
  else
    echo "✔ $name $(_secs "$ms") (budget ${budget}s)"
  fi
  if [ -z "$outcome" ] && [ "$ms" -gt $((budget * 1000)) ]; then
    outcome=slow
  fi
  [ -n "$outcome" ] && _ledger "$name" "$outcome" "$budget" "$deadline" "$ms" "$rc"
}

# The touched lane: the unsharded files in one runner, each shard in its own, side by side.
# Job control is off in here (it was on while the step started), so every runner stays in the
# step's process group and a deadline kill takes them all.
_touched_lane() {
  set +m
  local pids=() rc=0 index shard pid
  if [ "${#PLAIN[@]}" -gt 0 ]; then
    bash "$RUNNER" -j "$JOBS" "${PLAIN[@]}" &
    pids+=($!)
  fi
  for index in "${!SHARD_FILES[@]}"; do
    for ((shard = 0; shard < SHARD_COUNTS[index]; shard++)); do
      bash "$RUNNER" -j 1 "${SHARD_FILES[$index]}" -- \
        -p scripts._bundle_plugin.hermes_shard "--hermes-shard=$shard/${SHARD_COUNTS[$index]}" &
      pids+=($!)
    done
  done
  for pid in "${pids[@]}"; do
    wait "$pid" || rc=1
  done
  return "$rc"
}

# The gates' bundles are sized to fill the workers (FH-WORK-V1-CLAIM-GATES-WINDOWS-BUDGET): the
# runner's default (20 files, one bundle per test directory) ran the 11 gates as 3 serial bundles
# with 5 of 8 workers idle, so the step's wall was its longest directory's sum. ceil(gates / jobs),
# at least 2, runs them as ~one bundle per worker. Windows 2026-11-12, load 29-39, the step's two
# runs each way: 46.1 / 39.3 s at 3 bundles, 33.7 / 36.5 s at 7.
GATES_BUNDLE_SIZE=$(( (${#GATES[@]} + JOBS - 1) / JOBS ))
[ "$GATES_BUNDLE_SIZE" -ge 2 ] || GATES_BUNDLE_SIZE=2
_step gates "$BUDGET_GATES" "$DEADLINE_GATES" env ETERNIA_HEAVY_SLOTS=off bash "$GATES_RUNNER" --small -j "$JOBS" \
  --bundle-size "$GATES_BUNDLE_SIZE" "${GATES[@]}"
_step doc-cite "$BUDGET_DOC_CITE" "$DEADLINE_DOC_CITE" \
  "$PY" "$SCRIPT_DIR/doc_cite_adjacency.py" --exclude archive --exclude planned
if [ "${#CENSUS[@]}" -gt 0 ]; then
  _step census "$BUDGET_CENSUS" "$DEADLINE_CENSUS" bash "$RUNNER" -j "$JOBS" "${CENSUS[@]}"
fi
if [ "${#LANE[@]}" -gt 0 ]; then
  _step touched "$BUDGET_TOUCHED" "$DEADLINE_TOUCHED" _touched_lane
fi

if [ "${#OVERRUNS[@]}" -ne 0 ]; then
  echo "prepush: ${#OVERRUNS[@]} overrun(s), each a JSON line in ${LEDGER#"$REPO_ROOT"/} — file each row now"
  echo "  (Harness_Brain/20 — Active Initiatives/fork-hygiene-queue.md: check, budget, measured time, load):"
  for line in "${OVERRUNS[@]}"; do
    echo "  overrun: $line"
  done
fi
if [ -n "$CAPPED" ]; then
  echo "✘ prepush: CAPPED — the ${CAP}s whole-run cap was spent $CAPPED — ${RED_STEPS[*]} — do not push"
  _notify "prepush: CAPPED" "${CAP}s whole-run cap spent $CAPPED"
  exit 3
fi
if [ "${#RED_STEPS[@]}" -ne 0 ]; then
  echo "✘ prepush: RED — ${RED_STEPS[*]} — fix before pushing"
  _notify "prepush: RED" "${RED_STEPS[*]}"
  exit 1
fi
echo "✔ prepush: green"
