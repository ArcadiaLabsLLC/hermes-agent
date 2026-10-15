# Layout sheet — `agent_runtime/realm_sync.py` (lane R4)

Base: `main` @ `bf4377f226` · 4,464 raw / 3,244 code / 118 top-level defs · longest `publish_realm_sync` 242 (466–707) · chains 6/1 · `str==` 40 · `isinstance` 13 · owner doc `docs/agent-runtime-harness/06-office-and-board.md` (the sync families) and `09-multi-device-runtime.md`. 13 production importers, 26 test files; the importers take `RealmSyncError`, `MembershipDecision`, `RealmMembershipProvider`, `read_realm_sync_sidecar`, `resolve_realm_sync_artifacts`, `skill_tombstone_rows`, `sync_artifacts_for_workspace_agent` and five private names (`_canonicalize_text_bytes`, `_is_hard_excluded_path`, `_is_secretish_path`, `_profile_home_for_token`, `_held_skill_packages_for_realm`, `_realm_subtree`, `_sync_repo_path`) — the private ones become public in the CHANGE.

**Package `agent_runtime/realm_sync/`** (named after the file — every importer's path survives through `__init__`). The 09-21 R4 row (`publish,pull,skill_inbox,git,status,models,errors`) stands; this sheet adds `families` (the two ladders' owner), `artifacts` + `persona_artifacts` (the resolver is 1,000 raw lines and cannot share a module with publish), `drift` + `publish_scans`, `ledgers`, `sidecar`.

## 1. Section map → target modules

