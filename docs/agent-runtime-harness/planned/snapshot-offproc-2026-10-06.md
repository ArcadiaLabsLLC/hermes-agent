# Planned — the snapshot core builds off the serve's GIL, lane h-snapshot-offproc (2026-10-06)

**Status:** DESIGN 2026-10-06 (Fable, read-only against the live store `X:/Eternia/.hermes/agent-runtime`, the base `agent.log` and its three rotations 2026-10-03 → 10-05, 69 October turn records under `mission_chat_turns/`, the tree at `c9e66f7d61`, and one scratch-home measurement of the child-process costs). No production code was changed. **Row:** `Harness_Brain/20 — Active Initiatives/runtime-queue.md` "Snapshot builds stay 6–8 s of in-process Python … the structural answer is building the core off the serve's GIL" (RE-READ 2026-10-05; owner go 2026-10-06). **Owner docs:** [`../04-boot-and-lifecycle.md`](../04-boot-and-lifecycle.md) (Stage 7 receipt, Stage 8 cache lane), [`../03-transport-and-wire.md`](../03-transport-and-wire.md) §3–§4 (frames, watermarks, the fold negotiation). **Sibling plan:** [`turn-latency-h-turn1-2026-10-05.md`](turn-latency-h-turn1-2026-10-05.md) §2 (lane C: the `persona_chat_turn` overlay, whose launcher half C3 has NOT landed — §0.2 below).

**One paragraph.** Every core build is 2.2–16 s of pure-Python work on the serve's own interpreter, led by one of two stream subscribers (the hub room and the launcher's `cli_stream` lane) for every batch a chat turn appends, and since the h-chatperf yield landed every build still shares 1–2 s of GIL with the turn it stands aside for, because the yield can only pause between sections and the two biggest sections are 1.2–4.3 s (`prompt_observability`) and 0.5–6.9 s (`agents_readiness`) blocks. The chosen design is a **hybrid**: (1) the one section that is pure re-reading becomes incremental in-process (`events`: the cached event view re-reads and re-indexes 92 MB of log on every build the log moved — which is every turn — for a 20-row tail); (2) every LED default-store build runs in a **resident snapshot worker process**, spawned the way the conversations worker already is, answering over its stdio pipe with the core as JSON (570 KB, 8 ms to decode, ≤ 100 ms on the wire), with the serve keeping the coalescer, the roles, the ledger, the reuse memos and the cache lane exactly where they are; (3) the launcher declares `persona_chat_turn` (h-turn1 C3), which removes the turn-driven builds altogether. A per-build child is refused by measurement (3.0–4.2 s of imports plus a 15–16 s cold first build); a fully incremental projection is refused because its biggest section (`agents_readiness`) has no event to key on and would stay on the GIL whenever a profile tree moves.

---

## 0. Ground truth (measured 2026-10-05/06, this PC)

### 0.1 What still leads a full build after the overlay landed (`7ddb6949a1`, 20:44 local; serve pid 2140 booted 21:59 local from a tree that carries it)

`snapshot_build_core role=led` lines by caller and `snapshot_build reason=` lines by reason, per log file (base `agent.log`; `.1` = 10-04 14:05 → 10-05 19:16, `.2` = 10-03 17:55 → 10-04 14:05, `.3` = earlier 10-03):

| file | led: hub | led: cli | led: prewarm | led: unknown | `reason=demote` | `reason=hydrate` | `core_source=cache` hits | `never_converged` |
|---|---|---|---|---|---|---|---|---|
| `agent.log` (10-05 19:16 → 22:01) | 14 | 12 | 2 | 1 | 41 | 10 | 13 | 3 |
| `agent.log.1` | 31 | 26 | 17 | 1 | 65 | 62 | 83 | 8 |
| `agent.log.2` | 30 | 37 | 16 | 0 | 159 | 49 | 80 | 6 |
| `agent.log.3` | 15 | 8 | 10 | 0 | 41 | 38 | 48 | 2 |

