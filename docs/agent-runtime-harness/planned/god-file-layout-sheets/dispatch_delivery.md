# Layout sheet — `agent_runtime/dispatch_delivery.py` (lane R2)

Base: `main` @ `28012c8f8a` · sha256 `7a654ba97eb00ff70e8e0e811d9408d7fd5be1206682127ce4466ba888802955` · 1,801 raw / 1,311 code / 31 top-level defs · longest `drain_background_completions` 258 (1465–1722, depth 3) · chains 3/0 · `str==` 6 · `isinstance` 3 · owner doc `docs/agent-runtime-harness/05-chat-turn-lane.md` (the delivery drain, `wait: false`). 7 production importers taking 6 names (`serve/session.py` → `start_delivery_drain`; `status.py` → `delivery_drain_status`; `persona/chat_admission.py` → `delivery_drain_is_live`; `core_cache/vocabulary.py`, `core_cache_census.py` → `DRAIN_STATE_FILENAME`; `persona/chat_history_writes.py` → the module; **`tools/agent_chat_tool.py` → `_sender_persona`, a private**); 14 test files pinning 5 names plus the module.

**Package named after the file — `agent_runtime/dispatch_delivery/`.** The file's own banners (212 accounting · 958 idle gating · 1069 the forge · 1139 the drain · 1297 background-completion lane) are the skeleton, with the accounting's `[A]`/`[D]` tagging (215–221) becoming a module boundary instead of a comment discipline.

## 1. Skeleton (owner ruling 2026-09-25: readability first; modules target 100–300, hard cap 500; no flow over three modules)

```
agent_runtime/dispatch_delivery/
  __init__.py       wiring   the docstring (why a forged TURN, idle checked twice, what "delivered" may mean) + the map; re-exports the 6 importer names, sender_persona, and the test names
  vocabulary.py     models   the VOCABULARY module: DELIVERY_REQUESTED_BY, REPLY_LIMIT, the drain bounds (DEFAULT_DRAIN_INTERVAL_SECONDS … DRAIN_OWNERLESS_WARN_AFTER), DELIVERED_REASON/DELIVERED_SILENT_REASON/DELIVERY_REASONS, DRAIN_STATE_FILENAME, STEER_ACK_SECONDS, BOUNCE_GATES (CHANGE), terminal_forge_rejections, transient_forge_refusals  (~90; exempt from the floor as a vocabulary module)
  accounting.py     stores   [A] — IdleProbe, DrainBounce, _DrainTelemetry + the process singleton, _event_key, _delivery_outcome, _owns_event_with_accounting, _record_sender_busy — reads decisions, records them, steers nothing  (~250)   entry: (read through mirror.delivery_drain_status)
  mirror.py         stores   the drain-state file: _drain_state_path, _write_drain_state, read_delivery_drain_state, delivery_drain_status, delivery_drain_is_live  (~120)   entry: delivery_drain_status, delivery_drain_is_live, read_delivery_drain_state
  forge.py          lanes    the forge and the message it forges: the requested_by marker (delivery_client_message_id, delivery_requested_by, parse_delivery_requested_by), format_dispatch_delivery, idle gating (_probe_sender_idle, _sender_is_idle, sender_persona), forge_delivery_turn  (~310)   entry: forge_delivery_turn, sender_persona, parse_delivery_requested_by, delivery_client_message_id
  drain.py          lanes    the dispatch-store drain: drain_once, sweep_orphaned_dispatches, _chat_root_of_completion, _orphaned_persona_root, _steer_into_busy_turn, start_delivery_drain + its loop  (~260)   entry: start_delivery_drain, drain_once, sweep_orphaned_dispatches
  completions.py    lanes    the background-completion lane: _claim_durable_completion, _settle_durable_completion, drain_background_completions (BackgroundDrain after the CHANGE)  (~300)   entry: drain_background_completions
```

