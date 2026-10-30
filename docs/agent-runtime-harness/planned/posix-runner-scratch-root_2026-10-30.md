# Planned — the named test-temp root owns the runner's own scratch on POSIX too

**Status:** planned 2026-10-30 (planning lane w1030p-h), row
`FH-POSIX-RUNNER-IGNORES-TEST-TMP-ROOT` (fork-hygiene queue). Continues design sweep
[D3.08](design-sweep-d3-2026-10-10.md)
(built `b802ea9d57`). Owner doc: [`../../downstream-development.md`](../../downstream-development.md).

## In plain English

`HERMES_TEST_TMP_ROOT` is "the one place the test temp is set; every fixture inherits it"
(D3.08). On Windows that is true: `scripts/run_tests.sh` exports the root as `TEMP`, upstream's
`_runner_scratch_root` builds its `hermes-pytest` scratch under `tempfile.gettempdir()`, and
every child's `tmp_path` lands under the root. On POSIX the same upstream function hard-codes
`/var/tmp/hermes-pytest-<uid>` whenever `/var/tmp` exists, so with the root set a POSIX run is
split across TWO roots: every `tmp_path` under `/var/tmp`, every `tempfile.*` call under
`<root>/run-*` (the conftest plugin's redirect) — two prunes, two places to look after a red,
and the runner's own banner, "test temp root (runner and children)", is wrong for the runner.

This plan makes the banner true on every platform with one additive line in the upstream
function and a seam in the fork's own runner module, states the AF_UNIX path budget a named
root must respect, and has `run_tests.sh` say so when a root is over it.

## Where the tree and the notes disagree (the tree is followed)

Three notes say the runner scratch already follows the root — `scripts/_fork_test_env.sh`'s
comment above `fork_test_tmp_root` ("the runner's own scratch … landed in %TEMP% otherwise"),
`Harness_Brain/50 — Agent Handoffs/Running the tests.md` ("exports it as TEMP/TMP for the
RUNNER too, so its `hermes-pytest` scratch … stay out of `%TEMP%`") and the D3.08 stage 1 text.
The tree says otherwise on POSIX: `scripts/run_tests_parallel.py::_runner_scratch_root` takes
`tempfile.gettempdir()` only when `os.name == "nt"` or `/var/tmp` is missing. The one note that
matches the tree, the comment in `tests/scripts/test_run_tests_tmp_root.py`, calls the POSIX
split "by design"; no ruling records that design, and the notes written BEFORE the test say the
opposite, so that comment is read as a rationalisation of the tree after the fact. The tree is
upstream code and is followed as the fact; the design question is answered below.

## Decisions

### D1 — Yes: on POSIX the named root owns the runner scratch too

**Why.**

- The variable's contract is D3.08's: one root, set once, inherited by everything the run
  creates. An operator who sets it (or creates the `test-tmp` directory beside the checkout that
  defaults it) has said where the test temp goes; a runner that keeps its largest tree —
  every `tmp_path` fixture — somewhere else is the surprise, not the hard-code.
- Upstream's four reasons for `/var/tmp` are met or moot under an operator-named root:
  disk-backed (the plugin already lands every child's `tempfile.*` there; a tmpfs root would
  already be the operator's choice today), not under the Hermes home and not under a dot-dir
  (documented as the two roots not to name — the same constraint the plugin's redirect already
  carries silently), short enough for AF_UNIX sockets (a budget, D3, not a veto).
- The Linux box is now a primary lane host (14 lanes, 52 GB VM). The 983-root / 3.4 GB leak the
  upstream sweep comment records is a root-filesystem leak there; the named root was built to
  keep exactly that out of the system's own temp.
- Rejected: "Windows-only by design, fix the notes". Nothing in the POSIX reasons is
  platform-specific except `sun_path`, which D3 bounds; the two-root split is a worse state
  than either root alone.

### D2 — Mechanism: one additive line upstream, the seam in `scripts/_fork_runner.py`

- `scripts/_fork_runner.py` gains `scratch_root(name: str, default: str, environ=os.environ) -> str`:
  when `HERMES_TEST_TMP_ROOT` names an existing directory, `os.path.join(root, name)`; otherwise
  `default`. Pure, environ-injected, platform-neutral.
- `scripts/run_tests_parallel.py::_runner_scratch_root` gets ONE line before its `makedirs`:
  `root = _fork_scratch_root(name, root)  # Fork: scripts/_fork_runner.py` (import added to the
  existing fork import line). On Windows this is identical by value to today
  (`TEMP` = root ⇒ `gettempdir()/name` = `<root>/name`), so the fork no longer reasons per
  platform at all.
- Footprint: `scripts/run_tests_parallel.py` is already an edited upstream file (127/16);
  +1 added changes none of `files` / `deleted_lines` / `heavy` (128 + 16 < 200), so the fixture
  does not rise and no owner ruling is needed. The slice regenerates the ledger
  (`scripts/upstream_footprint.py --ledger`) and extends the row's reason cell.
- Why the seam lives in `_fork_runner.py` and not a new module: the module's own charter is
  "everything the fork adds to how a per-file subprocess is spawned", and
  `tests/scripts/test_run_tests_parallel.py::_probe_root` copies exactly
  `run_tests_parallel.py` + `_fork_runner.py` into a probe root — a new module reds six probe
  tests until each copy list learns it.
- Why not a fork-side wrapper that re-points the upstream function by name: silent on an
  upstream rename (the behaviour reverts and nothing says so until the shell test reds), and
  a second entry point for a runner that already has one.
- `scripts/run_tests_bundled.py` (`rtp._runner_scratch_root()` for its `bundles-*` scratch)
  follows for free; `_sweep_killed_run_roots` prunes the same directory it always did, now
  under the root; the plugin's hourly prune of `<root>` top-level entries older than a day cannot
  take the scratch out from under a run — the runner's own `mkdtemp(prefix="r-")` refreshes
  its mtime before the first child starts, and the plugin's `sweep_system_temp` never looks
  inside the redirect root.

### D3 — The AF_UNIX budget: a named root is at most 40 bytes on POSIX, and the runner scratch adds nothing to it

**Measured in the tree.** No test binds a socket under `tmp_path` (the directory the runner
scratch hosts). Every binder uses a SHORT `mkdtemp` directly under `tempfile.gettempdir()` —
`tests/gateway/test_shutdown_watchdog.py::short_home`,
`tests/gateway/test_scale_to_zero.py::short_sock_dir`, the module-level `tmp_path` override in
`tests/hermes_cli/test_update_wedged_gateway.py`, the `TemporaryDirectory(prefix='h-owner-')`
in `tests/hermes_cli/test_gateway_runtime_discovery.py` — or production's own
`gateway/control_socket.py::_fits_sun_path` fallback (`tests/cron/test_tick_without_gateway.py`).
On POSIX `gettempdir()` in a child is ALREADY `<root>/run-XXXXXXXX` through the conftest plugin,
so the budget is a property of the named root that exists today; moving the runner scratch
under it moves no socket path.

**The number.** The deepest in-tree socket path is
`<root>/run-XXXXXXXX/hwg-XXXXXXXX/state/gateway.loop-tick.<pid>.sock` = L + 13 + 13 + 6 + 19 +
≤7 + 5 = **L + 63** bytes (`gateway/shutdown_watchdog.py::get_loop_tick_socket_path` names the
leaf; Linux pids are at most 7 digits). `sun_path` is 108 on Linux (107 usable) and 104 on
macOS/BSD (103 usable): **L ≤ 40** keeps the deepest path under both. Today's upstream root
`/var/tmp/hermes-pytest-<uid>` is 27 bytes for a four-digit uid; an operator root such as
`~/Eternia/test-tmp` expands to 28 on this box. Windows is out of scope (named pipes).

**Enforcement is a warning, not a refusal.** `fork_test_tmp_root` (POSIX branch) prints
`⚠ test temp root is N bytes; over the 40-byte AF_UNIX budget, socket tests may fail with
"AF_UNIX path too long"` and still follows the root — the plugin has followed it regardless of
length since Stage 7, and the operator chose it. The constant and its derivation live in one
place, `scripts/_fork_test_env.sh`, beside the check.

### D4 — The docs say which

`docs/downstream-development.md`'s `HERMES_TEST_TMP_ROOT` sentence becomes: the root owns the
runner's own scratch and every child on every platform (the seam), the two roots not to name
(the Hermes home, a dot-dir), and the 40-byte POSIX budget with its reason.
`Running the tests.md` and the `_fork_test_env.sh` comment become true as written;
`tests/scripts/test_run_tests_tmp_root.py` loses its platform branch and its "by design" comment.

## Slices (landing order)

### S1 — the seam, the line, the test on every platform  (`FH-RUNNER-SCRATCH-FOLLOWS-TEST-TMP-ROOT`)

Files: `scripts/_fork_runner.py` (`scratch_root`), `scripts/run_tests_parallel.py`
(`_runner_scratch_root`: one added line + the import name), `docs/agent-runtime-harness/planned/upstream-footprint-ledger.md`
(regenerated; reason cell names this row), `tests/scripts/test_run_tests_tmp_root.py` (assert
`scratch = root` on every platform; delete the POSIX branch and comment),
`tests/scripts/test_run_tests_parallel_downstream.py` (unit arms for `scratch_root`: unset ⇒
default; set to a missing dir ⇒ default; set to a dir ⇒ `<root>/<name>`),
`docs/downstream-development.md`, `Harness_Brain/50 — Agent Handoffs/Running the tests.md`,
`scripts/_fork_test_env.sh` (comment only).
Test: `tests/scripts/test_run_tests_tmp_root.py` (spawns `run_tests.sh` with a throwaway root
on an out-of-repo probe) and the unit arms.
Killing mutation: make `scratch_root` return `default` unconditionally — on POSIX the probe's
`PYTEST_DEBUG_TEMPROOT` lands under `/var/tmp/hermes-pytest-<uid>`, the shell test reds; the
"set to a dir" unit arm reds on every platform.
Runs: the two test files above and `tests/scripts/test_run_tests_parallel.py` (probe copies),
`tests/scripts/test_upstream_footprint.py` (the ledger regen).

### S2 — the POSIX budget warning  (`FH-TEST-TMP-ROOT-SUN-PATH-BUDGET`)

Files: `scripts/_fork_test_env.sh` (`fork_test_tmp_root`: the 40-byte constant with its
derivation, the warning line, POSIX only — skip when `cygpath` exists),
`tests/scripts/test_run_tests_tmp_root.py` (a root longer than 40 bytes prints the warning and
the run still exits 0; a short one — a `mkdtemp` directly under `tempfile.gettempdir()`, the
same shape the socket tests use — prints none), `docs/downstream-development.md` (the budget
sentence; lands with S1's edit if the lanes merge).
Test: `tests/scripts/test_run_tests_tmp_root.py`.
Killing mutation: compare against 400 instead of 40 — the long-root arm sees no warning, red.
Runs: `tests/scripts/test_run_tests_tmp_root.py`, `tests/scripts/test_run_tests_shell.py`.

## Risks

- A named root longer than 40 bytes was already a socket-test hazard on POSIX before this plan
  (the plugin follows it for `gettempdir()`); S2 makes the hazard visible, it does not create or
  remove it.
- An operator root under a dot-dir or the Hermes home breaks the hidden-dir search tests /
  relocates basetemp — the same today for every child's `tempfile.*`. Documented, not guarded:
  the plugin has never guarded it either, and a guard here would be a second policy on one root.
- Upstream renames `_runner_scratch_root` or drops the `name` variable at a sync: the one-line
  hunk conflicts visibly (the file "conflicts every sync" already — Fork Boundary Map) and
  `test_run_tests_tmp_root.py` reds on POSIX if the seam is lost.
- Unchanged by design: a box with neither the variable nor a `test-tmp` directory beside the
  checkout keeps `/var/tmp/hermes-pytest-<uid>` exactly as today.

## Owner questions

None. Every decision above is technical with a clear best answer; the one process constraint
that could have needed a ruling (a footprint raise) does not arise.
