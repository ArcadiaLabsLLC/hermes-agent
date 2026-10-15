# Layout sheet — `agent_runtime/snapshot.py` (lane R3)

Base: `main` @ `bf4377f226` · 2,814 raw / 1,775 code / 53 top-level defs · longest `_parity_envelope` 338 (1083–1420) · chains 1/1 · `str==` 3 · `isinstance` 30 · owner doc `docs/agent-runtime-harness/02-runtime-data-and-shapes.md` (the frame) and `04-boot-and-lifecycle.md` (the build). **The hub**: 38 module-level fork imports (20–65) including six other Wave 2 files (`core_cache`, `office_store`, `persona_assignments`, `persona_chat_history`, `prompt_observability`, `realm_sync`), 18 production importers, 57 test files, 15 pinning 17 private names through 15 `setattr` sites — and five private names imported by PRODUCTION (`_parity_envelope`, `_workspace_summary`, `_realm_summary`, `_office_actor_summary_row`, `_board_card_row`). Four W0-G7 rows, two of them the contract-history class (Q3).

**Package `agent_runtime/snapshot/`** (named after the file; `stream.py`, `core_cache.py:1802` and `office_store.py:771` reach it lazily by attribute or name — `__init__` satisfies both). The 09-21 R3 row (`build, parity, warnings, sections`) stands; `parity` is spelled `envelope` here (`agent_runtime/parity.py` already exists and this module imports it), and `boards`, `offices`, `summaries`, `details`, `receipts`, `build_log`, `context` are added.

## 1. Section map → target modules

