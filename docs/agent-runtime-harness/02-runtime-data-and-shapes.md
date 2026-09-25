# 02 — Runtime Data and Shapes

Where runtime state lives, what shape it takes, and which artifact is authority
for which question. Three storage families answer three different questions: an
append-only **event log** that owns ordering, a tree of **atomic JSON stores**
that own durable entity state, and per-profile **SQLite** that owns chat
sessions. Everything a surface reads is a *projection* over those three — the
snapshot core — and every projection is rebuilt, never incrementally maintained.
Chat is the only lane; the goal/task mission lane was removed 2026-07-30.

---

## The store root

`paths.store_root()` (`agent_runtime/paths.py:8`) resolves the runtime root —
live, `X:\Eternia\.hermes\agent-runtime`. Every durable JSON write in this tree
goes through `utils.atomic_json_write` (stage a temp file, `os.replace` it into
position). That discipline is what makes the stat fingerprint below sound: a
rename always moves the target's mtime, even for a byte-identical rewrite.

Directories present in the live root, with the module that owns each:

| Path | Owner | Shape |
| --- | --- | --- |
| `events.jsonl` | `agent_runtime/events.py`, `paths.py:240` | the base-0 slice — the live file until the first rotation, **sealed** after it (live: `end_offset` 81417412) |
| `events_archive/` | `agent_runtime/event_rotation.py` | where every post-rotation slice is minted (`:258`) — including the **live, actively-appended** one (live: `events.81417412.jsonl`); sealed slices here are immutable and offset-load-bearing |
| `events_manifest.json` | `event_rotation.manifest_path()` | slice table (below) |
| `persona_instances/` + `_archive/` | `paths.py:20,24` | one `personainst_*.json` per instance |
| `persona_assignments/` + `_archive/` | `paths.py:37,41` | persona↔channel bindings |
| `persona_chat_mint_receipts/` | `paths.py:45` | durable idempotency receipts for server-minted chat roots |
| `persona_chat_leases/`, `persona_chat_clarify_tickets/` | `agent_runtime/persona_chat_continuity/mint_receipts.py::PersonaChatMintReceiptStore,1236` | per-chat leases and clarify tickets |
| `mission_chat_turns/` + `_archive/` | `mission_chat_turns/storage.py:33-42` | one `<safe_session_key>.json` + `.lock` per chat |
| `mission_chat_steer/` | `mission_chat_steer.py:328` | per-session steer drops |
| `tool_turn_context/`, `queued_skills/` | `tool_turn_history.py:132`, `queued_skills.py:16` | per-turn tool context; skill inbox |
| `prompt_observability/` | `paths.py:450` | one `ctx_<id>.json` per captured prompt context |
| `prompt_observability_catalogs/` | `paths.py:454` | content-addressed `<hash>.json` skill catalogs, written iff absent |
| `prompt_observability_index.json` | `paths.py:468` | latest-pointer cache; **never authority** — a corrupt index falls back to a directory scan |
| `agent_create_reservations/` | `paths.py:54` | recorded-progress receipts for `runtime.agent.create` |
| `boards/`, `office/`, `workspaces/`, `realms/`, `agents/` | `paths.py:81,132,73,77,228` | Mission Board / Office / topology entities |
| `levels/` | `paths.py:302`, `agent_runtime/level_sync.py` | one `<workspace token>.json` per workspace LEVEL — the launcher's `SceneSerializer` bytes VERBATIM. hermes validates only that it is UTF-8 JSON carrying a `version` and reformats nothing; realm-synced whole-document (adopt / converge / keep-local / HOLD) |
| `flow_graphs/` | `checkpoint.py:62` | checkpoint flow graphs |
| `realm_sync/`, `realm_sync_state/` | `realm_sync/git.py` (`_sync_repo_path`), `realm_sync/sidecar.py` (`realm_sync_sidecar_path`) | per-realm git worktrees + sync state |
| `serve_read_model/` | `core_cache/vocabulary.py:86` | the persisted snapshot core (below) |
| `serve_instances/` | `serve_registry.py` (`SERVE_INSTANCES_DIRNAME`) | one `<pid>.json` per live serve, one `<pid>.ended.json` per serve that ended, one `<pid>.stderr.log` per `--service` runtime (below) |
| `deleted_archive/`, `migration_backups/`, `wt_reaped_patches/`, `locks/` | `paths.py:302`, `default_scope.py:552`, `delivery_directive.py:65` | archive-never-delete and lock trees |

`paths.py` also declares `runs/`, `runtime_instances/`, `incidents/` and
`prompt_observability_archive/`. None exist in the live root — they are created
on first write, and a store with no such write has no directory.

One more path helper resolves to a file that can no longer exist:
`paths.snapshot_path()` → `snapshot.json` (`paths.py:275`). Its writer was
deleted at Stage 6 (2026-08-22) with the read-model lane, so the helper now
answers *where a legacy copy would be* rather than where a live file is. It is
kept deliberately: without it, a store that ran `harness snapshot` before the cut
has an orphan nothing in the tree can name. `read_model.db` was the other such
file and has no helper at all any more — `ReadModel` is deleted.

### serve_instances — the row, the end-reason sidecar, and the service log

Three file shapes, one directory. `<pid>.json` is the REGISTRY ROW: written at
boot, removed on any clean exit, classified at read time by
`list_serve_instances` (see `04-boot-and-lifecycle.md`).

`<pid>.ended.json` is the END-REASON SIDECAR (RL-16, 2026-09-05,
`serve_registry.py` "the end-reason sidecar"), written on the way out through
the same `write_json_atomic` helper the row uses:

```json
{
  "reason": "drained",
  "at": "2026-09-06T01:26:35.245Z",
  "boot_id": "1cb3ba7986944cff9968e67f7124bb67",
  "pid": 39584
}
```

Four keys, no `schema_version`: a fifth would be a fact about a process that no
longer exists to be asked about it. The vocabulary is CLOSED — `drained`,
`shutdown_op`, `stdin_eof`, `ctrl_close`, `ctrl_c`, `sigterm`, `logoff`,
`unknown_exit`, plus the one open-ended `uncaught:<ExceptionTypeName>` — because
the launcher's runtime sheet switches on it; a word the recorder does not
recognise is written as `unknown_exit` rather than passed through to an
operator's screen. Which ending writes which word is tabulated in
`04-boot-and-lifecycle.md`.

Three properties are load-bearing:

1. **It is a separate file** because the row is REMOVED on a clean exit and the
   reason has to outlive that removal.
2. **Absence is a reading.** `TerminateProcess` (a `taskkill /F`, a Job kill)
   runs no code in the target and writes nothing, so a stale row with no
   sidecar says *something killed this without asking* — the launcher words it
   `ended=absent`. Nothing may write a placeholder for an end it did not
   observe.
