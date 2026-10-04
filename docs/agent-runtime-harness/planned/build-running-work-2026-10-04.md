# Builds as a first-class `running_work` kind — the hermes half

**Status: designed 2026-10-04, not shipped. Owner decisions (fixed, 2026-10-04):** three sources
(agent-started, announced, detected only under the operator's launcher Projects folders); Stop AND
Restart on every row; Flutter first; hermes owns the rows; the launcher renders them and pushes the
authorized roots. Queue row: `Harness_Brain/20 — Active Initiatives/runtime-queue.md` ("Builds become a
first-class running_work kind"). Launcher half:
`EterniaLauncher/docs/mission_control/planned/build-running-work-launcher-2026-10-04.md`.

## 0. What exists, and what this reuses

| already here | where | reused as |
|---|---|---|
| background processes: spawn, `processes.json` checkpoint (`command`, `cwd`, `pid`, `host_start_time`, `started_at`, `heartbeat_seconds`, `notify_on_complete`), identity-guarded tree-kill, completion queue | upstream `tools/process_registry.py`, `tools/terminal_tool.py` | the **agent-started** source IS an upstream background process; Stop is `kill_process`; Restart is `spawn` |
| `running_work` projection: `work_row` shape, `LanePass`, `_pid_identity`, `_owner_of`, per-lane `sources`, bounded previews, `cancel_work` seams | `agent_runtime/running_work/` | the `build` lane is one more `LanePass`; the row keeps the shared shape and adds keys through `extra` |
| the QA build as a background job: `build_job` block, `ParityStageC.builds.job.json`, `qa_build_finished` wake | `tools/mcp_job_wake.py`, `EterniaLauncher/tool/stagec_qa_mcp_server/lib/qa_build_job.dart` | the **announced** record schema is that block generalised; the wake stays |
| `flutter build` argv parsing (`_tokens`, `_command_words`, `_cd_target`, `FlutterBuild`) | `agent_runtime/flutter_build_guard.py` | lifted into one parser both the guard and the recognizer import |
| background-work home authority, store fingerprinting | `agent_runtime/profile_home.py::get_hermes_background_work_home`, `running_work/ownership.py::running_work_store_paths`, `stream/fingerprint.py`, `core_cache/` | the registry dir lives under the same home and joins the same fingerprint |
| machine roots (`machine_roots.json`, `harness roots`) | `agent_runtime/machine_roots.py` | **not** reused for authorized roots: machine roots are config path tokens an operator binds by hand; the build roots are the launcher's Projects set, pushed, never edited here |

Upstream has no build concept, no process detection and no job registry. Nothing below edits an
upstream file: the lane reads the checkpoint and the registry's buffers through the reaches
`running_work` already has, the guard hook stays in `plugins/eternia-harness`, and the only new env
var is exported from serve's own process.

## 1. The `build` row — wire contract

`KIND_BUILD = "build"` joins `RUNNING_WORK_KINDS` and `RUNNING_WORK_SOURCES` (`running_work/vocabulary.py`).
`work_id = build:<source>:<stable>`:

| source | stable | identity proof |
|---|---|---|
| `agent` | the terminal `session_id` it reclassifies (`build:agent:<session_id>`) | the checkpoint's `pid` + `host_start_time`, exactly as the terminal lane proves it |
| `announced` | the record's `job_id` (`build:announced:<job_id>`) | the record's `writer.pid` + `writer.host_start_time`, plus `build_pid` when declared |
| `detected` | `<pid>-<host_start_time>` | observed directly; `pid_verified: true` because the start time is read at observation |

**Shared keys** (unchanged meaning): `work_id`, `kind: "build"`, `label` ("flutter build windows ·
eternia_launcher"), `command` (the argv joined, bounded 400), `pid` (the BUILD process, not the writer),
`pid_verified`, `owner` (agent: the spawning session's owner via `_owner_of`; announced: the record's
`session_key` if any; detected: empty — never invented), `status`, `started_at`, `elapsed_seconds`,
`progress`, `tail_preview` (redacted, ≤200), `source_lane` (`durable` for agent/announced, `live` for
detected), `cancellable` (= `controls.stop == "allowed"`).

**`status`** keeps the shared vocabulary; `liveness` and `outcome` carry what builds add:

| liveness (`live` / `stalled` / `dead` / `unknown`) | outcome | status on the wire |
|---|---|---|
| live | null | `running` |
| stalled, under the stall-fail threshold | null | `stalled` (`stalling` at half the threshold, the existing `STALLING_FRACTION`) |
| any | `succeeded` | `completed` |
| any | `failed` / `stalled` / `stopped` / `lost` | `error` |
| dead, no outcome recorded | `lost` | `error` |
| unknown (identity unproven) | null | `unknown` |

A `queued` build is never stalled: the QA build's `waiting_for_build_slot` and a heavy-run slot wait
are silent by design.

**Build keys** (`extra`, additive, every one present on every build row; unknown is `null` or the
`unknown` arm, never a guess):

| key | type / enum | notes |
|---|---|---|
| `source` | `agent` · `announced` · `detected` | |
| `project` | `{root, name}` | `root`: the authorized root for detected, the cwd for agent, the record's `project_root` for announced; `name` = basename |
| `toolchain` | `flutter` · `dart` · `unknown` (reserved, not emitted yet: `gradle`, `msbuild`, `cmake`, `npm`, `cargo`, `unreal`) | |
| `target` | string | `windows`, `apk`, `run:windows`, `qa_isolated`; `""` when unknown |
| `mode` | `debug` · `profile` · `release` · `""` | |
| `stage` | `queued` · `preparing` · `resolving` · `compiling` · `linking` · `packaging` · `finishing` · `done` · `unknown` | monotonic; §4 |
| `stage_detail` | bounded string ≤120 | the last matched line, redacted |
| `liveness` | `live` · `stalled` · `dead` · `unknown` | |
| `progress_signal` | `output` · `heartbeat` · `cpu` · `none` | what `liveness` was read from |
| `seconds_since_progress` | number or null | from the signal above |
| `progress_fraction` | 0..1 or null | `elapsed / expected_ms` clamped, only when `expected_ms` is known |
| `expected_ms` | int or null | writer-declared, else the history median (§6), else null |
| `eta_ms` | int or null | `expected_ms - elapsed`, floored at 0; null when unknown |
| `history_samples` | int | how many past builds the estimate rests on (0 = writer's own number or none) |
| `outcome` | null · `succeeded` · `failed` · `stalled` · `stopped` · `lost` | |
| `exit_code` | int or null | |
| `artifact` | `{path, kind}` or null | `kind`: `executable` · `bundle` · `directory` · `other` |
| `finished_at` | ISO UTC or `""` | |
| `started_by` | `{kind, label}`; `kind`: `agent` · `operator` · `tool` · `external` | announced from the QA server = `tool`/"launcher_qa"; detected = `external` |
| `controls` | `{stop: allowed·refused·unavailable, stop_reason, restart: allowed·refused·unavailable, restart_reason}` | reasons: `not_running`, `owner_not_here`, `writer_declines`, `argv_unknown`, `root_unauthorized`, `confirm_required` (detected restart, §7) |
| `restart` | `{argv: [...], cwd}` or null | what Restart would run; null ⇒ `restart: refused argv_unknown` |
| `origin_work_id` | string or null | agent source: `terminal:<session_id>` it replaced |
| `announcement` | `{record, writer_pid, heartbeat_age_seconds}` or null | announced only |
| `mcp_job` | `{server, job_id}` or null | announced only; the dedupe key for §8 |
| `restart_of` | string or null | the row this one re-ran |

**`sources.build`** is one entry with three sub-healths, because the three sources fail
independently and "I could not look" must be sayable per source:
`{"status": "ok"|"unavailable", "lane": "durable", "sub": {"agent": {...}, "announced": {...}, "detected": {...}}}`,
each sub `{status, reason}`; `detected` reasons: `not_in_process` (CLI lane), `roots_not_pushed`,
`roots_pusher_gone`, `scan_failed`; `announced`: `registry_unreadable`. The top-level status is
`unavailable` only when every sub is.

**Golden fixtures both sides pin.** Hand-pinned `tests/fixtures/builds/build_rows.json`: one row per
source × one per outcome arm × one per liveness arm (12 rows, every enum word appearing at least once),
plus a `sources.build` entry with every sub reason. hermes `tests/agent_runtime/test_build_rows_fixture.py`
proves the producer emits each row byte-equal from a seeded home (announced + agent; detected rows from
a fake process table), and that the file's enum words equal the vocabulary tuples (an enumeration from
the thing itself, not a literal typed beside it). The launcher mirrors the file into
`test/fixtures/harness_stream/build_rows.json` and round-trips every arm. The generated stream goldens
(`tests/fixtures/stream_frames/`) regenerate once for the new `sources.build` entry — contract 54 KEPT,
ledger entry in `02-runtime-data-and-shapes.md`; the README copy-status note is appended, not replaced
(the h-jobvis mirror is itself still owed).

## 2. The announced-job registry

**Location:** `<background-work home>/builds/` — `get_hermes_background_work_home()`, the directory
`processes.json` and `mcp_jobs.json` already resolve to, so writer and reader agree the way those two
do. One file per job, `<job_id>.json`, written temp-then-rename by the job's own writer. No shared file,
no merge: every writer owns its files, the reader lists the directory. `running_work_store_paths()`
grows a `builds/` entry and the fingerprint (`stream/fingerprint.py`, `core_cache/restat.py`) stats
`(name, mtime, size)` of every `*.json` under it, so a record appearing or changing invalidates the
read-model cache like a checkpoint rewrite does.

**Record schema v1** (every key present; the QA server's `build_job` block maps onto it one-to-one):

```json
{"schema_version": 1, "job_id": "qb-20261004T1511-3fa2c1", "toolchain": "flutter",
 "target": "qa_isolated", "mode": "release", "project_root": "X:\\...\\EterniaLauncher",
 "label": "QA build 4f1565459", "started_by": {"kind": "tool", "label": "launcher_qa"},
 "session_key": "", "mcp_job": {"server": "launcher_qa", "job_id": "qb-..."},
 "writer": {"pid": 4120, "host_start_time": 133412}, "build_pid": 9981, "build_host_start_time": 133480,
 "status": "running", "stage": "compiling", "stage_detail": "flutter build windows --release",
 "started_at": 1759590660.0, "heartbeat_at": 1759590720.0, "finished_at": null,
 "expected_ms": 330000, "outcome": null, "exit_code": null, "artifact": null,
 "log_path": "X:\\...\\ParityStageC.builds\\qb-...\\build.log", "tail": "", 
 "controls": {"stop": "request", "restart": "command"},
 "restart": {"argv": ["dart", "run", "tool/stagec_qa_mcp_server/bin/prebuild.dart"], "cwd": "X:\\...\\EterniaLauncher"},
 "expires_at": 1759594260.0}
```

`controls.stop`: `request` (hermes drops `<job_id>.stop` beside the record and the writer ends the
build and records `stopped`), `kill_tree` (hermes tree-kills `build_pid`, identity-guarded, and the
writer records what it sees), `none`. `controls.restart`: `command` (hermes runs `restart.argv` in
`restart.cwd` as its own background process), `none`.

**Writer liveness and expiry** (the reader's rules, all in `builds/registry.py`): `writer.pid`
dead/recycled with `status: running` ⇒ `liveness: dead`, `outcome: lost`, status `error` (the row is
KEPT, not dropped — a lost build is the thing the operator must see; it expires like a finished one);
`heartbeat_at` older than `stall_seconds` (default 240) ⇒ `stalled`; `expires_at` passed ⇒ dropped
`by_design` (`build_record_expired`). A running record carries `expires_at` = start + 6 h (the
`_ROUTE_TTL_S` the wake uses); a finished one, finish + 30 min (`_FINISHED_TTL_S`). The projection
stays read-only: expired files are deleted by a serve-boot sweep (`builds/sweep.py::gc`, files past
`expires_at` + 24 h), never by a read.

**How a writer finds the directory:** `HERMES_BUILD_REGISTRY_DIR`, exported into serve's own
`os.environ` at boot so every child it spawns (terminals, MCP servers — the QA server among them)
inherits it; `hermes harness builds registry-path --json` prints it for a writer started by hand
(`prebuild.dart` from an orchestrator shell). A writer with neither announces nothing and says so on
its stdout; the build still runs.

## 3. The authorized roots — `runtime.builds.roots.set`

One method, `TIER_CONSOLE` and in `LOCAL_CONSOLE_METHODS` (which folders this machine watches is the
desktop operator's move, not a paired phone's). `serve_rpc/builds.py`.

| | |
|---|---|
| params | `roots: [{path, name, project_id}]` (≤64; `path` absolute), `issued_at` (ISO, the launcher's gesture stamp), `account_scope` (an opaque hash — the launcher's `scope.storageKey` digest, never the account) |
| semantics | **replace the whole set.** The previous set is discarded; an empty list is a valid push and clears detection. Paths are normalised (`os.path.realpath`, case-folded on Windows) for the under-root test only; the wire keeps what the launcher sent. A root inside another root is allowed. |
| result | `{applied, count, missing: [paths that do not exist], superseded: bool}` — a push whose `issued_at` is older than the one held answers `applied: false, superseded: true` (newest gesture wins, the same basis `scope_activation` uses) |
| storage | **in-memory in the serve process only**, with the pusher's connection identity. No file, no CLI setter: hermes never holds a second editable list, and a serve restart honestly reports `detected: unavailable roots_not_pushed` until the launcher re-sends (it does, on every greeting). `harness builds roots show --json` is the read-only mirror. |
| missing folder | kept in the set and named in `missing`; nothing is detected under it; the launcher's own locate flow is the repair |
| account switch | the launcher pushes the new account's set (an empty one for a guest); rows already running under a root that left the set stay visible to completion with `controls.restart: refused root_unauthorized` — a build is a fact, the root is a permission for future detection |
| serve reconnect | the launcher pushes on every `ready` / `hello_ok` greeting whose `rpc` manifest lists the method; a hermes without it gets no push and the launcher says detection is unavailable |
| pusher gone | when the pushing connection drops, the set is kept for 60 s (a reconnect re-pushes) then cleared with reason `roots_pusher_gone` |

## 4. The Flutter recognizer — `builds/recognizer_flutter.py`

**Argv.** `builds/flutter_argv.py` is `flutter_build_guard.py`'s parser lifted whole (one pure move
commit; the guard imports it). It answers `FlutterCommand(kind: build|run|other, target, mode,
project_dir)` for `flutter`/`flutter.bat`/`flutter.exe`/`fvm flutter`/`dart … flutter_tools.snapshot`
and, for the QA build, `dart run tool/stagec_parity_build.dart` ⇒ `target: qa_isolated`.

**Stage, from output.** A data table `FLUTTER_STAGES: tuple[(stage, compiled regex)]`, one regex per
stage, read against each new output line; the stage only moves FORWARD through the enum order (a
later line matching an earlier stage is ignored — `pub get` lines after linking are a plugin's, not a
regression). A transcript matching nothing yields `stage: unknown` — not `queued`, not `preparing`.
The artifact comes from the `✓ Built <path>` line only (made absolute against the cwd); when that
line never appears the artifact is null even if a conventional output directory exists.

**Surviving Flutter output changes.** The table is pinned by goldens of REAL transcripts captured on
this machine (`tests/fixtures/builds/flutter_build_windows_release.txt`, `…_debug.txt`,
`flutter_run_windows.txt`, `flutter_build_failed_link.txt`), and the test asserts the ordered stage
sequence each produces AND that a transcript of random lines produces `unknown` throughout. When a new
Flutter version changes a phrase, the sequence test reds on the new golden and the fix is one regex;
until then the row says `unknown` for that stage rather than something it did not see.

**Where it reads from.** Agent source: the registry session's `output_buffer` in the owning process
(the live enrichment the terminal lane already does — `lanes_process.TerminalLane.live_row`); from the
durable lane the stage is `unknown` and `progress_signal: none`. Announced: the writer's `stage` is
authoritative (it watched its own child); hermes does not re-derive. Detected: no output; see §5.

## 5. The detected source — `builds/detect.py`

Runs in the serve process only, on the snapshot build cadence, only while the roots set is non-empty,
under a 50 ms budget (exceeded ⇒ `detected: unavailable scan_budget`). `psutil.process_iter` filtered
by executable name first (`dart`, `dart.exe`, `flutter`, `flutter.bat`), then `cmdline()` through the
Flutter argv parser, then the root test on `cwd()` — a process whose cwd cannot be read, or whose cwd
is under no authorized root, is not a detected build (unprovable scope is out of scope, by design).
A candidate whose pid is already an agent-started session or an announced `build_pid` is skipped
(dedupe by pid + start time). Liveness is `cpu`: the process tree's cumulative CPU time across two
consecutive scans; unchanged for `stall_seconds` ⇒ `stalled`, never auto-ended (§7). `started_by:
external`, empty owner, `restart.argv` = the observed cmdline, `restart.cwd` = the observed cwd.

## 6. Progress and ETA — `builds/history.py`

`<background-work home>/builds/history.jsonl`, one line per ENDED build
(`{project_root_hash, toolchain, target, mode, duration_ms, outcome, ended_at}`), appended by the serve
sweep (§7) — the projection never writes. `expected_ms` for a row = the writer's own declaration when
present (the QA server's 330 s), else the median of the last 5 `succeeded` lines for the same
`(project_root_hash, toolchain, target, mode)`, else null with `history_samples: 0`. The launcher
renders a determinate bar only when `expected_ms` is non-null.

## 7. Stop, Restart, stall — `builds/control.py`, `builds/sweep.py`

**Stop** = `cancel_work` with a `_cancel_build` canceller (`running_work/surface.py::_CANCELLERS`):

| source | seam | refusal |
|---|---|---|
| agent | `process_registry.kill_process` (identity-guarded tree-kill; `consume_output=False`) from the owning process | `owner_not_here` from any other process |
| announced, `controls.stop: request` | write `<job_id>.stop`; answer `cancel_requested` | writer declines (`none`) ⇒ `writer_declines` |
| announced, `controls.stop: kill_tree` | `terminate_host_pid(build_pid, build_host_start_time)` | identity mismatch ⇒ `not_found` |
| detected | `terminate_host_pid(pid, host_start_time)` | root no longer authorized ⇒ `root_unauthorized` |

The `--issued-at` replay guard applies unchanged (`work_commands._cancel_is_superseded`).

**Restart** = `runtime.work.restart {work_id, issued_at, confirm}` → stop if running, then spawn
`restart.argv` in `restart.cwd` through `process_registry.spawn` as a background process with the
completion default, `started_by: operator`, empty owner, `restart_of: <work_id>`; returns the new
`work_id`. A detected build's restart additionally requires `confirm: true` (the launcher's dialog;
without it, `confirm_required`), because hermes is about to run under its own registry a command it
only observed. `harness work restart <work_id> --issued-at …` is the argv mirror.

**Stall-fail** (the 2026-10-04 frozen-job class): the serve sweep ticks every 30 s beside the
delegation stale monitor. `stalled` for `stall_fail_seconds` (default 900) ⇒ the build is ENDED with
`outcome: stalled`: agent-started → `kill_process`; announced → the declared stop mode; detected →
**not killed** — marked `error`/`stalled` and left, since hermes does not own it. Every ending (stall,
lost, failed, succeeded) emits a `build.ended` EventLog event the launcher renders as a notice, and an
agent-started one additionally rides the completion queue so the owning agent is woken with the tail.

## 8. Folding `mcp_job` — no double rows at any step

1. hermes lands the lane with the announced source and a dedupe in `McpJobLane`: an `mcp_jobs.json`
   entry whose `(server, job_id)` matches a registry record's `mcp_job` key is dropped `by_design`
   (`folded_into_build`). Until the launcher announces, nothing matches and today's row stays.
2. the launcher's QA server and `prebuild.dart` announce (launcher rows L5). From the first announced
   job the Activity panel shows one `build` row and no `mcp_job` row for it.
3. hermes stops WRITING an `mcp_jobs.json` row for `job_kind == qa_build` (`mcp_job_wake._bind` keeps
   the route — the wake is untouched — and skips `_rows`). The `mcp_job` kind itself stays for any
   non-build MCP job; the launcher keeps its decoder.

## 9. Package map and tests

```
agent_runtime/builds/
  __init__.py          lanes    this map
  vocabulary.py        models   the enums above (one tuple each), limits, the registry dirname
  flutter_argv.py      models   the parser lifted from flutter_build_guard
  recognizer_flutter.py policy  FLUTTER_STAGES table, stage advance, artifact line
  registry.py          stores   record schema v1, reader (liveness/stall/expiry), writer helper, registry dir
  roots.py             stores   the in-memory authorized set (+ pusher identity, superseded basis)
  history.py           stores   history.jsonl append + median
  detect.py            lanes    the psutil scan under the roots
  control.py           lanes    stop / restart decisions (origin × declared controls)
  sweep.py             lanes    serve tick: stall-fail, build.ended, history append, registry gc
agent_runtime/running_work/lanes_build.py   lanes   BuildLane: announced rows + the terminal reclassification pass + detected rows
agent_runtime/serve_rpc/builds.py           lanes   runtime.builds.roots.set / .show, runtime.work.restart
```

Reclassification: `BuildLane` runs AFTER the terminal lane in `_COLLECTORS` and is handed the frame's
rows so far; a terminal row whose `command` parses as a build is REPLACED in place by a build row with
`origin_work_id` (accounted `reclassified_build`, by design) — one producer step, so `counts` never
double. Each row of §10 names its test and its killing mutation at the landing (`GATE_LANDING` rule).

## 10. Implementation rows (one commit each, in this order)

H1 `flutter_argv.py` move + `FlutterCommand` · `tests/agent_runtime/test_flutter_argv.py`; the guard's own tests unchanged and a pin that `flutter_build_guard` defines no token regex of its own.
H2 `recognizer_flutter.py` + four transcript goldens · `test_build_recognizer_flutter.py` (mutation: swap two stage regexes ⇒ the ordered-sequence assertion reds; random-line transcript ⇒ `unknown`).
H3 `builds/vocabulary.py` + `registry.py` + `running_work_store_paths` dir entry + fingerprint restat + `harness builds registry-path` · `test_build_registry.py`, `test_stream_fingerprint.py` arm (a record touched ⇒ fingerprint moves).
H4 `lanes_build.py` (announced + reclassification) + `sources.build` + `McpJobLane` dedupe + `build_rows.json` + stream goldens regen + contract ledger + README copy-status · `test_running_work.py` arms, `test_build_rows_fixture.py`.
H5 `roots.py` + `serve_rpc/builds.py::runtime.builds.roots.set/.show` + `LOCAL_CONSOLE_METHODS` + `harness builds roots show` · `test_build_roots.py`, `test_peer_authorization.py` tier table.
H6 `detect.py` + the detected sub-source · `test_build_detect.py` over a fake process table (under-root, outside-root, unreadable cwd, already-owned pid, cpu-stall).
H7 `history.py` + `sweep.py` (stall-fail, `build.ended`, history, gc) + serve boot `HERMES_BUILD_REGISTRY_DIR` export · `test_build_sweep.py` with a fake clock (queued never stalls; detected never killed; agent-origin wakes its owner).
H8 `control.py` + `_cancel_build` + `runtime.work.restart` + `harness work restart` · `test_build_control.py` (each origin × each declared mode; `confirm_required` on detected; replay guard).
H9 `mcp_job_wake` stops writing `qa_build` rows · `tests/tools/test_mcp_job_background_work.py` (route still bound, no row).

## 11. Open owner calls (each with the recommendation)

1. **Stall-fail for detected builds** — kill, or mark only? *Recommend mark only* (§7): hermes never started it, and a zero-CPU build waiting on a lock or a slot is indistinguishable from a wedged one without its output.
2. **Restart of a detected build** — operator confirm, or one click like the others? *Recommend confirm* (the launcher dialog names argv and cwd verbatim), because the restarted build runs under hermes' own registry and becomes hermes-owned.
3. **Stop/Restart transport** — new methods `runtime.work.cancel` + `runtime.work.restart`, or argv mirrors like today's `work.cancel`? *Recommend methods for both, used by build rows; the argv `work.cancel` stays for the older kinds until its own row moves it* (route-first rule).
4. **Roots durability** — in-memory only (§3) or a file written only by the method? *Recommend in-memory*: strictly "no second list", and the launcher re-pushes on every greeting within seconds.
5. **`ParityStageC.builds.job.json`** — keep as the QA server's output-directory lock beside the registry record, or make the record the lock? *Recommend keep both, one writer, one `toBuildJobJson()`*: the lock is keyed by output dir and read by foreign QA servers; the record is per job and operator-facing.
6. **Registry dir for hand-run writers** — env only, or the CLI fallback too? *Recommend both* (§2); a writer with neither prints that it is not announcing.
7. **Detected-source cost ceiling** — 50 ms per scan on the snapshot cadence, scan only while roots are non-empty. *Recommend as written*; the budget breach is a typed sub-reason, not a silent skip.

One deviation from the row's wording, stated: "the `mcp_job` row folds into this kind" is done for
the QA build (§8); the `mcp_job` KIND is kept for MCP jobs that are not builds, so a future non-build
server job still has a row.
