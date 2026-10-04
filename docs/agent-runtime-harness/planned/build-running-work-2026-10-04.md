# Builds as a first-class `running_work` kind — the hermes half

**Status: designed 2026-10-04, not shipped. Owner decisions (fixed, 2026-10-04):** three sources
(agent-started, announced, detected only under the operator's launcher Projects folders); Stop AND
Restart on every row; Flutter first; hermes owns the rows; the launcher renders them. **Amended
2026-10-04 after the owner ruled on the seven calls (§11), and REFINED the same day:** the authorized
roots are **repo slots** a WORKSPACE declares (clone URL, default branch, toolchain + environment KEYS,
`AGENTS.md` role — portable, carried by the realm), each MACHINE fills (local path + its private
environment, accounted for as set / missing / unknown, never a value) and each persona INSTANCE is
assigned a subset of (it loads only those repos' `AGENTS.md`, and its builds run with this machine's slot
environment) — the launcher Projects screen is the single editor, no hard limits anywhere, and the
workspace owner's setup recipe ("image") is the same data read as a per-machine checklist (§3); detected
builds that stall are MARKED, never killed;
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
| machine roots (`machine_roots.json` `{schema_version, roots: {name: path}}`, `write_machine_roots` the single write site, `${roots.<name>}` tokens, hard-excluded from realm sync) and a persona's `repo_scope` (one such token; workdir rung 3; readiness row) | `agent_runtime/machine_roots.py`, `config/persona_records.py`, `profile_readiness.py` | **a slot's machine fill IS a machine root** (§3): binding slot `launcher` writes `roots.launcher`, so every existing token and `repo_scope` keeps resolving; the slot adds the portable declaration, the environment, the assignment and the accounting a root never had |
| workspace records + the WORKSPACE realm-sync family (generic overwrite), persona-instance records with `workspace_id` / `placement_id` + their 3-way family, the level family's whole-document adopt-or-hold | `paths.workspace_path`, `realm_sync/families.py`, `persona_assignments/store.py`, `level_sync.py` | the slot document is a new key-wise family beside the workspace record; the per-instance assignment rides the persona-instance family |
| the one `AGENTS.md` a mission-chat turn injects today: the launcher's per-instance directory (`mission-chat message --agents-file`, machine-local SharedPreferences) → `load_workspace_agents_context` (128 KB, typed receipt) → workdir ladder rung 2 → `prompt_builder._load_agents_md` chains git-root→cwd | `mission_chat_turn_context.py`, `prompt_observability/workspace_agents.py`, `mission_chat_workdir.py`, `agent/prompt_builder.py` | the per-file loader and its receipt are reused per ASSIGNED slot, for BOTH `CLAUDE.md` and `AGENTS.md` (owner correction 2026-10-04); the `--agents-file` pointer is retired (§3) |
| the realm repository's clone + credential: `_git_clone`, `RealmSyncCredential.git_extra_config()` (launcher-brokered `http.extraHeader`, realm-scoped) | `realm_sync/git.py`, `realm_membership.py` | NOT reused for a slot's clone — a slot clone authenticates through the machine's own git (§3.5); the realm seam is named as the Phase C candidate for a brokered per-host credential |

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
| `project` | `{root, name}` | `root`: the bound slot path for detected, the cwd for agent, the record's `project_root` for announced; `name` = basename |
| `workspace_id` · `slot_id` | string or null each | the repo slot (§3) the build sits under, when one does — resolved for every source by the under-slot test over this machine's bound slots (deepest wins); null with an `unknowns` entry `slot_unresolved` otherwise |
| `env_source` | `slot:<name>` · `process` · `unknown` | what environment the build ran (or will restart) with — a slot's fill, hermes' own process env, or unobserved (detected) |
| `started_by_instance` | persona instance id or null | **OWNER 2026-10-04 (example):** the persona INSTANCE whose turn started the build — the shared `owner.persona_instance_id` lifted to a named build key so Activity can say "the backend agent's build" without re-deriving it. Agent source: the spawning session's owner via `_owner_of`; announced: the record's `session_key` resolved the same way; detected: null. Null ⇒ an `unknowns` entry `starter_unknown` with the evidence seen (the session key that did not resolve, or "detected: no session"). Together with `workspace_id` + `slot_id` this is what lets two instances in ONE workspace — a backend agent on `backend`, a frontend agent on `launcher` — each see their own builds. |
| `unknowns` | list of `{kind, evidence, seen_at}` (a per-row WIRE bound of 32, dedup by kind + evidence hash, newest kept, truncation declared `by_design`) | **owner rule "index the unknowns" (2026-10-04):** everything hermes could not classify, WITH what it saw. `kind` ∈ `stage_line_unrecognized` (evidence: the line, redacted ≤200), `output_unreadable` (the exception class), `process_unidentified` (exe name + argv head), `cwd_unreadable`, `wrapper_unobserved` (the parent chain seen, e.g. `cmd.exe /c flutter.bat`), `env_unobserved` (the env KEYS a restart cannot reproduce — only the keys the slot does not declare once a slot applies), `path_unobserved`, `artifact_unlocated` (the directories probed), `writer_unidentified`, `slot_unresolved`, `slot_unbound_here` (the slot and the machines that bind it), `slot_probe_unknown` (a tool/key/file probe that could not answer — the probe and its error class), `toolchain_unrecognized` (argv head). Empty list = nothing was unclassifiable, which is itself a claim the tests pin. |
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
| `controls` | `{stop: allowed·refused·unavailable, stop_reason, restart: allowed·refused·unavailable, restart_reason}` | reasons: `not_running`, `owner_not_here`, `writer_declines`, `argv_unknown`, `slot_unbound` (the slot it ran under is no longer bound here). No `confirm_required`: a detected restart is the same path as every row (owner 2026-10-04) |
| `restart` | `{argv: [...], cwd}` or null | what Restart would run; null ⇒ `restart: refused argv_unknown` |
| `origin_work_id` | string or null | agent source: `terminal:<session_id>` it replaced |
| `announcement` | `{record, writer_pid, heartbeat_age_seconds}` or null | announced only |
| `mcp_job` | `{server, job_id}` or null | announced only; the dedupe key for §8 |
| `restart_of` | string or null | the row this one re-ran |

**`sources.build`** is one entry with three sub-healths, because the three sources fail
independently and "I could not look" must be sayable per source:
`{"status": "ok"|"unavailable", "lane": "durable", "sub": {"agent": {...}, "announced": {...}, "detected": {...}}}`,
each sub `{status, reason}`; `detected` reasons: `not_in_process` (CLI lane), `no_slots_declared` (no
workspace in the active realm declares a slot), `slots_unbound_here` (slots exist, none bound on this
machine), `scan_budget`, `scan_failed`; `announced`: `registry_unreadable`. The top-level status is
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
`[]`; hermes appends its reader-side unknowns (`writer_unidentified`, `slot_unresolved`) to the row,
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

## 3. Repo slots — the workspace declares, the machine fills, the agent is assigned (OWNER 2026-10-04 + refinement)

**The ruling, refined (2026-10-04).** A WORKSPACE declares named **repo slots** (`launcher`, `backend`,
`hermes`) — the portable identity that travels with the realm: clone URL, default branch, the toolchain
and the environment KEYS it expects, its `AGENTS.md` role. Each MACHINE fills each slot: the local path
and that machine's environment for it (toolchain paths, SDK, venv, plain env vars, `.env`) — private to
the machine, never synced, but ACCOUNTED FOR (set / missing / unknown per key, never the value). An
AGENT is assigned slots and loads only those repos' `AGENTS.md`; its builds run with this machine's slot
environment. No hard limits anywhere; the only bound is what the machine can scan, and the scan cost
stays visible. The workspace owner's setup recipe ("image") is part of the same data (§3.5), its own later
phase. This supersedes the "loose folders" draft of the same day; nothing from that draft landed, so there
is no folder→slot migration — only the migrations in §3.6.

**What a slot subsumes, so there is one idea and not three.** hermes already has (a) `machine_roots.json`
— `${roots.<name>}` tokens an operator binds by hand to a local path, one write site
(`write_machine_roots`), hard-excluded from realm sync; (b) a persona's `repo_scope` — one such token
naming "the repo this persona works in" (workdir ladder rung 3, readiness row); (c) the launcher's
per-agent `AGENTS.md` directory (`--agents-file`, machine-local). **A slot's machine fill IS a machine
root**: binding slot `launcher` writes `roots.launcher` through the existing single write site, so every
`${roots.launcher}` token in every config starts resolving the moment the slot is filled, `repo_scope:
"${roots.launcher}"` keeps working unchanged, and a root with no slot behind it stays a plain root. The
slot adds what a root never had: the portable declaration, the environment, the assignment, the accounting.

### 3.1 The slot declaration — portable, synced

`paths.workspace_slots_path(workspace_id)` → `store/workspace_slots/<token>.json`, beside the workspace
record (not inside it: the record syncs by generic overwrite; this document merges key-wise). v1:

```json
{"schema_version": 1, "workspace_id": "ws_…",
 "slots": {
  "launcher": {
    "repo": {"clone_url": "https://github.com/ArcadiaLabsLLC/EterniaLauncher.git", "default_branch": "main"},
    "toolchain": {"kind": "flutter", "tools": [{"name": "flutter", "min_version": "3.41"}, {"name": "dart"}],
                  "env_keys": [{"key": "FLUTTER_ROOT", "required": true}, {"key": "PUB_CACHE", "required": false}],
                  "dotenv": {"path": ".env", "keys": [{"key": "ETERNIA_API_BASE", "required": true, "secret": false},
                                                        {"key": "KEYCLOAK_CLIENT_SECRET", "required": true, "secret": true}]}},
    "context": {"role": "launcher / frontend", "files": ["CLAUDE.md", "AGENTS.md"]},
    "recipe": {"revision": 3, "steps": [], "edited_at": "…", "edited_by": {"machine": "mach_…", "persona_instance_id": null}},
    "declared_at": "…", "declared_by_machine": "mach_…", "removed_at": null},
  "backend": {"…": "…"}},
 "machines": {
  "mach_a3f2…": {"reported_at": "…", "slots": {
     "launcher": {"status": "ready", "bound": true, "checkout": "matches",
                  "tools": {"flutter": {"status": "set", "version": "3.41.2"}, "dart": {"status": "set", "version": "3.11.1"}},
                  "env_keys": {"FLUTTER_ROOT": "set", "PUB_CACHE": "missing"},
                  "dotenv": {"present": true, "keys": {"ETERNIA_API_BASE": "set", "KEYCLOAK_CLIENT_SECRET": "set"}}},
     "backend": {"status": "not_cloned", "bound": false}}}}}
```

Slot names obey `machine_roots._ROOT_NAME_RE` (`[A-Za-z0-9_]+`) because they ARE root names. `slots`
has no count limit; `env_keys`, `tools`, `dotenv.keys` have none. `machines.<id>` is the ACCOUNTING a
machine reports about itself — statuses and versions, never a path and never a value — keyed by the
gateway device id so two machines never write the same key. Realm sync: family `WORKSPACE_SLOTS`
(`store/workspace_slots/`, owner `workspace_slots_sync.apply_pull`), key-wise at three depths: slot names
union (removal by tombstone + newest `issued_at`); inside a slot, `repo` / `toolchain` / `context` /
`recipe` by newest `recipe.revision` then `issued_at`; `machines` by machine id (disjoint, no conflict).
`context.files` defaults to both `CLAUDE.md` and `AGENTS.md` (owner correction 2026-10-04); a declaration
may narrow or add (an `AGENTS.override.md`, a nested `AGENTS.md` under a subfolder), never implicitly.

### 3.2 The machine fill — private, never synced, accounted for

Two files on this machine, both hard-excluded from realm sync exactly like `auth.json` and
`machine_roots.json` is today:

- the PATH: `machine_roots.json` `roots.<slot>` — the existing registry, unchanged schema, same write site.
- the ENVIRONMENT: `machine_slot_env.json` v1 — `{"schema_version": 1, "workspaces": {"ws_…": {"launcher":
  {"tool_paths": {"flutter": "C:\\flutter\\bin\\flutter.bat"}, "env": {"FLUTTER_ROOT": "C:\\flutter"},
  "path_prepend": ["C:\\flutter\\bin"], "dotenv": ".env", "venv": null, "bound_at": "…"}}}}`. Plain values
  live here because this is the machine's own file; keys the declaration marks `secret: true` are NEVER
  stored here — they come from the slot's `.env` under the bound path (read by the process that needs
  them, never copied) or from the launcher's secure storage, and hermes only ever reports their presence.

