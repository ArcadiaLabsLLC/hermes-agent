# Layout sheet — `agent/charsheet/draft.py` (lane C1)

Base: `main` @ `28012c8f8a` · sha256 `59035684b4ac243045d5acf36ae28da096bd59d9493a00dce78ede3f446dd1d4` · 2,000 raw / 1,600 code / 24 top-level defs · longest `CharacterDraft.compose` 151 (1586–1736) · chains 0/0 · `str==` 0 · owner doc: the module docstring (the stage machine, the lock, what is auto-approved). 4 production importers (`hermes_cli/charsheet_payload_contract.py`, `hermes_cli/harness_parts/characters/{auto,commands,payloads}.py`) taking `CharacterDraft`, `characters_dir`, `migrate_characters_home`, `path_or_none`, `read_palette`, `_handedness_accepted`, the five `*_FILENAME`/`DEFAULT_THUMB_*` constants and the module itself; 6 test files pinning 21 names including `_migration_entry_id` and `_handedness_accepted`.

**Fork-only file in an upstream directory** (ruling Q2): new modules stay under `agent/charsheet/`. **The class is the file**: `CharacterDraft` is 1,101 code lines (520–1854) with 44 methods — ruling Q8 applies: it moves WHOLE in the MOVE, crossing 800 for exactly that one commit, and the CHANGE splits it by composition. Package named after the file — `agent/charsheet/draft/` — so `from agent.charsheet.draft import CharacterDraft` and `from agent.charsheet import draft` keep resolving.

## 1. Skeleton (owner ruling 2026-09-25: readability first; modules target 100–300 code lines, hard cap 500)

The package `__init__` map, verbatim. The tree is the shape AFTER the CHANGE; the MOVE differs in exactly one file (`draft.py` holds the whole class for one commit, Q8 — the only module in this batch drawn above 500, and only for that commit).

```
agent/charsheet/_fs.py               models   utc_now, write_json_atomic, write_bytes_atomic, slugify, safe_segment — the package's one owner (~45)
agent/charsheet/_runtime_door.py     models   the ONE lazy reach into agent_runtime (shared_characters_dir) — Q9 (~15)
agent/charsheet/draft/
  __init__.py      wiring   the map; re-exports CharacterDraft, the constants and the test-pinned names
  layout.py        models   SCHEMA, Stage, STAGE_ORDER, the *_FILENAME/_DIRNAME and thumb constants        (~40)
  locations.py     stores   characters_dir, drafts_dir, stamp_recorded_home, migration ids                (~70)   entry: characters_dir, drafts_dir
  codec.py         models   spec ↔ dict, revision-key items, path_or_none, read_palette                  (~105)  entry: spec_to_dict, spec_from_dict, read_palette
  migration.py     lanes    migrate_characters_home                                                       (~100)  entry: migrate_characters_home
  draft.py         lanes    CharacterDraft: identity, create/load/list, properties, lock, record_home     (~300 after the CHANGE; 1,101 in the MOVE)  entry: CharacterDraft
  directions.py    lanes    DirectionStage: base image, turnaround, re-roll/approve directions           (~200)
  rows.py          lanes    RowStage: run_rows, reroll_row, add_state                                     (~230)
  thumbs.py        lanes    Thumbs: row_thumb, direction_thumb, _finish_thumb                            (~320)
  compose.py       lanes    Composer: compose (as phases), reopen                                         (~160)
  status.py        policy   status_payload, _item_status                                                  (~115)
  installed.py     stores   sprite_payload, sheet_revision, _handedness_accepted — the installed readers  (~120)  entry: sprite_payload
```

Layers point down: `layout`/`_fs`/`codec` ← `locations` ← `installed`/`status` ← `directions`/`rows`/`thumbs`/`compose` ← `draft` (the class composes the four stage objects and is the only entry the CLI sees). `pipeline` is imported by the four stage modules as a module, never by `layout`/`codec`.

### 1.1 Section map → target modules

