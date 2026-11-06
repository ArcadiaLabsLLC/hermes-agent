# Planned — renaming `recall_shared_projects` across mixed editions (RT-WS-ABSORB-RECALL-FIELD-RENAME, 2026-11-06)

**Status:** plan by lane w1105i-hm; S1 built, the other slices filed as rows (§5). Group: `workspace-absorbs-projects`.
**Owner domain:** persona-instance replication (`agent_runtime/persona_instance_sync/__init__.py`, its map) and the
slot lane (`agent_runtime/persona_slots.py`).
**Read (code, no live run):** hermes `origin/main` `3693670cf1` — `agent_runtime/models.py::PersonaInstance`,
`agent_runtime/persona_instance_sync/contract.py::PERSONA_INSTANCE_ALLOWED_KEYS`,
`agent_runtime/persona_instance_sync/projection.py` (`_OMITTED_WHEN_OFF`, `project_persona_instance`,
`refuse_persona_instance`, `persona_instance_def_hash`), `agent_runtime/persona_instance_sync/pull.py::_local_projection_hash`,
`agent_runtime/persona_assignments/store.py` (`_decode_stored_instance`, `_SLOT_LANE_FIELDS`),
`agent_runtime/persona_slots.py` (`set_instance_recall`, `show_instance_slots`).

## 0. What is true today

One boolean, `PersonaInstance.recall_shared_projects` (default off), has its Project-edition name on four
surfaces, and they do not move together:

| surface | who reads it | what an older edition does with a new key |
|---|---|---|
| the instance YAML on disk (`persona_assignments/store.py`) | this machine only | an older build reading a newer store drops the unknown key (`serde._coerce` keeps only dataclass fields), so a downgrade reads recall OFF |
| the sync projection body (`store/persona_instances.yaml`, `PERSONA_INSTANCE_ALLOWED_KEYS`) | every realm member's pull door | **refuses the whole row `unexpected_key`** (`refuse_persona_instance`) — the instance stops replicating to that member |
| the projection hash (`persona_instance_def_hash` over the projected body) | the pull's baseline and drift test | a body spelled with the new key hashes differently from the same fact spelled with the old one, so two editions disagree that nothing changed |
| the RPC reply of `runtime.persona.instance.slots.show` / `recall.set` | the launcher's recall switch | both keys are already answered (RT-WS-ABSORB-PERSISTED-NAMES-MIGRATE, `745a1e6f66`) |

`_OMITTED_WHEN_OFF` keeps the key out of a body while it is off, so today the hazard fires only for an
instance whose recall is ON, on a realm with a member one edition behind.

## 1. The options

- **A — rename everything at once.** A member one edition behind refuses every recall-on instance until it
  upgrades. Rejected: per-entity refusal is silent to the operator on the old member.
- **B — bump `PROJECTION_SCHEMA_VERSION`.** The pull side never reads the projection head's `schema_version`
  (nothing under `persona_instance_sync/` does), so a bump changes nothing for an older member: it still refuses
  the row. Rejected: it buys no protection.
- **C — read-both first, write-new later (recommended).** The pull door and the store learn the new key as an
  ALIAS that normalizes to one canonical spelling before the allowlist check and before hashing; publishing
  keeps the old key until every member's edition reads the new one; then publishing flips, and the alias of the
  old key stays read-only for a release.

## 2. Recommendation — C, in four slices

- **S1 — accept both, publish old (safe now).** One alias table in `persona_instance_sync/contract.py`
  (`{"recall_shared_workspaces": "recall_shared_projects"}`); `refuse_persona_instance` and the remote-body hash
  read the body through it (a body carrying BOTH keys with different values refuses `unexpected_key` — two
  answers for one fact); `_decode_stored_instance` reads either key from YAML. Nothing published changes, so an
  older member sees exactly today's bytes. **Safe now:** it only widens what this edition accepts.
- **S2 — the field rename, local.** `PersonaInstance.recall_shared_workspaces`; the store writes the new key and
  reads either (S1's decoder); the projection still publishes the OLD key (a projection-side spelling map, the
  inverse of S1's alias), so the wire and the hash are unchanged. Every Python reader is repointed in the same
  commit (`workspace_chat_recall.py`, `persona_slots.py`, `persona_assignments/store.py::_SLOT_LANE_FIELDS`).
- **S3 — publish the new key.** Flips the projection spelling map. Gated: only once every realm member's
  edition carries S1 — there is no edition floor in the sync today, so the gate is a release ruling (the
  release that ships S1 is named in the row) or an edition-floor field added to the projection head first.
  Because S1 hashes the canonical spelling, S1 members agree with S3 members that nothing changed.
- **S4 — drop the old `slots.show` / `recall.set` reply key.** Waits on launcher `MC-RECALL-SWITCH-KEY-REPOINT`
  (the launcher reads `recall_shared_workspaces`). Independent of S1–S3.

## 3. Tests each slice lands with

- S1: a pulled body spelled with the new key mints / updates the replica with recall on and hashes equal to the
  old-key body; a body carrying both keys disagreeing refuses `unexpected_key`; a YAML row with the new key loads.
  Killing mutation: drop the alias normalization before the allowlist check → the new-key body refuses.
- S2: the YAML written carries `recall_shared_workspaces`; the published body still carries
  `recall_shared_projects`; the projection hash of a recall-on instance is byte-identical before and after.
- S3: the published body carries the new key; an S1-shaped reader (alias on) hashes it equal.

## 4. Not in scope

The on-disk shared chat source and index (`workspace_shared`) migrated already (`745a1e6f66`).

## 5. Slice rows

S1 is built with this plan (lane w1105i-hm, the commit closing `RT-WS-ABSORB-RECALL-FIELD-RENAME`):
`persona_instance_sync/contract.py::PERSONA_INSTANCE_KEY_ALIASES` + `canonical_instance_body`, read by
`pull.py::PullPass._row_context` before the door and the hash, and by `persona_assignments/store.py::
_decode_stored_instance`. The rest are rows: `RT-WS-RECALL-RENAME-S2-FIELD` (READY),
`RT-WS-RECALL-RENAME-S3-PUBLISH` (BLOCKED owner decision — which release is the edition floor),
`RT-WS-RECALL-RENAME-S4-DROP-REPLY-KEY` (BLOCKED launcher `MC-RECALL-SWITCH-KEY-REPOINT`).