The ACCOUNTING (§3.1 `machines.<id>`) is computed by `workspace_slots.report(workspace_id)` — on bind, on
serve boot, on `runtime.workspace.slots.report`, and after any `set` — by probing: path exists and
`git remote get-url origin` matches `repo.clone_url` (`checkout: matches | remote_mismatch | not_a_repo`),
each tool resolves (`tool_paths` first, then `PATH` through `shutil.which`) with its `--version` parsed
where known, each env key present in `env` ∪ process env, the dotenv file present and each declared key
present in it (parsed as `KEY=`, value discarded). Every probe answers `set | missing | unknown` — an
unreadable file or a tool that hangs on `--version` is `unknown` with the evidence on the row
(`slot_probe_unknown`, §1). The report never carries a value and the test pins that by grepping the
written document for every value the fixture environment set.

### 3.3 The agent's assignment and what it changes

`assigned_slots: ["launcher", "backend"]` on the persona-INSTANCE record (`persona_assignments/store.py`,
rides the existing 3-way family). Always a subset of the workspace's declared slots (`slot_not_in_workspace`
refused; a removed slot is dropped from every assignment in the same write); empty means none — never all.
No limit on count. The canonical persona channel (no workspace) has no assignment.

**OWNER 2026-10-04 (example) — the motivating case.** A BACKEND agent and a FRONTEND agent are two persona
instances in the SAME workspace, assigned `backend` and `launcher` respectively; each turn loads only its
own slots' `CLAUDE.md` + `AGENTS.md`. Two facts follow and are pinned: (a) **a slot may be assigned to
several instances at once** — a shared `contracts` or `docs` slot sits in both agents' lists — and
assigning a slot to one instance NEVER removes it from another (assignment is a per-instance subset,
not a lease; `instance.slots.set` touches one record); (b) **every build row carries `workspace_id`,
`slot_id` and `started_by_instance`** (§1) — when known, else the typed unknown `starter_unknown` — so
Activity can say which agent's build it is.