| lines | what is there | → module | layer |
|---|---|---|---|
| 1–156 | the 38 imports, `SNAPSHOT_CONTRACT_VERSION = 54` (92), `SnapshotSummary` 98, `SnapshotBuildContext` 118, `_SNAPSHOT_BUILD_CONTEXT` 124, `snapshot_build_context_scope` 130 | `snapshot/context.py` (~90) — the contract version lives here, NOT in `__init__`, so `core_cache.contract_versions` (the core_cache sheet §1) reads a leaf | models |
| 157–348 | `_persona_chat_history_frame` 157, `_keyed` 188, `_runtime_paths_diagnostic` 219, `_ARCHIVED_CONVERSATION_SECRET_RE`, `_BUILD_COALESCE` 261, `BUILD_ROLE_*` 279–302, `BUILD_CALLER_UNKNOWN`, `BUILD_SECTIONS_WAIT_THRESHOLD_MS`, `build_receipt_facts` 317 | `snapshot/receipts.py` (~150): `BuildRole(StrEnum)` — rule 14 | policy |
| 349–509 | `_sections_top`, `_log_snapshot_build_core` 369, `AGENTS_READINESS_SPLIT_RECEIPT` 428, `_log_agents_readiness_split`, `_record_build_info`, `_build_caller`, `_timed_section` 496 | `snapshot/build_log.py` (~140) | policy |
| 510–746 | `build_snapshot` 510 (216, **depth 5**), `_build_snapshot_uncoalesced` 728 | `snapshot/build.py` (~230) | lanes |
| 747–1081 | `_build_snapshot_in_runtime_scope` 747 (334) | `snapshot/sections.py` (~330) — CHANGE → `SECTIONS` table (§2) | lanes |
| 1083–1469 | `_parity_envelope` 1083 (338 — of which 1119–1160 are the contract changelog, versions 43–54), `_snapshot_payload_size`, `_projection_age_ms`, `_runtime_root_identity`, `_runtime_profile_identity` | `snapshot/envelope.py` (~200 after the changelog moves to `02-runtime-data-and-shapes.md` § contract history — rule 7 / Q3) | policy |
| 1470–1685 | `MAX_BOARD_CARDS_PROJECTED`, `BOARD_CARD_DESC_LIMIT`, `_mask_board_secrets`, `_board_card_row` 1484, `_board_conflict_card_ids`, `board_summary_row` 1528 (64), `BoardsProjection` 1594, `_boards_summary` 1604 (depth 4, + `_card_unpublished`), `_board_parity_warnings` 1657 | `snapshot/boards.py` (~180) | stores |
| 1686–2003 | `MAX_OFFICE_ACTORS_PROJECTED` 1686, `_office_actor_summary_row` 1689, `office_summary_row` 1717 (88), `OfficesProjection` 1807, `_offices_summary` 1827 (92, depth 4, + `_actor_unpublished`), `_ORPHANED_OFFICE_DETAIL`, `_office_parity_warnings` 1939 (63) | `snapshot/offices.py` (~250); **`MAX_OFFICE_ACTORS_PROJECTED` moves to `office_models.py`** (R1's leaf, which `office_store` already imports at module level) so `office_store.py:771` and `serve_rpc` stop reaching up into the builder | stores |
| 2004–2379 | `_parity_warnings` 2004 (284, depth 4), `_LIVE_MISSION_RESTAMP_EPSILON_SECONDS`, `_parse_iso_timestamp` 2296, `_redaction_observed` 2308 (+ `visit`), `_event_summary_warnings` 2331 | `snapshot/warnings.py` (~280) | policy |
| 2380–2479 | `_default_persona_session_db`, `persona_session_db_scope` 2389, `_agent_tool_detail` 2429, `persona_instance_detail_for_id` 2451 | `snapshot/details.py` (~90) | lanes |
| 2480–2814 | `_workspace_summary` 2480, `_realm_summary` 2521, `_agent_summary` 2547 (70), `_PROFILE_TEMPLATE_TTL_SECONDS`, `_maybe_reconcile_profile_personas`, `_profile_templates_cached`, `_available_persona_summary` 2678 (76, depth 4), `_display_name_for_profile`, `_safe_repo_scope_label`, `_safe_model_label`, `_repo_scopes_summary`, `_repo_scope_entry`, `_safe_text` 2796 | `snapshot/summaries.py` (~250) | stores |

12 modules, none over 330. Edges: `build` → `sections` → every store/policy module → `context` (down). The module-level imports of the six Wave 2 siblings move with the sections that use them; no sibling imports `snapshot` at module level, and the three that reach it lazily (`core_cache` 1802 → `context.SNAPSHOT_CONTRACT_VERSION`, `prompt_observability` 1366 → `build_snapshot`, `office_store` 771 → the cap) are each closed by the owning sheet (core_cache §1, prompt_observability §1, this §1). Declaring `snapshot` = `lanes` is therefore safe only AFTER those three CHANGEs land — which is why this file is LAST in R3 and its `__layer__` declarations are the last Wave 2 commit.

## 2. Routing sites → tables (the CHANGE commit)

| site (base line) | shape today | replacement | killing mutation |
|---|---|---|---|
| `_build_snapshot_in_runtime_scope` 747–1081 | ~30 hand-written `with _timed_section(ctx, "<name>"):` blocks, each assembling one frame section into `data[...]`, the `sections_ms` keys spelled once per block | `sections.SECTIONS: tuple[Section, ...]` with `Section(key, build: Callable[[BuildInputs], Any], timed: bool)`; the function iterates, times and assigns; `sections_ms` keys come FROM the table (one vocabulary — `test_snapshot_build_logging.py` pins the key set) | drop the `office` section → `tests/agent_runtime/test_snapshot.py` reds on the missing key; reorder `persona_instances` after `agents` → `test_snapshot_build_logging.py`'s `agents_readiness` split receipt reds (838: "keeps its exact span, meaning and key") |
| `_parity_warnings` 2004–2288 | one function computing ~15 warning keys in sequence (2007 board/office · 2035 orphan/held · 2089 referential staleness · 2195 restamp · 2218–2231 operator channels) | `warnings.PARITY_WARNINGS: tuple[(key, check: Callable[[frame], list])]`; `_parity_warnings` = `{key: check(frame) for …}`; **`tests/agent_runtime/test_parity_warning_catalog.py` (2285) already fails if a key leaves — it becomes the table's reader** | drop the `stale_steering_refs` row → the catalog test reds |
| `_parity_envelope` 1083 (the one routed chain the probe counts, at the `redaction_observed` / evict-marker fold) | — | `envelope.Envelope` value object; the eviction markers (`*_ref`, `detail_ref`, `evicted`) become one `Evicted(kind, ref)` shape (rule 14) | rename `detail_ref` → `test_snapshot_deep_slim.py` reds |

## 3. W0-G7 floor rows (4) and the decomposition

| row | lines / depth | phases (comment map) | after |
|---|---|---|---|
| `build_snapshot` 510 | 216 / **5** | injected stores + profile discovery 556–581 · persisted-core consult 583–597 · shadow window 597 · coalesce / leader 610–648 · pre-build fingerprint + build 655–671 · own log line 683 · write-back 691–702 · close + receipt 707 | `SnapshotBuild.admit → consult → coalesce → build → persist`, ≤ 60 each, depth ≤ 3; the coalescer's condition-variable dance is `coalesce`'s whole body |
| `_build_snapshot_in_runtime_scope` 747 | 334 / 2 | the `SECTIONS` table (§2) | ≤ 60 |
| `_parity_envelope` 1083 | 338 / 1 | 42 lines of changelog + the slim/evict passes 1119–1129 | changelog relocated; `Envelope.slim → evict → stamp`, ≤ 80 each |
| `_parity_warnings` 2004 | 284 / 4 | the `PARITY_WARNINGS` table (§2) | ≤ 30 + one ≤ 60 function per row |

Depth-4 sites under 150 (`_boards_summary`, `_offices_summary`, `_available_persona_summary`) lose a level when their nested `_card_unpublished`/`_actor_unpublished` closures become functions.

## 4. Helpers that unify

| here | duplicate of | authority |
|---|---|---|
| `_safe_text` 2796 | `child_events` 58, `events` 628, `parity` 359, `running_work` 303 (W0-G3 row, 5 copies) | `serde.safe_text` — this lane folds its own; the other four fold in a `style:` commit after R2's `running_work` lands |
| `_parse_iso_timestamp` 2296 | `persona_chat_history._iso_timestamp` 1868 (the read side); H2's sheet named `clock.parse_iso` | `clock.parse_iso` (R3 owns `clock`; created here if the persona_chat_history sheet's `clock.iso_timestamp` has not landed — one function, tree wins) |
| `_boards_summary` 1604 / `_offices_summary` 1827 | one shape: walk a store, cap the projection, mark unpublished rows, collect warnings | `summaries.projection_summary(store, row_fn, cap, baseline)` |
| `_board_parity_warnings` 1657 / `_office_parity_warnings` 1939 | one shape | `warnings.projection_warnings(kind, projection)` |
| `_safe_model_label`, `_safe_repo_scope_label` | `serde.safe_text(value, limit=)` | `serde` |
| `_keyed` 188 | `serde.section_rows` 122 is the inverse; not a duplicate — named so nobody folds it | — |