- **Two subscribers, two builds per batch.** `stream_attach op=subscribe purpose=stream_lane client=eternia-launcher-local-console` (the hub, caller `hub`) and `stream_attach op=harness_stream purpose=cli_stream` (caller `cli`) are both in the serve pid, drain the same events, and each leads its own demote core: gens 3/4 at offset 92898441, 5/6 at 92901274, 9/10 at 92906829 … pairs at one offset on every chat window. `demote_core_reuse` caught ONE of them in the whole of `agent.log` (`role=reused` 21:55:48); the rest miss because the second lane's batch closes at a later offset (h-turn1 C5 explains why that is correct).
- **The overlay is unconsumed.** The launcher's declaration reads `fold_entities=incident,office_actor,office_actor_lifecycle,office_conflict,office_surface,office_surface_fold,persona_instance,persona_instance_create,scope` — no `persona_chat_turn` (`EterniaLauncher/lib/core/services/hermes/runtime/data/serve/mission_serve_stream_lane_slot.dart`, `…/remote/lan_socket_connector.dart`; `grep -rl persona_chat_turn lib/` is empty). pid 2140's first two minutes: 0 `turn_section` lines, 8 `reason=demote`, 4 led builds (gens 2–5, 4.2–6.6 s each). So the trigger table above IS the post-overlay table until C3 lands.
- **Prewarm / boot:** one led build per serve boot (`caller=prewarm generation=1`), always the cold one: `build_ms` 16141 (pid 7764), 15197 (pid 30988) — `agents_readiness` 8313 / 7536, `prompt_observability` 6038 / 5426, `events` 809 / 1335. The three serve restarts of 10-05 19:16 → 21:59 each paid it.
- **Cache lane:** boot-only by design (`lane_armed()`); on 10-05 it served 13 hits and then `never_converged builds=3 … diff=state.db,state.db-wal` (21:55:12) — the profile SessionDB is in the input closure and moves on every turn, so the persisted core cannot short-circuit a mid-session build. Not this lane's problem; stated so nobody expects the cache to absorb the demotes.
- **Shadow validation** (`core_cache/shadow.py::maybe_start_shadow_validation`) is a THIRD in-process full build on a cache-hit boot, on a daemon thread, unlogged as `role=led`.

### 0.2 What each section costs (`sections_top` of the 29 led builds in `agent.log`; `snapshot_agents_readiness` split receipts)

| section | warm, steady (pid 2140 / 7764 / 11040) | under a chat window (pid 30988, 21:55:11–54, four turns) | cold first build (prewarm gen 1) | yield points inside it |
|---|---|---|---|---|
| `prompt_observability` | 1,122–2,599 (top on 20 of 29 lines; 3,048–4,300 on four) | 2,272–5,925 | 5,426–6,038 | none — one block |
| `agents_readiness` | 500–1,670 (`walk_ms` 598–1,591, `tool_visibility_ms` 28–143) | 1,127–6,649 (`walk_ms` 4,560 / 6,591 / 4,103) | 7,536–8,313 (`walk_ms` 6,893, `tool_visibility_ms` 642) | one per persona of the readiness walk (5 personas) |
| `events` | 738–1,304 | 1,304–2,286 | 809–1,335 | none |
| `persona_chat` | 391–1,053 | 811 | — | none |
| `build_ms` total | 2,250–6,557 | 6,109–15,805 | 15,197–16,141 | section boundaries (11) |

- **`events` is I/O-free waste.** `CachedEventLog._cached_lines` keys a process-wide view on `(path, mtime, size)` of every slice and, on a miss, `read_text().splitlines()` + a regex id-index over ALL of them (81 MB sealed + 11 MB live). Every turn appends, so every build misses. The read itself is 78–85 ms for the 81 MB file (measured); the 0.7–2.3 s is the split and the index. The build then uses `tail(20)` and per-root scans.
- **`agents_readiness` has no event.** Its inputs are the profile tree (config, skills, the provider probe); the walk is 0.5–1.6 s warm and 4–8 s when another thread holds the GIL or the tree is cold. It is the "one uninterruptible 5,837 ms walk" of the row's RE-READ, and the per-persona yield inside it does not make it interruptible: a persona's walk is one call.
- **The yield works and is not enough.** `snapshot_build_yielded` on 10-05: `waited_ms` 1,003–8,228, `pauses` 1–4, `budget_exhausted=false` every time. The build stands aside at the next boundary, which arrives 1.2–6.6 s after the window opened.

