# Layout sheet — `agent_runtime/persona_chat_continuity.py` (lane R1)

Base: `main` @ `28012c8f8a` · sha256 `7a4f94b5c33afb1b55d63f93e4f7b16644b3f1d2faad6a20a6b812b343f36e0c` · 2,240 raw / 1,646 code / 36 top-level defs · longest `PersonaChatMintReceiptStore.mint` 232 (987–1218, depth 4) · chains 0/0 · `str==` 10 · `isinstance` 25 · owner doc `docs/agent-runtime-harness/04-chat-turn.md` (the lease, the mint, the native boundary). 19 production importers taking 16 names (the four persona CLI modules, `dispatch_delivery`, `native_persistence`, `persona_chat_actor_prewarm`, `persona_chat_durability`, `persona_chat_history/*`, `profile_runner/execute`, `serve/{boot_phases,session}`, `harness_support`, `tools/terminal_tool`); 12 test files pinning 36 names, seven private (`_MAX_*` ×4, `_bound_envelope`, `_signature_component_diff`, `CONTENT_BOUND_PARTS`).

**Package named after the file — `agent_runtime/persona_chat_continuity/`.** The six-line docstring already lists the file's contents as four primitives ("lease, mint-receipt, safe-history, and resident-actor"); the skeleton is those four plus the two the docstring forgot it had grown (the user-content bounds, the clarify tickets).

## 1. Skeleton (owner ruling 2026-09-25: readability first; modules target 100–300, hard cap 500; no flow over three modules)

```
agent_runtime/persona_chat_continuity/
  __init__.py           wiring   the map; re-exports the 16 importer names and the 36 test names
  bounds.py             policy   the composed-user-content bound: BOUND_PART_*/BOUND_ACTION_*, ContentBoundNote, BoundedUserContent, _redacted, _truncate, bounded_text (was _safe_text), _bound_envelope, bound_composed_user_content, _bounded_free_text  (~230)   entry: bound_composed_user_content
  wire.py               policy   the native wire boundary: WIRE_BOUNDARY, WireBoundaryRow, record_wire_boundary_drift, native_wire_row, safe_native_message, safe_native_history, native_lineage_summary, native_history_revision  (~260)   entry: native_wire_row, safe_native_history, safe_native_message, record_wire_boundary_drift, native_history_revision, native_lineage_summary
  lease.py              stores   the chat-root lease and the scopes a turn holds while it runs: tool_execution_scope, chat_root_session_key_scope, PersonaChatBusyError, the lease paths/locks, persona_chat_root_lease, repair_orphaned_chat_turns  (~190)   entry: persona_chat_root_lease, chat_root_session_key_scope, tool_execution_scope, current_tool_execution_scope, repair_orphaned_chat_turns
  mint_receipts.py      stores   PersonaChatMintReceiptStore (the idempotent mint, as Mint phases after the CHANGE) + the dispatch-lineage meta helpers and _atomic_json  (~180)   entry: PersonaChatMintReceiptStore
  clarify_tickets.py    stores   CLARIFY_* words, PersonaChatClarifyTicketStore: mint/resolve/settle/open_ticket_for_session/scan/sweep  (~515 in the MOVE — the class whole, Q8; ~240 after the CHANGE)   entry: PersonaChatClarifyTicketStore
  clarify_index.py      stores   ClarifyTicketIndex — the per-session index the store keeps beside its records (created by the CHANGE from the class's twelve _index_* methods)  (~280)
  runtime_registry.py   stores   ResidentPersonaChatRuntime, _signature_component_diff, PersonaChatRuntimeRegistry, the process-global registry and its initialize/get  (~200)   entry: persona_chat_runtime_registry, initialize_persona_chat_runtime_registry
```

