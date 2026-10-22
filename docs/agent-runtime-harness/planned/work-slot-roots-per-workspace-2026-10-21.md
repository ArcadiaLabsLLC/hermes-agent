# Planned — slot roots and Work worktrees keyed by workspace and checkout, not by slot name — 2026-10-21

**Owner domain:** multi-device ([09](../09-multi-device-runtime.md) § Repo slots, § Machine roots) and
the Work lane ([06](../06-office-and-board.md) § The todo board; plans
[work-on-markdown-2026-10-18.md](work-on-markdown-2026-10-18.md) §5,
[p10-work-2026-10-19.md](p10-work-2026-10-19.md) §2.5).
**Status:** IMPLEMENTATION-READY (design lane w1021i-plans). One doc, no code. Two rows, one mechanism:
a name-only key where the thing keyed is per workspace (the root) or per checkout (the worktree).
**Measured / read:** 2026-10-21 against hermes `origin/main` d087df7035.

Rows: `RT-SLOT-ROOT-NAME-GLOBAL` (§2–3), `RT-WORK-WORKTREE-KEYED-BY-SLOT` (§4) — runtime-queue
§ Fork-owned.

## 1. What is true today (file::symbol)

- **Machine roots** (`agent_runtime/machine_roots.py`): `machine_roots.json` is `{schema_version,
  roots: {<name>: <abs path>}}`, `_ROOT_NAME_RE = ^[A-Za-z0-9_]+$`, read by `load_machine_roots` (cached),
  written only by `write_machine_roots`. The SAME registry serves two purposes: config path tokens
  (`${roots.eternia_launcher}/…`, expanded by `expand_config_paths`, `flutter_build_guard`,
  `repo_context`) and workspace slot binds.
- **Slot bind** (`workspace_slots.py::bind(workspace_id, slot, path)`) checks the slot is declared by
  THAT workspace, then writes `roots[slot] = path` — the workspace id is dropped at the write.
  `bound_path(slot)` has no workspace argument. Readers: `work_store/board.py::_slot_board`,
  `work_store/writer.py::_clone`, `work_store/default_brain.py` (`_declare_brain_slot` binds
  `DEFAULT_BRAIN_SLOT = "brain"`, `_settle_pending`, the `here = bound_path(DEFAULT_BRAIN_SLOT)` read),
  `workspace_slot_setup.py` (`clone_slot`, `run_step`), `workspace_slots_probe.py::report`,
  `persona_slots.py` (×2), `slot_census` (`roots.get(name)` per workspace per slot → `BoundSlot(workspace_id,
  name, path)`), `snapshot_slots`.
- The environment half of a fill is ALREADY per workspace: `workspace_slot_env.py::slot_fill(workspace_id,
  slot)` in `machine_slot_env.json`. Only the root half is global.
- **The defect:** two workspaces each promote a default brain → each `_declare_brain_slot` → `bind(ws,
  "brain", <ws's brain dir>)` → the second write repoints `roots.brain`; workspace 1's board now reads
  workspace 2's brain (and `slot_census` lists `brain` bound for both at the second path).