| lines | what is there | → module | layer |
|---|---|---|---|
| 1–137 | docstring, imports (`pipeline` as a module 63; `draft_lock`, `revisions`, `spec`; upstream `agent.pet.constants`, `hermes_constants`; **`agent_runtime.profile_home.get_shared_characters_dir` 77** — §4), `SCHEMA`, `STAGES`, the seven `*_FILENAME`/`*_DIRNAME`, `DEFAULT_THUMB_SCALE` 129, `DEFAULT_THUMB_FRAME` 135, `_SLUG_RE` | `draft/__init__.py` (map + re-exports) and `draft/layout.py` (~40: the constants — every importer takes at least one) | wiring / models |
| 140–216, 339–383 | `characters_dir` 143, `drafts_dir` 164, `stamp_recorded_home` 171, `_migration_entry_id` 202; `slugify` 339, `_safe_segment` 345, `_utc_now` 350, `_write_json_atomic` 354, `_write_bytes_atomic` 371 | `draft/locations.py` (~70: the four location functions) and `agent/charsheet/_fs.py` (~45: `utc_now`, `write_json_atomic`, `write_bytes_atomic`, `slugify`, `safe_segment` — §3) | stores / models |
| 219–336 | `migrate_characters_home` 219 (+ `_relocate`), 118 lines | `draft/migration.py` (~100) | lanes |
| 386–514 | `spec_to_dict` 389, `spec_from_dict` 411, `turnaround_item` 456, `row_item` 461, `_strip_filename` 471, `path_or_none` 475, `read_palette` 492 | `draft/codec.py` (~105) — the spec round-trip and the revision keys | models |
| 517–1854 | `CharacterDraft` 520 whole: `create` 530, `load` 628, `list_drafts` 643, the properties 659–762, `generation_lock` 767, `record_home` 792, the `_require_*` guards 828–868, `set_base_image` 870, `run_turnaround` 887, `reroll_direction` 919, `approve_direction` 958, `approve_all_directions` 999, `run_rows` 1041, `reroll_row` 1108, `add_state` 1144, `row_thumb` 1250, `direction_thumb` 1390, `_finish_thumb` 1471, `reopen` 1574, `compose` 1586, `status_payload` 1740, `_item_status` 1814 | `draft/draft.py` (1,101 code — **over 800 for the one MOVE commit, Q8**) | lanes |
| 1857–2000 | `_row_json` 1857, `_sheet_revision` 1870, `sprite_payload` 1879, `_handedness_accepted` 1978 | `draft/installed.py` (~120) — the installed-sheet readers `characters list` and the payload contract call | stores |

Edges: `layout` → nothing; `_fs` → stdlib; `locations` → `_fs`, `layout`, and the runtime door (§4); `codec` → `spec`, `layout`; `migration` → `locations`, `codec`, `_fs`; `draft` → all of the above plus `pipeline`, `draft_lock`, `revisions`; `installed` → `layout`, `codec`, `_fs`. `pipeline` never imports `draft` (checked: `pipeline.py` has no `draft` import), so the package edge is one-way.

**The CHANGE's split of `CharacterDraft`, by composition** (the H4 `loop.py` → `ServeSession` precedent): the class keeps its constructor, `create`/`load`/`list_drafts`, the properties, the lock and `record_home` (~300) and delegates to four objects each holding the fields their methods read — `DirectionStage` (`set_base_image`, `run_turnaround`, `reroll_direction`, `approve_direction`, `approve_all_directions`, `_advance_if_directions_approved`, `_face_offset`; ~200) in `draft/directions.py`, `RowStage` (`run_rows`, `_row_reference`, `reroll_row`, `add_state`; ~230) in `draft/rows.py`, `Thumbs` (`row_thumb`, `direction_thumb`, `_finish_thumb`; ~320) in `draft/thumbs.py`, `Composer` (`compose`, `reopen`; ~160) in `draft/compose.py`, with `status_payload`/`_item_status` (~115) in `draft/status.py`. Every public method keeps its name and signature on `CharacterDraft` — the four importers and the CLI verbs never learn the split happened.

## 2. Routing sites → tables (the CHANGE commit)

W0-G5 holds no row for this file (no ladder, no vocabulary compare). Rule 12 has one site anyway, and rule 17 one floor row:

| site | shape today | replacement | killing mutation |
|---|---|---|---|
| `STAGES` 95 + `_set_stage`/`_require_stage` 828–840 + the per-verb `_require_stage(...)` calls | the stage machine is a tuple of three strings and each verb asks `_require_stage("rows")` by literal | `Stage(StrEnum)` {turnaround, rows, composed} in `layout.py` with `STAGE_ORDER: Final[tuple[Stage, ...]]` and a `VERB_STAGES: Mapping[str, Stage]` beside the guard, so the order a verb requires is one table the docstring's "enforced" sentence points at; the `ValueError` text is unchanged | swap `rows` and `composed` in `STAGE_ORDER` → `tests/agent/test_charsheet_draft.py::test_stages_are_declared_in_qa_order` and `::test_a_row_or_compose_verb_is_refused_while_the_directions_are_unapproved` red |
| `CharacterDraft.compose` 1586 (W0-G7: 151 / 2) | authored-row check 1613 · direction refs 1626 · validation + refusal payload 1640–1656 · clobber guard 1659–1673 · palette measured once 1678 · manifest 1692–1717 | `Composer.collect → validate → guard_slug → write_sheet → manifest`, ≤ 50 each; the "SCOPE FIRST, then the findings" order at 1645 is pinned by `::test_a_refusal_leads_with_the_failure_and_the_scope_it_was_judged_at` | — (a floor row, not a table) |

## 3. Helper folds