| lines | what is there | → module | layer |
|---|---|---|---|
| 1–109, 110–186 | imports, `SECRET_PATH_MARKERS` 53, `BASE_PROFILE_NAME`, `HARD_EXCLUDED_PATH_PARTS` 73, `_REALM_SYNC_GITATTRIBUTES*` 100–107; `RealmSyncError` 110, `RealmSyncArtifact` 119, `MembershipDecision` 158, `RealmMembershipProvider` 164 | `realm_sync/models.py` (~130) | models |
| 187–464 | `realm_sync_status` 187 (167), `_map_status_row` 356, `_level_status_row` 387, `_flow_graph_status_row` 425 | `realm_sync/status.py` (~250) | lanes |
| 466–708, 949–972, 3706–3731, 4332–4444 | `publish_realm_sync` 466 (242, depth 3), `_append_realm_sync_event` 949, `_notify_publish` 3706, `_record_skill_publish_baseline` 4332, `_timestamp_file` 4390, `_write_timestamp` 4397, `_published_artifacts_differ` 4414, `_dedupe_artifacts` 4430 | `realm_sync/publish.py` (~380) | lanes |
| 710–947, 974–1119, 3260–3518 | `pull_realm_sync` 710 (237), `_apply_workspace_tombstones` 974 (depth 4), `_apply_skill_tombstones` 1025, `skill_tombstone_rows` 1092, `_pulled_artifact_bytes` 3260, `_assert_no_secret_artifacts` 3476, `_artifact_contains_secret_assignment` 3496, `_file_contains_secret_assignment` 3510 | `realm_sync/pull.py` (~400) | lanes |
| 3320–3475, 3486–3494 | `_destination_for_sync_path` 3320 (88), `_profile_home_for_token` 3410, `_kind_for_sync_path` 3437, `_is_secretish_path` 3486, `_is_hard_excluded_path` 3491 | `realm_sync/families.py` (~160) — the two ladders' owner (§2); imports `paths`, `profile_context`, `hermes_cli.profiles` only, never an applier | policy |
| 1120–1624 | `_ResolvedPublish` 1120, `resolve_realm_sync_artifacts` 1196, `_resolve_artifacts_with_projection` 1200 (101), `_flow_graph_projection`, `_persona_instance_projection`, `_workspaces_for_realm`, `_required_realm_persona_ids`, `realm_agent_selection_state` 1398, `sync_artifacts_for_workspace_agent` 1427, `_skill_artifacts` 1443, `publishable_skill_packages` 1487, `_iter_publishable_skill_packages`, `_skill_slug_selected`, `_append_skill_package_artifacts` 1560, `_workspace_realm_artifacts` 1604 | `realm_sync/artifacts.py` (~380) | stores |
| 2623–3054 | `_office_wanted_persona_ids`, `_published_profile_file_hashes`, `_profile_files_row`, `_persona_artifacts` 2687 (99, + `_add` 2730), `_profile_relative_destination`, `_profile_relative_file`, `_raw_active_config`, `_persona_config_artifact`, `_persona_instance_artifact`, `_persona_instance_row`, `_flow_graph_artifact`, `_flow_graph_row`, `_persona_projection_row`, `_bound_profile_name`, `_assert_no_raw_profile_config` 2965, `_is_raw_profile_config_path`, `_assert_portable_artifacts` 2999, `_artifacts_from_subtree` | `realm_sync/persona_artifacts.py` (~330) | stores |
| 1625–1760, 1751–2355 | `BoardPublishScan` 1625, `_board_publish_scan` 1633; `DRIFT_FAMILY_*` 1709–1747, `StoreDriftItem` 1751, `_*_DRIFT_COUNTS` 1829–1867, `_drift_counts`, `store_drift_items` 1891, `_skill_store_drift_items` 1903 (+ `_row` 1960), `_flow_graph_store_drift_items` 1988 (+ `_row` 2031), `_persona_instance_store_drift_items` 2053, `_board_store_drift_items` 2141, `_board_store_drift`, `_office_store_drift_items` 2224, `_office_store_drift`, `_any_store_drift` 2338 | `realm_sync/drift.py` (~420) | stores |
| 2357–2622 | `OfficePublishScan` 2357, `_office_publish_scan` 2381 (96), `LevelPublishScan`, `_level_publish_scan` 2496, `MapPublishScan`, `_map_publish_scan` 2567 | `realm_sync/publish_scans.py` (~200) | stores |
| 3056–3258 | `_REALM_AUTHORITY_FIELDS`, `_UNIONED_REALM_LEDGERS`, `_tombstone_transition_at`, `_newer_tombstone_row`, `merge_skill_tombstone_ledgers` 3124, `merge_workspace_lift_ledgers` 3170, `merge_deleted_workspace_ledgers` 3216 | `realm_sync/ledgers.py` (~170) | policy |
| 3520–3704, 4445–4464 | `_authorize` 3520, `_ensure_sync_repo`, `_ensure_repo_gitattributes`, `_credential_git_config`, `_sync_repo_path`, `_realm_subtree`, `_git_state`, `_sync_state`, `_has_remote`, `_refresh_remote_tracking`, `_git` 3655, `_git_clone`, `_render_git_config`, `_scrub_config_values`, `_ensure_git_identity`; `_looks_like_remote`, `_safe_display_path`, `_redact_text` | `realm_sync/git.py` (~200) | stores |
| 3733–3900 | `realm_sync_sidecar_path`, `read_realm_sync_sidecar` 3737, `_held_profile_artifacts`, `_write_sync_sidecar` 3793, `_write_sync_metadata`, `_sync_result`, `_workspace_sync_statuses` 3865 | `realm_sync/sidecar.py` (~160) | stores |
| 3901–4330 | `SkillSyncSummary` 3901, `apply_skill_inbox_pull` 3959 (193, depth 4), `_subtree_package_slug`, `_mirror_realm_skill_inbox` 4178 (98), `_prune_empty_dirs`, `_held_skill_packages_for_realm` 4296, `_distinct_skill_package_count` | `realm_sync/skill_inbox.py` (~340) | lanes |