Per entry point, the modules an agent opens (the entry's module plus the modules of what it calls directly; `dispatch_store`, `mission_chat_turns`, `persona_chat_continuity`, `turn_visibility`, `mission_chat_steer` and upstream `tools.async_delegation` / `tools.process_registry` are below the package and not counted):

| entry point | opens | count |
|---|---|---|
| `start_delivery_drain` (serve boot) | `drain` → `mirror` (the per-pass mirror write) → `completions` (the second lane each pass runs) | 3 |
| `drain_once` | `drain` → `forge` → `accounting` | 3 |
| `drain_background_completions` | `completions` → `forge` → `accounting` | 3 |
| `forge_delivery_turn` (also `chat_history_writes`) | `forge` → `vocabulary` | 2 |
| `delivery_drain_status` / `delivery_drain_is_live` (status, chat admission) | `mirror` → `accounting` (`_telemetry.snapshot`) | 2 |

Floor rule (ruling 3): the first draft had `provenance.py` (the marker + `format_dispatch_delivery`, ~160) apart from `forge.py` (~150); `drain_once` then opened four modules, so the forge and the message it forges are one module — the delivered block is written for exactly one reader, the forge. `vocabulary` is the stated sub-100 module.

### 1.1 Section map → target modules

| lines | what is there | → module | layer (from imports) |
|---|---|---|---|
| 1–93 | docstring, imports (`utils.atomic_json_write` 71 — §4), `logger`, `__all__` | `dispatch_delivery/__init__.py` | wiring |
| 100–209, 228–280, 1352 | `DELIVERY_REQUESTED_BY` 100, `REPLY_LIMIT` 107, `_terminal_forge_rejections` 110 (lazy `mission_chat_outcome`), `_transient_forge_refusals` 147, `DEFAULT_DRAIN_INTERVAL_SECONDS` 173 … `MAX_BACKGROUND_DELIVERY_ATTEMPTS` 195, `_background_attempts` 200, `_drain_thread` 206, `_drain_lock` 209, `MAX_DRAIN_OUTCOME_ROWS` 228 … `DRAIN_OWNERLESS_WARN_AFTER` 243, `DELIVERED_*` 256–263, `DRAIN_STATE_FILENAME` 276, `DRAIN_MIRROR_HEARTBEAT_SECONDS` 280, `STEER_ACK_SECONDS` 1352 | `dispatch_delivery/vocabulary.py` (the three process globals `_background_attempts`/`_drain_thread`/`_drain_lock` go to `drain.py` — they are the thread's state, not vocabulary) | models |
| 284–623 | `IdleProbe` 284, `_LAST_IDLE_PROBE` 310, `DrainBounce` 316, `_DrainTelemetry` 337, `_telemetry` 517, `_event_key` 520, `_delivery_outcome` 534 (lazy `turn_visibility`), `_owns_event_with_accounting` 563, `_record_sender_busy` 591 | `dispatch_delivery/accounting.py` — imports `vocabulary` | stores |
| 626–742 | `_drain_state_path` 626, `_paths_store_root` 645, `_write_drain_state` 651, `read_delivery_drain_state` 686, `delivery_drain_status` 705, `delivery_drain_is_live` 734 | `dispatch_delivery/mirror.py` — imports `vocabulary`, `accounting`, `paths`, `utils.atomic_json_write` | stores |
| 745–955, 963–1136 | `delivery_client_message_id` 745, `delivery_requested_by` 758, `parse_delivery_requested_by` 790 (lazy `relay_policy`), `_elapsed` 821, `format_dispatch_delivery` 832 (lazy `persona_assignments`, `turn_visibility`), `_probe_sender_idle` 963 (lazy `mission_chat_turns`, `persona_chat_continuity`), `_sender_is_idle` 1032, `_sender_persona` 1048, `forge_delivery_turn` 1074 (lazy `.config`, **`hermes_cli.harness_parts.persona.chat_turn_message` 1131 — §4**) | `dispatch_delivery/forge.py` — imports `vocabulary`, `accounting` | lanes |
| 1144–1387, 1725–1801 | `drain_once` 1144, `sweep_orphaned_dispatches` 1275, `_chat_root_of_completion` 1302, `_orphaned_persona_root` 1321, `_steer_into_busy_turn` 1355 (lazy `mission_chat_steer`), `start_delivery_drain` 1725 (+ `_loop`) | `dispatch_delivery/drain.py` — imports `vocabulary`, `accounting`, `forge`, `mirror`, `completions`, `dispatch_store` (lazy) | lanes |
| 1390–1722 | `_claim_durable_completion` 1390, `_settle_durable_completion` 1430 (lazy `tools.async_delegation`), `drain_background_completions` 1465 (lazy `tools.process_registry`) | `dispatch_delivery/completions.py` — imports `vocabulary`, `accounting`, `forge`, `drain`'s two root resolvers (`_chat_root_of_completion`, `_orphaned_persona_root` — moved INTO `completions.py`, since both are called only from this lane and `sweep_orphaned_dispatches`; `drain` imports them back) | lanes |

Edges point down: `drain` → `completions` → `forge` → `accounting` → `vocabulary`; `mirror` → `accounting`. The two root resolvers live in `completions` so `drain` → `completions` is the only direction (no cycle). `tools/agent_chat_tool.py:678` imports `sender_persona` (public after the MOVE) through `__init__`.

## 2. Routing sites → tables (the CHANGE commit)

W0-G5 holds no row for this file (its three `chains≥3` are guards on `evt["type"]`, all BOUNDARY). Rule 14 has two sites, and there is one floor row:

| site (base line) | shape today | replacement | killing mutation |
|---|---|---|---|
| the bounce GATE names `record_bounce` (401–466) is handed at 17 call sites (580–1715) — `unclaimed`, `forge_busy`, `steered`, `persona_instance_missing`, the `sender_busy:<sub>` composite (614, whose `<sub>` is `IdleProbe`'s own vocabulary, 615), … — free strings spelled at each `[D]` site | a vocabulary with seventeen writers and one reader (`snapshot`, 496) | `vocabulary.BOUNCE_GATES: tuple[str, ...]` enumerated once (the composite's PREFIX is the gate; the sub-reason after the colon is `IdleProbe`'s list, `IDLE_SUB_REASONS`, beside it), and `record_bounce` REFUSES a gate outside it at the single writer (the `mission_chat_outcome._guard_turn_outcome_vocabulary` model, rule 14) — not a `StrEnum`: `dropped` is a fork-wide word (`RpcRefusal`), so a member here would make the gate's arm (c) count every `== "dropped"` in the fork (batch-1 rule; the class defect is rowed once) | remove `lease_busy_ownerless` from the tuple → `tests/agent_runtime/test_dispatch_delivery_observability.py::test_a_held_lease_with_no_owner_file_is_the_stale_lock_fingerprint` reds (the sub-reason is refused instead of recorded) |
| `DELIVERED_REASON` / `DELIVERED_SILENT_REASON` 256–257, spent by `_delivery_outcome` | two constants, one writer — already the right shape | unchanged; `DELIVERY_REASONS` 263 is the tuple that already groups them | — |

W0-G7 floor row (1):

| row | lines / depth | phases (comment map) | after |
|---|---|---|---|
| `drain_background_completions` 1465 | 258 / 3 | pairs from the process registry 1537 · the per-event `[A]` clear 1559 · dedup key derived ONCE 1565–1569 · ownership re-proven or re-queued 1573–1589 · claim AFTER the idle probe 1612 · not-ours → not re-queued 1617 · terminal and LOUD 1634 · the ledgered/ledgerless split 1638 | `BackgroundDrain(pairs).deliver_one(evt, text)` — the 163-line `for` body becomes one method sequence `own → key → claim → probe → forge → settle`, each ≤ 40; `drain_once` (129, under the floor) takes the same `deliver_one` shape so the two lanes read alike, which the accounting banner already asks for |

`str==` 6 → 3 at review (the three `evt["type"]` guards stay as boundaries).

## 3. Helper folds

| here | duplicate of | verdict |
|---|---|---|
| `_elapsed` 821 (seconds → prose) | `running_work._elapsed` 393 (epoch → int ms), `codex_observability._elapsed_ms`, `mission_chat_turn_context._elapsed_ms`, `profile_runner/status._elapsed_ms`, `clock.elapsed_ms` | NOT a fold (this one renders "3m 12s" for the delivered block; `clock.elapsed_ms` is arithmetic). Renamed `format_elapsed` (public in `forge`) to retire the name collision |
| `_sender_persona` 1048 | `running_work._owner_of` 537 — both resolve a session's owner through `persona_assignments.chat_session_owner_persona` ("one authority, shared with the dispatch-delivery lane", running_work docstring rule 5) | already one authority beneath both; `sender_persona` (public) stays the drain's spelling and `tools/agent_chat_tool` imports it publicly — no fold needed, the rule holds |
| `_write_drain_state` 651 via `utils.atomic_json_write` | `serde.write_json_atomic` | NOT a fold, by `serde`'s own docstring: the upstream writer fsyncs and preserves mode; this mirror is read back by `status`, never byte-compared — the lane keeps the upstream call (a public door) |
| `_terminal_forge_rejections` 110 / `_transient_forge_refusals` 147 | typed sets over `ChatErrorKind` | already rule 14; they move to `vocabulary` and drop their underscores |

## 4. Upstream doors — and the one reach UP

| reach | class | door |
|---|---|---|
| `utils.atomic_json_write` 71 (module-level), `tools.async_delegation.{claim_event_delivery, complete_event_delivery, release_event_delivery}` 1415/1444, `tools.process_registry.process_registry` 1538 | FIRST (public; the 2026-09-24 `notify_on_complete` ruling names `process_registry` as a door) | kept, lazy where they are lazy today; `atomic_json_write` moves to `mirror.py` with its one caller |
| **`hermes_cli.harness_parts.persona.chat_turn_message._cmd_mission_chat_message` 1131** — a PRIVATE handler in the CLI, reached from the runtime | not an upstream door — the runtime → CLI edge the `runtime-queue.md` "reaches UP into the CLI namespace" row names for this file, and a private name at that; `tools/agent_chat_tool.py:579` makes the same reach (its sheet §4) | **owner question Q10** (program §9). Default the lane follows: one `agent_runtime/mission_chat_door.py` (`run_mission_chat_turn(args) -> tuple[int, dict \| None]`, bound by `serve/session.py` at boot and by the plugin's CLI registration; unbound ⇒ a typed `MissionChatDoorUnbound` refusal, never a silent no-op); `forge_delivery_turn` calls the door and the lazy import at 1131 is deleted in the CHANGE. Until Q10 lands, the MOVE keeps the import where it is (in `forge.py`), byte-identical |

W0-G6 `private_upstream_imports` rows for this file: none (the private is a fork name). The `undeclared` row closes with the MOVE — except that `forge.py` declaring `__layer__ = "lanes"` while importing `hermes_cli.harness_parts.persona` is exactly the upward edge the gate's `harness_imports` arm counts; the CHANGE (Q10) is what closes it, and the MOVE's landing message says so.

## 5. Dead code (verdict + the grep the lane runs)

No queue row names this file. `git grep -nw` over the 31 defs: every public name has an importer, every private one an in-file caller (`_orphaned_persona_root` 1321 ← 576 and 1571; `_steer_into_busy_turn` 1355 ← 1602). `delivery_client_message_id` 745 is test-pinned and called at 1219. Nothing filed.

## 6. Positive controls — land in the MOVE (ruling Q6)

`BOUNCE_GATES` replaces no routing site (it constrains writers), so Q6 owes no control; its §2 mutation is the positive proof and is pasted in the CHANGE. The MOVE's own control is the killing mutation in §7.

## 7. MOVE hash-proof plan, then the CHANGE

1. **MOVE** `refactor(dispatch_delivery): dispatch_delivery.py → agent_runtime/dispatch_delivery/ (6 modules)` — spans byte-identical with the sha256 table (one row per §1.1 span; the two root resolvers are one span moved into `completions.py`); `__init__` carries the docstring and re-exports the 6 importer names, `sender_persona` (public alias of `_sender_persona`, which stays exported one commit), and the 5 test names; `tools/agent_chat_tool.py:678` retargets to the public name. **Killing mutation for the MOVE:** drop `mirror` from `__init__` → `agent_runtime/status.py` fails to import `delivery_drain_status` → `tests/agent_runtime/test_dispatch_delivery_observability.py::test_status_reads_the_mirror_when_no_drain_runs_in_this_process` reds. `[ds-size]` −1.
2. **CHANGE** `refactor(dispatch_delivery): BOUNCE_GATES guarded at record_bounce; BackgroundDrain.deliver_one; format_elapsed; mission_chat_door (Q10)` — §2 + §3 + the Q10 door with each red pasted; the `harness_imports` row for `forge.py` closes here.

## 8. Lane and what it must not touch

R2 (exec lane B3), second of its three — after `persona_chat_continuity.md` (whose `__init__` it imports from at module level) and before `operator_channels.md` (disjoint). Must not edit in parallel: `dispatch_store.py` (R1's file — consumed by name), `mission_chat_turns.py`, `mission_chat_steer.py`, `turn_visibility.py`, `relay_policy.py`, `status.py`, `core_cache/`, `harness_parts/persona/` (retarget-only for Q10's binding, one line in `serve/session.py` and one in the plugin `__init__`), `tools/agent_chat_tool.py` beyond the one-line retarget at 678 (T1's file; its own sheet takes the door).