- **Where the assignment is EDITED** (owner correction 2026-10-04): in the launcher's Agent Console, per
  persona instance — a slot picker over the active workspace's declared slots that REPLACES today's
  per-agent `AGENTS.md` directory picker in place. The workspace / Projects side declares and fills slots
  and never assigns agents. hermes stays the authority either way: the record and the two methods below.
- **Context files — `CLAUDE.md` AND `AGENTS.md`** (owner correction): the turn loads, for each assigned
  slot bound here, each of `context.files` under the bound path through the existing per-file loader
  (128 KB each, no total cap, overflow typed per file) as its OWN labelled `workspace_context` section
  (label: `<slot>/CLAUDE.md`, `<slot>/AGENTS.md` — never merged into one); receipts list every assigned
  slot and every file, including unbound slots (`slot_unbound_here`, evidence: the machines that bind it)
  and missing files (`missing`, not an error). `prompt_builder`'s own cwd chain still runs for the
  workdir slot, so its `CLAUDE.md` is deduplicated by content against the slot section (the chain's
  existing `seen_content` rule) rather than injected twice.
- **workdir**: ladder rung 2 = the first assigned slot bound here (assignment order is the launcher's;
  the first is primary). Rung 3 (`repo_scope`) stays.
- **environment, and why the restart unknowns shrink**: every subprocess the turn spawns whose cwd is
  under an assigned slot's bound path — the terminal tool's foreground and background commands, which is
  where builds come from — gets the slot environment overlaid: `path_prepend` in front of `PATH`, `env`
  merged, `dotenv` loaded (values from the file, never from the record), `venv` activated by prepending its
  `bin`/`Scripts`. ONE overlay function, `workspace_slots.env_overlay(cwd)`, applied through ONE seam: the
  subprocess env is built in upstream `tools/environments/local.py` (`_sanitize_subprocess_env`), so the
  fork adds one import and one call at that stable point reading a contextvar the mission-chat turn sets
  beside the workdir — a Seams row by the Fork Boundary Map, additive, named as such in §10. A build row's
  `restart` block then carries `env_source: "slot:launcher"` and its `env_unobserved` entry lists ONLY the
  keys the original process may have had that the slot does not declare; `wrapper_unobserved` disappears
  for agent-started and restarted builds because hermes resolves `flutter` through `tool_paths` itself and
  records the resolved executable in `restart.argv[0]`; `path_unobserved` becomes `path_prepend` seen. A
  detected build under a filled slot restarts with that slot's environment — the unknowns on the row
  before the restart say exactly what will be the same (the slot's keys) and what will not (the rest).

### 3.4 Methods and CLI

`serve_rpc/workspace_slots.py`, all `TIER_CONSOLE`; every verb that touches THIS machine's fill is in
`LOCAL_CONSOLE_METHODS`:

| method | params | result / refusals |
|---|---|---|
| `runtime.workspace.slots.show` | `workspace_id` | the document + this machine's fill status per slot (`bound_here`, path) — never another machine's path |
| `runtime.workspace.slots.declare` | `workspace_id`, `slots: [{name, repo, toolchain, context}]`, `issued_at` | replace the DECLARED set (missing names tombstoned); refuses a name that is not a root name (`invalid_slot_name`) or a clone URL that is not http(s)/ssh (`invalid_clone_url`); edit right = §3.5 |
| `runtime.workspace.slot.bind` (local) | `workspace_id`, `slot`, `path`, `issued_at` | writes `roots.<slot>` through `write_machine_roots`; probes; answers the report row; `remote_mismatch` is a typed WARNING in the answer, the bind still lands (call 8c) |
| `runtime.workspace.slot.env.set` (local) | `workspace_id`, `slot`, `env`, `tool_paths`, `path_prepend`, `dotenv`, `venv`, `issued_at` | replaces this slot's fill in `machine_slot_env.json`; a key declared `secret` in the value map is refused `secret_in_env` (it belongs in `.env`); re-reports |
| `runtime.workspace.slots.report` (local) | `workspace_id` | re-probe, write `machines.<me>`, answer it |
| `runtime.persona.instance.slots.set` | `persona_instance_id`, `slots`, `issued_at` | replace the subset; `slot_not_in_workspace` |
| `runtime.persona.instance.slots.show` | `persona_instance_id` | `{workspace_id, slots: [{name, bound_here, path, status}]}` |

CLI: `harness workspace slots show|declare|bind|env-set|report`, `harness persona slots show|set` over
the same store doors (contract dump re-runs). `harness roots set` keeps working and is what `bind` calls.

### 3.5 The setup recipe ("image") — the same data, its own later phase

The recipe is not a second model: it is the slot declaration READ AS A CHECKLIST, plus an ordered list of
setup steps the workspace owner adds to it. `recipe.steps` v1: `{id, kind: clone | locate | tool | env_key |
dotenv | command, slot, label, ...}` where `clone` / `tool` / `env_key` / `dotenv` steps are DERIVED from the
declaration (hermes materialises them; the owner cannot delete them, only annotate with `hint` text or a
URL) and `command` steps are the owner's additions (`argv`, `cwd_slot`, `run: on_setup_click | never_auto`).
A machine joining the workspace reads its own `machines.<me>` report against the steps and gets, per slot:

| machine state | checklist row | action |
|---|---|---|
| `bound: false` | "not cloned" | **Clone** (`runtime.workspace.slot.clone`) or **Locate** (`slot.bind`) |
| bound, `checkout: remote_mismatch` | "a different repository is at this path" | Locate again, or keep (typed warning stays on the row) |
| tools/keys/dotenv missing | "set up: flutter, FLUTTER_ROOT, .env (2 keys)" | **Set up** → the launcher's env editor (launcher plan §4) + the owner's `command` steps offered one by one |
| all required set | **"ready on this machine"** | — |

**"ready"** = bound ∧ `checkout ∈ {matches}` ∧ every declared tool `set` ∧ every `required` env key `set` ∧
(`dotenv` declared ⇒ file present ∧ every `required` dotenv key `set`). Optional keys missing ⇒ `ready`
with notes. Any `unknown` probe ⇒ `ready: unknown`, never `ready: true` — the unknowns rule.

**Clone** — `runtime.workspace.slot.clone {workspace_id, slot, dest_path, issued_at}` (local): hermes
spawns `git clone --branch <default_branch> <clone_url> <dest_path>` as an upstream BACKGROUND process
through `process_registry` (so it is a `terminal` row with a tail, a notification, a Stop), and on exit 0
binds the slot (`slot.bind`) and re-reports. **Authentication is the machine's own git**: hermes passes no
credential and holds none — the clone authenticates exactly as the operator's shell would (Git Credential
Manager on Windows, `gh auth` / the OS keychain elsewhere). The ONLY git credential seam hermes has today is
`RealmSyncCredential.git_extra_config()` (`realm_membership.py`) — a launcher-brokered, realm-scoped
`http.extraHeader` for the REALM repository — and it is deliberately NOT reused for arbitrary slot URLs.
A clone that fails on auth ends `clone_auth_required` with the redacted git stderr as evidence and the
checklist row says "sign in to <host> with your git credential manager, then Clone again". A
launcher-brokered per-host credential (the realm seam generalised) is a Phase C candidate, call 8b.