Per entry point, the modules an agent opens (the entry's module plus the modules of what it calls directly; `persona_assignments`, `dispatch_session_policy`, `runtime_hud`, `mission_chat_turns`, `events`, `file_locks` are outside the package and not counted):

| entry point | opens | count |
|---|---|---|
| `persona_chat_root_lease` / `repair_orphaned_chat_turns` / the two scopes | `lease` | 1 |
| `PersonaChatMintReceiptStore.mint` | `mint_receipts` → `lease` (the session-key scope it enters) | 2 |
| `safe_native_history` / `native_wire_row` / `record_wire_boundary_drift` | `wire` → `bounds` (`_redacted`, `bounded_text`) | 2 |
| `bound_composed_user_content` | `bounds` | 1 |
| `PersonaChatClarifyTicketStore.*` | `clarify_tickets` → `clarify_index` | 2 |
| `persona_chat_runtime_registry().acquire / transition / evict` | `runtime_registry` | 1 |

Floor rule (ruling 3a): the three scope functions (733–797, ~55 lines) were first drawn as `scope.py`; sub-100 and only meaningful beside the lease they bracket, so `lease.py` holds both. `clarify_tickets` is the one module drawn above 500, for exactly the MOVE commit (Q8: the class moves whole); the CHANGE's first row composes its index out.

### 1.1 Section map → target modules

| lines | what is there | → module | layer (from imports) |
|---|---|---|---|
| 1–36 | docstring, imports (`paths`, `dispatch_session_policy`, `persona_assignments` ×4, `redaction` ×2), `logger` | `persona_chat_continuity/__init__.py` | wiring |
| 38, 46–392 | `PERSONA_CHAT_SESSION_SOURCE` 38, `_SECRET_RE` 46, `_MAX_CONTENT` 68 … `_MAX_RUNTIME_CONTEXT_CONTENT` 89, `BOUND_PART_*` 92–103, `CONTENT_BOUND_PARTS` 107, `BOUND_ACTION_*` 116–117, `_TRUNCATION_MARKER` 121, `ContentBoundNote` 125, `BoundedUserContent` 136, `_redacted` 167 (lazy `agent.redact`), `_truncate` 206, `_safe_text` 213, `_bound_envelope` 217, `bound_composed_user_content` 266 (lazy `runtime_hud` ×3), `_bounded_free_text` 363 | `persona_chat_continuity/bounds.py` — imports `redaction`, `persona_assignments.safe_assignment_text` | policy |
| 397–729 | `WIRE_BOUNDARY` 397, `WireBoundaryRow` 401, `record_wire_boundary_drift` 500, `native_wire_row` 535, `safe_native_message` 621, `safe_native_history` 633, `_utc_now_iso` 696, `native_lineage_summary` 702, `native_history_revision` 725 | `persona_chat_continuity/wire.py` — imports `bounds` | policy |
| 39–41, 733–979 | `_TOOL_EXECUTION_SCOPE` 39, `tool_execution_scope` 733, `current_tool_execution_scope` 741, `chat_root_session_key_scope` 746 (lazy `tools.approval_context`), `PersonaChatBusyError` 800, `_root_stem` 809, `_lease_paths` 815, `_try_lock` 821, `_unlock` 833, `persona_chat_root_lease` 846, `repair_orphaned_chat_turns` 921 (lazy `mission_chat_turns`, `hermes_time`, `events`, `models`) | `persona_chat_continuity/lease.py` — imports `paths`, `file_locks` (§3) | stores |
| 982–1218, 1945–1998 | `PersonaChatMintReceiptStore` 982 (`_path`, `mint`; lazy `persona_chat_durability`), `_DISPATCH_LINEAGE_KEYS` 1945, `_stored_dispatch_lineage` 1948, `_dispatch_lineage_meta` 1971, `_atomic_json` 1995 | `persona_chat_continuity/mint_receipts.py` — imports `paths`, `persona_assignments` (`PersonaInstanceStore`, `persona_chat_session_id_for`), `dispatch_session_policy`, `lease` | stores |
| 1224–1938 | `CLARIFY_TICKET_TTL_SECONDS` 1224, `CLARIFY_TOKEN_PREFIX` 1232, `CLARIFY_TICKET_OPEN/ANSWERED/REBOUND` 1237–1239, `PersonaChatClarifyTicketStore` 1242 (28 methods, of which twelve are `_index_*`/`_read_index`/`_write_index`/`_rebuild_index`/`_ensure_index`/`_invalidate_index`/`_sweep_index`) | `persona_chat_continuity/clarify_tickets.py` (whole, MOVE) → `clarify_tickets.py` + `clarify_index.py` (CHANGE) — imports `paths`, `serde`? no: `json`/`os`/`uuid` only | stores |
| 2002–2240 | `ResidentPersonaChatRuntime` 2002, `RESIDENT_SIGNATURE_DIFF_RECEIPT` 2028, `_signature_component_diff` 2031, `PersonaChatRuntimeRegistry` 2059, `_REGISTRY` 2224, `initialize_persona_chat_runtime_registry` 2227, `persona_chat_runtime_registry` 2239 | `persona_chat_continuity/runtime_registry.py` — imports stdlib only | stores |

Edges point down: `wire` → `bounds`; `mint_receipts` → `lease`; `clarify_tickets` → `clarify_index`; the rest are leaves. The lazy reaches into `mission_chat_turns` (940) and `runtime_hud` (286) stay lazy — both import this package back (`mission_chat_turns` reads the lease through `persona_chat_root_lease`), and `lease.py`/`bounds.py` import neither at module level, so no cycle is created by the package. `dispatch_delivery` (its own sheet) imports `PersonaChatBusyError` and `persona_chat_root_lease` at module level from `__init__`, which keeps working.

## 2. Routing sites → tables (the CHANGE commit)

| site (base line) | fixture row | replacement | killing mutation |
|---|---|---|---|
| `PersonaChatRuntimeRegistry.transition` 2159: `if state not in {"cold", "busy", "hot", "failed"}` | `\|vocab\|failed` — `failed` is a fork-wide word only because `states.TaskState`/`RunState`/`turn_visibility` declare it; the registry's state vocabulary is its own | **not enum-ised** (batch-1 rule): `runtime_registry.RUNTIME_STATES: tuple[str, ...] = ("cold", "busy", "hot", "failed")` beside the class and `transition` reads it by name; the gate's arm counting a `states.py` member here is the class defect rowed once (report §rows) | drop `"hot"` from the tuple → `tests/agent_runtime/test_persona_chat_continuity.py::test_24_registry_observer_truth_and_transitions` reds |
| `role == "user"` 563, `item["role"] == "assistant"` 679, `== "tool"` 674/690 (`native_wire_row`, `safe_native_history`) | not fixture rows (no fork vocabulary declares the OpenAI wire roles); `persona_chat_history/vocabulary.py::WIRE_ROLES` maps `user`/`assistant`/`tool` to `MessageRole` but is a different question (projection, not the wire) | `wire.WIRE_ROLE_USER / ASSISTANT / TOOL` constants — boundary checks against the provider's wire, read by name; no table (these are validate-then-keep guards, rule 12's BOUNDARY case) | swap `WIRE_ROLE_TOOL` and `WIRE_ROLE_ASSISTANT` in `safe_native_history`'s orphan-drop → `::test_18_safe_history_drops_orphan_tool_results` reds |
| `key == "predecessor_chat_session_id"` 1988, `key == "platform_message_id"` 578 | key-name guards on a payload — BOUNDARY | unchanged | — |