### 0.3 What a build costs a turn today (69 October turn records with `builds_overlapped` and `stream_done`; ms from `anchored_at`)

| cohort | n | `write_ahead` p50 / max | `preflight_done → request_built` p50 / max | `request_sent → response_headers` p50 / max | `stream_done` p50 / max |
|---|---|---|---|---|---|
| warm, `builds_overlapped = 0` | 9 | 1,083 / 2,495 | **44** / 62 | **762** / 1,219 | **3,988** / 9,632 |
| warm, `builds_overlapped ≥ 1` | 26 | 615 / 2,923 | 136 / 1,754 | 974 / 4,002 | 5,582 / 391,439 |
| cold, `builds_overlapped = 0` | 6 | 1,831 / 2,118 | 0 / 589 | 0 / 1,085 | 7,095 / 19,716 |
| cold, `builds_overlapped ≥ 1` | 28 | 1,783 / 6,250 | 0 / 1,733 | 0 / 2,879 | 28,629 / 840,053 |

(The `stream_done` maxima are tool turns; the two middle columns are the hot windows the yield protects, where a 0-ms gap means the record predates the mark.) Since the yield landed (records from 10-05 18:14 on): 24 of 28 turns still carry `builds_overlapped` 1–2; the four clean ones are the only ones whose `request_sent → response_headers` reads under 850 ms. The row's RE-READ turn (`…339c66e95690` t3, 18:14:33Z) is in this set: `builds_overlapped=1`, headers at 4,002 ms with `profile_conversation_provider_dispatch_ms=4995`.

### 0.4 What a child process costs (scratch home, the serve's own interpreter `X:/Eternia/.hermes/venvs/hermes-agent`, cwd the tree; script and output in this lane's scratch, numbers reproduced here)

| cost | measured |
|---|---|
| `python -c pass` spawn | 92–113 ms |
| `import agent_runtime.snapshot.build` in a fresh process | **2,994–4,158 ms** (three runs) |
| first full build in a fresh process | **15,197–16,141 ms** (the prewarm receipts, §0.1) |
| `core.json` of the live generation | 570,398 B; pickle 404,661 B |
| `json.loads` / `json.dumps` of the core | 8.2 / 5.4–5.9 ms |
| `pickle.loads` / `pickle.dumps` | 4.7–5.5 / 4.8–8.3 ms |
| `copy.deepcopy` of the core (what the coalescer hands each rider today) | 25.9–31.3 ms |
| core through a child's stdin→stdout, including the spawn | 118–262 ms (so the transfer itself is under ~100 ms) |
| `events.jsonl` 81 MB sequential read | 78–85 ms |
| the consult's stat walk over the 4,903 `entries.json` inputs | UNVERIFIED (the entries payload is not a flat path map; the one read is `core_cache/persist.py::_entries_payload` and a timed `cache_decision.consult` against a scratch copy). Not on the chosen transport (§1 R2). |

A per-build child therefore costs 3–4 s before it reads a byte and 15–16 s for its first core; a RESIDENT worker costs that once per serve boot — which the serve already pays as the prewarm.

---

## 1. The designs, compared

| | (a) child process per build | (a') resident snapshot worker | (b) incremental per-section projection | (c) hybrid = (a') + the one cheap (b) section + C3 |
|---|---|---|---|---|
| GIL time per build left in the serve | ~50 ms (decode + one deepcopy per rider) | same | the whole build minus memo hits; `agents_readiness` stays whenever a profile tree moves (0.5–8 s) | ~50 ms |
| wall cost per build | 3–4 s import + 15–16 s cold build, every time | 2.2–6.6 s warm (today's), off-GIL | 0.3–3 s | 1.5–5 s off-GIL (`events` ~0) |
| boot cost | — | one cold build, which IS today's prewarm | none | same as (a') |
| what it breaks | the ledger's "LED span = GIL span" claim; the receipt's `pid`; the shadow build; the cache lane's `note_full_build_completed`; `SnapshotBuildContext` (ContextVar does not cross a process) | same list, each answered in §2 | `sections_ms` semantics (a memo hit is 0 ms); the MCF-Q1 direction per section; a second fingerprint authority beside `core_cache`'s | the (a') list; `events` keeps its key and its meaning |
| fold tokens / frames / parity envelope | unchanged (the core is the same dict) | unchanged | unchanged keys; `sections_ms` values move | unchanged |
| memory | transient | one more interpreter with the builder's imports resident (RSS UNVERIFIED; the one read is the worker's RSS after its first build, `psutil.Process(pid).memory_info()` in the serve's register row) | none | same as (a') |
| verdict | refused: measured dead on arrival | **chosen** | refused as the whole answer; `events` taken | **chosen** |

