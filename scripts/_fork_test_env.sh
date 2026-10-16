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
