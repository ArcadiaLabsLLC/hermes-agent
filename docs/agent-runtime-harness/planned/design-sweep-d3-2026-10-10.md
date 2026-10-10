# Design sweep D3 — suite isolation, timing flakes, footprint, release-gate scope (2026-10-10)

Lane fable-design-D3 over the 17 rows a lane-1010 fix lane returned as too big
(`Harness_Brain/20 — Active Initiatives/queue-sweep-2026-10-10/D3-rows.md` is the sheet;
each `Ln.NN` is that lane's outcome line). Design only: no production or test code changed
here. Every verdict is one of PLAN (implementation-ready for an Opus build lane),
PROGRAM-EXISTS (a plan or standing lane owns it), INVESTIGATION (cause unknown; the
measurement protocol is the deliverable), DROP (stale or wrong, with the evidence).

Owner rulings 2026-10-10 this sweep follows: the turn-cost / timing files keep their
absolute budgets and run only on an idle box, serial, never inside a parallel gate — no load
margin (fork-hygiene-queue rows "turn-cost guard span budgets", "send-window GIL-stall
positive control", "turn-cost guard's absolute warm bound"). Rows sharing one mechanism get
ONE design and pointers: process-global state (D3.12 → the standing CLASS row), temp homes
(D3.08), the user-PATH writers (D3.15), the index-lock writers (D3.16), the GIL-hog positive
controls (D3.01 ← D3.09).

Files are cited by path and symbol, never line number. "Upstream" means present in
`v0.21.6` (`git cat-file -e v0.21.6:<path>`); an upstream file is edited additively or not at
all, and every such edit names its row in
`docs/agent-runtime-harness/planned/upstream-footprint-ledger.md`. A lane that lands a stage
runs only the test files that import a module it touched (`Running the tests.md`); the
landing runs the gate once per batch.

## D3.01 = L2.06 — the send-window GIL-hog stall floor is scheduler-dependent

**Verdict: PLAN** (one design for the GIL-hog positive controls; D3.09 points here).

**Decision and why.** `tests/agent_runtime/test_send_window_receipt.py::test_a_gil_hog_in_the_send_window_shows_as_a_local_stall`
asserts `stall_over50_ms >= 500`. The number comes from `agent_runtime.stream_gap_receipt._StallProbe`
(a daemon thread sleeping `STALL_INTERVAL_S` = 10 ms and summing wake-ups later than
`STALL_REPORT_FLOOR_MS` = 50 ms) between the request hook and the first parsed event
(`SendWindow.begin` → `SendWindow.on_first_event`). The hog (`big * big` on a 700,000-digit
int, ~70 ms per GIL hold) starves the main thread's httpx read as well as the probe, so on an
idle box the window stretches to 5.6–7.9 s and the stall sums to 4.9–7.4 s (L2.06, 6/6
green). Under gate load the OS gives the hog thread less CPU, the main thread parses the
first event ~300 ms after the fake server's `time.sleep(0.3)`, and the window closes with
76–232 ms of stall. The floor is right for what it measures; the window length is what load
changes. The owner ruled: keep the budgets, run these files on an idle box, serial. The
mechanism for "idle box only" does not exist yet — `slow_native` is a registered marker with
no consumer in `scripts/` (grep: only its `pytest_configure` registration), and the bundled
runner's solo list (`scripts/test_bundles_unbundled.txt`) still runs a solo INSIDE the
8-worker gate. So the design is the mechanism, not a new number.

**Files and symbols.** All fork-owned.
- `scripts/test_idle_box_files.txt` (new): one repo-relative path per line, the owner ruling
  as its header; initial rows `tests/agent_runtime/test_send_window_receipt.py`,
  `tests/agent_runtime/test_stream_gap_receipt.py`,
  `tests/agent_runtime/test_turn_cost_guard_downstream.py`.
- `tests/_downstream/conftest_plugin.py`: `pytest_configure` registers marker `idle_box`;
  `pytest_collection_modifyitems` adds it to every item whose file is on the list;
  `pytest_runtest_setup` skips an `idle_box` item unless `HERMES_TEST_IDLE_BOX=1`, reason
  "idle-box file (owner ruling 2026-10-10): run scripts/run_tests_idle.sh".
- `scripts/run_tests_bundled.py`: `select_scope` gains `idle_box: Iterable[str]` and a
  `ScopeSelection.idle_box` bucket; a listed file goes there (and nowhere else) unless NAMED
  on the command line, same shape as the skip list (owner ruling O1); the Summary prints
  "idle-box: N files not run — scripts/run_tests_idle.sh".
- `scripts/run_tests_idle.sh` (new): refuses to start while another `pytest`/`run_tests`
  process is alive (tasklist/psutil, printed), then runs the list through `scripts/run_tests.sh`
  with `HERMES_TEST_WORKERS=1 HERMES_TEST_IDLE_BOX=1`, appending its record to
  `.pytest_cache/hermes_bundled_runs.jsonl` with `kind: idle`.
- `Harness_Brain/50 — Agent Handoffs/Running the tests.md`: a step after "What a landing runs,
  once": when the batch touches `agent_runtime/send_window_receipt.py`,
  `agent_runtime/stream_gap_receipt.py`, `agent_runtime/transport_phase_trace.py` or the
  turn-cost path, the landing runs `scripts/run_tests_idle.sh` after the gate, box idle, and
  quotes its jsonl line.

**Stages.**
1. List + marker + skip. Test `tests/scripts/test_idle_box_files.py`: every listed file
   exists and is absent from `tests/fixtures/upstream_manifest.txt`; a subprocess pytest of a
   throwaway marked test skips without the env and runs with it. Killing mutation: drop the
   env check in `pytest_runtest_setup` → the "without env" arm reds (the test ran).
2. Runner bucket. Unit test over `select_scope` with a fake list: the listed file lands in
   `idle_box`, a NAMED listed file in `named`. Killing mutation: delete the `idle_box` branch
   → the file lands in `fork_only`.
3. `run_tests_idle.sh` + the handoff page + close the four fork-hygiene rows that carry the
   ruling by pointing at this section.

**Size.** S–M: ~120 lines of script/plugin, ~60 of tests, docs. One MOVE-free lane, one
CHANGE commit per stage.

**Risks.** The three files stop running in any gate unless the idle step is run; the handoff
step and the jsonl `kind: idle` record are the only evidence it was. A hardening of the hog
test itself (the server holds its headers until the hog has done K multiplies, so the window
is hog-paced not scheduler-paced) was weighed and NOT planned: `SendWindow.fields` picks
`wait_on` as the largest of local/network/server shares, and a K-paced window makes
`server_wait_ms` ≈ the stall, so `wait_on == "local"` would flip by construction (L2.06 saw
this). Re-open only if the idle runs still flake.

**Owner question.** None blocking. (Optional: should `scripts/run_tests_idle.sh` refuse to
run, rather than warn, while another heavy process is alive? Default here: refuse.)

## D3.02 = L4.05 — writer preflight against a vanishing SQLite WAL sidecar

**Verdict: PLAN** (cause named from the code; the reproducer is stage 1 and decides it).

**Decision and why.** `hermes_state_repair.preflight_db_writability` (upstream) builds its
list as `[(p, False) for p in (db_path, *sidecars) if p.is_file()]`, then tests each with
`os.access(p, os.R_OK | os.W_OK)`. `os.access` returns False for a path that does not exist.
SQLite unlinks `state.db-wal`/`-shm` when the last connection to a WAL database closes, so a
sidecar that was a file at list-build time and is gone at the access call reads as
"read-only", `in_scope` chmod fails (`OSError` suppressed), and the function raises
`sqlite3.OperationalError("state.db is not writable: file …state.db-wal is read-only…")` —
the exact message the 2026-10-01 observer saw while a native reader was coming and going.
The fix is one guard: a sidecar that no longer exists is a finished checkpoint, not a
permission problem. `read_only=True` opens (`SessionDB._open_read_only`) never call the
preflight, which is why the observer fix worked and why it proved nothing about the writer.

**Files and symbols.**
- `hermes_state_repair.py::preflight_db_writability` (upstream): before the refusal, `if not
  is_dir and not p.exists(): continue` — two added lines, no deletion. Ledger row: `carry`,
  reason "vanished-WAL TOCTOU in the writer preflight; upstream PR candidate (body under the
  operator's `pr-bodies/`)"; the PR itself waits on the account's PR access (fork-hygiene row
  "the `nekwo` account cannot create upstream PRs", RULED maintainer-side).
- `tests/hermes_state/test_preflight_vanished_wal_downstream.py` (new, fork): the reproducer.

**Stages.**
1. Reproducer first, on the unchanged tree: create `state.db` and `state.db-wal` as files;
   monkeypatch `os.access` so its first call for the `-wal` path unlinks it, then delegates
   to the real `os.access`; call `preflight_db_writability`. Expected on today's code: raises
   with "-wal". If it does NOT raise, the hypothesis is wrong — stop, report, leave the row
   INVESTIGATION with the live-reader protocol below.
2. The two-line guard; the test now passes; killing mutation = revert the guard (the stage-1
   red, recorded in the commit body). Ledger row in the same commit; fixture
   `tests/fixtures/upstream_footprint.json` follows (`reasons` row).
3. Optional live control (no idle box needed, ~1 min): thread A opens and closes
   `SessionDB(path)` in a loop (WAL appears and vanishes); the main thread calls
   `preflight_db_writability(path)` 10,000 times and counts raises before/after the guard.
   Report the two counts; not a gate (timing-shaped).

**Size.** S: 2 production lines, ~40 test lines, one ledger row.

**Risks.** None to behaviour: a genuinely read-only sidecar still exists and still raises.
**Owner question.** Accept one more carried hunk in `hermes_state_repair.py` until the PR can
be opened? (The alternative — no fork fix until upstream merges — leaves the live race.)

## D3.03 = L6.02 — the 2026-10-07 carried-PR sync landed eight unledgered upstream edits

**Verdict: PLAN** (a footprint lane with upstream-edit licence; the owner grants it or
this stays filed).

**Decision and why.** The ledger rows marked `W1 2026-10-08` name the eight hunks. Three
are fork tests inside upstream test files (`tests/agent/test_turn_context.py` +8,
`tests/hermes_cli/test_uninstall_dry_run.py` +1,
`tests/tools/test_windows_agent_loop_papercuts.py` +23): the rule is already written —
"a fork test never goes inside an upstream test file" (`Running the tests.md`). Two are
pure drops: `tests/hermes_cli/test_worktree_sync_base.py` (a comment respelled) and the
three `inference_base_url` literals in `tests/hermes_cli/test_auth_commands.py`, which pair
PR #121642 — name it in `tests/fixtures/carried_prs.json` if its diff carries them, else
restore tag bytes and move the assertions out. `_posix_match_forms` exists in NEITHER file
at `v0.21.6` (`git grep` on the tag: none) — both copies are fork hunks and one of them is
redundant with the fork's own `tools.path_identity`. Two are real NON-ADDITIVE fixes with no
PR (`plugins/plugin_loader.py` +5/−1, `tools/file_tools_read_tracking.py` +12/−4): they
stay carries until a PR exists, and the plan does not pretend otherwise. The structural
half is the gate: `scripts/upstream_footprint.py::merge_ledger` admits a new row as
`carry / unreviewed / -` and nothing reds on it, so a sync job can land upstream edits with
no reason and no manifest entry — exactly what happened.

**Files and symbols.**
- MOVE (one commit): the three tests → `tests/agent/test_turn_context_downstream.py`,
  `tests/hermes_cli/test_uninstall_dry_run_downstream.py`,
  `tests/tools/test_windows_agent_loop_papercuts_downstream.py`, importing upstream's
  fixtures; the three upstream files restored to `v0.21.6` bytes (`git checkout v0.21.6 --
  <file>`, diff read before staging: nothing but the moved tests may change).
- CHANGE (one commit): `test_worktree_sync_base.py` → tag bytes; `test_auth_commands.py` →
  PR #121642 named in `carried_prs.json` (`files` entry, mode `hunks`) or tag bytes + a
  `_downstream.py`; `_posix_match_forms` kept once in fork-owned `tools/path_identity.py`
  with a one-line import in each upstream file (the two defs deleted — a footprint drop, so
  `test_duplicate_helper_bodies` goes green on it); ledger rows rewritten for all eight;
  `tests/fixtures/upstream_footprint.json` regenerated in the same commit (files 185 → 182
  expected; `reasons` rows for the two held carries).
- GATE: `tests/scripts/test_upstream_footprint.py::test_no_ledger_row_is_unreviewed_or_unledgered`
  — red when any ledger row's reason starts `unreviewed` or contains `landed unledgered`.
  A negative source-walk over the ledger, which is the artefact itself, so over-approximation
  is the safe direction. Killing mutation: run `scripts/upstream_footprint.py --ledger` after
  a throwaway edit to an upstream file → the new `unreviewed` row reds the gate.
- `Harness_Brain/50 — Agent Handoffs/Merging upstream.md` and the carried-PR job's brief
  (`docs/agent-runtime-harness/planned/carried-pr-sync-2026-10-07.md`, "Job 1"): the sync
  commit carries its ledger rows and `carried_prs.json` entries; the gate enforces it at
  landing.

**Stages.** 1 MOVE. 2 CHANGE. 3 GATE + runbook. Each stage's tests: the moved files and
`tests/scripts/test_upstream_footprint.py`, `tests/scripts/test_duplicate_helper_bodies*`;
the landing's gate covers the upstream files restored.

**Size.** M: ~6 files moved/restored, ~40 lines of gate, ledger edits.

**Risks.** Restoring an upstream test file to tag bytes can drop a fix the fork relies on —
the diff is read, not assumed. The two held carries keep 5 deleted lines in the footprint.
**Owner questions.** (1) Grant the upstream-edit licence for this lane (the files are
upstream; refactor lanes may not touch them). (2) The two NON-ADDITIVE fixes: hold as carries
with PR bodies drafted, or rewrite additively now (plugin_loader's one deleted line is a
condition that can become a second branch; read_tracking's four are a stat/fstat compare
that cannot be made additive without a wrapper, which is still a deletion at the call site)?

## D3.04 = L6.14 — the serve-socket disconnect test's second subscriber-release path

**Verdict: PLAN** (the second path is named; the test gets a deterministic shape and a
killing mutation).

**Decision and why.** `tests/agent_runtime/test_serve_socket_lane.py::test_a_disconnect_unsubscribes_and_does_nothing_else`
subscribes a `leaver` to `_fake_stream`, which yields a `delta` every 5 ms, closes the
socket, polls `connections` until `count == 1`, then asserts `subscribers == 0` at once.
Two paths release the subscriber. (a) The server's read loop sees EOF →
`agent_runtime/serve_socket/server.py::SocketServer._drop_connection` pops the connection,
closes it, calls `on_disconnect` →
`hermes_cli/harness_parts/serve/subscriptions.py::SubscriptionLanes._on_connection_closed` →
`_release_subscription` → `hub.unsubscribe(key)`. (b) The hub's own consumer thread:
`agent_runtime/serve_stream_hub.py::_Subscription._run` writes the next 5 ms delta to the
RAW sink (`handle_message.py` subscribes with `sink=raw_sink`, not the swallowing
`frames._SafeSink`), the write raises on the closed socket, `_drop_reason =
"sink_error:<Type>"`, `_notify_drop` → `handle_message.py::_on_stream_drop` emits
`subscription_dropped`, and the subscription leaves the room. With a 5 ms delta cadence (b)
almost always wins, which is why L6.14's 0.5 s delays inside `_drop_connection` and the
outright deletion of `_release_subscription` both stayed green: the test never exercised (a).
The recorded red is the one ordering where the poll saw `count == 1` (the pop happens before
`on_disconnect`) and neither path had released yet. A both-halves poll fixes the red; it has
no killing mutation while (b) is in play — so the test must take (b) out.

**Files and symbols.** Fork-owned test only; no production change.
- `tests/agent_runtime/test_serve_socket_lane.py`: a second stream factory
  `_quiet_stream(gate)` that yields one `hydrate` and then blocks on `gate.wait()` (no
  deltas, so no sink write can fail after the close). The disconnect test uses it, polls
  until `count == 1 and subscribers == 0` (deadline `WAIT`), then asserts the full summary.
  Its docstring names paths (a) and (b). A sibling test keeps (b) honest:
  `test_a_dead_subscriber_socket_is_dropped_by_the_fan_out_with_a_typed_reason` uses
  `_fake_stream`, closes the leaver, and reads the stayer's `subscription_dropped`-shaped
  log receipt / `connections` summary (`subscriptions.subscribers == 0` before the server's
  close receipt for that key, or simply that the drop reason is `sink_error:*`).

**Stages.**
1. Stage 0, measurement (one run, no idle box): a throwaway log line in `hub.unsubscribe`
   and in `_Subscription._run`'s except branch; run the file 3× with
   `HERMES_TEST_WORKERS=2 scripts/run_tests.sh tests/agent_runtime/test_serve_socket_lane.py`;
   record which fired first in the commit body; revert the log lines.
2. The quiet-stream test + both-halves poll. Killing mutation: delete `hub.unsubscribe(key)`
   in `_release_subscription` → the test times out with `subscribers == 1` (red recorded).
3. The fan-out sibling test. Killing mutation: make the hub swallow sink exceptions (wrap
   `self._sink(...)` in `except Exception: pass`) → no `sink_error` drop, red.

**Size.** S: ~60 test lines.

**Risks.** If stage 0 shows (b) is NOT the path (e.g. the room drops subscribers on
`frames_out` accounting instead), the quiet-stream shape still isolates (a) — the sibling
test's premise changes, not the plan.
**Owner question.** None.

## D3.05 = L6.32 — no test loads a live-shape multi-profile config root through the producer

**Verdict: PLAN** (the two design calls the lane returned are made below; one owner
question on publishing sanitized shapes).

**Decision and why.** The refusal is fixed (`a40612b68c`, `5c02a698ae`) and
`tests/agent_runtime/test_persona_records.py::test_a_profile_config_carrying_the_key_keeps_the_producer_serving`
pins ONE key on ONE hand-written config. The gap is the class: a config-reading change is
never run against a root shaped like the operator's. Census of the operator's live root
(key paths only, 2026-10-10): ten profiles, 148–705 keys each, 0–5 personas; four shapes —
the bundled minimum (`base`: 148 keys, 5 personas), the full operator persona home
(`alice`/`neko`/`unbounded`: ~700 keys, 5 personas), the lane/QA home
(`backend-dev`, `launcher-*`, `qa`: ~430 keys, 1 persona), and the persona-less home
(`gpt-launcher`: 0 personas). Representative = one of each: `base`, `neko` (the refusal's
carrier), `launcher-qa`, `gpt-launcher`. Which producer entry: the serve's rebuild is
`agent_runtime/stream/build.py` → `agent_runtime/snapshot/build.py::build_snapshot`
(`hydrate_frame` wraps the same call), so the test drives `build_snapshot`, with
`load_agent_runtime_config` + `persona_records_from_config` run first so a config-read raise
is attributed to the read, not the build.

**Files and symbols.** All fork-owned.
- `scripts/sanitize_profile_config.py` (new): reads one `config.yaml`, keeps every key and
  every value's TYPE; replaces a string whose key matches
  `key|token|secret|password|url|host|path|home|dir|email` or whose value contains a drive
  or home prefix with `<redacted:<kind>>`; keeps booleans, numbers, enumerations, persona
  ids, toolset and model names (the shape under test). Writes
  `tests/fixtures/profile_roots/live-<yyyy-mm>/<profile>/config.yaml` and the
  `profile.yaml` identity marker (`bundled_persona_profiles` explains why the marker is not
  `config.yaml`). Idempotent; re-run at each release merge (`Merging upstream.md` step).
- `tests/fixtures/profile_roots/live-2026-10/{base,neko,launcher-qa,gpt-launcher}/` plus
  `expected_issues.json` per profile: the `DeclarationIssueKind` codes the root is KNOWN to
  carry (for `neko`: `persona_toolsets_key_refused` × carriers, until the startup migration
  strips it).
- `tests/agent_runtime/test_live_shape_profile_roots.py` (new), parametrized over the four
  profiles: copy the fixture root to `tmp_path`, point `HERMES_HOME` at it, run
  `load_agent_runtime_config()`, `persona_records_from_config(cfg)`,
  `merge_persisted_personas([], cfg)`, then `build_snapshot(build_info={"caller": "test",
  "reason": "live-shape"})`; assert no exception, every issue code ∈ `expected_issues.json`,
  and the snapshot's persona count equals the config's.

**Stages.**
1. Sanitizer + the four fixture roots (the operator runs the script against the live root;
   the lane commits the output after reading it — no secret may land).
2. The producer test. Killing mutation: restore the raise in `persona_records_from_config`
   (`if "toolsets" in overrides: raise RuntimeError(...)`) → `neko` reds; a second mutation,
   drop `gpt-launcher`'s `personas: {}` handling in `merge_persisted_personas` → that arm
   reds. Both reds recorded.
3. Runbook line in `Merging upstream.md` ("re-cut the live-shape roots") and a pointer from
   `Touching the harness CLI.md`.

**Size.** M: ~120 lines of sanitizer, 4 small fixture roots, ~80 test lines.

**Risks.** The fixture ages: a key the operator adds next month is not in it until the
re-cut — hence the runbook step, and the dated directory name. `build_snapshot` reads the
runtime store too; the test gives it an empty store (as other `build_snapshot` tests do).
**Owner question.** May sanitized shapes of the operator's profile configs (persona ids,
toolset names, model names, mode enumerations — no secrets, no paths) be committed to the
fork repository?

## D3.06 = L6.34 — CLASS: every new upstream test patching `load_config` needs a hand-added id

**Verdict: PLAN** (a rule computed from the ledger and the import graph replaces the id set).

**Decision and why.** `tests/_downstream/conftest_plugin.py`'s read-through fixture makes
`hermes_cli.config.load_config_readonly` defer to `load_config()` for the ids
`tests/_downstream/id_markers/fork_marks.py` marks `_CONFIG_READ_THROUGH`. The lane's
objection stands against a BLANKET read-through: upstream's own `load_config_readonly`
callers (~196 files) inside an upstream test that patches `load_config` would start
reading the patch, a semantic change. The rule that is both automatic and narrow has two
halves. (1) WHICH tests: an item whose test file imports a reader the FORK moved to
`load_config_readonly`. The moved readers are exactly the ledger rows that name
`load_config_readonly` — today `hermes_cli/config.py`, `hermes_cli/plugins_discovery.py`,
`plugins/dashboard_auth/_shared.py`, `tools/image_generation_tool.py`,
`tools/tool_search.py`, `tools/tts_tool.py`, `tools/vision_tools.py` — so the set is read
from the ledger, not hand-kept. (2) WHEN: only while `hermes_cli.config.load_config` is not
the original function object (an upstream patch is in place); unpatched calls stay
readonly, so a test that never patches sees no change. Together: no id rows, no new red
when the next upstream test arrives, and no blanket.

**Files and symbols.** Fork-owned.
- `tests/_downstream/fork_readonly_readers.py` (new): `FORK_READONLY_READERS` as module
  names, derived at import from the ledger's rows (parse
  `docs/agent-runtime-harness/planned/upstream-footprint-ledger.md`, rows whose reason
  contains `load_config_readonly`, path → module). A constant mirror is NOT kept; the
  ledger is the one source.