3. **Every reader of this directory filters the suffix.** `list_serve_instances`
   is the single scan the rest of the tree is built on (`resolve_socket_target`
   → `harness serve connect` and the launcher's `local_serve_attach`,
   `prune_stale_serve_instances`, `harness status`'s `serves=` count), and a
   sidecar read as a row is a pid-less record that classifies `unknown` — the
   fail-safe direction, and therefore silent. Since RL-19 the filter is a tuple
   (`_NON_ROW_SUFFIXES`), and the `.stderr.log` below is excluded twice over: it
   is not a `.json`, and it is named there anyway.

Retention is a boot-time floor: `prune_serve_ended` keeps the newest
`SERVE_ENDED_RETENTION = 20` by the record's own `at` (never mtime — a copied or
restored store's mtimes say when it was moved), because nothing ever consumes a
reason. It is blind to rows by construction.

`<pid>.stderr.log` is the SERVICE RUNTIME'S OWN STDERR (RL-19, 2026-09-06,
`serve_registry.py` "the service runtime's stderr"). Written only under
`--service`, opened by `open_serve_stderr_log` at boot — line-buffered UTF-8,
truncated per pid, never closed — and carrying one header line before anything
the runtime says:

```
# harness serve --service pid=8476 boot_id=e64d4601872544e694530de3b34586b0 build=f7b89826eb28eb825a2c99029887b857c01ce8f2 started=2026-09-06T09:55:48.649Z
```

It exists because RL-17 hands the launcher's runtime three `DEVNULL` handles: a
pipe nobody reads is a runtime that blocks on its first full buffer (the older
defect), and the price was that everything it wrote to stderr went nowhere.
Measured 2026-09-06: an uncaught fault in a serve child leaves NO traceback on
any channel — the harness dispatch turns it into an error envelope the `--ndjson`
serve never emits — so `serve_loop`'s uncaught arm writes the traceback into this
file itself, beside the `uncaught:<Type>` the sidecar records. Two records, one
death: the reason and the cause, joined by `boot_id`.

Not a contract and not parsed — the header is read back for one purpose only,
ordering the retention. `prune_serve_ended` floors this family at the same
newest-20, SEPARATELY from the reasons (pooling them would let twenty service
boots evict every reason a non-service serve wrote). A non-service serve writes
no log at all: its parent is holding its stderr pipe and reading it as frames.

#### Who removed a row: `serve_registry_pruned` (RO-3, 2026-09-06)

The boot prune (`serve_registry.prune_stale_serve_instances`, called once from
`serve_loop` right after this runtime registers itself) was this directory's one
silent writer. It reported only in aggregate — `serve_instances_pruned`, and only
when the count was non-zero — so the question the 2026-09-06 field run actually
asked, *who removed the row for pid 43244 and when*, had no answer on any channel
while `SocketOwnerLock`'s takeover and the end-reason sidecar each had one.

It now emits one event per row it ACTED ON, through the caller's sink (the serve
passes `_service_log`, so the line lands in `<pid>.stderr.log` under `--service`
and reaches the supervisor as an ordinary `stderr` frame otherwise):

```json
{"event": "serve_registry_pruned", "action": "removed", "pid": 43244,
 "reason": "stale_dead_pid", "classification_reason": "pid_not_running",
 "by_pid": 11728, "row_boot_id": "1cb3ba79...", "boot_id": "e64d4601..."}
```

Four things are load-bearing, and each is a rule a neighbouring lane already
follows:

* **`action` is three words** (`SERVE_REGISTRY_PRUNE_ACTIONS`): `removed`,
  `refused` — a recycled or unclassifiable row the prune deliberately KEEPS, the
  ruling's "and what it refuses" — and `remove_failed`. A deletion count cannot
  carry the middle one, and a surviving recycled pid is exactly what an operator
  wants told.
* **The vocabulary is `classify_serve_instance`'s, not a second one.** `reason`
  is the classification verbatim (`stale_dead_pid` / `stale_recycled_pid` /
  `unknown`) and `classification_reason` its finer word — the same two keys the
  aggregate report's rows already carry.
* **A `live` row says nothing.** That is this boot's own entry on every boot, and
  a line every boot is how a channel stops being read. The pruner's OWN row,
  matched by `boot_id`, says nothing whatever it classifies as. Its command
  line is only a hint, and under pytest, or in a checkout whose path lacks
  `hermes`, it reads `cmdline_not_serve_like` (2026-09-24).
* **`boot_id` is the PRUNER's**, so an event joins that boot's `ready` frame the
  way `serve_instances_pruned` does; the pruned row's own boot rides as
  `row_boot_id`. Best effort throughout: a sink that raises changes nothing about
  what the prune removed or kept.

Ordering moved with it: `open_serve_stderr_log` is now armed BEFORE the prune,
not after. Armed after, a `--service` runtime's verdicts went to the `DEVNULL`
stderr RL-17 hands it — which is the silence this event exists to end. The real
`--service` boot that removes a planted dead row and leaves the line in its own
log is `tests/agent_runtime/test_serve_socket_child_e2e.py::test_a_service_boots_and_writes_what_its_prune_removed_into_its_own_log`.

---

### mission_chat_turns

One file per chat session, `mission_chat_turns/<safe_session_key>.json`, holding
that session's `{client_message_id: record}` map, plus a co-located
`.lock` (`mission_chat_turns/storage.py:30-41`). Concurrent turns in *different* chats
never contend. The filename is a sanitized 80-char prefix plus a 12-char sha256
suffix, keeping the total under the Windows `MAX_PATH` budget
(`mission_chat_turns/storage.py:52-57`). The pre-2026-07-17 single-file monolith is
split once on first read/write and renamed to `mission_chat_turns.legacy.json`,
never deleted — that file is still on disk live. Retention is
`_RETENTION_MAX_TURNS_PER_SESSION = 100` turns per session (`:72`, applied
`:800-806` inside the per-session lock), which must stay comfortably above the
projection's displayable tail — `MAX_PERSONA_CHAT_MESSAGE_TAIL = 40` in
`agent_runtime/persona_chat_history/vocabulary.py` — or a displayable agent row loses its
`turn_elements` (`:320`); plus an opportunistic session-file GC under
`mission_chat_turns.gc.lock`. `_MAX_ELEMENTS = 80` (`:65`) is a DIFFERENT bound:
it caps the `elements` list inside ONE turn record (`_safe_elements`, `:1272`),
not the turns a session keeps. Live counts (2026-08-22): 50
session files, 234 locks, beside 18 persona instances and 19 prompt contexts.

---

## The event log is the ordering authority

`event_offset` is a **byte position**, and every watermark in the runtime is one.
`parity.events_watermark` (`agent_runtime/parity.py:284`) reads it via `stat`, in
O(1), without scanning the log.

**An unreadable log yields `None`, never `0`** (`parity.py:244-256`). Zero is the
single most damaging value the field can carry: every reader treats it as a real
position, so a swallowed stat error replays the entire log as fresh activity.