**Why not a thread.** It is the GIL: every section is pure Python over dicts and files. `agents_readiness` and `prompt_observability` release the GIL only inside `os.stat`/`read`, which §0.4 shows is a few percent of their time.

**Why the worker and not the persisted generation as the transport.** `write_back` already lands a core the next PROCESS can read, but the read side is boot-only (`lane_armed()`), validated by a 4,903-input stat walk that `never_converged` proves cannot match mid-session, and arrives one `os.replace` late. The pipe is 8 ms to decode and needs no validation: the worker built it for THIS request.

---

## 2. Stages (hermes unless marked; each one lane, one CHANGE commit with its positive control in the body)

### S1 — `events` becomes an appending view (in-process; lands first, independent of everything)

- **Goal:** `sections_ms.events` ≈ 0 on a build whose log only GREW since the last view; a rotation or a shrink still rebuilds the view whole.
- **Touches:** `agent_runtime/events.py` `CachedEventLog._cached_lines` and `_EVENT_VIEW_CACHE` — key the cached view on the slice LIST and the sealed slices' `(mtime, size)`; for the live slice keep `(path, consumed_size)` and, on a miss where the path set and every sealed stat are equal and the live slice's size ≥ consumed, read only the bytes from `consumed_size` (`seek`), split them, extend `lines` and the id index in place; any other difference (a new slice, a sealed stat moved, the live file shrank) takes today's whole re-read. `agent_runtime/event_rotation.py::ordered_line_sources` unchanged. The `events` key in `REPORTED_SECTIONS` and its span are unchanged (an appended view costs what the append costs).
- **Positive control:** (i) a journal that grows by one line between two `CachedEventLog()` instances → the second's view equals a whole re-read line-for-line and token-for-token (`_lines_by_id_token`) and performed one `seek`-read of exactly the appended bytes; plant = extend without re-indexing the new lines → the token test reds. (ii) a sealed slice rewritten in place at the same size with a new mtime → whole re-read; plant = drop mtime from the sealed key → red. (iii) the live file truncated below `consumed_size` → whole re-read.
- **Tests:** `tests/agent_runtime/test_events.py` (extend), `tests/agent_runtime/test_event_rotation.py` (the slice-list key).
- **Saving:** 0.7–2.3 s per build, in-process, on every build — a fifth to a third of a warm build — whether or not S2 lands. Also the overlay's `trace_ms` floor (h-turn1 §7 row 2) halves.

### S2 — the resident snapshot worker (the lead build runs in a child; the serve keeps every decision)