- `tests/_downstream/conftest_plugin.py`: the read-through fixture becomes autouse for items
  whose file imports one of those modules (`scripts/run_tests_bundled.py::imported_modules`
  already does the AST import scan; reuse it); the lambda becomes
  `lambda: _config.load_config() if _config.load_config is not _ORIGINAL else _original_readonly()`,
  with `_ORIGINAL` captured at plugin import.
- `tests/_downstream/id_markers/fork_marks.py`: delete the `_CONFIG_READ_THROUGH` rows;
  `reasons.py` drops the mark; `pytest_configure` drops its registration.
- `tests/_downstream/test_readonly_read_through_downstream.py` (new): positive controls.

**Stages.**
1. Readers-from-ledger + the dynamic deferral, id rows kept (both mechanisms on). Tests: the
   five known files (`tests/tools/test_browser_console.py`, `test_image_generation.py`,
   `test_vision_native_fast_path.py`, the nous_provider and self_hosted files,
   `plugins/dashboard_auth` jwt clock-skew) green.
2. Delete the id rows. Killing mutations (two, recorded): (a) remove the `is not _ORIGINAL`
   deferral → `tests/tools/test_browser_console.py::TestBrowserVisionConfig` reds as it did
   before any id existed; (b) drop one module from the derived set (edit the ledger row's
   reason on a throwaway copy) → that module's upstream test reds. Positive control: a fork
   test patches `hermes_cli.config.load_config` and asserts `load_config_readonly()` returns
   the patch; unpatched, asserts the readonly projection refuses mutation.