`read_model.snapshot_watermark` used to restate this rule on the write side and
was deleted with its module at Stage 6 (2026-08-22). The rule did not go with it
— it is a property of the producer, and `parity.events_watermark`'s docstring is
now its only home, which is why that docstring states the argument in full rather
than pointing at a neighbour.

### Rotation preserves logical offsets

`agent_runtime/event_rotation.py` seals slices in place rather than renaming or
truncating, because on Windows `os.replace` of a file with an open handle raises
`PermissionError` and a paused `iter_from_offset` generator holds exactly such a
handle across yields (`event_rotation.py:33-44`).

    logical_offset(x) = slice.start_offset + byte_position_within(slice)

The manifest lists sealed slices as `(file, start_offset, end_offset)` plus one
open-ended live slice carrying `base_offset` (`SliceRef`,
`event_rotation.py:76-86`). `offset_reads()` (`:190`) resolves which slice a
logical offset lives in and seeks there; `log_end_offset()` (`:181`) is
`live.start_offset + live_size`. Every existing reader keeps working unmodified
and stored watermarks resolve exactly as before. With no rotation the manifest is
absent, the single live slice is `events.jsonl` at base 0, and logical == byte
offset. Live cap: `DEFAULT_ROTATION_CAP_BYTES = 16 MiB` (`event_rotation.py:63`),
overridable by `event_log.rotation_cap_bytes` or the env equivalent. Live
manifest, verbatim:

```json
{"version":1,"slices":[{"file":"events.jsonl","start_offset":0,"end_offset":81417412}],
 "live":{"file":"events_archive/events.81417412.jsonl","base_offset":81417412}}
```

`CachedEventLog` (`events.py:323`) reads the log once per build and serves every
`for_task`/`for_session`/`tail` from the cached lines, concatenating slices
oldest-first so the flat cumulative byte position *is* the logical offset. It is
a point-in-time view by design: appends made during a build are not reflected,
and the next builder observes the changed size/mtime and loads a fresh view.

---

## SessionDB — `state.db`

`hermes_state.SessionDB` owns chat sessions and lives at
`get_hermes_home() / "state.db"` (`hermes_state.py::_default_db_path`) — **per profile**,
not in the store root. Live: 10 of the 11 profile directories under
`.hermes/profiles/` carry one — `profiles/unbounded/` has none — plus a root
`.hermes/state.db`. The path is resolved at
call time, not at import: freezing it at import let a test that only set
`HERMES_HOME` write into the developer's live profile
(`hermes_state.py::_ensure_test_isolation`).

Journal mode is `WAL` by default, resolved by `resolve_journal_mode()`
(`hermes_state_wal.py::resolve_journal_mode`) from `database.journal_mode` in `config.yaml`.
`hermes_state_wal.py::apply_wal_with_fallback` falls back to `journal_mode=DELETE` when the
filesystem cannot support WAL's shared-memory and byte-range locking (NFS,
SMB/CIFS, some FUSE, WSL1) — and it treats a `PRAGMA journal_mode=WAL` that
returns a non-WAL mode *without raising* as a refusal, because that
PRAGMA is a query-that-sets. The upstream guard also refuses unsafe WAL use
with vulnerable SQLite builds; `hermes_state_wal.py::is_sqlite_wal_reset_vulnerable`
and `apply_wal_with_fallback` own that decision. Deployment must verify the
linked SQLite version rather than disabling the guard. The snapshot's `persona_chat` section reads this
database through `chat_session_scope.open_chat_session_db` (`agent_runtime/snapshot/details.py::_default_persona_session_db`).

---

## The snapshot core

A **core** is one dict: the whole read model for the runtime, built by
`build_snapshot()` (`snapshot/build.py:49`) from the three storage families above.
Top-level sections include `summary`, `runtime_default`, `runtime_config`,
`migration`, `prompt_observability`, `repo_scopes`, `workspaces`, `realms`,
`boards` / `boards_unreadable`, `offices` / `offices_unreadable`,
`running_work`, `persona_chat`, and `parity`.

Seven sections are timed and land in `parity.sections_ms`: `events`,
`agents_readiness`, `prompt_observability`, `boards_offices`, `running_work`,
`persona_chat`, `parity` (`snapshot/sections.py:89-218,1030,1097`).

`parity` is the frame's self-describing provenance envelope
(`snapshot/envelope.py:329-357`), keyed in build order: `contract_version`,
`generated_at`, `redaction_mode`, `redaction_observed`, `build_ms`,
`sections_ms`, `snapshot_bytes`, `event_log_bytes`, `projection_age_ms`,
`watermark`, `runtime_root`, `resolution`, `profile`, `capabilities`,
`freshness`, `completeness`, `drops`, `warnings` — plus `core_source` and
`frame_source`, stamped afterwards by the core cache and the read-model
resolver.

**Generations and coalescing.** Builds inside a process are numbered; concurrent
callers coalesce. The coalescer is deliberately strict — a caller arriving while
a build runs waits for the *next* build, never the in-flight one, because an
in-flight build began earlier and may miss writes the caller already observed.
`accept_inflight=True` opts out, and both non-test callers are the same
boot-hydrate lane — `hydrate_frame` (`agent_runtime/stream/frames.py::hydrate_frame`) and the `stream_frames`
boot job that drives it (`agent_runtime/stream/session.py::stream_frames`) — because the hydrate's payload carries its own
watermark and the stream tails from exactly that offset
(`snapshot/build.py:48-62`). Roles:
`BUILD_ROLE_LED` / `RODE` / `SHARED_NEXT` / `CACHE` / `REUSED`
(`snapshot/receipts.py:176-205`).

`agent_runtime/demote_core_reuse.py` adds a second, *sequential* saving: one
demote build's core reused by the next demote build **at the same event offset**.
Its claim is about position, not time — which is what makes it safe where riding
an in-flight build is not.

### The build receipt

One line per **actual** build, emitted by the caller that ran it
(`_log_snapshot_build_core`, `snapshot/build_log.py:33`); every other line about a build
is a *wait*. Format, pinned:

```
snapshot_build_core role=%s caller=%s generation=%s build_ms=%s offset=%s sections_top=%s pid=%d
```

`pid` rides last deliberately — it is the join key between a launcher boot
receipt and a serve's `agent.log`. `sections_top` is the three most expensive
sections as `name:ms`, sorted cost-descending then by name, so consecutive boots
of the same shape print the same string and a diff means the shape moved
(`snapshot/receipts.py:254`). A sibling receipt splits the misleading `agents_readiness`
number into its two halves: `snapshot_agents_readiness walk_ms=%d
tool_visibility_ms=%d pid=%d` (`snapshot/build_log.py:88`). The often-quoted numbers for
that split — 4,001 ms first build (3,054 tool visibility / 947 walk) against
183 ms steady state (36 / 146) — are the **bench from `25cd488d33`'s commit
body**, 5 personas against the operator's profiles root, and appear in no live
log. The live 2026-08-22 splits are `walk_ms=2133 tool_visibility_ms=2232` on
the cold boot (pid 30588) and `walk_ms=769 tool_visibility_ms=26` warm
(pid 32164).

