# Planned — `machine_roots.json` names its two halves, then merges them (RT-MACHINE-ROOTS-TWO-HALVES, 2026-10-26)

**Owner domain:** runtime data ([02-runtime-data-and-shapes.md](../02-runtime-data-and-shapes.md)), boot
and lifecycle (store epoch).
**Status:** RULED 2026-10-26 (lane w1026a-h-b, by the wave brief's "go with recommendations"); build rows in §5.
**Spec:** [naming-and-address-map-2026-10-25.md](naming-and-address-map-2026-10-25.md) ruling 6.

## 1. What is true today (read 2026-10-26 on `main`)

- `machine_roots.json` (schema 2, `agent_runtime/machine_roots.py`) holds `roots.<name>` — the CONFIG roots
  that `${roots.<name>}` tokens expand to — and `workspace_roots.<ws>.<slot>` — the SLOT FOLDERS a
  workspace's repo slots are bound to (`agent_runtime/workspace_slots.py`).
- The two meet in one place: binding a slot writes `workspace_roots[ws][slot]` and MIRRORS it into
  `roots.<slot>` with `setdefault` — first binding wins, a second workspace binding the same slot name to
  another folder never repoints it, silently.
- Both editions read one namespace; `agent_runtime/store_epoch.py` raises the epoch only for a BREAKING
  shape change (an older build refuses a newer store); an additive change does not.
- `agent_runtime/machine_roots_migration.py` is a different migration (configs' absolute paths into tokens).

## 2. Decisions

1. **Rename additively.** Decided (plan): schema 3 writes `config_roots` and `slot_folders` AND keeps
   writing `roots` / `workspace_roots` as mirrors; readers prefer the new keys and fall back to the old.
   One `store_epoch` registry entry, `breaking: false`. Dropping the old keys is a later BREAKING entry,
   filed only when both editions ship the schema-3 reader.
2. **A slot folder IS a config root, in its workspace.** Decided (plan): `${roots.<name>}` expands in a
   workspace context first — `slot_folders[ws][name]` when the reading config belongs to workspace `ws` —
   then `config_roots[name]`. The `setdefault` mirror is retired: a slot binding never writes a config root.
3. **Ambiguity is typed, never first-wins.** Decided (plan): a token read with NO workspace context whose
   name is bound only as a slot folder resolves when exactly one workspace binds it; when two bind it to
   different folders it yields a typed `PathTokenIssue` `root_ambiguous` naming both workspaces, on the
   existing readiness lanes, and resolves nothing.
4. **Moving existing files.** Decided (plan): the schema-2 → 3 upgrade runs once in the existing
   `workspace_slots` first-read upgrade seam (where schema 1 → 2 already runs): copy `roots` →
   `config_roots` minus entries that are exactly a mirror of a single slot binding (same path as the only
   `workspace_roots[*][name]`), copy `workspace_roots` → `slot_folders`, write both shapes, emit
   `machine_roots.migrated` with the counts. Idempotent: a schema-3 file is not rewritten.

## 3. Recommendation

M1 (additive keys + upgrade), then M2 (workspace-context expansion + typed ambiguity, mirror retired).

## 5. Build rows (hermes `runtime-queue.md`)

`RT-MACHINE-ROOTS-M1-NAMED-HALVES`, `RT-MACHINE-ROOTS-M2-SLOT-IS-ROOT`.