**Who may edit the recipe and the declaration**: whoever may PUBLISH the realm — the existing
`realm_sync.git._authorize(realm, "publish", membership)` decision, evaluated by `slots.declare` before it
writes (a member who cannot publish gets `ERR_HANDLER_FAILED` `realm_publish_denied`). A finer
"workspace owner" role does not exist in hermes or the backend today; call 8a.

**Where it renders**: the launcher's Projects home (the editor) and a readiness chip in the Mission
Control scope selector — launcher plan §4.

### 3.6 Detection, migration, no limits

**Detection** (§5) reads `authorized_roots_bound_here()` = every slot bound on this machine across every
workspace of the active realm; a detected row carries `workspace_id` / `slot_id`. The under-slot test is one
prefix compare per bound slot per candidate; its cost is inside `scan_ms`. **No hard limits**: no cap on
slots, workspaces, assignments, keys or steps anywhere in this plan; the `unknowns` index's ≤32 entries is
a per-row WIRE bound like `TAIL_PREVIEW_LIMIT`, declared `by_design` when it truncates, not a model limit.

**Migration.** (1) Existing `machine_roots.json` entries are untouched and keep resolving; a workspace that
later declares a slot of the same name is bound on this machine at once (the root IS the fill) — the
first report says so. (2) Persona `repo_scope` stays as rung 3; the readiness row it already has is
unchanged. (3) The launcher's per-agent `AGENTS.md` directory picks (`LocalMissionAgentContextStore`):
the console picker is REPLACED IN PLACE by the slot picker (owner correction), and on first run each
instance's bound directory is mapped to the matching slot — a slot bound here at that path, else a slot
whose `clone_url` matches the directory's `origin` remote — and written as that instance's assignment;
a directory matching no slot is OFFERED as "declare slot `<basename>` in <workspace> from this checkout"
(clone URL and branch read from the checkout; declaring needs the publish right) and, accepted, declared +
bound + assigned; declined or not a checkout ⇒ listed once in the picker and dropped. Nothing is declared
or assigned unasked beyond the exact-match mapping. (4) `--agents-file`: the one-release alias of call
4e, ignored under an assignment.

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
one slot (§3), under a 50 ms budget (exceeded ⇒ `detected: unavailable scan_budget`, with the measured
`scan_ms` still reported — the budget is the ONLY bound; there is no cap on slots, and a machine that
binds eighty pays for eighty prefix compares per candidate, visibly). `psutil.process_iter` filtered by
executable name first (`dart`, `dart.exe`, `flutter`, `flutter.bat`), then `cmdline()` through the
Flutter argv parser, then the slot test on `cwd()` — a process whose cwd cannot be read, or whose cwd is
under no bound slot, is not a detected build (unprovable scope is out of scope, by design). A candidate whose pid is
already an agent-started session or an announced `build_pid` is skipped (dedupe by pid + start time).
Liveness is `cpu`: the process tree's cumulative CPU time across two consecutive scans; unchanged for
`stall_seconds` ⇒ `stalled`, **never auto-ended** (owner 2026-10-04, call 1 — the operator ends it with
Stop). `started_by: external`, empty owner, `restart.argv` = the observed cmdline, `restart.cwd` = the
observed cwd.