W0-G7 floor rows (2), plus the clarify split:

| row | lines / depth | phases (comment map) | after |
|---|---|---|---|
| `PersonaChatMintReceiptStore.mint` 987 | 232 / 4 | precondition through the bind seam 1033–1052 · the replay signal 1072 · EARLY BIND (the whole remaining defect, 1088–1094) · session/meta/title · commit, and the retraction that restores the pointer it found | `Mint(store, request).precondition → receipt → early_bind → session → title → commit`, with `retract()` the one place a failed write undoes the bind (`::test_a_transcript_write_that_fails_retracts_the_bind_it_was_ordered_behind`); each ≤ 50; the 159-line `try` at 1060 becomes the phase sequence with one `except` |
| `persona_chat_root_lease` 846 | 73 / **5** | open · lock · owner file · yield · release order unlink-owner → unlock → close (890–895) | a `_release(fd, paths)` function holding the three-step release with its two WARNINGs; the context manager is then `open → lock → yield → _release`, depth 3; `::test_09a_a_failed_byte_unlock_is_reported_and_release_still_works` pins the order |
| `PersonaChatClarifyTicketStore` 1242 (not a floor row; the module over 500) | 509 code | the twelve index methods (1307–1590, 1856–1899) are one concept: a per-session pointer index with its own rebuild/sweep, invalidated by the store's writes | `clarify_index.ClarifyTicketIndex(root)` with `lookup / add / drop / rebuild / sweep / invalidate`; the store holds one and calls it — `::test_the_open_ticket_lookup_does_not_read_every_ticket`, `::test_a_rebuild_cannot_drop_a_pointer_minted_while_it_scanned`, `::test_the_ticket_loop_and_the_index_sweep_share_one_cutoff` pin the join |

`str==` 10 → ≤ 4 at review.

## 3. Helper folds

| here | duplicate of | verdict |
|---|---|---|
| `_try_lock` 821 / `_unlock` 833 (fd-based, raw `OSError`) | `mission_chat_turns._lock_fd_exclusive_nonblocking` 1006 / `_unlock_fd` — W0-G3 `body_groups[6]`, `[7]`, byte-identical; program §4 names `file_locks.try_lock_exclusive/unlock` the authority | FOLD — but **not onto `try_lock_exclusive(handle)`**: that one takes a file HANDLE, pads an empty file and translates `errno` into `LockUnavailable`; the fd pair raises the raw `OSError` the lease's `except` reads (`PersonaChatBusyError` is raised from it). So `file_locks` gains `try_lock_fd(fd)` / `unlock_fd(fd)` as MOVED spans (behaviour-identical), both copies are deleted, and `mission_chat_turns.py` gets a two-line retarget (R2's file — "tree wins") |
| `_utc_now_iso` 696 | `mission_chat_phases._utc_now_iso` 163, `mission_chat_turns._utc_now_iso` 1468 (same name, three files); `clock.now_iso` is MILLISECONDS `Z`, this one MICROSECONDS `Z` | NOT a fold onto `now_iso` (a different string — `native_history_revision` hashes it). The lane diffs the three bodies: identical ⇒ `clock.now_iso_micros()` is created and all three fold; different ⇒ this one is renamed `wire_stamp` and the name row stays with R2 |
| `_safe_text` 213 | nine `_safe_text` in the fork (program §4); `serde.safe_text` is the survivor | NOT a fold: this one redacts through `agent.redact` and appends `_TRUNCATION_MARKER`; `serde.safe_text` collapses whitespace and cuts. Renamed `bounded_text` (public in `bounds`), which retires this file's share of the name group |
| `_atomic_json` 1995 | `serde.write_json_atomic` (indent 2, LF-pinned), `mission_chat_steer._write_json_atomic` (compact) | NOT a fold: compact `sort_keys` bytes, no `mkdir`; the receipt path is hashed into `paths.persona_chat_mint_receipt_path`. Stays in `mint_receipts` under its unique name |
| `_redacted` 167 | none (`redaction.py` holds patterns, not this walker) | stays in `bounds` |

