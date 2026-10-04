# Builds as a first-class `running_work` kind — the hermes half

**Status: designed 2026-10-04, not shipped. Owner decisions (fixed, 2026-10-04):** three sources
(agent-started, announced, detected only under the operator's launcher Projects folders); Stop AND
Restart on every row; Flutter first; hermes owns the rows; the launcher renders them. **Amended
2026-10-04 after the owner ruled on the seven calls (§11):** the authorized folders are PERSISTED in
hermes at two levels — the WORKSPACE holds the authorized folder set (what detection watches; realm sync
carries it) and each persona INSTANCE is assigned a subset it loads `AGENTS.md` from — with the launcher
Projects screen as the single editor of both (§3); detected builds that stall are MARKED, never killed;
Restart of a detected build is the same path as every row, no confirm; and every row and record
**indexes its unknowns** — anything hermes could not classify is a typed unknown WITH the evidence
seen (§1 `unknowns`). Queue row: `Harness_Brain/20 — Active Initiatives/runtime-queue.md` ("Builds become a
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
| machine roots (`machine_roots.json`, `harness roots`) | `agent_runtime/machine_roots.py` | **not** reused for authorized folders: machine roots are config path tokens an operator binds by hand; the authorized folders are workspace state (§3) — but the PORTABILITY lesson is reused: a path is a per-machine binding, never the portable identity |
| workspace records + the WORKSPACE realm-sync family (generic overwrite), persona-instance records with `workspace_id` / `placement_id` + their 3-way family, the level family's whole-document adopt-or-hold | `paths.workspace_path`, `realm_sync/families.py`, `persona_assignments/store.py`, `level_sync.py` | the folder SET is a new family beside the workspace record; the per-instance assignment rides the persona-instance family |
| the one `AGENTS.md` a mission-chat turn injects today: the launcher's per-instance directory (`mission-chat message --agents-file`, machine-local SharedPreferences) → `load_workspace_agents_context` (128 KB, typed receipt) → workdir ladder rung 2 → `prompt_builder._load_agents_md` chains git-root→cwd | `mission_chat_turn_context.py`, `prompt_observability/workspace_agents.py`, `mission_chat_workdir.py`, `agent/prompt_builder.py` | the per-folder loader and its receipt are reused per ASSIGNED folder; the `--agents-file` pointer is retired (§3) |

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
| `project` | `{root, name}` | `root`: the authorized folder for detected, the cwd for agent, the record's `project_root` for announced; `name` = basename |
| `workspace_id` · `folder_id` | string or null each | the authorized folder (§3) the build sits under, when one does — resolved for every source by the under-folder test; null with an `unknowns` entry `folder_unresolved` otherwise |
| `unknowns` | list of `{kind, evidence, seen_at}` (≤32, dedup by kind + evidence hash, newest kept) | **owner rule "index the unknowns" (2026-10-04):** everything hermes could not classify, WITH what it saw. `kind` ∈ `stage_line_unrecognized` (evidence: the line, redacted ≤200), `output_unreadable` (the exception class), `process_unidentified` (exe name + argv head), `cwd_unreadable`, `wrapper_unobserved` (the parent chain seen, e.g. `cmd.exe /c flutter.bat`), `env_unobserved` (the env keys a restart cannot reproduce), `path_unobserved`, `artifact_unlocated` (the directories probed), `writer_unidentified`, `folder_unresolved`, `folder_unbound_here` (the folder id and the machines that bind it), `toolchain_unrecognized` (argv head). Empty list = nothing was unclassifiable, which is itself a claim the tests pin. |
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
| `controls` | `{stop: allowed·refused·unavailable, stop_reason, restart: allowed·refused·unavailable, restart_reason}` | reasons: `not_running`, `owner_not_here`, `writer_declines`, `argv_unknown`, `folder_unauthorized`. No `confirm_required`: a detected restart is the same path as every row (owner 2026-10-04) |
| `restart` | `{argv: [...], cwd}` or null | what Restart would run; null ⇒ `restart: refused argv_unknown` |
| `origin_work_id` | string or null | agent source: `terminal:<session_id>` it replaced |
| `announcement` | `{record, writer_pid, heartbeat_age_seconds}` or null | announced only |
| `mcp_job` | `{server, job_id}` or null | announced only; the dedupe key for §8 |
| `restart_of` | string or null | the row this one re-ran |

**`sources.build`** is one entry with three sub-healths, because the three sources fail
independently and "I could not look" must be sayable per source:
`{"status": "ok"|"unavailable", "lane": "durable", "sub": {"agent": {...}, "announced": {...}, "detected": {...}}}`,
each sub `{status, reason}`; `detected` reasons: `not_in_process` (CLI lane), `no_authorized_folders`
(no workspace in the active realm holds a folder), `folders_unbound_here` (folders exist, none bound on
this machine), `scan_budget`, `scan_failed`; `announced`: `registry_unreadable`. The top-level status is
`unavailable` only when every sub is. **The detected sub always carries its cost** (owner 2026-10-04,
call 7): `scan_ms`, `processes_examined`, `candidates`, `budget_ms` — and the same `scan_ms` lands in
`parity.sections_ms` as `running_work.build_detect`, so the number is visible on every frame and can be
made smaller later without first having to be measured.

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
 "unknowns": [{"kind": "stage_line_unrecognized", "evidence": "Running Gradle task 'assembleRelease'...", "seen_at": 1759590700.0}],
 "expires_at": 1759594260.0}
```

`unknowns` is the writer's own index (same kinds as §1): a writer that recognised everything writes
`[]`; hermes appends its reader-side unknowns (`writer_unidentified`, `folder_unresolved`) to the row,
never to the file.

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

## 3. The authorized folders — persisted in hermes at two levels (OWNER 2026-10-04, call 4)

**The ruling.** The WORKSPACE holds the authorized folder set: what build detection watches, surviving
restarts, carried by realm sync. Each persona INSTANCE (a specialized agent) is ASSIGNED a subset and
loads `AGENTS.md` only from its assigned folders — never from every folder of a multi-folder workspace.
The launcher Projects screen stays the single editor of both levels; hermes stores and is the authority
for the persisted set. This replaces the in-memory push the first draft had.

**What is true today, and what moves.** A mission-chat turn gets ONE `AGENTS.md`: the launcher keeps a
per-instance directory in machine-local SharedPreferences (`LocalMissionAgentContextStore`, "deliberately
outside workspace/realm state"), sends it as `--agents-file`, hermes reads that one file with a typed
receipt (`load_workspace_agents_context`) and grounds the turn's cwd on its directory (workdir ladder
rung 2), after which `prompt_builder._load_agents_md` chains git-root→cwd. So "one folder per agent" is
already the shape; what is missing is persistence, the set it is a subset OF, and the second folder.
Workspace records are JSON at `paths.workspace_path(id)` and travel as the `WORKSPACE` family through
the GENERIC overwrite loop; persona instances carry `workspace_id` / `placement_id` and travel through
the 3-way `PERSONA_INSTANCE_CONFIG` family.

**Level 1 — the workspace's authorized folders.** A new store beside the workspace record,
`paths.workspace_folders_path(workspace_id)` (`store/workspace_folders/<token>.json`), NOT a key inside
the record: the record syncs by generic overwrite, and a per-machine binding map must merge key-wise or
a peer's publish deletes this machine's paths. Document v1:

```json
{"schema_version": 1, "workspace_id": "ws_…", "folders": {
  "fld_7c1e…": {"name": "EterniaLauncher", "added_at": "…", "added_by_machine": "mach_…",
                "bindings": {"mach_a3f2…": {"path": "X:\\…\\EterniaLauncher", "bound_at": "…"},
                             "mach_9b01…": {"path": "/home/t/eternia/launcher", "bound_at": "…"}}}}}
```

`folder_id` is minted by the launcher (`ProjectFolder.id` — already stable across locate) and is the
PORTABLE identity; a `path` is a per-machine binding keyed by this install's machine id (the gateway
identity's device id, the same key a paired peer is known by). A member machine with no binding for a
folder sees the folder as `folder_unbound_here` (typed unknown, evidence: which machines bind it) —
detection and `AGENTS.md` loading skip it, nothing is fabricated. Realm sync: a new family
`WORKSPACE_FOLDERS` (`store/workspace_folders/`, owner `workspace_folders_sync.apply_pull`) merging
KEY-WISE at two depths — folder ids union, and inside a folder the `bindings` map unions by machine id,
so two machines never write the same key and no conflict can arise from paths; `name` and removal
follow the newest `issued_at` (the same basis the scope pointers use). A folder removed from the set is
tombstoned (`removed_at`, `removed_by_machine`) for one publish cycle so the removal wins over a peer's
stale copy, then dropped.

**Level 2 — the instance's assigned subset.** `assigned_folder_ids: [fld_…]` on the persona-INSTANCE
record (`persona_assignments/store.py` field + the 3-way family it already rides). Always a subset of its
workspace's set (a write naming a folder the workspace does not hold is refused `folder_not_in_workspace`;
a folder later removed from the workspace is dropped from every assignment in the same write). Empty
means none: an instance with no assignment loads no folder `AGENTS.md` — never "all of them". The
canonical persona channel (no workspace) has no assignment and keeps today's behaviour.

**Methods** (`serve_rpc/workspace_folders.py`, `TIER_CONSOLE`; the two `set` verbs also in
`LOCAL_CONSOLE_METHODS` — which folders THIS machine binds is the desktop operator's move):

| method | params | result / refusals |
|---|---|---|
| `runtime.workspace.folders.set` | `workspace_id`, `folders: [{folder_id, name, path}]` (≤64), `issued_at` | **replace-whole-set for this machine**: the folder-id set becomes exactly the list (others tombstoned), this machine's bindings become exactly the paths given; OTHER machines' bindings are untouched. `{applied, count, missing: [folder_ids whose path does not exist here], superseded}` |
| `runtime.workspace.folders.show` | `workspace_id` | the document, with `bound_here` per folder |
| `runtime.persona.instance.folders.set` | `persona_instance_id`, `folder_ids`, `issued_at` | replace the subset; `ERR_INVALID_PARAMS` `folder_not_in_workspace` |
| `runtime.persona.instance.folders.show` | `persona_instance_id` | `{workspace_id, folder_ids, folders: [{folder_id, name, bound_here, path}]}` |

CLI mirrors, read-only plus the same two setters: `harness workspace folders show|set`,
`harness persona folders show|set` (argv over the same store doors; the contract dump re-runs).

**What the turn does with it.** `mission_chat_turn_context` resolves the addressed instance's
`assigned_folder_ids` → this machine's bindings → loads each folder's `AGENTS.override.md`/`AGENTS.md`
through the existing per-file loader (128 KB each, 256 KB total, overflow typed `too_large` in the
receipt, the remaining folders still loaded) and injects each as its own provenance-labelled
`workspace_context` section; the receipts list every folder, including the unbound and the missing. The
workdir ladder's rung 2 becomes "the FIRST assigned folder bound here" (assignment order is the
launcher's order; the launcher marks the first as primary). `--agents-file` is accepted for one release
as a deprecated alias that is IGNORED when the instance has an assignment (receipt `status:
superseded_by_assignment`), then deleted.

**What detection reads.** The authorized roots for §5 = every folder bound on this machine across every
workspace of the ACTIVE realm (a detected row carries the `workspace_id` / `folder_id` it fell under; a
build under two nested folders takes the deepest). Recomputed when the store's fingerprint moves — the
`store/workspace_folders/` directory joins the read-model fingerprint — never pushed, never cached in
serve beyond the frame.

**Migration.** (1) Existing workspaces: an absent document is an empty set — nothing to migrate, detection
is off until the Projects screen authorizes a folder. (2) The launcher's `LocalMissionAgentContextStore`
bindings: on the first run after the launcher half lands, for each persona instance bound to a directory
that equals a Projects folder's path (case-folded, realpath) the launcher writes the folder into the
instance's workspace set (if absent) and assigns it; a bound directory that is NOT a Projects folder is
listed once in a notice ("these agents pointed at folders outside your Projects; add the folder to a
project to keep its instructions") and the binding is dropped — the launcher does not silently widen the
authorized set with folders the operator never picked for a project. (3) hermes' `--agents-file`: the
deprecation window above.

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
line never appears the artifact is null even if a conventional output directory exists — and the row
carries `artifact_unlocated` with the directories probed. **Index the unknowns:** a line that looks like
a phase announcement (matches the loose shape `^\w[\w\s]{2,40}\.\.\.$` or begins with `Running`,
`Building`, `Linking`, `Compiling`, `Launching`) but matches no stage regex is recorded as
`stage_line_unrecognized` with the line as evidence — bounded, deduped, newest kept — so a Flutter
version that renames a phase leaves its new wording ON THE ROW the first time it is seen, not in
someone's memory.

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

Runs in the serve process only, on the snapshot build cadence, only while this machine binds at least
one authorized folder (§3), under a 50 ms budget (exceeded ⇒ `detected: unavailable scan_budget`, with
the measured `scan_ms` still reported). `psutil.process_iter` filtered by executable name first
(`dart`, `dart.exe`, `flutter`, `flutter.bat`), then `cmdline()` through the Flutter argv parser, then
the folder test on `cwd()` — a process whose cwd cannot be read, or whose cwd is under no authorized
folder, is not a detected build (unprovable scope is out of scope, by design). A candidate whose pid is
already an agent-started session or an announced `build_pid` is skipped (dedupe by pid + start time).
Liveness is `cpu`: the process tree's cumulative CPU time across two consecutive scans; unchanged for
`stall_seconds` ⇒ `stalled`, **never auto-ended** (owner 2026-10-04, call 1 — the operator ends it with
Stop). `started_by: external`, empty owner, `restart.argv` = the observed cmdline, `restart.cwd` = the
observed cwd.

**Its unknowns, indexed on the row** (the owner rule): a name-filtered process whose cmdline the parser
cannot classify ⇒ `process_unidentified` (exe + argv head, the process is NOT shown as a build);
`cwd_unreadable` (AccessDenied class) for a build-shaped cmdline that is dropped for want of scope;
and on every detected row, because the scan cannot see them: `env_unobserved` (the env a restart
cannot reproduce — `PATH`, `PUB_CACHE`, `FLUTTER_ROOT`, `JAVA_HOME` named as the keys it would need),
`wrapper_unobserved` (the parent chain observed, e.g. `explorer.exe → cmd.exe → flutter.bat → dart.exe`),
`path_unobserved`. These are what the launcher lists under Restart, so the operator sees what will differ.

**Cost, visible on every frame:** `scan_ms`, `processes_examined`, `candidates`, `budget_ms` on
`sources.build.sub.detected`, and `running_work.build_detect` in `parity.sections_ms` (§1).

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
| detected | `terminate_host_pid(pid, host_start_time)` | folder no longer authorized ⇒ `folder_unauthorized` |

Both verbs are direct METHODS (owner 2026-10-04, call 3): `runtime.work.cancel {work_id, issued_at,
reason}` and `runtime.work.restart {work_id, issued_at}` in `serve_rpc/work.py`, `TIER_CONSOLE`, each
the same decision the argv verb reaches (`cancel_work`; `harness work restart` is the argv mirror of the
second). The `issued_at` replay guard applies unchanged (`work_commands._cancel_is_superseded`, lifted
beside the decision so both doors share it).

**Restart** = stop if running, then spawn `restart.argv` in `restart.cwd` through
`process_registry.spawn` as a background process with the completion default, `started_by: operator`,
empty owner, `restart_of: <work_id>`; returns the new `work_id`. **A detected build restarts through the
SAME path and method as every other row, with no confirm step** (owner 2026-10-04, call 2): the row
already shows the exact argv and cwd it will run and lists, as typed unknowns, what hermes could not
observe (`env_unobserved`, `wrapper_unobserved`, `path_unobserved`). The restarted build runs under
hermes' registry — with hermes' own env and PATH — which is precisely what those unknowns say will
differ.

**Stall-fail** (the 2026-10-04 frozen-job class): the serve sweep ticks every 30 s beside the
delegation stale monitor. `stalled` for `stall_fail_seconds` (default 900) ⇒ agent-started and announced
builds are ENDED with `outcome: stalled` (agent-started → `kill_process`; announced → the declared stop
mode) and the owner notified; **detected builds are MARKED only — never auto-killed** (owner 2026-10-04,
call 1): the row stays `stalled` with its `seconds_since_progress` climbing, and the operator ends it
with Stop. Every ending (stall, lost, failed, succeeded, stopped) emits a `build.ended` EventLog event the
launcher renders as a notice, and an agent-started one additionally rides the completion queue so the
owning agent is woken with the tail.

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
  unknowns.py          models   the unknown kinds tuple, the bounded/deduped index, evidence redaction
  history.py           stores   history.jsonl append + median
  detect.py            lanes    the psutil scan under this machine's bound folders (+ scan cost)
  control.py           lanes    stop / restart decisions (origin × declared controls)
  sweep.py             lanes    serve tick: stall-fail (agent/announced only), build.ended, history append, registry gc
agent_runtime/workspace_folders.py          stores   level 1: the per-workspace folder set document, machine bindings, tombstones, `authorized_folders_bound_here()`
agent_runtime/workspace_folders_sync.py     stores   the WORKSPACE_FOLDERS realm-sync family: key-wise merge at two depths
agent_runtime/persona_assignments/store.py  (field)  level 2: `assigned_folder_ids` on the instance record
agent_runtime/running_work/lanes_build.py   lanes    BuildLane: announced rows + the terminal reclassification pass + detected rows
agent_runtime/serve_rpc/workspace_folders.py lanes   runtime.workspace.folders.set/.show, runtime.persona.instance.folders.set/.show
agent_runtime/serve_rpc/work.py             lanes    runtime.work.cancel / runtime.work.restart
```

Reclassification: `BuildLane` runs AFTER the terminal lane in `_COLLECTORS` and is handed the frame's
rows so far; a terminal row whose `command` parses as a build is REPLACED in place by a build row with
`origin_work_id` (accounted `reclassified_build`, by design) — one producer step, so `counts` never
double. Each row of §10 names its test and its killing mutation at the landing (`GATE_LANDING` rule).

## 10. Implementation rows (one commit each, in this order)

Order changed 2026-10-04 with the rulings: the two-level folder store (H5a/H5b) now sits BEFORE the
lane that needs `workspace_id` / `folder_id` on its rows, and the unknowns index is born in H1 so every
later row writes into it rather than retrofitting.

H1 `builds/unknowns.py` (kinds tuple, bounded/deduped index, evidence redaction) + `flutter_argv.py` move + `FlutterCommand` (an unparseable head ⇒ `toolchain_unrecognized` with the argv head) · `tests/agent_runtime/test_build_unknowns.py` (cap, dedup, newest kept, evidence redacted), `test_flutter_argv.py`; the guard's own tests unchanged and a pin that `flutter_build_guard` defines no token regex of its own.
H2 `recognizer_flutter.py` + four transcript goldens + `stage_line_unrecognized` / `artifact_unlocated` · `test_build_recognizer_flutter.py` (mutation: swap two stage regexes ⇒ the ordered-sequence pin reds; random-line transcript ⇒ `unknown` AND zero unknowns; a renamed-phase transcript ⇒ exactly that line indexed).
H3 `builds/vocabulary.py` + `registry.py` (record v1 with `unknowns`) + `running_work_store_paths` dir entry + fingerprint restat + `harness builds registry-path` · `test_build_registry.py`, `test_stream_fingerprint.py` arm (a record touched ⇒ fingerprint moves).
H4 `lanes_build.py` (announced + reclassification; `workspace_id`/`folder_id` resolved through H5a's reader, null + `folder_unresolved` before any folder exists) + `sources.build` with sub-health and cost keys + `McpJobLane` dedupe + `build_rows.json` + stream goldens regen + contract ledger + README copy-status · `test_running_work.py` arms, `test_build_rows_fixture.py` (every unknown kind appears in the golden at least once).
H5a `workspace_folders.py` (document v1, machine bindings keyed by gateway device id, tombstones, `authorized_folders_bound_here()`) + `workspace_folders_sync.py` family + `paths.workspace_folders_path` + the store dir in the read-model fingerprint + `serve_rpc/workspace_folders.py::runtime.workspace.folders.set/.show` (`LOCAL_CONSOLE_METHODS`) + `harness workspace folders show|set` · `test_workspace_folders.py` (replace-whole-set touches only this machine's bindings; tombstone wins over a stale peer; unbound ⇒ `folder_unbound_here` with the binding machines), `test_realm_sync_workspace_folders.py` (two machines bind one folder ⇒ union, no conflict), `test_peer_authorization.py` tier table.
H5b `assigned_folder_ids` on the persona-instance record + `runtime.persona.instance.folders.set/.show` + `harness persona folders show|set` + `mission_chat_turn_context` loads each assigned bound folder's `AGENTS.md` as its own `workspace_context` section (per-file 128 KB, 256 KB total, receipts for unbound/missing/too-large) + workdir ladder rung 2 = first assigned bound folder + `--agents-file` deprecated alias · `test_persona_instance_folders.py` (subset refused when not in the workspace; workspace removal drops assignments; empty ⇒ no folder loaded, NEVER all), `test_mission_chat_turn_context.py` arms (two folders ⇒ two labelled sections; alias ignored under an assignment with `superseded_by_assignment`).
H6 `detect.py` + the detected sub-source reading H5a's bound folders + `process_unidentified` / `cwd_unreadable` / the three restart unknowns + `scan_ms` into the sub-health and `parity.sections_ms` · `test_build_detect.py` over a fake process table (under-folder, outside, unreadable cwd, already-owned pid, cpu-stall, unparseable cmdline ⇒ indexed not shown, budget breach ⇒ typed with the measured ms).
H7 `history.py` + `sweep.py` (stall-fail for agent/announced ONLY, `build.ended`, history, gc) + serve boot `HERMES_BUILD_REGISTRY_DIR` export · `test_build_sweep.py` with a fake clock (queued never stalls; a detected build past the threshold is still `stalled` and alive — the mutation that kills it reds; agent-origin wakes its owner).
H8 `control.py` + `_cancel_build` + `serve_rpc/work.py::runtime.work.cancel/.restart` + `harness work restart` · `test_build_control.py` (each origin × each declared mode; a detected restart succeeds with no confirm param and the new row carries `restart_of`; replay guard shared by both doors), tier table.
H9 `mcp_job_wake` stops writing `qa_build` rows · `tests/tools/test_mcp_job_background_work.py` (route still bound, no row).

## 11. Owner calls — ruled 2026-10-04, plus the new ones call 4 raises

1. **Stall-fail for detected builds** — *recommended mark only.* **OWNER 2026-10-04: MARK only, never auto-kill; the operator kills with Stop. Agent/announced keep end-failed + notify. NEW RULE "index the unknowns": anything hermes cannot classify (unrecognized stage line, unreadable output, unidentifiable process, unknown env/wrapper) is recorded on the row/registry as a typed unknown WITH the evidence seen, so future problems can be debugged from the record.** → §1 `unknowns`, §2, §4, §5, §7.
2. **Restart of a detected build** — *recommended a confirm dialog.* **OWNER 2026-10-04: SAME path and method as every other row, NO confirm dialog; the row shows the exact argv + cwd it will run and lists what hermes could not observe (shell env, wrapper script, PATH) as typed unknowns.** → §5, §7; `confirm_required` deleted.
3. **Stop/Restart transport** — *recommended methods.* **OWNER 2026-10-04: new direct methods `runtime.work.cancel` / `.restart` — accepted.** → §7, `serve_rpc/work.py`.
4. **Roots durability** — *recommended in-memory.* **OWNER 2026-10-04: CHANGED — authorized roots are PERSISTED in hermes at TWO levels: the WORKSPACE holds the authorized folder set (what build detection watches; survives restarts; realm sync carries it), and each PERSONA / specialized agent is ASSIGNED a subset — it loads AGENTS.md only from its assigned folders, never every folder in the workspace. The launcher Projects screen stays the single editor for both levels; hermes stores and is authority for the persisted set.** → §3 replaced; migration named there.
5. **`ParityStageC.builds.job.json`** — *recommended keep both, one writer.* **OWNER 2026-10-04: accepted.**
6. **Registry dir for hand-run writers** — *recommended env + CLI fallback.* **OWNER 2026-10-04: hand-run `prebuild.dart` asks hermes for the registry path, else no announce + a stdout line — accepted.**
7. **Detected-source cost** — *recommended as written.* **OWNER 2026-10-04: as written; keep the per-snapshot cost metric visible so it can be made faster later.** → `scan_ms` on the sub-health and in `parity.sections_ms` (§1, §5).

**New calls that ruling 4 raises** (each with the recommendation; the plan above is written to the
recommendation):

- **4a. How a folder's PATH travels between machines.** A realm has members on different machines, and
  the same folder lives at different paths on each. *Recommend per-machine bindings inside the folder
  document, keyed by the gateway device id* (§3) — the launcher on each machine binds its own path through
  the ordinary "locate" gesture, the portable identity is the launcher's `folder_id`, and an unbound
  folder is a typed unknown rather than a fabricated path. The alternative — logical `${roots.…}` tokens
  bound in `machine_roots.json` — would make every Projects folder a hand-edited config token, which is
  the second editable list the ruling forbids.
- **4b. Default assignment for a NEW instance.** Empty (loads nothing) or the workspace's only folder when
  it has exactly one? *Recommend empty, always*: the ruling says never every folder, "exactly one" is
  "every" in the common case, and the launcher's assign control is one click. The launcher may OFFER the
  single folder at instance creation; it never writes it unasked.
- **4c. Which workspaces feed detection.** The active workspace only, or every workspace of the active
  realm? *Recommend every workspace of the active realm*, each detected row tagged with its
  `workspace_id`: an operator who authorized a folder in workspace B still expects to see B's build while
  looking at A, and the filter is a render choice the launcher can add.
- **4d. The `WORKSPACE_FOLDERS` family's conflict policy.** Key-wise union (as §3) or whole-document
  adopt-or-hold like the level? *Recommend key-wise*: bindings are disjoint by machine id, so the only
  contended keys are `name` and removal, both ordered by `issued_at`; whole-document HOLD would block a
  realm's detection over a rename.
- **4e. The deprecation window for `--agents-file`.** One launcher release as an ignored-under-assignment
  alias, then deleted? *Recommend yes*; the receipt names the supersession so the one operator still on
  the chip sees why their file stopped loading.

One deviation from the row's wording, stated: "the `mcp_job` row folds into this kind" is done for
the QA build (§8); the `mcp_job` KIND is kept for MCP jobs that are not builds, so a future non-build
server job still has a row.
