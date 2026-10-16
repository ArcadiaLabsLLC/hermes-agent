# shellcheck shell=bash
# The fork's env-extension door for scripts/run_tests.sh (fork-hygiene CLASS row, 2026-10-15).
#
# run_tests.sh starts every test process under `env -i` with an explicit allowlist
# (TEST_ENV). That allowlist is upstream-owned, so each new fork test variable used to
# need a wrapper script of its own or another hunk in an upstream file. The fork's
# variables are listed instead in scripts/fork_test_env.txt — one NAME per
# line, `#` starts the reason — and this function appends each one that is set.
#
# Still an explicit allowlist: names only, no glob, so "no credential can leak"
# stays auditable in one tracked file. A line that is not a variable name fails
# the run (exit 2) rather than forwarding something unintended.

fork_test_env_extend() {
  local list="$1" line name
  [ -f "$list" ] || return 0
  while IFS= read -r line || [ -n "$line" ]; do
    name="${line%%#*}"
    name="${name//[[:space:]]/}"
    [ -n "$name" ] || continue
    case "$name" in
      [!A-Za-z_]* | *[!A-Za-z0-9_]*)
        echo "error: $list: not a variable name: $name" >&2
        return 2
        ;;
    esac
    if [ -n "${!name:-}" ]; then
      TEST_ENV+=("$name=${!name}")
    fi
  done <"$list"
}

# Fork (owner ruling 2026-10-15): on a workstation, no HERMES_PYTHON means the
# shared test venv (HERMES_TEST_VENV, default ~/.venvs/hermes-test), never the
# PM test environment activation would sync inside the operator's live Hermes
# home. Missing shared venv = refuse. CI keeps upstream's activation path.
fork_shared_test_venv_fallback() {
  if [ -z "${__HERMES_ACTIVATED:-}" ] && ! _has_pytest "${HERMES_PYTHON:-}" && [ -z "${CI:-}" ]; then
    _SHARED_VENV="${HERMES_TEST_VENV:-$HOME/.venvs/hermes-test}"
    for _candidate in "$_SHARED_VENV/Scripts/python.exe" "$_SHARED_VENV/bin/python"; do
      if _has_pytest "$_candidate"; then HERMES_PYTHON="$_candidate"; break; fi
    done
    if ! _has_pytest "${HERMES_PYTHON:-}"; then
      echo "error: no HERMES_PYTHON and no shared test venv with pytest at $_SHARED_VENV" >&2
      echo "       create it, or set HERMES_PYTHON / HERMES_TEST_VENV (Running the tests.md)" >&2
      exit 1
    fi
    echo "▶ no HERMES_PYTHON — using the shared test venv: $HERMES_PYTHON"
  fi
}

# Fork (rows 2026-10-15): say which interpreter runs the tests, and refuse one
# inside the operator's live store root (warn only under CI, whose store root
# is the runner's throwaway home) — owner ruling 2026-10-15.
fork_refuse_live_home_interpreter() {
  _TEST_INTERP="$(
    "$PYTHON" -c 'import os, sys
e = os.path.normcase(os.path.realpath(sys.executable)); r = sys.argv[1]
r = os.path.normcase(os.path.realpath(r)).rstrip(os.sep) + os.sep if r else ""
print(("INSIDE " if r and e.startswith(r) else "") + sys.executable)' "${REAL_HERMES_ROOT:-}" 2>/dev/null || true
  )"
  echo "▶ test interpreter: ${_TEST_INTERP#INSIDE }"
  if [ "${_TEST_INTERP#INSIDE }" != "$_TEST_INTERP" ]; then
    if [ -n "${CI:-}" ]; then
      echo "⚠ that interpreter lives inside the store root ($REAL_HERMES_ROOT)" >&2
    else
      echo "error: that interpreter lives inside the live Hermes home ($REAL_HERMES_ROOT); tests never run there — set HERMES_PYTHON to the shared test venv" >&2
      exit 1
    fi
  fi
}