3. Ledger reason wording gate: a row that moves a reader to `load_config_readonly` must say
   so with that spelling (the derivation depends on it) — one assertion in
   `tests/scripts/test_upstream_footprint.py`, over-approximating is safe.

**Size.** S–M: ~70 plugin lines, −30 id lines, ~40 test lines.

**Risks.** A reader moved WITHOUT a ledger row is invisible to the rule — but such a row is
already required by the footprint gate, so the failure is loud elsewhere first.
**Owner question.** None.

## D3.07 = L6.35 — a release merge's `--scope fork` gate selects the whole tree

**Verdict: PLAN** (measured: the rule below shrinks the v0.21.6 gate's change set from
4,138 paths to 127).

**Decision and why.** `scripts/run_tests_bundled.py::changed_paths` is `git diff
--name-only <since>...HEAD`; after a release merge, every spelling of `<since>` (the
previous main, the tag) yields thousands of paths, and `select_scope` reaches every upstream
test under a directory whose `conftest.py` changed. `tests/conftest.py` carries a standing
fork hunk (ledger row: PR #131905, the stale-lock sweep), so it is "changed" against the tag
forever and `changed_conftest_dirs` contains `tests` → 5,571 upstream files. The right
change set for a MERGE is what the merge itself produced: paths whose blob differs from
BOTH parents. That is git's combined diff — `git diff-tree -c --name-only -r <merge>`
(plus `<merge>..HEAD` for fix(merge) commits). Measured on `3002eaa067`: 128 paths (vs
4,138 against the first parent, 2,715 against the tag), 13 of them under `tests/`, three
conftests among them: `tests/conftest.py`, `tests/_downstream/conftest_plugin.py`,
`tests/_downstream/tools_conftest.py`. The plugin files are not `conftest.py` and do not
reach. `tests/conftest.py` IS in the combined diff — because the merge re-applied the fork's
hunk onto upstream's new version — but the hunk itself is byte-identical before and after
(`git diff ee5f49b943 ff7bf3138a -- tests/conftest.py` equals `git diff v0.21.6 3002eaa067
-- tests/conftest.py`, 13 ± lines each): the merge changed nothing of the fork's in it, and
upstream tested its own part at the tag. So the second rule: a conftest in the combined
diff reaches only when its fork hunk CHANGED across the merge. With both rules the v0.21.6
gate would have been 949 fork files plus the reach of 127 paths (their named tests, the
`tests/<pkg>/test_<mod>.py` convention sources, their importers) — on the order of a normal
landing gate, not 115 minutes.

**Files and symbols.** Fork-owned.
- `scripts/run_tests_bundled.py`: `--since-merge <sha>` (mutually exclusive with `--since`):
  `changed_paths_for_merge(repo_root, merge_sha)` = combined diff of the merge ∪
  `git diff --name-only <merge>..HEAD` ∪ working-tree edits; and
  `conftest_hunk_unchanged(repo_root, path, merge_sha)` = compare `diff(prev_upstream_point,
  parent1, path)` with `diff(tag, merge, path)` where `prev_upstream_point =
  merge-base(parent1, parent2)` and `tag = parent2`; a conftest whose hunk is unchanged is
  dropped from `changed_conftest_dirs`. Summary line prints both exclusions.
- `tests/scripts/test_run_tests_bundled_merge_scope.py` (new): a scratch repo with an
  "upstream" branch and a "fork" branch carrying one conftest hunk; merge; assert the
  change set and the conftest exclusion.
- `Harness_Brain/50 — Agent Handoffs/Merging upstream.md` step 7: the release gate is
  `scripts/run_tests_bundled.sh --since-merge <merge-sha> tests`.

**Stages.**
1. `changed_paths_for_merge` + unit test. Killing mutation: replace the combined diff with
   `parent1...HEAD` → the upstream-only file appears in the change set, red.
2. `conftest_hunk_unchanged` + unit test. Killing mutation: always return False → the
   scratch repo's conftest dir reaches, red.
3. Runbook step; re-run the v0.21.6 selection with `--since-merge 3002eaa067` and record the
   `Scope fork (…)` line in the commit body as the measurement (selection only, no run needed
   — the runner prints its plan before running; or run with `--bundle-size 1 -k nothing`).

**Size.** S–M: ~90 script lines, ~80 test lines, one runbook step.

**Risks.** Upstream changes to files the fork never edits are not re-tested by the fork's
gate — by design: upstream tested the tag, and `--scope full` remains the weekly lane's
instrument (P0 row). A fix(merge) commit after the merge is covered by `<merge>..HEAD`.
**Owner question.** None.

## D3.08 = L7.20 — test and lane runs leave copied homes, runtimes and venvs in `%TEMP%`

**Verdict: PLAN** for the hermes half; the bulk is a LAUNCHER row (filed verbatim below).

**Decision and why.** Census of the operator's `%TEMP%` on 2026-10-10 (518 directories):
`realm_sync_test_cred*` 75, `hermes-test-home-*` 17, `legacy_scope*` 15, `open_in_studio*`
6, launcher real-serve sandboxes (`stage2/3/4/8-*`, `c1l-serve-*`, `ro9-*`, `rb7-*`,
`rs7-*`, `p-l-longrun-*`) ~30, `hermes-*` 3, `hermes-stream-fixtures*` 2. The creators:
`realm_sync_test_cred`, `legacy_scope`, `recently_seen_cap` are LAUNCHER Dart tests
(`EterniaLauncher/test/features/mission_control/realm_sync_test_support.dart`,
`…/posts/intake/legacy_scope_intake_test.dart`, `…/posts/ranking/recently_seen_store_test.dart`);
the sandboxes are `EterniaLauncher/test/support/real_serve_sandbox.dart`
(`Directory.systemTemp.createTempSync(prefix)`, deleted on ordinary teardown, kept when the
run is killed) and the hygiene/remote `*_real_serve_test.dart` files; each sandbox copies a
home AND a runtime venv, which is where the gigabytes are. On the hermes side the plumbing
already exists and is opt-in: `tests/_downstream/conftest_plugin.py::_maybe_redirect_test_tmp`
moves `TMP/TEMP/TMPDIR` for the pytest process and its children under
`HERMES_TEST_TMP_ROOT/run-*`, removes the run dir on green, prunes at 24 h; what it misses is
(a) the RUNNER process itself (`scripts/run_tests_parallel.py::_runner_scratch_root` →
`%TEMP%\hermes-pytest`, upstream code; `scripts/run_tests.sh` forwards
`HERMES_TEST_TMP_ROOT` but does not set `TMP` for the runner), (b) upstream's root conftest
minting `hermes-test-home-*` with `tempfile.mkdtemp` at import — redirected only when the
plugin loaded first, and left behind by killed sessions, and (c) anything launched outside
`scripts/run_tests.sh` (bare pytest; the lane question's answer is therefore RUNNER-level:
one place sets the root, every fixture inherits it; no per-fixture plumbing).

**Files and symbols (hermes half).** Fork-owned.
- `scripts/run_tests.sh` and `scripts/run_tests_bundled.sh`: when `HERMES_TEST_TMP_ROOT`
  names a directory, export `TMP`/`TEMP`/`TMPDIR` to it for the RUNNER too (so
  `_runner_scratch_root` lands under it); when it is unset, default it to
  `<repo-parent>/test-tmp` if that directory exists (the operator's `X:\Eternia\test-tmp`),
  else leave today's behaviour. Print the root in the "launching test runner" line.
- `tests/_downstream/conftest_plugin.py`: the existing 24 h prune also sweeps `%TEMP%` for
  the KNOWN hermes prefixes (`hermes-test-home-`, `hermes-pytest`, `hermes-stream-fixtures`)
  older than 24 h, printing one line per removed entry — the "sweep that names what it
  removed". The prefix list lives in `tests/_downstream/temp_prefixes.py`; a launcher prefix
  is never on it (another repo's artefacts are not this sweep's to delete).
- `Harness_Brain/50 — Agent Handoffs/Running the tests.md`: the environment note becomes
  "set once, defaulted by the runners".

**Stages.**
1. Runner-level root (both shell runners) + a test that spawns `scripts/run_tests.sh` with
   a throwaway `HERMES_TEST_TMP_ROOT` on a one-test file and asserts the runner's scratch and
   the child's basetemp are both under it. Killing mutation: drop the runner's `TMP` export →
   the scratch lands in `%TEMP%`, red.
2. The named sweep + unit test over a fake `%TEMP%` (an aged known-prefix dir is removed and
   named; a fresh one and a foreign-prefix one are kept). Killing mutation: remove the age
   check → the fresh dir is removed, red.
3. Handoff note.

**Size.** S: ~40 shell lines, ~50 plugin lines, ~60 test lines.

**Risks.** A default root on a box without `X:\Eternia\test-tmp` changes nothing (today's
behaviour); the sweep deletes only prefixes this repo mints.
**Owner question.** None for the hermes half.

**Launcher row (verbatim, for `Launcher_Brain/20 — Active Initiatives/mission-control-queue.md`):**
`**Launcher test sandboxes leak copied homes and venvs into %TEMP% (realm_sync_test_cred 75,
legacy_scope 15, real-serve sandboxes ~30 on 2026-10-10; 42.7 GiB 10-01..06)** · launcher /
test isolation · evidence: hermes D3.08 census · lane: real_serve_sandbox.dart and the posts
test supports create under HERMES_TEST_TMP_ROOT when set (else systemTemp); a gate-start
sweep in tool/_gate_sdk.dart removes the launcher's own prefixes older than 24 h and names
them; keep-on-failure stays`

## D3.09 = L7.28 — the starved-reader stream-gap positive control is scheduler-dependent

**Verdict: PLAN — the D3.01 design; this row is a pointer.**

Same mechanism as D3.01: `tests/agent_runtime/test_stream_gap_receipt.py::test_starved_reader_shows_lag_and_late_wakeups`
asserts `max_lag_ms >= 150`, where `StreamGapReceipt.on_event` measures parse time minus the
latest chunk's arrival and the hog must hold the GIL between the two. The fake server's ten
`response.in_progress` frames each echo 300 tools so the SDK's model build is long enough
for the hog to take the GIL; under load the OS starves the HOG instead and the reader
parses on time (91 ms / 75 ms recorded; 3/3 green off-load, L7.28). L7.28 also showed hold
length is not the lever (300 ms made it slower, 70 ms still passed) — because the lever is
scheduling, not the hold. The file is on the D3.01 idle-box list (stage 1). No change to the
test's floors; no change to `agent_runtime/stream_gap_receipt.py`. If an idle run still
reds, the measurement is one failing run with `STALL_INTERVAL_S` samples printed (the
receipt line already carries `stall_samples`, `stall_max_ms`, `max_lag_ms`) — file it as a
new row with that line.

## D3.10 = L7.35 — the v0.21.6 supersession pass over the 21 kept hunks

**Verdict: PROGRAM-EXISTS.** Owned by `Harness_Brain/50 — Agent Handoffs/Merging
upstream.md` Steps 4–6 ("Run the supersession pass … report … supersession rows
retired/kept, the [up-fp] line before/after") and by the owner-offered lane named in the
row. The merge commit body (`git show --no-patch 3002eaa067`) is the worklist: it names
each of the 21 kept hunks by file and rule (`agent/agent_init.py` tool-defs receipt,
`agent/conversation_compression.py` child_model_config, `agent/conversation_loop.py`
reuse_current_user_message, `agent/prompt_builder.py` ×3, `agent/skill_utils.py`,
`agent/turn_context.py` + `turn_facade.py`, `gateway/platforms/base.py`,
`hermes_cli/web_server_config.py`, `hermes_cli/webhook.py`, `tools/credential_files.py`,
`tools/environments/local.py`, `tools/file_tools_write_guards.py` +
`mcp_tool_handlers.py` + `process_registry.py`, `tools/skills_tool.py` ×2,
`tools/vision_tools.py`, `tui_gateway/event_replay.py`, `tui_gateway/prompt_turn.py` +
`session_lifecycle.py` + `session_workdir.py`, `tui_gateway/server.py`). Per hunk the lane
reads `git diff ee5f49b943 v0.21.6 -- <file>` (upstream's own change over the release) and
answers drop / extract / kept with reason; the ledger row is rewritten in the same commit;
the `[up-fp]` line (`python scripts/upstream_footprint.py`) is quoted before and after. One
addition to the runbook, filed as a fork-hygiene docs row by the lane that lands it: the
merge report's "Verdict counts" line gains `superseded N / partly N / kept N` so a missing
supersession count is visible in the body, not discovered two days later.

## D3.11 = L8.04 — a fresh SessionDB costs 0.8–1.0 s per test; the template fixture is wired into 2 files

**Verdict: PLAN** (the census is a permanent cheap receipt the landing's gate already pays
for; the widening is one fixture, opt-out, not per-file plumbing).

**Decision and why.** `tests/agent_runtime/_session_db_template.py::session_db_from_template`
monkeypatches `hermes_state.SessionDB.__init__` to copy a module-scoped template into a
writer-opened, not-yet-existing path; 32 of 626 files under `tests/agent_runtime` construct
`SessionDB(` directly and an unknown number open stores through production paths (serve
boots, snapshot builds, persona stores). The lane is right that the count needs a run over
the tree — and wrong that it needs a lane's run: the landing's whole-tree gate runs every
fork file anyway; the receipt only has to be written. Widening then does not need a per-file
decision: the fixture's contract ("a READ open of an absent store is untouched; a WRITER
open of an absent path gets the template; everything after the copy is production code")
is safe for every test except one whose SUBJECT is the fresh-file schema path — those live
in `tests/hermes_state` and are excluded by directory; a fork test elsewhere whose subject
is the schema opts out with a marker.

**Files and symbols.** Fork-owned.
- `tests/_downstream/conftest_plugin.py`: (a) `HERMES_TEST_COUNT_FRESH_DBS=1` wraps
  `hermes_state.SessionDB.__init__` at session start to count writer opens of a not-yet-
  existing path per test file, and `pytest_sessionfinish` appends `{file, fresh_dbs,
  seconds}` lines to `.pytest_cache/hermes_fresh_dbs.jsonl` (git-ignored, per checkout —
  the same home as `hermes_bundled_runs.jsonl`); (b) `session_db_from_template` becomes
  autouse for items under `tests/agent_runtime/` (the module-scoped template fixture moves
  to `tests/agent_runtime/conftest.py`), skipped for items marked `fresh_schema_path`.
- `tests/agent_runtime/conftest.py`: the template fixture; the two importing files
  (`test_persona_assignments.py`, `test_relay_session_lifecycle.py`) drop their explicit
  import.
- `scripts/run_tests_bundled.sh`: sets `HERMES_TEST_COUNT_FRESH_DBS=1` (the gate pays the
  census; the wrap is one attribute read per open).
- `docs/agent-runtime-harness/planned/suite-speed-2026-10-05.md` Stage 4F: the census
  numbers from the first gate that carries it (top 20 files by `fresh_dbs`, before/after
  seconds).

**Stages.**
1. The counter + jsonl receipt. Test: a subprocess pytest of a two-test file (one fresh
   writer open, one read-only open) with the env set writes `fresh_dbs: 1`. Killing
   mutation: count read-only opens too → `fresh_dbs: 2`, red.
2. The landing's next gate runs with the counter; the lane reads the jsonl and records the
   census in the plan (no separate run).
3. Autouse widening + `fresh_schema_path` marker. Tests: the two files that use it today
   stay green; `tests/hermes_state` untouched by construction (directory scope). Killing
   mutation: copy the template on READ opens too → `tests/agent_runtime`'s "a read never
   creates the store" assertions red (the fixture docstring names them). Second gate run
   gives the after-numbers; the Stage 4F table is the receipt.

**Size.** S–M: ~60 plugin lines, −10 lines in two files, docs.

**Risks.** A fork test outside `tests/hermes_state` whose subject is the schema path and is
not marked gets a template instead — it would pass for the wrong reason; the census (stage
2) lists every file whose fresh-DB count drops to zero, and the lane reads that list against
each file's docstring before stage 3 lands.
**Owner question.** None.

## D3.12 = L8.10 — validated-suite residuals that pass alone and red in a bundle

**Verdict: INVESTIGATION** (one mechanism — process-global state — with the standing CLASS
row; the protocol below needs no idle box and no new whole-tree run).

The realm-history ordering half is FIXED (`d1e35aec6a`). The residuals
(`test_local_download_jobs`, `test_local_models_routes`, `test_delivery_directive`,
`test_realm_revert_version`, `test_source_channel_integration`, three Git-fixture setup
errors) are green alone and red after other members — the shape the fork-hygiene CLASS row
"Process-global state, the CLASS" already names (tool registry, `builds.detect._ENABLED`,
resident-chat registry, idle keeper, memos). The bundled runner names a leak itself when it
sees one: red bundled, green alone → `ISOLATION LEAK` line with bundle number and member
count; the file's failing node ids go to `.pytest_cache/hermes_bundled_runs.jsonl`.

**Protocol.**
1. From the primary checkout's `.pytest_cache/hermes_bundled_runs.jsonl` (worktrees read the
   primary's record since `b96dc66372`), list every record where one of the eight files is
   red with `via: bundle` and green in a later `rerun` — the leak records. Each names the
   bundle's ordered member list in the gate log of that run (`ISOLATION LEAK … bundle #N
   after K earlier members`). No new run.
2. For each leak record, bisect the ordered prefix: `HERMES_TEST_WORKERS=1 scripts/run_tests.sh
   <prefix members> <victim>` — the L6.30 method (one ordered prefix, halve until the one
   member whose presence flips the victim is found). Each bisect step is a handful of files,
   a lane's budget. Shared box is fine: the leak is state, not timing.
3. Decision: the member found names the leaked state (read what it sets on a module and does
   not restore). If the state is one the CLASS row already lists, add the victim and the
   member as evidence on that row and leave the fix to the suite-isolation lane. If it is new
   state, file a one-line row under the CLASS ("… and `<module>.<name>`") — never a fix in
   passing. A victim that reds in the bisect ALONE (no prefix) is not a leak: file it as a
   product/test defect row with the node id.
4. A file that has no leak record (red bundled, red alone too, or never red since the fix)
   is closed with the jsonl line as evidence.

**Result that decides.** Each of the eight files ends either attached to the CLASS row with
its leaking member named, or closed with a jsonl line. Nothing here needs the validated
suite: the bundle membership is already recorded.

## D3.13 = L8.11 — re-qualify `upstream_reds.py` on the canonical test venv

**Verdict: PLAN** (73 files, not ~200; a named-file run is a lane's run).

**Decision and why.** `tests/_downstream/id_markers/upstream_reds.py` carries 69 `_up_red`
rows (strict xfail) across 73 distinct upstream test files, classified at v2026.9.24 on
CPython 3.12.5 / SQLite 3.45.3; the venv is 3.14.5 / 3.50.4 and lane w5-fh found eight
rows whose condition was the interpreter. A strict xfail that passes is already a FAILED
node (`XPASS(strict)`), so re-qualification is a RUN, not a reading: name the 73 files on
the bundled runner's command line (a named file runs even when skip-listed — owner ruling
O1) and read the failing node ids off the jsonl line. 73 files at 8 workers is minutes, and
it is the end-of-lane run the lane is allowed: the module it touches is `upstream_reds.py`,
whose subjects are exactly those files.

**Files and symbols.** Fork-owned.
- `tests/_downstream/id_markers/upstream_reds.py`: every row that XPASSes becomes
  `_up_red_when(<condition>, detail)` with the condition that made it red — the interpreter
  (`sys.version_info < (3, 13)`), its SQLite (`sqlite3.sqlite_version_info < (3, 46)`), the
  clock (`time.get_clock_info("monotonic").resolution`), a drive (`os.path.isdir("/dev")`)
  — or is deleted when the red was a bug upstream has since fixed (detail says which
  upstream SHA). A row that still reds keeps `_up_red` and gains the venv's versions in its
  detail.
- `tests/_downstream/id_markers/reasons.py`: `_up_red` grows a `qualified: str` keyword
  (interpreter/SQLite pair it was last seen red on), so the next re-qualification reads its
  age off the row.
- `tests/_downstream/test_upstream_reds_rows_resolve.py` (new): every row's file is in
  `tests/fixtures/upstream_manifest.txt` and its node exists (the collection-time stale
  check in `hooks.py::pytest_collection_modifyitems` already refuses a missing id when the
  file is collected; this gate does it for the whole table without collecting the tree —
  parse each file's `def test_` / class names with `ast`).
- `Harness_Brain/50 — Agent Handoffs/Merging upstream.md` step 5b: the weekly lane re-runs
  the 73 named files beside the skip-list re-check and records XPASSes.

**Stages.**
1. The run: `scripts/run_tests_bundled.sh $(python -c "<print the 73 paths>")` in the
   background, log + unpiped exit code, timeout ≥ 600000; the jsonl line and the XPASS node
   list go into the commit body.
2. Row edits. Killing mutation: flip one `_up_red_when` condition to `True` on the venv →
   that node XPASSes, red; recorded.
3. The resolve gate. Killing mutation: point one row at a renamed test → red.
4. Runbook step 5b.

**Size.** S–M: a run, ~70 row edits, ~50 gate lines.

**Risks.** A node that XPASSes on the venv and still reds under system Python 3.12 (the
bare-pytest trap, fork-hygiene row "Running the tests.md misleads on one-file runs") is a
`_up_red_when(sys.version_info < (3, 13))`, not a delete — the condition is the record.
**Owner question.** None.

## D3.14 = L8.13 — classify the validated-suite residuals (97 nodes in 25 files)

**Verdict: INVESTIGATION** (the failing set is stable and known; the classification is a
25-file run on a clean worktree, not the validated suite).

The row's evidence has converged: six qualifications (2026-09-30 → 2026-10-10) each found
the same population reproducing on untouched main, latest 97 failing/error nodes in 25
files (`docs/downstream/native-result-policy-2026-10-10.json`, `pre_existing_failures`),
all fork-owned files: `test_serve_gateway_peer_lane.py` 24, `test_serve_gateway_lane.py`
17, `test_gateway_peer_two_roots_e2e.py` 9, `test_gateway_media_fetch_e2e.py` 5,
`test_harness_core_ratchet.py` 5, `tests/tui_gateway/test_contract_catalog.py` 5,
`test_agent_chat_runtime_roster.py` 4, and eighteen files with 1–3 nodes (the two fleet
identity assertions and the gateway certificate mismatch were already settled green,
h10b-triage). "Needs the validated suite" is no longer true: the set is enumerated, so the
run is the 25 files.

**Protocol.**
1. Box: any; no idle needed (none of the 25 is a timing file). Cut a detached worktree at
   `origin/main` from a neutral cwd; run `scripts/run_tests.sh <25 files>` once, 8 workers,
   background, log + unpiped exit code, timeout ≥ 1200000. Compare the node set to the JSON's
   97 (a diff of node ids is the receipt). A node not in the 97 is new and is filed on
   arrival.
2. Classify each node by reading its assertion, into exactly one bucket:
   (a) ENVIRONMENT — the test needs a second root, a paired gateway, a certificate, the
   network, or a live launcher (the gateway-peer and e2e files, expected ~60 nodes): the
   test gains a typed skip through `tests/_downstream/id_markers/` (`_env_when(<probe>)`,
   the probe being the thing the test needs — a second store root, a reachable peer), and
   the file is named in `docs/downstream-development.md`'s "needs a host" list. Not a
   waiver: the probe is a positive statement of the precondition.
   (b) DRIFT GATE red on main — `test_harness_core_ratchet.py`, `test_doc_cite_adjacency.py`,
   `test_no_source_grep_assertions.py`, `test_path_identity_gate.py`,
   `test_contract_catalog.py`, `test_coverage_claims_resolve.py`, `test_env_gap_registry.py`,
   `test_no_silent_package_patches.py`, `test_toolset_manifest.py`: each is a ratchet whose
   violation list is the work — burn the violations (ruling 0010: ratchets first, never
   baseline), one row per gate in `fork-hygiene-queue.md` with the violation count as the
   measure.
   (c) DEFECT — an assertion about fork behaviour that is simply false today
   (`test_agent_chat_runtime_roster.py`, `test_local_llama_adapter*.py`,
   `test_kanban_blocked_pm_tick.py`, `test_turn_cost_guard_downstream.py` → D3.01's idle
   list, `test_no_midtest_monkeypatch_undo.py`): a runtime-queue or fork-hygiene row each,
   with the node id and the assertion's two sides.
3. Result that decides: every one of the 97 nodes has a bucket and a row (or a skip probe)
   in one commit; the row for THIS classification closes with the node-to-bucket table in
   `docs/downstream/validated-suite-residuals-2026-10.md` and the JSON's `pre_existing_failures`
   is regenerated by the next qualification to show the population shrinking. The
   "program-end validated-suite run" owed since 2026-09-29 is retired as a requirement: the
   25-file run with the node diff is the same evidence at a twentieth of the cost.

## D3.15 = L8.19 — test and lane homes still land their `bin` on the operator's user PATH

**Verdict: PLAN** (one mechanism: the fence marker the writers must honour; the launcher's
sandbox exports it already).

**Decision and why.** Three writers put `<home>\bin` on `HKCU\Environment\Path`:
`hermes_cli/_launchers.py::_register_windows_user_path` (upstream, `winreg.SetValueEx`),
`hermes_cli/windows_env.py::set_user_env` (fork, `winreg.SetValueEx`), and
`scripts/install.ps1::Set-LauncherUserPath` (upstream, PowerShell
`[Environment]::SetEnvironmentVariable("Path", …, "User")`). The Python audit-hook fence
(`hermes_cli/_registry_write_fence.py`, `HERMES_REGISTRY_WRITE_FENCE=1`) covers the first
two in any process that imports `hermes_bootstrap`; it cannot see PowerShell. The leaked
`…test_desktop_stage_uses_pm_syn-25\hermes-home\bin` is install.ps1 driven by
`tests/scripts/test_install_ps1_desktop_stage.py::test_desktop_stage_uses_pm_sync_and_product_cli`
(upstream test, `-Stage desktop` → `Stage-Products` → `Publish-UserCommand` →
`Set-LauncherUserPath`). The launcher's real-serve sandboxes have exported
`HERMES_REGISTRY_WRITE_FENCE=1` since 2026-10-02 (`EterniaLauncher` `3081282cb2`,
`test/support/real_serve_sandbox.dart`), the launcher-managed venv is an editable install of
the checkout (`__editable__.hermes_agent-0.21.3.pth` → `X:/Eternia/hermes-agent`), so their
10-07 leaks were NOT an unfenced Python writer; the installer path those sandboxes run
(`hermes_installer.dart` → `scripts/install.ps1`) is the remaining candidate, and stage 0
names it rather than assuming it. The fix is one rule: every PATH writer honours the fence
marker, which is an environment variable precisely so that children inherit it — the
pytest fence (`tests/_downstream/registry_write_fence.py`) and the launcher sandbox both
set it, so once install.ps1 reads `$env:HERMES_REGISTRY_WRITE_FENCE` no test or sandbox
needs a change.

**Files and symbols.**
- `scripts/install.ps1::Set-LauncherUserPath` (upstream): one additive guard at the top —
  `if ($env:HERMES_REGISTRY_WRITE_FENCE -eq "1") { Write-Ok "fenced: not adding $binDir to
  the user PATH (HERMES_REGISTRY_WRITE_FENCE=1)"; return }`. Ledger row `carry`, reason
  "PATH fence for PowerShell; upstream PR candidate `-SkipUserPath` + env honour". No
  deletion.
- `tests/scripts/test_install_ps1_path_fence_downstream.py` (new, fork): dot-sources
  install.ps1 with the env set and calls `Set-LauncherUserPath <tmp>\bin`; asserts the
  "fenced" line and that `[Environment]::GetEnvironmentVariable('Path','User')` is
  byte-identical before and after. The test never writes the PATH when the guard holds.
- `scripts/prune_user_path.ps1` (new, fork): lists user-PATH entries whose directory no
  longer exists or lies under `$env:TEMP`, `$env:LOCALAPPDATA\Temp`, `HERMES_TEST_TMP_ROOT`
  or a `scratchpad\live`; `-Apply` rewrites the value without them, printing each removal.
  The operator runs it once; its unit test (`tests/scripts/test_prune_user_path.py`) drives
  the filter function on a string and never touches the registry.
- `tests/tooling/test_registry_write_fence_children.py`: a row that the PowerShell writer is
  honoured is added as a pointer to the new test (no second mechanism).

**Stages.**
0. Measurement (owner's box, once, PATH leak accepted and pruned after): run one launcher
   real-serve sandbox test with Process Monitor filtering `RegSetValue` on
   `HKCU\Environment\Path`; the writing process's image (python.exe vs powershell.exe) and
   command line go into the commit body. If it is python.exe, the fence is not installed in
   that process (check `hermes_bootstrap` import on `python -m hermes_cli.main harness
   serve`) — a different fix, filed on arrival.
1. The install.ps1 guard + the fork test. Killing mutation: remove the guard → the test
   reds on the "fenced" line — and WRITES the operator's PATH once; run the mutation on a
   disposable Windows VM or accept one entry and prune it (owner call below).
2. `prune_user_path.ps1` + its test; the operator runs `-WhatIf`, then `-Apply`; the 30
   leaked entries are the receipt in the commit body.
3. Upstream PR body for the `-SkipUserPath` switch (opened when the account can; row 326).

**Size.** S: ~4 ps1 lines, ~60 ps1 for the pruner, ~80 test lines, one ledger row.

**Risks.** A PowerShell host where `$env:` is unavailable (Constrained Language Mode reads
env fine). The guard is skipped when the marker is absent — exactly the installer's real
run.
**Owner questions.** (1) Run stage 1's killing mutation on a disposable VM, or on this box
with one accepted PATH write? (2) Accept the carried install.ps1 hunk until the PR lands?

## D3.16 = L8.20 — a gate run leaves a stale `index.lock` in the worktree it runs from

**Verdict: PLAN** (the hypothesis is sound and the fix is one environment line in three
fork-owned places; the positive gate is cheap).

**Decision and why.** `git status`, `git diff` (without `--no-optional-locks`) and
`git describe`-style porcelain refresh the index opportunistically, taking `index.lock`;
a process killed between the lock and the write leaves a zero-byte lock — the shape
observed (0 bytes, created mid-run, no git alive after). The runners kill a bundle process
on `--file-timeout` (SIGKILL on Windows, no cleanup), and twenty test files run git with
`REPO_ROOT` in reach; the ones that run lock-taking verbs are
`tests/scripts/test_release_entrypoint.py` (23 such calls), `tests/hermes_cli/test_update_custody.py`
and `test_update_lock_windows_live.py` (12 each), `test_update_lock.py`,
`test_update_lock_protocol.py`, `test_release_canary_git.py`, `test_release_revision_anchor.py`,
`tests/test_audit_old_updater_imports.py`, `tests/scripts/test_install_stamp_distance.py`,
`test_update_flat_install_state_gitignore.py`, `tests/pm/test_no_lazy_deps.py` and six more
with one or two calls. Most of those build a scratch repo; "most" is what the zero-byte lock
argues with. `GIT_OPTIONAL_LOCKS=0` makes git skip the opportunistic refresh — the fork
already sets it for its own git children (`agent_runtime/build_identity.py`,
`agent_runtime/build_stamp.py`, `hermes_cli/source_check.py`); nothing sets it for the test
process tree. A whole-tree run to NAME the one test is not needed to remove the mechanism;
the name is still worth having, so stage 3 records it from the gate that already runs.

**Files and symbols.** Fork-owned.
- `scripts/run_tests.sh`: `GIT_OPTIONAL_LOCKS=0` in the `exec env -i` list.
- `scripts/run_tests_bundled.py` (`main`, beside the `PYTHONPATH` export) and the fork
  plugin `tests/_downstream/conftest_plugin.py` (import-time `os.environ.setdefault`, so a
  bare one-file run under the plugin is covered too).
- `tests/_downstream/conftest_plugin.py`: with `HERMES_TEST_GIT_AUDIT=1`, an autouse fixture
  records every `subprocess` git call whose `cwd` resolves inside the checkout (not a
  `tmp_path`) to `.pytest_cache/hermes_git_in_checkout.jsonl` — `{file, nodeid, argv}` —
  via the existing subprocess footgun seam (`tests/scripts/test_footgun_subprocess_encoding.py`
  shows the pattern). A negative inventory, over-approximating.
- `tests/scripts/test_git_optional_locks_in_runners.py` (new): spawn a one-test file
  through `scripts/run_tests.sh`; the test writes `os.environ["GIT_OPTIONAL_LOCKS"]` to a
  file; assert `"0"`.

**Stages.**
1. The three environment sites + the positive gate. Killing mutation: delete the line in
   `run_tests.sh` → the gate reads nothing, red.
2. The audit receipt; the landing's next gate runs with `HERMES_TEST_GIT_AUDIT=1`; the lane
   reads the jsonl and files one row per test that runs a lock-taking verb against the
   checkout ("point it at a temp repo"), with the argv as evidence.
3. `Running the tests.md`: "a stale `index.lock` after a killed run is `rm` once the log's
   last lines are read; the runners set `GIT_OPTIONAL_LOCKS=0`".

**Size.** S: 3 one-line sites, ~50 plugin lines, ~40 test lines.

**Risks.** A test that ASSERTS on index refresh behaviour (none known; the audit names it if
one exists). The mechanism is removed before the writer is named — the owner's rule "run the
thing before fixing it" is honoured by stage 2's receipt from the gate that runs anyway.
**Owner question.** None.

## D3.17 = L8.25 — the JSON-root ledger scan recognises emitters by a hand-kept name set

**Verdict: PLAN** (resolve emitters through the import graph to one root; the twenty
unclassified callees the current scan admits it skips become ledger rows).

**Decision and why.** `tests/hermes_cli/test_harness_json_root_observability.py::_handlers`
walks `hermes_cli/harness.py` and `harness_parts/**`, marks a `_cmd_*` as emitting when it
calls a name in `_EMIT_CALLS = {"emit_json", "_print_stage42", "emit_operation_result"}`,
and follows only `_emit_*` seams to a fixpoint. Its own docstring records the hole: following
every local callee adds thirty handlers, twenty of them neither classified nor attaching.
The root is one function, `agent_runtime/cli_format.py::emit_json` (and `emit_json_line`);
every emitter reaches it. The positive guarantee the gate wants — "this verb prints a JSON
root" — is a reachability question on resolved calls, which the AST plus the file's imports
answers without executing anything: resolve each called name to its defining module through
the scanned file's `import` / `from … import` statements (`scripts/run_tests_bundled.py::imported_modules`
and `scripts/check_carried_prs.py::symbol_source` already do the two halves), parse that
module on demand, and take the fixpoint "reaches `emit_json`" over the resolved graph,
bounded to modules under `hermes_cli/` and `agent_runtime/`. `_EMIT_CALLS` is then deleted:
`emit_operation_result` emits because its body reaches `emit_json`, not because someone
remembered to list it.

**Files and symbols.** Fork-owned.
- `tests/_downstream/call_graph.py` (new, ~120 lines): `resolve_calls(path) ->
  dict[func, set[(module, name)]]` (imports + attribute calls on imported modules;
  unresolved names recorded, not dropped), `reaches(root_module, root_name, start, limit_to)`
  fixpoint with a visited set (cycles terminate). Pure functions over `ast`; unit-tested on
  fixture modules under `tests/fixtures/call_graph/`.
- `tests/hermes_cli/test_harness_json_root_observability.py`: `_handlers` builds `emits`
  from `reaches("agent_runtime.cli_format", "emit_json", …)` (and `emit_json_line`);
  `attaches` / `chat_scope` keep today's `_ATTACH_CALL` and `ATTACHING_DELEGATES` rules
  (those are runtime-proven, not graph-proven — unchanged). `_EMIT_CALLS` deleted;
  `_print_stage42` is reached or it is not. The classified ledger gains rows for the ~20
  handlers the general follow surfaces, each classified ("packet states runtime_root" /
  "attaches via <delegate>") or fixed to attach — the lane reads each verb, never bulk-adds.
- `tests/_downstream/test_call_graph.py` (new): the fixture graph — a direct caller, a
  two-hop caller through an imported helper, a cycle, an unresolved name — asserts
  reachability and termination.

**Stages.**
1. `call_graph.py` + its tests. Killing mutations: drop the visited set → the cycle fixture
   hangs (use `pytest.mark.timeout(5)` on it, red by timeout); resolve attribute calls by
   `attr` only (today's `_call_name` behaviour) → the fixture where two modules export the
   same name reads wrong, red.
2. The scan rewrite with the ledger rows for the surfaced handlers.
   `test_the_scan_sees_the_known_adopters` stays as the positive control; killing mutation:
   make `emit_operation_result` call `print(json.dumps(...))` instead of `emit_json` on a
   throwaway copy → it stops reaching the root and the adopters test reds (the regression
   `66866fb496` fixed by hand, now caught by the graph).
3. The docstring's "twenty are a real hole" paragraph is replaced by the row count landed.

**Size.** M: ~120 + ~60 new lines, ~40 changed in the scan, ~20 ledger rows (each read).

**Risks.** Dynamic dispatch (a handler table of callables) is invisible to the graph; today's
scan does not see it either, and `ATTACHING_DELEGATES` remains the runtime-proven door for
it. Resolution limited to two packages keeps parse cost at a few hundred files.
**Owner question.** None.

## Summary

| row | verdict | size | owner question |
|---|---|---|---|
| D3.01 = L2.06 | PLAN (idle-box lane) | S–M | — |
| D3.02 = L4.05 | PLAN (vanished-WAL guard) | S | carry the 2-line hunk until the PR can open? |
| D3.03 = L6.02 | PLAN (footprint lane) | M | upstream-edit licence; hold or rewrite the two NON-ADDITIVE fixes? |
| D3.04 = L6.14 | PLAN (quiet-stream test) | S | — |
| D3.05 = L6.32 | PLAN (live-shape roots) | M | may sanitized profile shapes be committed? |
| D3.06 = L6.34 | PLAN (ledger-derived read-through) | S–M | — |
| D3.07 = L6.35 | PLAN (`--since-merge`, measured 4,138 → 127) | S–M | — |
| D3.08 = L7.20 | PLAN hermes half + launcher row | S | — |
| D3.09 = L7.28 | PLAN → D3.01 | — | — |
| D3.10 = L7.35 | PROGRAM-EXISTS (Merging upstream.md 4–6) | — | — |
| D3.11 = L8.04 | PLAN (census receipt + autouse) | S–M | — |
| D3.12 = L8.10 | INVESTIGATION (bundle-prefix bisect) | — | — |
| D3.13 = L8.11 | PLAN (73-file re-qualification) | S–M | — |
| D3.14 = L8.13 | INVESTIGATION (25-file classification) | — | — |
| D3.15 = L8.19 | PLAN (fence marker honoured by install.ps1) | S | VM or one accepted PATH write for the mutation; carry the hunk? |
| D3.16 = L8.20 | PLAN (`GIT_OPTIONAL_LOCKS=0` + audit) | S | — |
| D3.17 = L8.25 | PLAN (import-graph emitter scan) | M | — |

Counts: PLAN 13 (one a pointer), PROGRAM-EXISTS 1, INVESTIGATION 2, DROP 0. Shared
mechanisms: GIL-hog controls (D3.01 ← D3.09), temp homes (D3.08, launcher row), PATH
writers (D3.15), index-lock writers (D3.16), process-global state (D3.12 → the standing
CLASS row).

Structural findings this sweep adds, filed by the landing (the design lane stands in a
worktree that should not fight the shared checkout for the queue files):

- `fork-hygiene-queue.md`: **A registered marker with no consumer: `slow_native` is
  registered in `tests/_downstream/conftest_plugin.py` and read by nothing in `scripts/`;
  the "first and alone" scheduling it promises is the duration cache's, not the marker's**
  · fork / suite · D3.01 (grep over `scripts/*.py`) · lane: D3.01 stage 2 retires or wires
  it.
- `fork-hygiene-queue.md`: **The release-merge gate reaches 5,571 upstream files through the
  root conftest's STANDING fork hunk, which `select_scope` cannot tell from a changed one**
  · fork / suite · D3.07 measurement (`3002eaa067`: 128 combined-diff paths, conftest hunk
  identical across the merge) · lane: D3.07.
- `runtime-queue.md` § Upstream-owned: **`hermes_state_repair.preflight_db_writability`
  reads `os.access` on a sidecar it listed a moment earlier; a WAL unlinked in between
  reports as read-only (`os.access` is False for a missing path)** · fork / upstream-owned ·
  D3.02 · lane: D3.02 (reproducer first).