Result after the MOVE: 14 modules, none over 450. Edges: `status`/`publish`/`pull`/`skill_inbox` → every store module (down); `pull` → `families` (down); `families` → nothing in the package. The lazy cycles with the appliers stay lazy and are legal: `pull.py` lazily imports `persona_config_sync`, `persona_instance_sync`, `flow_graph_sync`, `level_sync`, `map_sync`, `office_sync`, `board_sync`, `profile_artifact_sync` (744–867), and `profile_artifact_sync` + `realm_membership` + `sync_admission` import back — from `models.py` / `families.py`, which import no applier. **`_profile_home_for_token` (3410) and `_is_hard_excluded_path`/`_is_secretish_path` therefore live in `families.py`, not `pull.py`**, so the importer's edge lands on a leaf.

## 2. W0-G5 ladder sites → dispatch tables (the CHANGE commit)

| site (base line) | fixture row | replacement | killing mutation |
|---|---|---|---|
| `_destination_for_sync_path` 3320–3408 | `\|ladder\|parts[0]`, `\|ladder\|parts[1]` — eleven `if parts[..] == "store"/"skills"/"profiles"` guards, seven of them returning `None` with a comment saying which applier OWNS the family | `families.SYNC_PATH_FAMILIES: tuple[SyncPathFamily, ...]` where `SyncPathFamily(kind: SyncFamily, match: Callable[[PurePath], bool], destination: Callable[[parts], Path] \| None, owner: str)`; `destination_for_sync_path(rel)` = the first matching family's `destination`, `None` when the family is applier-owned — the ownership comments become the `owner` field, read by `pull.py`'s report | swap the `store/levels/` and `store/maps/` rows → `tests/agent_runtime/test_realm_sync_level_artifact.py` reds (a level artifact classified as `map`); `test_realm_sync_profile_destinations.py` pins the destination arm |
| `_kind_for_sync_path` 3437–3475 | `\|ladder\|rel` — sixteen `startswith`/`==`/`in` arms returning a kind string | the SAME table: `kind_for_sync_path(rel)` = the matching family's `kind`; the `profile_files` arm keeps its `classify_destination` call as that family's `kind_of(rel)`; **one vocabulary**: `SyncFamily(StrEnum)` replaces the 16 return strings AND `DRIFT_FAMILY_*` 1709–1736 (today two spellings of the family set — `office_actor` appears in both) | same mutation as above; plus `test_realm_sync_ledger_union.py` for the `persona_instance` member shared with drift |
| the five `_*_store_drift_items` walkers 1903–2293 | not a ladder row, but five copies of one shape (walk a store, compare each row's hash against the baseline, emit added/changed/removed) | `drift.DRIFT_FAMILIES: Mapping[SyncFamily, DriftFamily]` with `(rows, baseline_key, content_hash)`; `store_drift_items` iterates the mapping; `_drift_counts` derives from the rows as today | remove the `flow_graph` entry → `test_realm_sync.py`'s canvas-drift case reds |

`str==` 40 → ≤ 10 at review (payload-key guards in the sync report).

## 3. W0-G7 floor rows (4) and the decomposition

| row | lines / depth | phases (comment map) | after |
|---|---|---|---|
| `realm_sync_status` 187 | 167 / 2 | authorize + fetch-first 194–225 · legacy sidecar 242 · one drift walk per family 252–280 · honesty pair 302 | `RealmStatus.remote() → drift() → held() → envelope()`, ≤ 60 each |
| `publish_realm_sync` 466 | 242 / 3 | fetch-first 476 · canonicalize 512 · change detection 521 · gitattributes 526 · **eight "same baseline discipline" blocks 557–655** · accounting 666–685 | `Publish.stage → commit → baselines → account`; the eight blocks become `BASELINE_FAMILIES: tuple[(SyncFamily, update_after_publish)]` iterated once — rule 12, and the reason the table in §2 exists |
| `pull_realm_sync` 710 | 237 / 2 | canonical compare 735 · per-family exclusions 741–782 · re-read 786 · deletions 800 · **seven appliers IN ORDER 807–872** ("the position in this sequence is the argument" 836) · unconditional report rows 888–915 | `Pull.overwrite → appliers → tombstones → report`; the appliers are `PULL_APPLIERS: tuple[(SyncFamily, apply)]` whose ORDER is the fixture's — the mint door before the canvas (829–861) is a test, not a comment |
| `apply_skill_inbox_pull` 3959 | 193 / 4 | legacy sidecar 4024 · one baseline read 4044 · per-package loop 4057 · admission scan 4065 · promotion verdict 4077 | `SkillInboxPull.mirror → admit_each → write_baseline`; the loop body → `_admit_inbox_package` (depth 4 → 2) |

## 4. Helpers that unify

| here | duplicate of | authority |
|---|---|---|
| `_git` 3655 | `build_stamp._git` 322, `scripts/upstream_footprint._git` 242 (W0-G3 row) | new leaf `agent_runtime/git_cmd.py::run_git(args, cwd, env)` (models); `realm_sync/git.py` and `build_stamp` call it; the script keeps its own (outside the package — baselined `script_copy_left`) |
| `_row` 1960 / 2031 (nested), `_add` 2730 | program §4 `running_work/collect.row` | the nested `_row`s disappear with `DRIFT_FAMILIES` (§2); `_add` becomes `persona_artifacts.append_artifact` |
| `merge_skill_tombstone_ledgers` / `merge_workspace_lift_ledgers` / `merge_deleted_workspace_ledgers` 3124–3258 | 44/44/42 lines, one body over three key names | `ledgers.merge_ledger(kind: Ledger)` with `Ledger(StrEnum)` = `_UNIONED_REALM_LEDGERS` 3075 |
| `_write_timestamp` 4397 / `_timestamp_file` | `clock.now_iso` (created by R3's serve_rpc sheet) | `clock.now_iso` |
| `_prune_empty_dirs` 4278 | `skill_promotion._archive_package`'s prune (1058 imports it) | stays here until R4 opens `skill_promotion` (program §3.2); named so the two lanes fold toward `skill_inbox.prune_empty_dirs` |

## 5. Dead code found while reading

| symbol | lines | evidence |
|---|---|---|
| `sync_artifacts_for_workspace_agent` 1427 | 14 | queue row (line 58): reach census 0 hits. NOT dead — `harness_parts/workspace_commands.py` calls it (`git grep -nw` → 2 hits there); the row's verdict is "untested live"; this lane lands a positive control with the MOVE |
| `publishable_skill_packages` 1487 | 29 | 7 in-file references; `harness_parts/skills_commands.py` reads the same fact through `_held_skill_packages_for_realm` — keep, row not filed |

Nothing else: every other def is imported by a test or called in-file.

## 6. Doors

All FIRST (public names): `agent.skill_utils.{EXCLUDED_SKILL_DIRS, SKILL_SUPPORT_DIRS}` 16, `hermes_constants.{get_config_path, get_hermes_home}` 17, `hermes_time.now` 19, `utils.atomic_json_write` 20, `hermes_cli.profiles.{get_profile_dir, normalize_profile_name}` (3430, lazy), `yaml`. W0-G6 private rows for this file: none. No widening.

## 7. Commits

1. **MOVE** `refactor(realm_sync): realm_sync.py → agent_runtime/realm_sync/ (14 modules)` — spans byte-identical; `__init__` re-exports the 7 public + 7 private importer names; the 7 test files pinning 9 private names retargeted; `sync_artifacts_for_workspace_agent` gets its positive control.
2. **CHANGE** `refactor(realm_sync): SyncFamily + SYNC_PATH_FAMILIES, DRIFT_FAMILIES, BASELINE_FAMILIES/PULL_APPLIERS; status/publish/pull/inbox as phases; merge_ledger; git_cmd` — three ladder rows deleted; four floor rows deleted; `[ds-size]` −1.

## 8. Lane and what it must not touch

R4, its first file. Must not edit in parallel: `realm_revert.py`, `persona_config_sync.py`, `persona_instance_sync.py`, `profile_artifact_sync.py`, `skill_promotion.py`, `realm_membership.py` (all importers or appliers — they keep their paths through `__init__`); `office_store.py` (R1; consumed as `OfficeStore` by name); `snapshot.py` (R3; imports `read_realm_sync_sidecar` — survives).