# ── The functions below are the rest of run_tests.sh's fork blocks (lane pb-a) ──
# Each is called once from run_tests.sh, at the spot its block used to stand.
#
# Why tests/hermes_cli runs through run_tests.sh (`scripts/run_tests.sh
# tests/hermes_cli -j 6`): it is THE checkpoint runner for that directory, and a
# red is defined as "any FILE red under it". Running `pytest tests/hermes_cli`
# directly asks a different question: 568 files then share one interpreter,
# and ~41 failures appear in test_web_server_* / test_web_ui_build.py that are
# green when each file is run alone (ledger row F3). That is module-level
# state leaking across files — the exact thing per-file spawning exists to
# prevent — so it is a fact about the interpreter, not a defect in those
# tests, and it is not being chased (ML-7 / operator ruling R-e, 2026-08-18).
# Without the shared venv (fork_shared_test_venv_fallback) the runner activates
# the checkout (upstream's supported path).
#
# The Windows platform vars run_tests.sh forwards through `env -i` are opt-in for
# the same reason PATH/HOME are: they are not credentials, they are how the OS
# answers "where is the user, and where is scratch space". Without
# USERPROFILE/LOCALAPPDATA/APPDATA, CPython's ``Path.home()`` has nothing to
# resolve against and every import that touches it dies at COLLECTION time — a
# baseline run on Windows reported ~56 files failing for reasons no source change
# caused, which makes the failure-set diff (the only honest "is this mine?"
# signal) unreadable. SYSTEMROOT is required by the socket/ssl/subprocess
# machinery on Windows, and TEMP/TMP keep tempfile off a fabricated path. All six
# are absent-safe: `${VAR:+VAR="$VAR"}` expands to nothing on POSIX, so
# Linux/macOS/CI runs are byte-for-byte unchanged.
#
# SYSTEMROOT is read UPPERCASE on purpose. Windows treats env var names as
# case-insensitive; the shell reading them does not. git-bash exports the
# variable as `SYSTEMROOT`, so the mixed-case `${SystemRoot:+…}` run_tests.sh
# used to carry expanded to NOTHING and the var was silently dropped from the
# hermetic env — the exact class of dead guard it was written to prevent. The
# child is still handed it under the spelling Windows itself uses.
#
# The branch measurement's one variable: HERMES_TEST_COVERAGE_RC names a coverage
# config file. When it is set, every per-file subprocess becomes `coverage run
# --rcfile=<it> -m pytest <file>` (``scripts/_fork_runner.py::pytest_argv``); when
# it is not, the argv is byte-identical to what it has always been, so an
# ordinary run pays nothing. Its only caller is
# ``scripts/unreachable_branch_report.py``, which measures THROUGH run_tests.sh
# rather than re-spelling its hermetic env — a second spelling of that env would
# report branches taken under pins and variables no suite actually runs with.
# Nothing consumes the report's exit code: it is a report, not a gate.

# Fork-only test deps (requirements-fork-dev.txt): the one place they install.
fork_ensure_dev_deps() {
  "$PYTHON" "$REPO_ROOT/scripts/ensure_fork_dev_deps.py" || exit 1
}

# Fork (design sweep D3.08): the test-temp root is set ONCE, here, for the runner
# and every child it spawns — the runner's own scratch (run_tests_parallel.py's
# `hermes-pytest`) and the root conftest's `hermes-test-home-*` landed in %TEMP%
# otherwise. Unset, it defaults to a `test-tmp` directory beside the checkout or
# beside the primary checkout of a worktree (the operator's X:\Eternia\test-tmp);
# neither existing leaves today's behaviour.
fork_test_tmp_root() {
  if [ -z "${HERMES_TEST_TMP_ROOT:-}" ]; then
    _common_dir="$(git -C "$REPO_ROOT" rev-parse --path-format=absolute --git-common-dir 2>/dev/null || true)"
    for _tmp_candidate in "$REPO_ROOT/../test-tmp" ${_common_dir:+"$_common_dir/../../test-tmp"}; do
      if [ -d "$_tmp_candidate" ]; then
        HERMES_TEST_TMP_ROOT="$(cd "$_tmp_candidate" && { pwd -W 2>/dev/null || pwd; })"
        break
      fi
    done
  fi
  if [ -n "${HERMES_TEST_TMP_ROOT:-}" ] && [ -d "$HERMES_TEST_TMP_ROOT" ]; then
    export HERMES_TEST_TMP_ROOT TMP="$HERMES_TEST_TMP_ROOT" TEMP="$HERMES_TEST_TMP_ROOT" TMPDIR="$HERMES_TEST_TMP_ROOT"
    echo "▶ test temp root (runner and children): $HERMES_TEST_TMP_ROOT"
  fi
}

