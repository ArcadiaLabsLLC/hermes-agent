# Planned — the canonical persona channel carries no scene claim in storage

**Status:** planned 2026-10-27 (planning lane w1027k-h-plan), replanning row
`RT-GLOBAL-SINGLETON-CANONICAL`. Supersedes
[`global-singleton-persona-instances.md`](global-singleton-persona-instances.md) (left in
place). Owner doc: [`../01-system-architecture.md`](../01-system-architecture.md).

## Problem

A persona's canonical operator channel (`persona_instance_id_for(persona_id)`,
`agent_runtime/persona_assignments/identity.py`; tested by
`is_canonical_persona_channel`) is meant to be runtime plumbing with no scene claim —
the operator ruling of 2026-07-18, "instance = in-level placement", which
`agent_runtime/workspace_scope.py` encodes for the ADVERTISED roster. Storage disagrees:

- **The bind stamps scope on canonicals.** `_apply_open_fields` in
  `agent_runtime/persona_assignments/chat_binding.py` writes any supplied
  `workspace_id` / `realm_id` onto the instance, canonical or not; the launcher supplies
  its active scope on every open.
- **Readers then follow the pointer.** `exclude_global_canonicals` keeps a canonical
  that carries a pointer ("made a scene claim"), so opening an operator chat from a
  level puts that persona on the level's roster and in agents' Runtime HUD — the
  advertising the 2026-07-24 incident and the 07-18 ruling removed for pointerless rows.
  `effective_workspace_id` answers the pointer to `operator_conversation.exact_operator_target`
  (`agent_runtime/operator_conversation.py`), `instance_selection.opened_instance_identity`,
  `peer_directory`, `instance_history` and `prompt_observability/snapshot_frame.py`.
- **Sync and retire already treat canonicals as global.** Realm sync skips them
  (`agent_runtime/persona_instance_sync/projection.py`, `skipped_canonical`;
  `agent_runtime/realm_sync/drift.py`), and retire refuses them
  (`agent_runtime/persona_assignments/retire.py`). Only workspace scoping still reads
  the pointer.

## Decisions

1. **A canonical row may not carry a `workspace_id` or `realm_id`.** This is the 2026-07-18
   ruling applied to storage, not a new product choice: a canonical with a pointer is a
   scene claim made by the act of opening a chat, which is what that ruling says an
   instance is not. A persona is on a level only through a placement.
2. **Read side first, at the store's decode, so no reader changes.** `PersonaInstanceStore`
   decodes a row in two places (`get` and `scan_all`, `agent_runtime/persona_assignments/store.py`);
   both go through one `_decode_instance` that sets `workspace_id` / `realm_id` to `None`
   when `is_canonical_persona_channel` holds. Every reader — `workspace_scope`'s
   functions, `effective_workspace_id`'s five callers — then sees a canonical as global
   without being edited, and `workspace_scope.py` keeps not importing the
   discriminator. Why the store and not a helper in `workspace_scope`: one chokepoint
   instead of five call-site changes, and a forgotten caller cannot keep the old answer.
   `exclude_global_canonicals` keeps its pointer clause (now unreachable for canonicals,
   still correct for the predicate it is passed); its docstring sentence about
   pointer-bearing canonicals is rewritten.
3. **Write side stops stamping.** `_apply_open_fields` skips the scope pointers when
   the instance id is canonical (`row_is_canonical_persona_channel`).
4. **Stored pointers are cleared by the reconciler, recorded.** A new phase in
   `reconcile_persona_instances` (`agent_runtime/persona_instance_identity.py`) clears
   `workspace_id` / `realm_id` on canonical rows, emits `persona_instance.reconciled`
   with `action: "canonical_scope_cleared"`, honours `--dry-run`, and is a no-op the
   second time. It is hygiene: after decisions 2–3 no reader sees the old pointer.
5. **The bare-persona SEND fallback onto the canonical is untouched.** Retiring it is
   the separate "global-row adoption" question `workspace_scope.py` names; this plan
   narrows what is listed, as before, and adds no refusal.
6. **One transient, accepted:** a launcher holding an operator-conversation identity
   that recorded a canonical's old `workspace_id` gets `workspace_changed` once and
   re-selects, which is that refusal's existing purpose.

## Slices

**S1 — canonicals are global on read and write, stored pointers cleared** (row
`RT-GLOBAL-SINGLETON-CANONICAL`, shipped 2026-10-27 by lane w1028a-h-persona: the clearing
phase lives in `persona_assignments/repair.py::clear_canonical_scope_pointers`, called as
the reconciler's phase 6; tests in `tests/agent_runtime/test_canonical_channel_global_storage.py`)

- `agent_runtime/persona_assignments/store.py` — `_decode_instance`, used by `get` and `scan_all`.
- `agent_runtime/workspace_scope.py` — docstring of `exclude_global_canonicals` and the module note.
- `agent_runtime/persona_assignments/chat_binding.py` — `_apply_open_fields` skips
  canonical ids.
- `agent_runtime/persona_instance_identity.py` — the clearing phase.
- `tests/agent_runtime/test_workspace_scope.py`, `tests/agent_runtime/test_persona_instance_identity.py`,
  `tests/agent_runtime/test_persona_assignments.py` — cases below.
- `docs/agent-runtime-harness/01-system-architecture.md` — the canonical-row sentence.

## Test plan

- *Read:* a canonical row stored WITH `workspace_id="ws_a"` is excluded from the
  `ws_a` addressable roster and `effective_workspace_id(…, active_workspace_id=None)` is
  `None`. **Killing mutation:** drop the canonical clause in `_decode_instance` → red.
- *Read, positive control:* a placement row with `workspace_id="ws_a"` is kept and
  answers `ws_a`, through both `get` and `scan_all`. **Killing mutation:** null the
  pointer for every row, or apply the clause in `get` only → red.
- *Write:* `open_chat` on a canonical id with `workspace_id="ws_a"` leaves the stored
  pointer `None`; on a placement id it stores `ws_a`. **Killing mutation:** drop the
  canonical check in `_apply_open_fields` → the first half reds; skip stamping for all
  ids → the second half reds.
- *Migration:* a store with one pointer-bearing canonical and one placement — dry run
  reports one clear and writes nothing; apply clears only the canonical and emits one
  event; a second apply reports zero. **Killing mutation:** clear every row's pointer →
  the placement assertion reds.

## Open questions

None for the owner (decision 1 is the 2026-07-18 ruling; the SEND fallback stays where
the earlier ruling left it).