**The walk binds each persona's profile CONTEXT-LOCALLY.**
`profile_readiness_for_persona` enters `profile_context.persona_profile_scope`,
not the env-exporting `persona_profile_context`: it installs the ContextVars
(`set_hermes_home_override`, `set_hermes_auth_home_override`, the head-home
recording) and writes **no** `os.environ`. That matters because this walk runs
on the snapshot builder thread every 2–4 s in the same `harness serve` process
that hosts chat turns, and takes no `profile_runner._WORKDIR_LOCK` — so under
the old env mirror every ambient `get_hermes_home()` reader on every other
thread resolved the WALKED profile for the width of the walk. Measured cost of
that (2026-08-23 turns): a bundle-free turn built context in 453 ms, while turns
overlapping a walk billed 1,796 / 2,343 ms with `visibility_bundle_builds=3/6`,
because `chat_lane_bundle`'s key carries the ACTIVE `config.yaml`'s
`(mtime_ns, size)` and the race moved *which file that was*.

It is sound because the walk reaches no env-pinned reader: it spawns no
subprocess and drives no plugin; its skill, config and machine-root reads
resolve through `get_hermes_home()` (ContextVar-first) or an explicit path;
`get_default_hermes_root()` collapses to the same answer either way, because a
binding's `profile_home` is always `<root>/profiles/<name>`; and the one raw-env
reader it does reach — `hermes_cli.auth._global_auth_file_path`, on the provider
probe — now reads `agent_runtime.profile_home.get_hermes_auth_home()`, which resolves the
ContextVar first and the `HERMES_AUTH_HOME` env var second. The named residue is
`HOME`: POSIX `os.path.expanduser` has no context-scoped hook, so a `~` expanded
under the binding (a `skills.external_dirs` entry, the `~/.codex` / `~/.qwen`
singletons) resolves to the process home rather than `<profile>/home`. Inert on
native Windows, where `expanduser` consults `USERPROFILE`.

