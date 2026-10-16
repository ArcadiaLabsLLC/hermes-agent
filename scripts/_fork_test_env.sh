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