- **Goal:** on a serve with `snapshot.subprocess_worker` on and a live worker, `_lead_build_now`'s `_build_snapshot_uncoalesced()` is answered by the worker over its pipe; everything around it — consult, coalescer, roles, `build_info`, the ledger span, the receipt, `write_back`, `note_full_build_completed`, `demote_core_reuse`, `turn_section_reuse` — runs in the serve exactly as today.
- **Touches:**
  - new package `agent_runtime/snapshot_worker/` (`__layer__ = "lanes"`): `worker.py::start_worker(home, …) -> SnapshotPeer` shaped on `agent_runtime/conversations/worker.py::start_worker` (`served_profile_child_env(target_home=home, inherit_credentials=True)`, `spawn_server([sys.executable, "-u", "-m", "agent_runtime.snapshot_worker.entry"])`, `register_child(pid, "snapshot-worker")`, `CREATE_NO_WINDOW`); `peer.py::SnapshotPeer` on the `native_peer` frame codec (one JSON object per line, `MAX_FRAME_BYTES` raised to cover a 2 MB core — ruling R4); `entry.py` (the child's main: resolve `HERMES_HOME`/`HERMES_AGENT_RUNTIME_ROOT` from env exactly as the serve child does, then loop `build` requests → `_build_snapshot_uncoalesced()` inside its own `snapshot_build_context_scope` → reply `{"core": …, "receipts": [...]}`); `select_worker_factory()` returning the in-process twin (today's `_build_snapshot_uncoalesced`) when the switch is off.
  - `agent_runtime/bundle_profiles/manifest.py`: `"snapshot.subprocess_worker": "agent_runtime/snapshot_worker/worker.py::subprocess_worker_enabled"` (default on; off wherever `conversations.subprocess_worker` is off).
  - `agent_runtime/snapshot/build.py::_lead_build_now`: `result = _lead_executor()(…)` where the executor is the bound worker's `build()` or the in-process function; on `WorkerLost` → in-process build for THIS request, receipt `snapshot_worker lost=… fallback=inproc`, respawn on the next lead (bounded: three respawns per serve life, then in-process for the rest of it). `_build_injected` (tests, doctors, `prompt_skills_catalogs` captures) and `hermes harness snapshot` (`runtime_commands.py::_cmd_snapshot`, no serve) never see the worker.
  - `agent_runtime/core_cache/shadow.py::maybe_start_shadow_validation`: `build=` becomes the same executor (ruling R3) — the shadow is the most expensive build of a cache-hit boot and it is the one nobody sees.
  - `agent_runtime/snapshot/build_log.py::_log_snapshot_build_core`: `executor=%s` (`worker` / `inproc`) and `worker_pid=%s` added BEFORE `pid=` (BO-3: `pid` rides last). The worker's own `snapshot_agents_readiness` split and any section receipt ride back in the reply's `receipts` list and are logged by the SERVE's logger (ruling R5: one writer per `agent.log`; the child's stderr goes to `DEVNULL` as the conversations worker's does).
  - `hermes_cli/harness_parts/serve/boot_phases.py`: bind the worker beside `_prewarm_read_model_snapshot` (the prewarm's `build_snapshot(build_info={"caller": "prewarm"})` is the worker's first, cold build — the boot pays it once, as today); the drain closes the peer (`serve/drain.py`, beside the pool join).
  - `agent_runtime/snapshot_turn_yield.py`: unchanged in code; `build_yield_scope` on a worker-executed lead still arms the PRE-lead `stand_aside()` (a build that need not start during a hot window still should not: it would compete for disk and for the serve's decode), and the in-build yield points become no-ops in the serve (the child has no `_ACTIVE` scope). Receipt unchanged.
  - `agent_runtime/snapshot_build_ledger.py`: unchanged — the span is the serve's wait for the lead, which is what `builds_overlapped` has always counted (ruling R6).
- **What the child must get right, each with its pin:** (i) `HERMES_HOME` at CALL time from the env the serve passes (never module scope) — the `served_profile_child_env` door; (ii) its own `SessionDB` via `persona_session_db_scope()` (MCF-27: one owner opens and closes, now per process); (iii) `events_position()` captured in the child BEFORE the first section, as today — the watermark direction is unchanged because the child IS the builder; (iv) `_maybe_reconcile_profile_personas()` stays in the SERVE before the consult (it is a write-side admission step and must precede the fingerprint); (v) `cache_lane.pre_build_fingerprint()` and `write_back` stay in the serve (the key is the serve's consult; the write is best-effort and must not race the child's next build); (vi) `label_core` is applied in the serve on the decoded dict.
- **Positive control:** (i) golden: the worker's core for the fixture store equals the in-process core field-for-field except `generated_at`, `parity.build_ms`, `parity.sections_ms` and `parity.watermark.captured_at` (the comparator `core_cache/shadow.py::compare_cores` already strips those); plant = drop the child's `runtime_resolution_scope` → `runtime_paths_diagnostic` differs → red. (ii) a killed worker mid-request → the lead completes in-process, the receipt reads `fallback=inproc`, the coalescer releases every rider exactly once; plant = swallow `WorkerLost` → riders hang → red by timeout. (iii) `builds_overlapped` for a turn that overlaps a worker build is still ≥ 1 (the ledger span is the serve's wait). (iv) the switch off → no child spawned, `executor=inproc` on every receipt, every existing snapshot test byte-identical.
- **Tests:** new `tests/agent_runtime/test_snapshot_worker.py` (the shape of `test_native_conversation_worker.py` + `test_native_conversation_in_process.py`), `tests/agent_runtime/test_snapshot_build_logging.py` (the role matrix with the executor), `tests/agent_runtime/test_stale_core_under_fresh_offset.py` (the shadow through the executor), `tests/agent_runtime/test_snapshot_turn_yield.py` (pre-lead stand-aside still fires).
- **Saving:** the serve's GIL share of a build drops from 2.2–16 s to ~50 ms (8 ms decode + 26–31 ms deepcopy per rider + the receipt). The build's WALL stays — subscribers still wait 2–7 s for a demote core until S3.

### S3 — the launcher declares `persona_chat_turn` (launcher; = h-turn1 C3, not re-specified here)

- **Goal:** the trigger table's `reason=demote` rows that are turn batches stop existing; `builds_overlapped` → 0 on an ordinary turn.
- **Touches:** `EterniaLauncher/lib/features/mission_control/data/mission_fold_declaration.dart` (`kMissionFoldDeclaredEntities`), `mission_read_model.dart::applyStreamFrame`, the `persona_chat_turn.json` golden mirror — exactly h-turn1 C3. Hermes side already landed (`7ddb6949a1`).
- **Saving:** per turn, 3–5 led cores (2.2–16 s each) → 0; the overlay is ~0.9 s on the stream thread, shared by both lanes. After S2 that 0.9 s is the only build-side GIL a turn can meet, and it carries no hot-window overlap of its own (it runs at flush, after `turn_ended`).

### S4 — the clean read (both repos, after S1–S3)

Ten warm turns and one cold turn from the records: `builds_overlapped`, the two hot-window columns of §0.3, and `executor=` on every `snapshot_build_core` line in the window. Re-arm or close the row's second half (`rt_provider_wait_ms` charges the GIL to the provider) on those numbers.

**Not proposed.** A readiness memo keyed on each persona's profile-tree stat (the incremental half for the one section with no event): after S2 it buys wall time in the child, not GIL in the serve, and it would be a second fingerprint authority beside `core_cache`'s. Re-measure after S4 (ruling R7). Collapsing the two subscribers' builds: h-turn1 C5 stands.

---

## 3. Projected effect

| measure | today (§0.3, warm) | after S1 | after S1+S2 | after S1+S2+S3 |
|---|---|---|---|---|
| serve GIL per led build | 2.2–6.6 s (15–16 s cold) | 1.5–4.5 s | ~50 ms | ~50 ms, and 3–5 fewer builds per turn |
| `builds_overlapped` on a warm turn | 1–2 on 24 of 28 | 1–2 | 1–2 (wall overlap, now harmless; receipt says `executor=worker`) | 0 on an ordinary turn |
| `preflight_done → request_built` p50 / max | 136 / 1,754 | — | 44 / ~60 (the clean cohort) | same |
| `request_sent → response_headers` p50 / max | 974 / 4,002 | — | 762 / ~1,200 (the clean cohort) | same |
| `stream_done` p50, warm | 5,582 | — | ~3,990 (the clean cohort) | same |
| board sees a turn's rows after `turn_ended` | 3–13 s (a queued core) | 2–11 s | 2–7 s | ~1 s (the overlay) |
| boot | one cold 15–16 s prewarm in-process | — | the same build, in the child; serve GIL free during it | same |

The clean-cohort numbers are the projection's ceiling: a turn cannot read faster than the nine turns that met no build. Anything under them after S4 is a different row.

---

## 4. Open rulings (recommended answer first)

| id | question | recommended |
|---|---|---|
| R1 | Per-build child or resident worker? | Resident: a child pays 3.0–4.2 s of imports and a 15–16 s cold build per build (§0.4). |
| R2 | Transport: the pipe reply, or the persisted generation (`serve_read_model/gen-*`) with a stat consult? | The pipe: 8 ms to decode, no validation needed; the generation path is boot-only, 4,903-input, and `never_converged` mid-session. `write_back` keeps landing in the serve. |
| R3 | Does the shadow validation build run in the worker too? | Yes: it is a full in-process build on every cache-hit boot and the one no receipt names as `led`. |
| R4 | Pickle or JSON on the pipe? | JSON on the existing `native_peer` codec (`MAX_FRAME_BYTES` raised to 8 MiB): 8 vs 5 ms is not worth a second codec, and the core is JSON-shaped by contract (`to_jsonable`). |
| R5 | Who writes the child's receipts? | The serve: the child returns them in the reply and the serve logs them under its own `pid=` with `worker_pid=` beside — one writer per `agent.log`, and the pid joins of 04-boot-and-lifecycle keep working. |
| R6 | Does `builds_overlapped` keep counting worker builds? | Yes, unchanged: it counts led spans on the serve's clock, and a wall overlap is still a fact. The GIL claim moves to the receipt's `executor=`. No new key on the turn record or the parity envelope. |
| R7 | The per-persona readiness memo (incremental `agents_readiness`)? | Not now; re-measure at S4. After S2 it is wall in the child, not GIL in the serve. |
| R8 | The switch's default on an embedded/phone profile? | Off wherever `conversations.subprocess_worker` is off (one rule, `bundle_profiles/manifest.py`); the in-process twin is byte-identical to today. |
| R9 | Worker memory bound? | UNVERIFIED (§1); read the RSS at S4. If it matters, the worker exits after N idle minutes and the next lead respawns it (paying the cold build again — a trade the owner makes with the number in hand). |

## 5. Rows corrected or restated

- The row's "6–8 s" is the under-chat figure; steady warm builds are 2.2–6.6 s and the cold one is 15–16 s (§0.2). Its structural claim stands and is sharpened: the yield cannot help inside `prompt_observability` (one block) and inside a persona's readiness walk (one call).
- The RE-READ's "no turn read clean" has a second cause beside the GIL: the launcher has not declared the overlay, so every turn still leads 3–5 demote cores (§0.1). S3 is the larger half of the fix by count; S2 is the structural half by kind.

## 6. Landing order and discipline

1. **S1** (one hermes lane, one CHANGE commit) — independent, measurable on the next serve's `sections_top`.
2. **S2** (one hermes lane; the package is a MOVE-free CHANGE; one commit for the worker + executor, the switch default on) — the lane runs only the test files that import a touched module; the suite runs once at the landing. The operator's next boot reads `executor=worker` on the prewarm line and one `snapshot_worker` bind receipt.
3. **S3** (launcher lane, h-turn1 C3) — may run concurrently with S2; it is on the other side of the wire.
4. **S4** after all three.

Every CHANGE commit carries its positive control in the body (the plant, the red, the revert).

## 7. Rows to file (found by this lane; the parent files them)

- `Harness_Brain/20 — Active Initiatives/runtime-queue.md` § Fork-owned, "Filed on arrival — 2026-10-06 (lane h-snapshot-offproc)": **`CachedEventLog._cached_lines` re-reads and re-indexes every slice (81 MB sealed + 11 MB live) whenever the live slice's `(mtime, size)` moved — every turn — for a 20-row tail; the read is 80 ms, the split+index 0.7–2.3 s per build** · fork / events · evidence: this plan §0.2, §0.4 · = S1 · UNCLAIMED
- same heading: **The launcher does not declare `persona_chat_turn`; the overlay that landed in `7ddb6949a1` is unconsumed and every turn still leads 3–5 demote cores across the hub and `cli_stream` lanes** · launcher / `mission_fold_declaration.dart` · evidence: §0.1 (pid 2140) · filed on the launcher side as h-turn1 C3; this row names it
- same heading: **The cache-hit boot's shadow validation is a third full in-process build with no `role=led` receipt** · fork / `core_cache/shadow.py` · evidence: §0.1 · = S2 R3