**So does the prompt-observability section**, and it is the more expensive half:
`snapshot_prompt_observability` enters a binding once per roster instance
(`mission_chat_prompt_observability`'s `skill_profile_context`), and that section
bills `prompt_observability:4520` against `agents_readiness:4366` on the
2026-08-22 cold boot. Same switch, same reason. This site also has a **second
lane**: `persona.chat_turn_message._cmd_mission_chat_message` calls the same function at
`observability_built`, *before* `profile_runner` installs its own locked
binding — so under the env mirror a chat turn was rebinding the process for every
concurrent turn and for the builder, not only the other way round. Both lanes are
fixed by the one switch.

Its branch audit lands in the same place as readiness, with one axis doing more
work. Reached from inside the binding: no subprocess, no plugin dispatch, and no
`hermes_cli.auth` path at all (this block runs no provider probe, so the
`HERMES_AUTH_HOME` reader is not even reachable here). Skill discovery resolves
through `get_hermes_home()` — `skills_tool._skills_dir`, `skill_utils.get_skills_dir`,
`get_config_path` — and the per-persona hash check takes an **explicit**
`hermes_home=` from `resolve_persona_profile`, never the ambient one. The realm
rows are a sidecar file read (`read_realm_sync_sidecar`, "zero git calls in the
snapshot"), and `paths.store_root()` collapses because the env mode exports the
root it resolved *before* the override, which is what the ambient env resolves to
anyway. The identity-prompt, operative-rules, SOUL-overlay and profile-context-file
reads all run **outside** the binding and are unaffected either way.

The one axis that carries weight is `get_default_hermes_root()`, which reads
`HERMES_HOME` raw and is reached five ways from inside the binding
(`get_shared_skills_dir`, `hermes_cli.profiles.get_profile_dir`,
`skill_install.harness_skill_destination`, `skills_inventory.build_shared_catalog`,
and `skill_utils.skill_source_kind` per resolved candidate). It **collapses**, and
the reason is structural rather than incidental: a binding's `profile_home` always
comes from `get_profile_dir` — `get_default_hermes_root()/profiles/<name>` — and
that function is a fixed point over exactly those paths (a path under the native
home maps back to the native home; a custom `<root>/profiles/x` maps back to
`<root>`; with `HERMES_HOME` unset the profiles root *is* the platform default, so
the written home lands under it). `get_shared_skills_dir`'s docstring states the
same property for its own case. It is pinned by
`test_the_profiles_root_survives_dropping_the_HERMES_HOME_write`, parametrized
over all three ambient layouts, rather than left as an argument in prose.

---

### The contract version ledger

Relocated verbatim from the comment on `contract_version` in the parity envelope (`agent_runtime/snapshot/envelope.py::parity_envelope`) by lane R3 (rule 7 / ruling Q3): every contract-version bump and every KEPT ruling, and the two-part rule that decides them. A change to the snapshot contract adds its entry HERE.

S8 (DEEP SLIM inside live rows): the same history-eviction knife one
level deeper. Goal rows become compact HEADS (heavy detail →
``harness goal detail``); the ``skills_catalogs`` table leaves the frame
(rows keep ``*_ref`` hashes → ``harness skills catalog --hash``); the
``runs`` map keeps only ACTIVE runs (history → ``harness run list``);
``persona_assignments.recent`` and stale ``chat_contexts`` rows are
evicted to pointers; archived operator channels become pointer stubs
(transcript → ``harness task history``). Every eviction is accounted
(typed ``*_ref`` / ``detail_ref`` / ``evicted`` markers), never a silent
absence. S2/S3/S4 shape unchanged. Launcher pin
(kSupportedMissionContractVersion) moves in lockstep.

44 (snapshot residue-slim R1/R2/R5a, 2026-07-17; 43 was taken by the
office-realm-sync landing): the dead ``capabilities`` /
``observability.capabilities`` / ``event_contracts`` / ``blueprints`` /
``blueprint_runs`` frame sections (zero readers in all three repos) are
DELETED; ``persona_instances`` / ``agents`` rows evict the heavy
tool-detail payloads behind a typed ``visibility_ref`` (fetched via
``harness persona-instance detail``) and ``agent_hud_state`` is RETIRED;
45 removes mission rows while retaining chat/runtime graph projections.

46 (S47, 2026-08-01): two emitted fields whose values no code path
could move leave the frame — ``runtime_config.role_envelope`` (the
config block S44's store-family cut left governing nothing, shipping
``enabled: true``) and ``workspaces[].goals`` (a count over an
always-empty seed). Field removals, not section removals, but the
S9/S10 rule is the same: anything that leaves the wire bumps, and the
Launcher pin moves in the same wave.
47 (S56, 2026-08-01): one coherent wave, one bump. Leaving the frame:
every `worker_session` trace (the store is deleted — `status`'s
`worker_sessions` + `active_worker_sessions` rows, the
`observability` worker signals/rows, `dirty_state`'s four worker
counters, `persona_instances[].active_worker_session_id`); the
constant-by-construction repo-bundle wires `repo_bundles` /
`repo_bundle_closeout` / `bundle_queue` / `repo_locks` and the
duplicate `lanes` (doc 19 filed the last two as asserted-constant
debt); `production_envelope` (hand-written prose, several claims false
against this tree) with `swarm` / `swarm_budget`; and SEVEN
`runtime_config` blocks that no production code read —
`continuous_role_sessions`, `enterprise_worker_sessions`,
`normal_worker_flow`, `repo_bundle_routing`,
`simplified_agent_contract`, `swarm`, plus three of the four
`supervision` fields. The persona-instance roster stops being gated on
`enterprise_worker_sessions.persona_instance_runtime` and ships
unconditionally. The Launcher pin moves in the same wave.

48 (S57, 2026-08-01): the S56 reader-gate's `UNRULED_DEBT` bucket is
emptied and the last whole store of the repo-bundle lane goes. Leaving
the frame: TWENTY-NINE `runtime_config` scalars with no production
reader (the `daemon_*` family, the four `live_run_*` budgets, the four
`liveness_*` knobs, the three `artifact_storage_*` watermarks, the two
mission ceilings, the two neko caps, `heartbeat_ttl_seconds`,
`max_actions_per_tick`, `root_node_mode`,
`preferred_goal_execution_mode`, `scope_wait_deadline_seconds`,
`run_lease_seconds`, `tool_wait_timeout_seconds`,
`child_progress_min_interval_seconds`, `deploy_timeout_seconds`) —
all VERIFIED present on the live frame at contract 47, so this edits
the wire rather than only the code — together with the validator arms
that range-checked them, and `migration.counts.repo_bundles`, the last
wire trace of the `RepoBundleStore` deleted whole in the same wave. The
Launcher pin moves in the same wave.

49 (S58, 2026-08-01): ``runtime_config.migration`` was a byte-for-byte
duplicate of the authoritative top-level ``migration`` block. The
Launcher reads neither copy; its supported-contract pin moves in
lockstep with this emitted-field removal.
51 retires the last task/proof migration-count rows and the
run-summary conversation source. The legacy contract-hash wire names
remain compatibility aliases for the event-only registry.

52 (WP-H1, 2026-08-03) ADDS the ``running_work`` section — the first
additive move in several waves, and the reason the pin still has to
travel: the Launcher's ``MissionSnapshotEnvelope.health()`` requires
EXACT equality, so an additive section that arrives under an unbumped
version would be invisible rather than merely unread. The section
carries its own ``sources`` health block and a ``completeness``
accountant row of the same name. The Launcher pin
(``kSupportedMissionContractVersion``) moves to 52 in WP-L1, and the
live venv is refreshed only AFTER that lands — refreshing first
fail-closes the console with a ``newerContract`` banner.

52 KEPT (WP-H2, 2026-08-03) — ``running_work`` gained its sixth lane,
``dispatch``, and this entry records WHY that did not bump. The rule
this ledger actually states is not "any wire change bumps"; it is
(a) anything that LEAVES the wire bumps (the S9/S10 rule, cited at 46),
and (b) an ADDITION bumps when it would otherwise be "invisible rather
than merely unread" — the 52 entry above, where the Launcher had no
parse for the new section at all. Neither applies here: nothing left
the wire, and 52 itself published ``dispatch`` inside
``RUNNING_WORK_KINDS`` with the stated intent that "the wire
vocabulary is complete from the first landing and a consumer does not
have to re-derive it when the lane arrives". What arrives is a sixth
key in a health MAP plus rows carrying a ``kind`` string the version
already declared, both of which a consumer pinned at 52 consumes. The
Launcher pin has also not moved to 52 yet (WP-L1 is pending), so the
section and its sixth lane reach the Launcher in the SAME wave either
way. The constraint this puts on WP-L1 is explicit and load-bearing:
parse ``sources`` as a map and ``kind`` as an open string. An
exhaustive five-lane enum switch would turn this ruling into a
fail-closed frame and would have needed the bump instead.

52 KEPT AGAIN (WP-L2 attribution, 2026-08-03) — the operator
conversation gained a ``harness_delivery`` message ``kind`` and a
typed ``delivery`` sub-block ({dispatch_id, notify_operator}) on the
row a dispatch DELIVERY turn produces. The same two-part rule answers
it: (a) nothing LEFT the wire — the row still projects role="operator"
with the same id/text/timestamps, so a consumer that ignores the kind
renders exactly what it renders today; and (b) it is not "invisible
rather than merely unread" — the Launcher's conversation adapter falls
through unknown kinds to a generic bubble BY DESIGN, and it parses
this one in the SAME wave (WP-L2 lands both halves). The 52 entry
above bumped because the Launcher had no parse for a whole new
SECTION; here the section, the message list and the row are all
pre-existing and already parsed. The constraint this puts on the
consumer is the same one the dispatch lane put there: conversation
``kind`` stays an OPEN string. An exhaustive switch over it would turn
this ruling into a fail-closed frame and would have needed the bump.

52 KEPT, THIRD TIME (WP-L2 review fixes, 2026-08-03) — the
``delivery`` sub-block gained ``state`` (the settled dispatch outcome)
and the ``running_work`` dispatch lane gained terminal ``error`` rows
for completions whose delivery was ABANDONED. Both are additions to
blocks a consumer already parses, on a ``kind`` it already knows, and
both are consumed by the Launcher in the same wave. The reason
``state`` had to be added at all is worth recording: without it an
``error`` dispatch — which ``pending_deliveries`` selects and delivers
exactly like a successful one — was distinguishable from success only
in the prose body, so a consumer would have had to sentence-match to
phrase an honest notification. That is precisely what the typed marker
exists to prevent, so the fix belongs on the wire rather than in the
reader.

53 (Activity ownership correction, 2026-08-04) REMOVES the
``mcp_server`` running-work source and its rows. A connected MCP
transport is reusable capability infrastructure, not a background
task: it can stay warm after the admitting turn settles and several
persona instances can share the same profile/server. It therefore has
no single truthful owner and must not make an idle runtime say
"1 running". Active calls remain visible on their owning chat turn's
tool trace. This is a wire removal, so the contract and Launcher pin
move together under the removal rule recorded at 46.

54 (S70 persona-instance wire prune, 2026-08-09) REMOVES six keys from
every ``persona_instances`` row. Two were duplicate ALIASES that
projected byte-identical values to the canonical key beside them —
``current_work_assignment_id`` (= ``current_assignment_id``) and
``attached_task_id`` (= ``current_task_id``); ``attached_task_id`` also
leaves the ``state_patches`` projection in this wave, because a patch
lane that kept emitting a key the full rebuild dropped would make the
two lanes disagree about the row's shape. Four were writer-less since
the worker/goal lanes died, with no consumer past a Launcher model copy:
``context_receipt_id``, ``compression_receipt_id``, ``tool_budget_used``,
``watchdog_warning_count`` (these four also leave ``PersonaInstance``
itself; ``serde._coerce`` ignores the stale keys still on disk).

Two fields the deferred-debt ledger grouped with them deliberately DID
NOT move, and the distinction is the point of this entry: writer-less is
not the same as reader-less. ``token_budget_used`` feeds the Launcher's
token-total fallback (``totalTokens ?? tokenBudgetUsed``) and
``last_heartbeat_at`` is read by the Launcher's roster-recency tiebreak
AND re-emitted on the Agent Gateway state frame AND read here by
``classify_orphan_persona_instances`` as the heartbeat HOLD. Dropping
either would silently retire a live consumer, so retiring them is a
reader-side decision that needs its own ruling — not a wire cleanup.
This is a wire removal, so the contract and Launcher pin move together
under the removal rule recorded at 46.

54 KEPT (running_work contract/ambient split, 2026-08-09) — the
``running_work`` section stops folding MACHINE-LOCAL state into its
per-source ``detail`` prose, gains a typed ``live_enrichment_error`` on
a source entry, and gains a sibling ``ambient`` block naming the
resolved background-work home. The two-part rule recorded at "52 KEPT"
answers it, and the FIRST part needs stating carefully, because a key
does stop appearing on some entries:

(a) Nothing LEAVES the wire. ``detail`` is not removed — it keeps its
key, its type and its documented meaning ("bounded operator detail,
WHEN hermes attached one"), and on the entries a consumer actually
renders it from (``unavailable`` lanes, where it has always been a bare
exception class name) it is byte-identical. Its presence was ALREADY
conditional on both sides: three of the five lanes ship ``ok`` entries
with no ``detail`` today, and the Launcher models it as
``_string(json['detail'], fallback: '')``. What changes is which values
an optional diagnostic takes on the ``ok`` entries of two lanes — not
the schema. That is categorically different from 46/49/53/54, each of
which deleted a key or a section a consumer modelled and could no
longer find.

(b) The additions are "merely unread", not "invisible". ``sources`` is
parsed as a MAP with named-key reads — the constraint the WP-H2 ruling
put on the consumer, for exactly this reason — so an unknown
``live_enrichment_error`` is ignored; ``ambient`` is a new sibling key
on a section the Launcher already parses field-by-field, so a
pinned-54 reader ignores it rather than fail-closing.

Why it had to move at all: the old ``detail`` concatenated contract
with ambient filesystem state, and the filesystem half was perturbed by
the projection's OWN lazy import (``_collect_chat_turns`` reaches a
tool singleton whose constructor creates ``state.db``), so the same
producer emitted two different strings for identical work depending on
import order. A wire field no consumer can rely on and no test can pin
honestly is worse than no field.

54 KEPT, THIRD TIME (EG-3.1, the persisted core, 2026-08-17) — the
parity envelope gains ``core_source`` (+ ``core_stale``) and the office
rows gain ``actors_unreadable``. The two-part rule recorded at
"52 KEPT" answers both, and the SECOND part needs stating carefully
because the fixtures are the evidence:

(a) Nothing LEAVES the wire. No key, no section, no value a consumer
models is removed or narrowed.

(b) Neither addition is "invisible rather than merely unread".
``core_source`` is emitted ONLY when a persisted core was available to
decide between (see ``core_cache.label_core``) — a build in a root that
has never held one answers no such question and stamps nothing, which
is why every committed producer fixture is byte-unchanged by this
landing. The precedent for the shape is one file over: ``read_model``
already stamps ``parity.frame_source`` under the same reasoning ("one
location, additive, no contract bump"), and the ``delta_patches``
hydrate marker is absent when its lane is off for exactly this
golden-stability reason. ``actors_unreadable`` is a new key on an office
row the Launcher parses field-by-field, alongside the
``actors_truncated`` it already ignores.

The STALE label deliberately reuses an existing field rather than
adding one: a stale-served core sets ``parity.freshness.state =
"stale"``, which ``MissionSnapshotEnvelope`` already parses and
``health()`` already maps to ``MissionSnapshotHealth.stale``. So the
honesty half of EG-3.1 needs no launcher change and no bump — an
unvalidated projection reads as stale on a pinned-54 launcher today.

54 KEPT (AX2, the writerless assignment lane, 2026-08-31) — THE FIRST
KEPT RULING OVER A DEPARTURE, written at length because rule (a)
recorded at 46 ("anything that LEAVES the wire bumps") is unconditional
on its face and this entry does not pretend otherwise. Three things
leave: the whole ``persona_assignments`` block (with S8's
``recent_ref`` eviction pointer), ``persona_instance_runtime
.assignment_store_enabled`` (constant ``true`` since it was written),
and top-level ``warnings``.

Rule (a) exists to stop ONE failure: a consumer that modelled a key
keeps parsing, silently receives nothing, and a real surface goes blank
with no signal. Here that failure is not merely unlikely — it is PINNED
ABSENT IN THE CONSUMER'S OWN SUITE. The launcher deleted every read of
the block in the same wave (``6bf48ba26``: the model, the decoder, the
roster-fold parameter and five always-null fields) and keeps
``mission_agent_instance_test.dart`` feeding a payload that still
CARRIES the block while asserting nothing in it reaches the instance.
``warnings`` never had a launcher reader at all — the bridge mapper's
forward list does not carry it, so it never reached
``MissionControlSnapshot.fromJson``, and its one code
(``agent_already_assigned``) is already a launcher tombstone row.

And the bump is the RISKIER move here, which is what settles it.
``MissionSnapshotEnvelope.health()`` requires EXACT equality, so 55
against a pinned-54 launcher is ``newerContract`` — and
``MissionFrameTrust`` maps that to ``mayWrite == false``: an operator
who cannot delete or place anything until the launcher's own pin lands.
Moving the number would spend a live operator write-gate to defend a
read that provably does not exist; keeping it means neither repo has to
move in lockstep at all.

What this entry does NOT license: a departure whose consumer-side
absence is believed rather than measured and pinned. The evidence
standard is the launcher's test, not the removal's tidiness. The
goldens still move and still have to be mirrored — see
``tests/fixtures/stream_frames/README.md``.

The number itself lives at module scope as ``SNAPSHOT_CONTRACT_VERSION``
(``agent_runtime/snapshot/context.py``) so that consumers derive it instead
of restating it.

## The core cache — `serve_read_model/`

`agent_runtime/core_cache/` persists the built core so the next process pays
**validation** instead of reconstruction. Its module docstring is the design
authority; this is the distillation. **The directory name is a historical trap:
it is not, and never was, the `read_model.db` described below** — that lane is
retired and this one is live.

**A pair is a core plus the fingerprint of every input the build read.** The
on-disk unit is a trio inside a generation directory: `core.json`,
`sidecar.json`, `entries.json` (`core_cache/vocabulary.py:87-100`). The sidecar carries
the digest and the cheap facts read on every consult; `entries.json` holds the
full stat set the digest summarises, in its own file so the cheap half of the
judgement does not pay for the diagnostic half. `live.json` is a pointer naming
the live generation and is **the one file whose replacement publishes a
write-back** (`core_cache/vocabulary.py:102-107`) — a pointer, not a directory rename,
because between two renames there is no live generation at all.

Live pair (2026-08-22 15:46), sidecar verbatim:

```json
{"build_stamp":"git:74702c193e…:clean","contract_versions":{"parity_envelope":1,
 "snapshot_contract":54,"stream_schema":1},"core_sha256":"8bdf4fe4…",
 "event_offset":90007293,"fingerprint":"37f5a746…","fingerprint_entries":2461,
 "fingerprint_home":"X:\\Eternia\\.hermes\\profiles\\base",
 "fingerprint_home_authoritative":true,"generated_at":"…",
 "runtime_root":"X:\\Eternia\\.hermes\\agent-runtime"}
```

**The fingerprint decides validity, full stop.** It is a directory-level walk of
`(path, mtime_ns, size)` triples — directory-level because a file that did not
exist at the last build has no previous triple to compare, and per-file because
replacing an entry does not move the containing directory's mtime on NTFS. An
event-offset key is refused for cause — but only half of that cause is still
measured. The design-era argument reads "the events section is 3 ms of a 5,485 ms
build" (`planned/core-cache-input-closure.md` (the relocated module docstring)); that figure is **historical**, and this document's
own live receipt disagrees with it — the cold build's `events` section is 842 ms,
its third most expensive. What carries the refusal today is the other half: two
shipped incidents came from writers that mutate durable state with no EventLog
event at all, which an offset key cannot see no matter how cheap it is.
`event_offset` **is** recorded in the sidecar — as a diagnostic only, never read
into the match decision (`planned/core-cache-input-closure.md` (the relocated module docstring)).

SQLite is the one mtime-blind case covered explicitly: a WAL commit that has not
checkpointed leaves `state.db`'s mtime untouched, so the `-wal` and `-journal`
siblings are fingerprinted beside it, under a mask that stops *reading* the
database from looking like *writing* it (`core_cache/vocabulary.py:554-607`).

**Demote** is the read-side outcome: a persisted pair that is not served. Every
demote emits `snapshot_core_cache core_source=rebuilt caller=… reason=…`; the ten
reasons are enumerated at `core_cache/vocabulary.py:147-179`. `absent` is deliberately *not*
logged, so a census must never read "no demote line" as "no demote". Read entry
point `core_cache.consult()` (`:3112`); write-back `core_cache.write_back()`
(`:1708`), one unit by MCF-21 — a torn trio is unrepresentable.

A stale-labeled core sets `parity.freshness.state = "stale"`, which the launcher
already maps to `MissionSnapshotHealth.stale`
(`mission_control_snapshot.dart`, `MissionSnapshotHealth`; the `declaredStale`
predicate that mapping reads is in the same file). **A cached or stale core never deletes,
never refuses a write, and never wins a conflict** — the 2026-08-15 mass archive
was a projection that had acquired store powers.

Two receipts name the ways this lane fails *quietly* rather than wrongly:
`fingerprint_refused` (a walk hit its entry bound, cache off for this install)
and `never_converged` (consecutive write-backs never agreed, so no later process
can be served the cache at all). `agent_runtime/core_cache_census.py` executes
the census rules as code, run by `scripts/core_cache_demote_census.py`.

---

## The parse cache

`agent_runtime/parse_cache.py` is process-wide and mtime-keyed, for hot
idempotent leaf loads — YAML config/meta files, skill frontmatter, file hashes. A
build re-resolves the same profile and skill tree several times per persona
(readiness plus four tool-visibility passes), and YAML scanning profiled as the
dominant snapshot cost. Keyed on `(path, mtime_ns, size)`, bounded at
`_MAX_ENTRIES = 4096`, self-clearing on overflow. A loader error returns the
default and is **not** cached, so a transient failure self-heals
(`parse_cache.py:42-60`).

---

## The read model — `read_model.db` — RETIRED 2026-08-22

**There is no second cache of the snapshot core.** `serve_read_model/` above is
the only one. The `read_model.db` lane (module, schema, projector, both CLI
verbs, `write_snapshot` and the `snapshot.json` boot cache) was deleted at
Stage 6 of the duplicate-implementation retirement — the full what/why record
is that stage's row in
[planned/duplicate-implementation-retirement.md](planned/duplicate-implementation-retirement.md)
and the `fac754194e` commit body; the s74 rows in
`tests/agent_runtime/test_tombstone_registry.py` enforce it. `harness snapshot`
calls `build_snapshot()` directly and still stamps `parity.frame_source` — now
always `"built"`, because removing an envelope key is a contract change and the
additive rule cuts one way only.

**What survives, and why each one is not an oversight** (this table is the live
truth a reader needs; the lane's name still appears in a live config file and
six committed wire goldens):

| Survivor | Why |
| --- | --- |
| `serve_read_model/` (`core_cache/vocabulary.py:86`) | the LIVE core cache. Never was the read model; the rename that would have de-collided the name is cancelled, because with the other one gone there is nothing left to collide with |
| `read_model.delta_patches` (`runtime_config.py`) | gates the live S7-A patch producer. Its YAML key path is cross-repo wire — the launcher's base seed writes it |
| `ReadModelConfig.enabled` / `.serve_snapshot_from_db` / `.db_filename` | reader-less, but on the snapshot WIRE via `asdict(cfg)` → `core.runtime_config`, in six goldens the launcher mirrors byte-for-byte. Deleting them is a contract bump plus a two-repo manifest change, not a grep-clean cut — see the Open row |
| `paths.snapshot_path()` | the one authority for where a legacy `snapshot.json` lives, so an orphan left by an older build is still nameable |
| `core_cache._EXCLUDED_STORE_ENTRIES`' `read_model.db` trio | a store written before the cut still holds those files; dropping the exclusion would fold them into that store's fingerprint |

**Naming trap, still live.** `CORE_CACHE_DIRNAME = "serve_read_model"` is the
core cache's on-disk home and has never had anything to do with the database
above. Anyone reading this domain cold meets the phrase "read model" in a
directory name whose contents are `core.json` / `sidecar.json` / `entries.json`.
The warning outlives the module it used to disambiguate from.

---

## Every build re-projects the store

There is no incremental projection lane. `build_snapshot()` walks the store
trees, scans the event log, and reads SessionDB on every build; caching happens
*around* the build (core cache, parse cache, coalescing, demote reuse), never
*inside* it as a delta. The cost is real and measured — cold boot 2026-08-22
15:46, live serve log:

```
snapshot_build_core role=led caller=prewarm generation=1 build_ms=11235 offset=90007293
  sections_top=prompt_observability:4520,agents_readiness:4366,events:842 pid=30588
```

Warm builds in the same process land at 1,948–3,733 ms (generations 18–22, same
log, 13:45–13:46). The `events` section is not the problem; the two walks are.

---

## Invariants

1. **`event_offset` is a byte position, and unknown is `None` — never `0`.** A
   swallowed stat error must not render as the head of the log.
2. **Rotation preserves logical offsets.** Sealed slices are immutable and
   offset-load-bearing; nothing rewrites them. A reader mid-iteration keeps its
   handle and continues into the new live slice with no gap and no duplicate.
3. **Every durable JSON write is atomic** (`utils.atomic_json_write`: stage +
   `os.replace`). The stat fingerprint's soundness depends on it.
4. **The fingerprint alone decides cache validity.** No event-tail replay, ever
   — a second validity authority would drift from the first.
5. **The store decides; the projection serves.** A cached or stale-labeled core
   never deletes, never refuses a write, never wins a conflict.
6. **A cache miss is never silent.** Every demote emits a reason; the two quiet
   failure modes have their own named receipts. `absent` is the one deliberate
   exception and a census must account for it.
7. **A write-back is one unit.** The trio is published by replacing `live.json`;
   a torn trio is unrepresentable.
8. **A never-populated projection returns `None`, not `{}`**, and the
   observability index is a cache, never authority — a missing or corrupt
   `prompt_observability_index.json` falls back to a directory scan.
9. **Archive, never delete.** `events_archive/`, `deleted_archive/`, `*_archive/`
   and `mission_chat_turns.legacy.json` are all kept.

---

## Open rows

- **2026-08-22 — the core cache cannot serve boots reliably.**
  `snapshot_core_cache never_converged` fired 10 times between 2026-08-20 18:21
  and 2026-08-22 13:42 (`profiles/base/logs/agent.log`); the diff paths include
  runtime-authored `state.db-wal`, `state.db`, and the live events slice
  `events_archive/events.81417412.jsonl`. Five of the ten carry
  `diff_scope=every_pass` (self-perturbation, the class worth acting on).
  → [planned/core-cache-input-closure.md](planned/core-cache-input-closure.md)
- **2026-08-22 — cold boot costs 11.2 s of re-projection.**
  `build_ms=11235 sections_top=prompt_observability:4520,agents_readiness:4366,events:842`
  (prewarm, generation 1, pid 30588). Every build re-projects the whole store;
  RD3's incremental lane was retired 2026-08-01 with no successor.
  → [planned/incremental-projection.md](planned/incremental-projection.md)
- **2026-08-22 — the retired lane's last traces have a removal plan.** Three
  dead config fields still ride the snapshot wire (contract-bump lockstep —
  rides the NEXT bump, never its own), the operator's live `config.yaml` still
  carries the inert `read_model.enabled: true` (operator-owned one-liner), and
  this doc's RETIRED section shrinks when the wire fields go.
  → [planned/read-model-residue-removal.md](planned/read-model-residue-removal.md)
- **2026-08-22 — RD4's push invalidation is still absent.** No change feed in the
  codebase; consumers poll. Unaffected by Stage 6 — the question is about the
  LIVE core-cache lane, not the retired database; any revival names a new
  producer (the projector is gone).
  → [planned/read-model-change-feed.md](planned/read-model-change-feed.md)
- **2026-08-22 — the Unverified carry-forward sections have no burn-down
  owner.** Seven domain docs carry claims from archived sources that no pass
  has verified against code; nothing schedules that verification.
  → [planned/unverified-carryforward-burndown.md](planned/unverified-carryforward-burndown.md)

---

## Unverified carry-forward

Both from archived docs, both touching this domain's stores, neither verified
against current code in this pass:

- **`state.reconciled` bounded-staleness backstop** — SLO "client staleness ≤ 2×
  heartbeat interval (~10s) for ANY write, rule-compliant or not"
  ([12-read-path-freshness-hardening.md](archive/2026-08-22-pre-consolidation/12-read-path-freshness-hardening.md)).
- **Supersede guard at the store chokepoint** — intent basis, `issued_at` /
  `intent_issued_at`, `superseded` vs `duplicate` outcomes
  ([13-write-path-intent-integrity.md](archive/2026-08-22-pre-consolidation/13-write-path-intent-integrity.md)).

---

## Supersedes

- [archive/2026-08-22-pre-consolidation/05-runtime-data-enterprise-storage.md](archive/2026-08-22-pre-consolidation/05-runtime-data-enterprise-storage.md)
  — primary. Its SQLite DDL still creates `goals` / `runs` / `proofs` /
  `incidents`; those tables were removed with the mission lane, were then
  explicitly `DROP TABLE IF EXISTS`-ed on every connect, and finally went with
  the whole database at Stage 6 (2026-08-22).
  Its RD7 `(segment_seq, byte)` segmentation proposal was **not** built as
  specified — `event_rotation.py`'s manifest scheme shipped instead. Its header
  claim that the "NDJSON change feed … is live and current" is false.
- [14-snapshot-core-build-performance.md](archive/2026-08-22-pre-consolidation/14-snapshot-core-build-performance.md)
  — the `base_offset` design originates here, not in doc 05.
- [12-read-path-freshness-hardening.md](archive/2026-08-22-pre-consolidation/12-read-path-freshness-hardening.md)
  · [13-write-path-intent-integrity.md](archive/2026-08-22-pre-consolidation/13-write-path-intent-integrity.md)
  · [MC_DROPS_SNAPSHOT_CACHE_INVESTIGATION_2026-08-18.md](archive/2026-08-22-pre-consolidation/MC_DROPS_SNAPSHOT_CACHE_INVESTIGATION_2026-08-18.md)
  · [SCOPED_INVALIDATION_PLAN_2026-08-16.md](archive/2026-08-22-pre-consolidation/SCOPED_INVALIDATION_PLAN_2026-08-16.md)
  · [EG0_2_RECEIPTS_2026-08-17.md](archive/2026-08-22-pre-consolidation/EG0_2_RECEIPTS_2026-08-17.md)
  · [MISSION_CONTROL_ENTERPRISE_PLAN_2026-08-17.md](archive/2026-08-22-pre-consolidation/MISSION_CONTROL_ENTERPRISE_PLAN_2026-08-17.md)
  · [MISSION_CONTROL_LEDGER_REFACTOR_PLAN_2026-08-17.md](archive/2026-08-22-pre-consolidation/MISSION_CONTROL_LEDGER_REFACTOR_PLAN_2026-08-17.md)