**Its unknowns, indexed on the row** (the owner rule): a name-filtered process whose cmdline the parser
cannot classify ⇒ `process_unidentified` (exe + argv head, the process is NOT shown as a build);
`cwd_unreadable` (AccessDenied class) for a build-shaped cmdline that is dropped for want of scope;
and on every detected row, because the scan cannot see them: `env_unobserved` (the env a restart
cannot reproduce — with a filled slot under it, ONLY the keys the slot does not declare; without one, the
toolchain's whole key list — `PATH`, `PUB_CACHE`, `FLUTTER_ROOT`, `JAVA_HOME`), `wrapper_unobserved` (the
parent chain observed, e.g. `explorer.exe → cmd.exe → flutter.bat → dart.exe`; absent when the slot's
`tool_paths` resolves the executable hermes will run), `path_unobserved` (absent when the slot declares
`path_prepend`). `env_source` says which case applies. These are what the launcher lists under Restart,
so the operator sees exactly what will differ.

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
| detected | `terminate_host_pid(pid, host_start_time)` | slot no longer bound here ⇒ `slot_unbound` |

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
hermes' registry with the SLOT's environment when the cwd is under a bound slot (§3.3: `path_prepend`,
`env`, `.env`, `venv`, the executable resolved through `tool_paths`; `env_source: slot:<name>`), and
with hermes' own process env otherwise (`env_source: process`) — which is precisely what the row's
remaining unknowns say will differ.

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
agent_runtime/workspace_slots.py            stores   the slot document (declaration + machines' accounting), tombstones, `report()` probes, `authorized_roots_bound_here()`, `env_overlay(cwd)`
agent_runtime/workspace_slot_env.py         stores   `machine_slot_env.json` (private fill: tool paths, env, path_prepend, dotenv, venv); never synced; secrets refused
agent_runtime/workspace_slots_sync.py       stores   the WORKSPACE_SLOTS realm-sync family: key-wise merge at three depths
agent_runtime/workspace_slot_recipe.py      policy   Phase B: derived + owner steps, `ready` computation, the clone verb's spawn
agent_runtime/machine_roots.py              (reuse)  `write_machine_roots` is the slot path binding's write site
agent_runtime/persona_assignments/store.py  (field)  `assigned_slots` on the instance record
agent_runtime/running_work/lanes_build.py   lanes    BuildLane: announced rows + the terminal reclassification pass + detected rows
agent_runtime/serve_rpc/workspace_slots.py  lanes    runtime.workspace.slots.show/.declare/.report, runtime.workspace.slot.bind/.env.set/.clone, runtime.persona.instance.slots.set/.show
agent_runtime/serve_rpc/work.py             lanes    runtime.work.cancel / runtime.work.restart
tools/environments/local.py                 SEAM     one import + one call in `_sanitize_subprocess_env`: `workspace_slots.env_overlay(cwd)` (additive; Fork Boundary Map "Seams")
```

Reclassification: `BuildLane` runs AFTER the terminal lane in `_COLLECTORS` and is handed the frame's
rows so far; a terminal row whose `command` parses as a build is REPLACED in place by a build row with
`origin_work_id` (accounted `reclassified_build`, by design) — one producer step, so `counts` never
double. Each row of §10 names its test and its killing mutation at the landing (`GATE_LANDING` rule).

## 10. Implementation rows (one commit each, in this order)

Order, after the 2026-10-04 refinement: **Phase A** (H1–H9) ships builds on repo slots — declaration,
machine fill, accounting, assignment, environment; **Phase B** (H10–H11) is the setup recipe / "image" —
its own later phase, because every verb it needs (declare, bind, report, env.set) exists after H5a and the
checklist is those verbs read back. H5a/H5b stay ahead of H4 (the lane needs `workspace_id` / `slot_id`);
the env-overlay SEAM is its own row (H5c) because it is the one upstream-file edit in the program.

H1 `builds/unknowns.py` (kinds tuple incl. `slot_*`, the 32-entry wire bound declared `by_design`, dedup, evidence redaction) + `flutter_argv.py` move + `FlutterCommand` (an unparseable head ⇒ `toolchain_unrecognized`) · `tests/agent_runtime/test_build_unknowns.py` (bound, dedup, newest kept, redaction, truncation accounted), `test_flutter_argv.py`; the guard's own tests unchanged and a pin that `flutter_build_guard` defines no token regex of its own.
H2 `recognizer_flutter.py` + four transcript goldens + `stage_line_unrecognized` / `artifact_unlocated` · `test_build_recognizer_flutter.py` (swap two stage regexes ⇒ the ordered-sequence pin reds; random-line transcript ⇒ `unknown` AND zero unknowns; a renamed-phase transcript ⇒ exactly that line indexed).
H3 `builds/vocabulary.py` + `registry.py` (record v1 with `unknowns`) + `running_work_store_paths` dir entry + fingerprint restat + `harness builds registry-path` · `test_build_registry.py`, `test_stream_fingerprint.py` arm.
H5a `workspace_slots.py` (slot document v1: declaration + `machines.<me>` accounting; tombstones; `report()` probes answering set/missing/unknown and NEVER a value; `authorized_roots_bound_here()`) + `workspace_slot_env.py` (private fill file, hard-excluded from sync, `secret_in_env` refusal) + `workspace_slots_sync.py` family (key-wise, three depths) + `paths.workspace_slots_path` + the store dir in the read-model fingerprint + `serve_rpc/workspace_slots.py::runtime.workspace.slots.show/.declare/.report` + `runtime.workspace.slot.bind` (writes through `write_machine_roots`) + `runtime.workspace.slot.env.set` (local verbs in `LOCAL_CONSOLE_METHODS`; `declare` gated on the realm publish right) + `harness workspace slots show|declare|bind|env-set|report` · `test_workspace_slots.py` (declare replaces the declared set and tombstones; bind writes the root and reports; the written document contains none of the fixture's env VALUES — grep pin; unbound ⇒ `slot_unbound_here` naming the binding machines; a hanging `--version` ⇒ `slot_probe_unknown`; no count limit — a 200-slot declaration round-trips), `test_realm_sync_workspace_slots.py` (two machines report one slot ⇒ union; a stale peer's removed slot loses to the tombstone), `test_peer_authorization.py` tier table + `realm_publish_denied`.
H5b `assigned_slots` on the persona-instance record (the authority; the launcher edits it from the Agent Console, never from Projects — owner correction) + `runtime.persona.instance.slots.set/.show` + `harness persona slots show|set` + `mission_chat_turn_context` loads, for each assigned bound slot, each of `context.files` (default `CLAUDE.md` AND `AGENTS.md`) as its own labelled `workspace_context` section (128 KB per file, no total cap, typed receipts for unbound/missing/too-large; content-dedup against the cwd chain) + workdir rung 2 = first assigned bound slot + `--agents-file` deprecated alias · `test_persona_instance_slots.py` (not-in-workspace refused; slot removal drops assignments; EMPTY ⇒ nothing loaded, never all; no count limit), `test_mission_chat_turn_context.py` arms (one slot with both files ⇒ two sections `<slot>/CLAUDE.md` + `<slot>/AGENTS.md`; two slots ⇒ four; a missing `CLAUDE.md` ⇒ receipt `missing`, the `AGENTS.md` section still loads; alias ignored with `superseded_by_assignment`).
H5c **SEAM** — `workspace_slots.env_overlay(cwd)` applied in upstream `tools/environments/local.py::_sanitize_subprocess_env` (one import, one call; contextvar set by the mission-chat turn beside the workdir; `path_prepend`, `env`, `.env` values from the file, `venv`) · `test_slot_env_overlay.py` (a command under a bound slot sees the slot's PATH head and keys; outside it sees none; a secret key never appears in the overlay from the record, only from `.env`; the seam row in `tests/fixtures/import_layers_grandfathered.json` if the layer gate needs it).
H4 `lanes_build.py` (announced + reclassification; `workspace_id`/`slot_id`/`env_source` through H5a; null + `slot_unresolved` before any slot exists) + `sources.build` sub-health + cost keys + `McpJobLane` dedupe + `build_rows.json` + stream goldens regen + contract ledger + README copy-status · `test_running_work.py` arms, `test_build_rows_fixture.py` (every unknown kind appears once; every `env_source` arm).
H6 `detect.py` reading H5a's bound slots + `process_unidentified` / `cwd_unreadable` / the restart unknowns narrowed by the slot's declaration + `scan_ms` into the sub-health and `parity.sections_ms` · `test_build_detect.py` over a fake process table (under-slot, outside, unreadable cwd, already-owned pid, cpu-stall, unparseable cmdline ⇒ indexed not shown, budget breach ⇒ typed with ms, 80 bound slots ⇒ still correct and the cost reported).
H7 `history.py` + `sweep.py` (stall-fail for agent/announced ONLY; detected MARKED; `build.ended`; history; gc) + serve boot `HERMES_BUILD_REGISTRY_DIR` export · `test_build_sweep.py` with a fake clock (queued never stalls; a detected build past the threshold is still `stalled` and alive — the kill mutation reds; agent-origin wakes its owner).
H8 `control.py` + `_cancel_build` + `serve_rpc/work.py::runtime.work.cancel/.restart` (restart spawns with the slot env overlay and `tool_paths`-resolved argv[0]; `env_source` on the new row) + `harness work restart` · `test_build_control.py` (each origin × declared mode; detected restart with no confirm; a restart under a bound slot carries `env_source: slot:<name>` and fewer `env_unobserved` keys than the row it re-ran; replay guard both doors), tier table.
H9 `mcp_job_wake` stops writing `qa_build` rows · `tests/tools/test_mcp_job_background_work.py` (route still bound, no row).
H10 **Phase B** — `workspace_slot_recipe.py`: derived steps materialised from the declaration, owner `command` steps (`run: on_setup_click | never_auto`), `ready` computation (any `unknown` ⇒ `ready: unknown`), `recipe.revision` merge, `runtime.workspace.recipe.set` (publish right) + `recipe.show` · `test_workspace_slot_recipe.py` (derived steps cannot be deleted, only annotated; `ready` truth table incl. the unknown arm; revision wins).
H11 **Phase B** — `runtime.workspace.slot.clone` + `runtime.workspace.recipe.run_step` (both local; clone and command steps spawn through `process_registry` as background `terminal` rows; clone success ⇒ `slot.bind` + `report`; auth failure ⇒ `clone_auth_required` with redacted stderr; no credential passed — pinned by asserting the spawned argv and env carry none) + `harness workspace slots clone` · `test_workspace_slot_clone.py` with a fake registry.

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

**OWNER 2026-10-04 (refinement): 4a–4e accepted (and the launcher's calls, including deleting the
console per-agent AGENTS.md picker). The folder model is refined:** (1) REPO SLOTS replace loose folders
— a workspace declares named slots (clone URL, default branch, toolchain + environment KEYS, `AGENTS.md`
role) that travel with the realm; each machine fills each slot (local path + that machine's environment:
toolchain paths, SDK, venv, env vars, `.env`); an agent is assigned slots, loads only those repos'
`AGENTS.md`, and its builds run with this machine's slot environment. (2) NO HARD LIMITS anywhere — the
only bound is what the machine can scan; keep the scan-cost metric visible; design for ~8 per workspace
without a cap. (3) Environment = typical dev env, PRIVATE to the machine, never synced, but ACCOUNTED FOR:
set / missing / unknown per key, never the value; secrets from that machine's `.env` or secure storage.
(4) NEW: the workspace owner's setup recipe ("image") — a joining machine sees a per-slot checklist (Clone
or Locate / Set up / "ready on this machine"), designed as part of the same data. → §3 rewritten (3.1–3.6),
§1 `slot` / `env_source` / `slot_*` unknowns, §5, §7, §9, §10 (H5a/H5b/H5c Phase A; H10/H11 Phase B).

**OWNER 2026-10-04 (correction): the WORKSPACE (launcher Projects / workspace screen) owns the repo
slots — which repos exist, each machine's path and environment — and does NOT assign agents. ASSIGNMENT
lives in the AGENT CONSOLE, per persona instance: the instance picks which of the workspace's slots it
uses. An instance's assigned slots load each slot's CLAUDE.md AND AGENTS.md, each as its own section. The
console's per-agent picker is NOT deleted: it is REPLACED IN PLACE by a slot picker, migrating today's
per-agent AGENTS.md pick to the matching slot. hermes H5b stays the authority; only the launcher editor
moves.** → §3.1 `context.files`, §3.3, §3.6 (3), §10 H5b; the launcher plan §4 drops its agent × slot
matrix and keeps a read-only "used by" count.

**OWNER 2026-10-04 (example): the motivating case is a BACKEND agent and a FRONTEND agent as two persona
instances in the SAME workspace, each assigned different slots (backend vs launcher), loading only their
own slots' CLAUDE.md + AGENTS.md. (a) A slot may be assigned to several instances at once (a shared
contracts/docs repo) — assignment never moves a slot away from another instance; (b) every build row
carries `workspace_id`, `slot_id` and the starting persona instance (when known; else a typed unknown) so
Activity can say which agent's build it is.** → §1 `started_by_instance` + `starter_unknown`, §3.3, H4 and
H5b tests (two instances, one shared slot; a build row names its starter).

**New calls the refinement raises** (each with the recommendation; the plan is written to it):

- **8a. Who may edit a slot declaration and the recipe.** hermes has no "workspace owner" role; what it
  has is the realm PUBLISH right (`realm_sync.git._authorize`, backend-decided membership). *Recommend the
  publish right now*, evaluated by `slots.declare` / `recipe.set`; a finer per-workspace owner role is a
  backend row (the realm membership payload would carry it) and is not needed to ship Phase A or B.
- **8b. How Clone authenticates.** The machine's own git credential helper (no credential in hermes),
  with `clone_auth_required` as the typed failure — or generalise the realm's launcher-brokered
  `http.extraHeader` seam into a per-host credential now? *Recommend the machine's git, now*; the brokered
  per-host credential is Phase C, because it is a backend feature (per-host token minting) before it is a
  hermes one, and the realm seam already shows the exact shape it would take.
- **8c. Locate onto a checkout whose remote does not match the declaration.** Refuse, or bind with a typed
  warning? *Recommend bind with `remote_mismatch` as a typed warning that stays on the slot's report*: a
  fork or a mirror is a legitimate fill, and refusing would make the operator lie to the declaration.
- **8d. Owner `command` steps (e.g. `flutter pub get`) — run automatically after Clone, or only on click?**
  *Recommend only on click* (`run: on_setup_click`), each as a visible background `terminal` row under the
  slot env; `never_auto` is the only other value. Automatic post-clone execution of realm-synced commands
  is remote code execution by publish right, and the step list is synced.
- **8e. Does the slot environment apply to ALL of an assigned agent's commands or only to builds?**
  *Recommend all commands whose cwd is under the slot* — one rule, applied at one seam, no second
  classification; "a build" is only the recognizer's label for some of those commands.
- **8f. Where "ready on this machine" renders first.** Projects home (the editor) with a readiness chip in
  the Mission Control scope selector, or the scope selector as the primary? *Recommend Projects home
  primary + the chip*: setting up is editing (Locate, env values), and Projects is where the editor lives.
- **8g. Slot names and machine-root names share one namespace** (`[A-Za-z0-9_]+`, `roots.<slot>`). A
  workspace declaring a slot whose name an operator already bound by hand adopts that root as its fill
  (§3.6). *Recommend adopt, and report it* (`adopted_existing_root` in the first report), rather than
  refusing the name — it is the migration path for every `${roots.eternia_launcher}` config in use.

One deviation from the row's wording, stated: "the `mcp_job` row folds into this kind" is done for
the QA build (§8); the `mcp_job` KIND is kept for MCP jobs that are not builds, so a future non-build
server job still has a row.