## 5. Dead code found while reading

| symbol | lines | evidence |
|---|---|---|
| `_agent_tool_detail` 2429 | 20 | queue row line 64 (reach census 0 hits): called at 2476 by `persona_instance_detail_for_id` — untested live; `tool_visibility.py:182` names it in a comment. Positive control lands with the MOVE |
| `_redaction_observed` 2308 | 21 | one caller (1394) — keep |
| the five production-imported private names (`_parity_envelope`, `_workspace_summary`, `_realm_summary`, `_office_actor_summary_row`, `_board_card_row`) | — | not dead — made PUBLIC in the CHANGE (`envelope`, `workspace_summary`, …); the importers (`scope_activation`, `harness_parts/office.py`, `state_patches`, …) retargeted |

Nothing new.

## 6. Doors

`hermes_time.now` 21 (FIRST), `agent_runtime.profile_home` 20 (fork), `_upstream_doors.profiles_root` 236 (already the door). W0-G6 private rows: none. No widening.

## 7. Commits

1. **MOVE** `refactor(snapshot): snapshot.py → agent_runtime/snapshot/ (12 modules; contract changelog to 02-runtime-data-and-shapes)` — spans byte-identical; `__init__` re-exports 16 public + 5 private importer names; 15 `setattr` sites and 17 private pins retargeted to the binding module. **Mutation:** re-point the `_profile_templates_cached` pin at the package → `test_snapshot_catalog_memo.py` reds.
2. **CHANGE** `refactor(snapshot): SECTIONS and PARITY_WARNINGS tables; SnapshotBuild phases; Envelope; BuildRole; MAX_OFFICE_ACTORS_PROJECTED to office_models; __layer__ declared` — four floor rows deleted; `[ds-size]` −1; the layer declarations are the LAST Wave 2 commit (§1).

## 8. Lane and what it must not touch

R3, **last of five and last of Wave 2** (it imports six of the ten; every other package must have landed with its `__init__` re-exports so this MOVE retargets imports once). Must not edit in parallel: anything — by construction nothing else is moving when it runs. Before it: `office_models.py` gains one constant in R1's office_store CHANGE (or in this lane's if R1 has not landed — tree wins, and the sha256 table names the line).