| here | duplicate of | verdict |
|---|---|---|
| `_utc_now` 350 | `draft_lock._utc_now` 95, `revisions._utc_now` 74 (same body: `datetime.now(timezone.utc).isoformat()`) | FOLD to `agent/charsheet/_fs.py::utc_now` — same package, byte-identical output; **NOT** `agent_runtime.clock.now_iso` (millisecond `Z` form — a different string, and across the packaging boundary) |
| `_write_json_atomic` 354 | `agent_runtime/mission_chat_steer.py::_write_json_atomic` 343 (W0-G3 `name_groups[33]`) and `serde.write_json_atomic` | NOT a fold: this one fsyncs and writes `indent=2` + trailing newline; `serde`'s pins LF and does not fsync; `mission_chat_steer`'s is compact. Three writers, three byte contracts. The NAME collision is retired by the move (`_fs.write_json_atomic` inside the charsheet package; the steer copy is R2's) — the gate's name arm counts fork-wide, so the sheet records the rename here rather than pretending the bodies match |
| `_write_bytes_atomic` 371 | none | `_fs.write_bytes_atomic` |
| `_sheet_revision` 1870 | `hermes_cli/harness_parts/pets_commands.py::_pet_sheet_revision` 176 (W0-G3 `body_groups[0]`, H2 sheet leftover row in `runtime-queue.md`) | FOLD toward `installed.sheet_revision` (public); the pets command imports it — the H2 row closes with this lane's CHANGE, and the row says so |
| `slugify` 339 / `_safe_segment` 345 | none | `_fs` |

## 4. Upstream doors — and the one reach the package forbids

| reach | class | door |
|---|---|---|
| `agent.pet.constants.{DEFAULT_SCALE, LOOP_MS}` 75, `hermes_constants.get_hermes_home` 76 | FIRST (public) | `agent/charsheet/_upstream_doors.py` (created by the pipeline sheet) — one module holds every upstream name the package reads |
| **`agent_runtime.profile_home.get_shared_characters_dir` 77, module-level** | not an upstream door — a reach in the OTHER direction, into a package the wheel does not ship. `agent/charsheet/__init__.py` says "nothing here imports `agent_runtime`"; `revisions.py:44` and the lock's docstring repeat it; this import breaks all three and is what makes `import agent.charsheet.draft` fail in a plain hermes wheel | **owner question Q9** (program §9). Default the lane follows: the reach stays, moved into `agent/charsheet/_runtime_door.py` as ONE lazy function (`shared_characters_dir()`), called from `locations.characters_dir` at call time so the module imports cleanly and only the call needs the runtime; the three docstrings are corrected to say so; a row is filed (report §rows). If the owner instead retires the packaging boundary, the door is deleted and the import stays where it is |

## 5. Dead code (verdict + the grep the lane runs)

No queue row names this file. `git grep -nw` over the 24 defs: every one has an in-file, CLI or test caller (`_migration_entry_id` is called at 300 and test-pinned; `_handedness_accepted` at 1974 and by `characters/payloads.py`). `reopen` 1574 (11 lines) has one CLI caller (`characters/commands.py:307`). Nothing filed.

## 6. Positive controls — land in the MOVE, before the stage table (ruling Q6)

`tests/agent/test_charsheet_draft.py` already refuses every stage verb out of order (`::test_a_row_or_compose_verb_is_refused_while_the_directions_are_unapproved`, `::test_a_turnaround_verb_is_refused_once_the_stage_has_advanced`, `::test_every_generation_verb_is_refused_after_the_sheet_is_composed`) and `::test_a_mirrored_direction_is_never_a_qa_item` reaches `_require_authored_direction` 851 through `reroll_direction`. The `VERB_STAGES` table therefore lands against a suite that reaches every arm it rewrites; no new control is owed. The lane's positive proof is the killing mutation in §2, run and pasted.

## 7. MOVE hash-proof plan, then the CHANGE

1. **MOVE** `refactor(charsheet): draft.py → agent/charsheet/draft/ (7 modules; CharacterDraft whole, Q8)` — spans byte-identical with the sha256 table (7 rows; the class is one span); `__init__` re-exports the 21 test-pinned names and the 12 importer names; `_fs.py` receives `_utc_now`/`_write_*_atomic`/`slugify`/`_safe_segment` as MOVED spans (the two sibling `_utc_now` copies are deleted in the CHANGE, not here, so the MOVE stays a move). **Killing mutation for the MOVE:** drop `installed` from `__init__` → `tests/agent/test_charsheet_draft.py::test_the_sprite_payload_ships_the_installed_bytes` reds on `sprite_payload`. `[ds-size]` for this commit: `draft/draft.py` is NEW at 1,101 — the W0-G1 fixture gains it for one commit and the landing message says so (Q8).
2. **CHANGE** `refactor(charsheet): CharacterDraft by composition (DirectionStage/RowStage/Thumbs/Composer); Stage + VERB_STAGES; _fs owner; sheet_revision fold` — §1's split, §2, §3, with each red pasted; `[ds-size]` −1 and the fixture row from step 1 deleted.

## 8. Lane and what it must not touch

C1, second of its two, after `pipeline.md` lands (this file imports `pipeline` as a module and the `_upstream_doors` it creates). Must not edit in parallel: `hermes_cli/harness_parts/characters/*` and `hermes_cli/charsheet_payload_contract.py` (retarget-only if a private name moves); `hermes_cli/harness_parts/pets_commands.py` gets exactly one import line in the CHANGE (the `sheet_revision` fold) and nothing else; `agent_runtime/profile_home.py` is not edited under either answer to Q9.