## 4. Upstream doors

All FIRST (public): `agent.redact.redact_sensitive_text` 199, `tools.approval_context.{set_current_session_key, reset_current_session_key}` 786, `hermes_time.now` 961 (all lazy). W0-G6 `private_upstream_imports` rows for this file: none. The `undeclared` row closes with the MOVE. No widening.

## 5. Dead code (verdict + the grep the lane runs)

| row (`dead-code-burn-down-queue.md`, second instalment, R1) | verdict | proof |
|---|---|---|
| `PersonaChatClarifyTicketStore._scan_open_ticket_for_session` 1789 (17, "0 hits") | KEEP, untested live — called at 1766, the index-miss fallback ("Correctness must never depend on the index existing") | `git grep -n _scan_open_ticket_for_session agent_runtime` → def + 1 call; control §6 |
| `PersonaChatRuntimeRegistry.finish` 2139 (16, "0 hits") | KEEP, live AND tested — `hermes_cli/harness_parts/persona/chat_turn_commit/settle.py:276` calls `runtime_registry.finish(`; `::test_31_resident_finish_detaches_turn_handles_without_erasing_history` names it | `git grep -n "registry.finish(" hermes_cli` → 1; the census row is closed as a false negative with that grep in the CHANGE body |

Nothing else: `git grep -nw` over the 36 defs finds a caller for each.

## 6. Positive controls — land in the MOVE (ruling Q6)

One case in `tests/agent_runtime/test_persona_chat_continuity.py`: a store whose index cannot be written (monkeypatch `_write_index` to raise `OSError`) still answers `open_ticket_for_session` with the newest open ticket — the arm at 1766 reached, before `ClarifyTicketIndex` is composed out and the fallback becomes `index.lookup() or store.scan()`. No table replaces a routing site in §2, so no other control is owed by Q6; the two §2 mutations are run and pasted in the CHANGE.

## 7. MOVE hash-proof plan, then the CHANGE

1. **MOVE** `refactor(persona_chat_continuity): persona_chat_continuity.py → agent_runtime/persona_chat_continuity/ (6 modules; clarify store whole, Q8); file_locks.try_lock_fd/unlock_fd` — spans byte-identical with the sha256 table (one row per §1.1 span; `_try_lock`/`_unlock` are moved spans INTO `file_locks.py`, and `mission_chat_turns.py` gets its two-line retarget); `__init__` re-exports the 16 + 36 names. **Killing mutation for the MOVE:** drop `wire` from `__init__` → `agent_runtime/native_persistence.py` fails to import → `tests/agent_runtime/test_persona_chat_wire_boundary.py` reds at collection. The §6 control lands here. `[ds-size]` −1; `clarify_tickets.py` is new at ~515 for this one commit (W0-G1 fixture row, deleted in step 2).
2. **CHANGE** `refactor(persona_chat_continuity): ClarifyTicketIndex composed out; Mint phases; _release; RUNTIME_STATES, WIRE_ROLE_*; bounded_text` — §2 + §3 with each red pasted; the two §5 rows close.

## 8. Lane and what it must not touch

R1 (exec lane B3), FIRST of its three — `dispatch_delivery` imports two of its names at module level and lands next. Must not edit in parallel: `persona_assignments/` (R1's landed package, consumed by name), `persona_chat_history/`, `persona_chat_durability.py`, `native_persistence.py`, `profile_runner/execute.py`, the persona CLI modules (all keep their paths through `__init__`); `mission_chat_turns.py` receives exactly the two-line lock retarget in the MOVE and, if the bodies match, the `_utc_now_iso` fold in the CHANGE — nothing else; `file_locks.py` gains the two functions and nothing else.