- **Worktrees** (`paths.py::work_worktree_dir(ws, slot)` = `work/<ws>/worktrees/<slot>`):
  `writer.py::Writer.__init__` sets `self.worktree` from it; `_ensure_worktree` compares
  `_common_dir(worktree)` with `_common_dir(clone)` and `rmtree`s a worktree of another checkout
  (p10-work §2.5's comment names the default brain and a declared `brain` slot sharing it). While both
  boards are live (the default board until its binding is `retired_into`, the declared slot once bound) each
  write flips the worktree: `rmtree` + `worktree add` + sparse-checkout per op.

## 2. Decisions

- `Decided (plan):` **a workspace-scoped root is keyed `<workspace_id>/<slot>` in a second map,
  `workspace_roots`, in the same registry file;** `roots` keeps the config-token namespace exactly as it
  is. Reason: `${roots.<name>}` is a MACHINE fact a config token names by a bare name and
  `_ROOT_NAME_RE` forbids `/`, so folding workspace ids into `roots` would either break the token
  grammar or leak slot binds into config expansion. Two maps, one file, one write site.
- `Decided (plan):` **`bound_path(slot, *, workspace_id)` — the workspace is required.** Every reader
  today has the workspace in hand (§1); the signature change is the gate that no caller keeps reading
  the global key. A slot that is also a config root (an operator binds `eternia_launcher` for a
  workspace AND configs reference `${roots.eternia_launcher}`) keeps working through a one-way
  mirror: `bind` writes `workspace_roots[ws][slot]` and, when `roots[slot]` is absent, ALSO
  `roots[slot]` (never overwriting an existing config root — the mirror fills, it does not repoint).
- `Decided (plan):` **migration is read-time, once, recorded.** `load_machine_roots` returns both maps
  (`MachineRoots.workspace_roots: Mapping[str, Mapping[str, str]]`). A legacy registry (no
  `workspace_roots`) is upgraded by `workspace_slots.slot_census` on first call: for every workspace
  of the active realm and every slot it declares, `roots.<slot>` (if it exists and is a dir) becomes
  `workspace_roots[ws][slot]`; `schema_version` bumps to 2; a receipt `machine_roots.migrated
  {workspaces, slots}` is logged. A name bound by TWO workspaces in the legacy map is migrated to the
  one whose declaration's `repo.clone_url` matches the checkout's `origin` (`workspace_slots_probe`
  already computes `remote_mismatch`); an unmatched second workspace is left UNBOUND with a receipt
  `machine_roots.migration_ambiguous {slot, workspaces}` — the operator re-binds through Locate. Fail
  closed: never guess a brain.
- `Decided (plan):` **Hermes's worktree is keyed by the CHECKOUT it is cut from**:
  `work/<ws>/worktrees/<slot>-<checkout_token>` where `checkout_token` is the first 12 hex of
  `sha256(os.path.normcase(os.path.realpath(<git common dir>)))`. Two boards over one checkout (the
  default brain before and after promotion, same `.git`) share one worktree as they should; two
  checkouts never collide; the `rmtree`-another-checkout arm in `_ensure_worktree` becomes
  unreachable and is deleted. A stale worktree directory (checkout moved) is pruned by
  `git worktree prune` on the clone as today, and its directory removed by `retire_binding`
  (`default_brain.py`) and by a new `writer.drop_worktrees(ws, slot)` called from
  `workspace_slots.declare` when a slot is tombstoned.

## 3. Stages — the root

**R1 — registry schema v2** (`machine_roots.py`). `MachineRoots` gains `workspace_roots`;
`_read_registry_file` reads it (absent → `{}`), validating each inner key with `_ROOT_NAME_RE` and each
workspace key with the workspace-id token rule (`paths.safe_path_token` round-trips it);
`write_machine_roots(roots, *, workspace_roots=None, dry_run, path)` writes both maps (a `None`
`workspace_roots` keeps what the file has — one write site, additive signature).
Tests (`tests/agent_runtime/test_machine_roots.py`): round-trip both maps; a legacy v1 file loads with
`workspace_roots == {}`; `${roots.x}` expansion ignores `workspace_roots` entirely. Killing mutation:
let `_expand_text` fall back to `workspace_roots` → the "ignores" test reds.

**R2 — `bound_path(slot, *, workspace_id)` and `bind` write the scoped key** (`workspace_slots.py`).
`bind` writes `workspace_roots[ws][slot]` and the fill-only mirror into `roots`. Every reader in §1
passes its workspace. `slot_census` reads `workspace_roots[ws].get(name)`; `snapshot_slots` likewise.
Tests (`tests/agent_runtime/test_workspace_slots.py`): two workspaces each declare `brain` and bind
different dirs → `bound_path("brain", workspace_id=ws1)` and `…ws2` differ and `slot_census().bound`
lists both with their own paths; binding `eternia_launcher` fills `roots.eternia_launcher` only when
absent. Killing mutations: (a) `bind` writes `roots[slot]` as before → the two-workspace test reds (ws1
reads ws2's dir); (b) the mirror overwrites → the "only when absent" test reds.

**R3 — the one-time migration** in `slot_census` (the first reader every boot path reaches:
`builds/detect`, the board, the probe). Tests: a v1 registry with `roots.brain` and one workspace
declaring `brain` → migrated, receipt logged, file rewritten v2; two workspaces declaring `brain` whose
`origin` differ → the matching one bound, the other unbound with the `migration_ambiguous` receipt.
Killing mutation: migrate the ambiguous name to the FIRST workspace → the ambiguity test reds.

**R4 — the default brain** (`default_brain.py`): `_declare_brain_slot` / `_settle_pending` /
`promote_default_brain`'s `here` read pass `workspace_id`. Test
(`tests/agent_runtime/work_store/test_default_brain_promote.py`): promote in ws1 then ws2 (fake
GitHub) → ws1's `default_board`/`declared_boards` still read ws1's brain dir. Killing mutation: revert
R2's `bind` → red.

## 4. Stages — the worktree

**W1 — `paths.work_worktree_dir(workspace_id, slot, checkout_token)`** (`paths.py`) and
`work_store/writer.py::checkout_token(clone: Path) -> str` (reads `git rev-parse --git-common-dir`,
realpath, normcase, sha256[:12]). `Writer.__init__` computes `self.worktree` lazily in `_clone()`
(the clone is only known there), stored on the instance as today. Batch's `lane_git.py::worktree_beside`
is a different tree (beside the operator's clone) and is untouched.
Tests (`tests/agent_runtime/work_store/test_writer_worktree.py`): two boards over one checkout share a
worktree path; a default board and a declared slot over two different repos get two paths and ten
alternating writes create exactly two worktrees (count `worktree add` calls through the fake git: 2).
Killing mutation: key by slot only → the alternating test reds (10 adds).

**W2 — delete the "another checkout's worktree" arm** in `_ensure_worktree`; what remains is prune →
exists-and-same-common-dir → return; else add. A worktree dir whose `.git` points at a checkout that no
longer exists is removed (the existing `rmtree` when `_common_dir` fails) — keep that arm, it is the
moved-checkout case, with a `work.worktree_stale {slot, path}` receipt. Test: a worktree whose checkout
was deleted is recreated once, receipt logged. Killing mutation: drop the receipt → red.

**W3 — lifecycle:** `retire_binding` removes `work/<ws>/worktrees/brain-<token of the default brain>`
(prune on the brain repo first); `workspace_slots.declare` calls `writer.drop_worktrees(ws, slot)` for
each tombstoned slot (every `<slot>-*` under the workspace's worktrees dir; prune on the bound clone when
still bound). Tests: retire → directory gone; tombstone → gone. Killing mutation: skip the prune → the
`git worktree list` assertion on the clone reds (a registered but missing worktree).

## 5. Build cut and ordering

R1 → R2 → R3 → R4 (one lane, one CHANGE commit per stage is fine; R2 and R4 may share), then W1 → W2 →
W3 (one lane). W depends on nothing in R (the writer keys by `_common_dir`, not by `bound_path`), so the
two lanes run concurrently; land R first because its migration receipt is what the owner reads on the
next boot.

## 6. Out of scope

The launcher's Locate / Bind UI (it calls `slots.bind` with the workspace it shows — no change on the
wire; the launcher row is a note, not a change). `machine_slot_env.json` (already per workspace). The
config-token namespace and `scripts/machine_roots_migration.py` (config paths, not slots).

## 7. Open rulings

None. (The ambiguous-legacy-bind rule — leave the non-matching workspace unbound, never guess — is a
fail-closed default the owner can relax later; it affects only registries written before this lands.)
