#!/usr/bin/env bash
# scripts/prepush.sh — the checks every push to `main` owes, as ONE command
# (CLAUDE.md § Git discipline: "Every push to `main` is a landing", owner
# 2026-10-29, adopting the launcher's `dart tool/prepush/run.dart`). It is a
# COMMAND, not a hook: there is still no pre-push gate.
#
# It runs, in one `scripts/run_tests.sh` invocation (per-file isolation):
#   * the queue gates — the row grammar and the row-history guard (ADR 0038);
#   * the cheap whole-tree text gates (PREPUSH_TEXT_GATES below);
#   * the pusher's touched tests — every `tests/**/test_*.py` that differs from
#     merge-base(HEAD, origin/main), committed, staged, unstaged or untracked;
#   * any extra test paths given as arguments — pass here every test that
#     references a shared symbol you changed (`grep -rl <name> tests/`), which
#     no diff can find for you.
# Then, outside pytest, `scripts/doc_cite_adjacency.py` over the ruled scope.
#
# It prints its plan first and exits non-zero on any red.
#
# Usage:
#   scripts/prepush.sh                      # plan, then run
#   scripts/prepush.sh tests/foo/test_x.py  # plus the tests that use your symbol
#   scripts/prepush.sh --plan               # print the plan and exit 0
#   scripts/prepush.sh -j 4 ...             # worker cap (default 8)
#
# PREPUSH_RUNNER overrides the test runner (default scripts/run_tests.sh) and
# PREPUSH_PYTHON the interpreter for the doc-cite probe; both exist so the
# script's own test can drive it without running the suite.

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

PLAN_ONLY=0
JOBS=8
EXTRA=()
while [ $# -gt 0 ]; do
  case "$1" in
    --plan) PLAN_ONLY=1 ;;
    -j|--jobs) shift; JOBS="${1:?-j needs a number}" ;;
    -h|--help) sed -n '2,27p' "${BASH_SOURCE[0]}"; exit 0 ;;
    -*) echo "prepush: unknown option $1" >&2; exit 2 ;;
    *) EXTRA+=("$1") ;;
  esac
  shift
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

# One list, each file once, in plan order.
ALL=()
SEEN=$'\n'
for path in "${PREPUSH_QUEUE_GATES[@]}" "${PREPUSH_TEXT_GATES[@]}" \
    ${TOUCHED[@]+"${TOUCHED[@]}"} ${EXTRA[@]+"${EXTRA[@]}"}; do
  case "$SEEN" in *$'\n'"$path"$'\n'*) continue ;; esac
  SEEN="$SEEN$path"$'\n'
  ALL+=("$path")
done

_list() { local label="$1"; shift; echo "  $label ($#):"; for p in "$@"; do echo "    $p"; done; }
echo "prepush — base $(git rev-parse --short "$BASE") (merge-base with origin/main)"
_list "queue gates" "${PREPUSH_QUEUE_GATES[@]}"
_list "text gates" "${PREPUSH_TEXT_GATES[@]}"
_list "touched tests" ${TOUCHED[@]+"${TOUCHED[@]}"}
_list "named by you" ${EXTRA[@]+"${EXTRA[@]}"}
echo "  then: scripts/doc_cite_adjacency.py --exclude archive --exclude planned"
echo "  not run: the landing gate (scripts/run_tests_bundled.sh tests) and the importers of a"
echo "    symbol you changed unless you named them above"
[ "$PLAN_ONLY" = 1 ] && exit 0

RUNNER="${PREPUSH_RUNNER:-$SCRIPT_DIR/run_tests.sh}"
PY="${PREPUSH_PYTHON:-${HERMES_PYTHON:-python}}"
RED=0

echo "▶ ${#ALL[@]} test file(s), -j $JOBS"
bash "$RUNNER" -j "$JOBS" "${ALL[@]}"
rc=$?
if [ "$rc" -ne 0 ]; then
  echo "✘ prepush: tests red (exit $rc)"
  RED=1
fi

echo "▶ doc-cite adjacency"
"$PY" "$SCRIPT_DIR/doc_cite_adjacency.py" --exclude archive --exclude planned
rc=$?
if [ "$rc" -ne 0 ]; then
  echo "✘ prepush: doc-cite adjacency red (exit $rc)"
  RED=1
fi

if [ "$RED" -ne 0 ]; then
  echo "✘ prepush: RED — fix before pushing"
  exit 1
fi
echo "✔ prepush: green"