# Fork: SYSTEMDRIVE too. Without it the Git-Bash `sleep.exe` grandchild of a
# process-registry test survives `taskkill /T /F`, its stdout pipe never reaches
# EOF, and tests/hermes_cli/test_process_dock.py hangs in `stream.close()` to
# the per-test timeout (fork-hygiene-queue, 2026-09-26 row).
fork_win_env_extend() {
  [ -z "${SYSTEMDRIVE:-}" ] || WIN_ENV+=("SYSTEMDRIVE=$SYSTEMDRIVE")
}

# ── The operator's REAL store root, named for the fence ─────────────────────
#
# ``tests/hermes_cli/_gateway_fence.py`` has a "would run hermes against the
# operator's REAL store" arm. It learns that root by calling the production
# resolver, ``hermes_constants.get_default_hermes_root()`` — which reads
# ``HERMES_HOME``. Under BARE pytest, launched from an operator shell where
# HERMES_HOME names the live store, that answers correctly and the arm works.
#
# Under run_tests.sh it did not, and the reason is that script's `env -i`:
# HERMES_HOME is deliberately not forwarded, so ``tests/conftest.py`` mints a
# throwaway session home, the fence imports AFTER that, and the resolver hands
# it the TEMPDIR. Measured on this workstation 2026-09-03, before this block:
#
#   _REAL_ROOT under run_tests.sh = C:\...\Temp\hermes-test-home-g_quyxlh
#   _REAL_ROOT under bare pytest  = X:\Eternia\.hermes
#
# and a `hermes config get` argv aimed at X:\Eternia\.hermes\profiles\alice
# classified ALLOWED in the first case, REFUSED in the second.
#
# So the whole arm — and the three tests in test_gateway_spawn_fence.py that
# drive it — was measuring a directory that had existed for a few milliseconds
# and would never appear in any argv. The defence existed only on the path
# nobody is told to use.
#
# Forwarding HERMES_HOME itself is NOT the fix: conftest must keep installing
# its own hermetic home, and handing the child the real one would put the live
# store back in front of every test — the hazard, not the guard. Instead the
# root travels under a dedicated TEST-ONLY name the fence reads first
# (run_tests.sh forwards REAL_HERMES_ROOT as HERMES_TEST_REAL_ROOT).
# HERMES_REAL_HOME was NOT reused: that is a production variable
# (``hermes_constants.py`` ``_iter_real_home_candidates``, whose first
# candidate it is — the OS-user home an ACP child inherits, not a
# store root) and ``tests/conftest.py`` blanks it per test on purpose.
#
# Computed with the probed venv python and the production resolver rather than
# re-derived in shell, so the "which profile dir belongs to which root"
# unwrapping has exactly one implementation. Fail-soft: if the probe prints
# nothing the variable is not forwarded and the fence falls back to today's
# behavior. Runs from REPO_ROOT (the probe imports hermes_constants from ".").
fork_real_root_fence() {
  REAL_HERMES_ROOT="$(
    "$PYTHON" -c 'import sys; sys.path.insert(0, "."); from hermes_constants import get_default_hermes_root; print(get_default_hermes_root())' \
      2>/dev/null || true
  )"
  if [ -n "$REAL_HERMES_ROOT" ]; then
    echo "▶ real store root handed to the gateway fence: $REAL_HERMES_ROOT"
  fi
  fork_refuse_live_home_interpreter
}
