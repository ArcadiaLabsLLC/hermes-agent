# Layout sheet — `agent_runtime/core_cache.py` (lane R3)

Base: `main` @ `bf4377f226` · 4,073 raw / 2,502 code / 85 top-level defs · longest `build_input_fingerprint` 236 (1535–1770, depth 4) · chains 1/0 · `str==` 2 · `isinstance` 20 · owner doc `docs/agent-runtime-harness/04-boot-and-lifecycle.md` (the persisted core) and `08-performance-and-debt-ledger.md`. **1,571 of the 4,073 lines are prose** — a 245-line module docstring and eleven `# ---` section banners whose history (ML-10, MC-1/2, IC-2, P3/P5, EG-3.1) is the ruling-Q3 class: relocate, never split for it. 6 production importers; 15 test files, of which 11 pin **32 distinct private names** through 36 `monkeypatch.setattr(core_cache, …)` sites — the largest retarget in Wave 2.

**Package `agent_runtime/core_cache/`** (named after the file; `stream.py:13` does `from . import core_cache` and calls `core_cache.close_cache_lane(...)`, `harness_parts/serve/session.py:350` calls `_core_cache.declare_fingerprint_home_boot_site` — attribute access on the package, which `__init__` satisfies). The 09-21 R3 row (`fingerprint,write_back,config_keys,read,census`) stands in grain; `config_keys` is the `walk` module here, `census` already left for `core_cache_census.py`, and six modules are added.

## 1. Section map → target modules

| lines | what is there | → module | layer |
|---|---|---|---|
| 1–245 | the module docstring (history of every mechanism below) | `core_cache/__init__.py` map ≤ 60 lines; the history → `docs/agent-runtime-harness/planned/core-cache-input-closure.md` (already the design note) — rule 7 relocation | wiring |
| 246–836 | `CORE_CACHE_DIRNAME` … `POINTER_FILENAME`, `CORE_SOURCE_*`, `DEMOTE_*` ×11 (293–307), `RECEIPT_*` (323–347), `REFUSAL_*`, `DIFF_SCOPE_*`, `BUILD_SELF_PERTURBED_CLASSES`, the banner at 309 | `core_cache/vocabulary.py` (~120 code): `DemoteReason(StrEnum)`, `Receipt(StrEnum)`, `Refusal(StrEnum)`, `DiffScope(StrEnum)` — rule 14, the strings unchanged so the receipts on disk are byte-identical | models |
| 837–855, 1330–1344, 2100–2115, 2208–2214, 2708–2730, 2988–3000, 3069–3084, 3365–3388, 3746–3760 | `FingerprintEntry`, `CoreFingerprint`, `FingerprintHomeCapture`, `_SelfPerturbedInputs`, `_RestatOutcome`, `_StreakSeed`, `PersistedEntries`, `CacheRead`, `_ConsultStamp`, `_ConsultMemo`, `CoreDecision` | `core_cache/models.py` (~140) | models |
| 856–1265 | `_stat_entry` 860, `_entry_triple`, `_walk_tree` 891 (102), `_wal_without_frames_is_content_free` 995, `_config_input_is_content_keyed` 1069 (112), `_config_input_entry`, `sqlite_fingerprint_triples` 1189, `_db_entries`, `_receipt_fingerprint_refused` 1235 | `core_cache/walk.py` (~280) | stores |
| 1267–1533 | `_capture_fingerprint_home_locked` 1345, `_receipt_fingerprint_home_lazy_capture`, `declare_fingerprint_home_boot_site` 1385, `capture_fingerprint_home` 1406, `fingerprint_home_capture` 1426, `resolved_fingerprint_home` 1451, `reset_fingerprint_home` 1483, `_pinned_to_fingerprint_home` 1507 | `core_cache/home.py` (~150); **`hermes_cli/harness.py::_capture_core_cache_fingerprint_home` joins it** (dead-code queue line 32, "R3 takes it into `core_cache/`") | stores |
| 1535–1838 | `build_input_fingerprint` 1535 (236, depth 4), `_fingerprint_over`, `contract_versions` 1792, `build_stamp_token` 1812 | `core_cache/fingerprint.py` (~250) | stores |
| 1840–2023 | `_cache_dir`, `pointer_path`, `_is_generation_name`, `_new_generation_name`, `_live_generation_dir` 1885, `_live_generation_name`, `core_path`, `sidecar_path`, `entries_path` 1963, `_core_digest` | `core_cache/generations.py` (~150) | stores |
| 2025–2300 | `_self_perturbed_inputs` 2126 (69), `_restat_on_post_build_reality` 2215 (85) | `core_cache/restat.py` (~160) | stores |
| 2302–2700 | `write_back` 2305 (223), `_entries_payload`, `_reap_superseded_generations` 2563 (63), `_receipt_generation_residue` 2628 | `core_cache/write_back.py` (~300) | stores |
| 2700–2986 | `_reset_convergence_state`, `_changed_paths`, `_capture_boot_streak_seed` 2771, `_persisted_streak_seed`, `_note_written_key` 2839 (87), `_receipt_never_converged`, `_diff_detail`, `_diff_unavailable_detail` | `core_cache/convergence.py` (~200) | stores |
| 2988–3270 | `_persisted_entries` 3002, `_runtime_root_for_sidecar`, `read_persisted_core` 3085, `_read_pair`, `_judge_persisted_pair` 3135, `_sidecar_answers_a_different_question` 3163 (50), `label_core` 3218 | `core_cache/read.py` (~220) | stores |
| 3272–3660 | `_pair_stamp`, `_store_position` 3412, `_consult_stamp`, `_stamp_still_stands`, `_drop_consult_memo`, `_armed_window_read` 3490, `pre_build_fingerprint` 3527, `reset_process_state` 3559, `lane_armed`, `note_full_build_completed` 3589, `close_cache_lane` 3618, `shadow_build_scope` 3658 | `core_cache/lane.py` (~250) — the process-level state (`_CONSULT_MEMO` etc.) has ONE writer module | lanes |
| 3668–3866 | `_demote_diff_detail`, `_log_demote` 3701, `consult` 3761 (51), `take_stale_first_core` 3814 (52) | `core_cache/consult.py` (~170) | lanes |
| 3868–4073 | `compare_cores` 3898, `_stripped`, `shadow_validate` 3940 (93), `claim_shadow_slot`, `maybe_start_shadow_validation`, `iter_fingerprint_paths` 4069 | `core_cache/shadow.py` (~150) | lanes |

14 modules, none over 300. Edges: `lane`/`consult`/`shadow` → the store modules → `models`/`vocabulary` (down). Two reaches to watch: `fingerprint.contract_versions` 1792 lazily imports `snapshot.SNAPSHOT_CONTRACT_VERSION` 1802, `stream.STREAM_SCHEMA_VERSION` 1803, `parity.PARITY_ENVELOPE_VERSION` 1801 — `snapshot` imports `core_cache` at module level (23), so this is a lazy cycle today and becomes an UPWARD import (stores → lanes) the day R3's snapshot sheet declares `snapshot` as `lanes`. **The CHANGE breaks it:** `contract_versions()` reads the three versions from `decision_contract_registry` (already a leaf `snapshot` imports at 27) or takes them as a parameter the builder passes. Module-level imports of `serve_socket`, `serve_registry`, `serve_auth`, `dispatch_delivery` (230–235) are FILENAME constants — `paths`-class; they move to `vocabulary.py` and stay downward.

## 2. W0-G5 ladder sites

None in the fixture. The CHANGE still lands rule 12 twice, because the file routes on strings without an `elif`: (a) `_judge_persisted_pair` 3135 + `_sidecar_answers_a_different_question` 3163 decide a `DEMOTE_*` reason by sequential `if` checks → `read.DEMOTE_CHECKS: tuple[(DemoteReason, predicate)]` walked in order, the first failing predicate naming the reason — **killing mutation:** reorder `contract_mismatch` before `core_digest_mismatch` → `tests/agent_runtime/test_core_cache_demote_census.py` reds on the reason for a pair with both faults; (b) `build_input_fingerprint`'s seven numbered input classes (1612–1761: store root · running_work · SessionDB · profile inputs · config authorities · skill registries · event rotation) → `fingerprint.INPUT_CLASSES: tuple[InputClass]` with `(name, roots, pinned: bool, keyed: Keyed)` — the `PINNED`/`CONTENT-KEYED` comments become fields — **killing mutation:** drop the `skill registries` class → `test_core_cache_exclusions.py` reds (the 1,237-entry divergence the comment at 1732 records).

## 3. W0-G7 floor rows (2) and the decomposition

| row | lines / depth | phases | after |
|---|---|---|---|
| `build_input_fingerprint` 1535 | 236 / 4 | the seven classes above, each `try: walk except: refuse` | `for cls in INPUT_CLASSES: entries += cls.collect(refusals)`; `collect` ≤ 40; the function ≤ 60 |
| `write_back` 2305 | 223 / 1 | re-key on restat 2427 · question stamp 2445 · diagnostics 2458 · staged writes 2467–2489 (core, sidecar, convergence, entries) · landing 2501 · reap 2508 · accounting 2524 | `WriteBack.rekey → stage → land → reap`, ≤ 70 each; `stage` is the one place the four files are written (rule 13 — today it already is; the phase object makes it visible) |

## 4. Helpers that unify

| here | duplicate of | authority |
|---|---|---|
| `_stat_entry` 860 / `_walk_tree` 891 | `harness_parts/serve/boot.py`'s `_stat_board_tree` / `_stat_turn_store_tree` (H4 folded them to `boot.stat_tree`) | `core_cache/walk.py` — the boot fingerprint and the core fingerprint are one stat walker; H4's `stat_tree` retargets here in this lane's CHANGE |
| `_capture_core_cache_fingerprint_home` (`hermes_cli/harness.py`, 39 lines) | `home.capture_fingerprint_home` + a receipt | `home.py` (queue row line 32 closes) |
| `_diff_detail` / `_diff_unavailable_detail` / `_demote_diff_detail` | three shapes of one "why the pair differs" record | `convergence.diff_detail(scope, …)` |
| `atomic_json_write` (2475, 4 sites) | — | stays `utils.atomic_json_write` (public upstream) — `serde.write_json_atomic` is the fork wrapper for the secure-path case, not this one |

## 5. Dead code found while reading

| symbol | lines | evidence |
|---|---|---|
| `fingerprint_home_capture` 1426, `iter_fingerprint_paths` 4069, `BUILD_SELF_PERTURBED_CLASSES` | 23 + 5 + 5 | queue row line 20 (TEST SEAM): `git grep -nw` → def only in production; 2/3/1 test files |
| `reset_fingerprint_home` 1483 | 21 | same class, unrowed: production caller is `reset_process_state` 3581 only, which is itself test-only (`test_core_fingerprint_cache.py`, `test_stale_core_under_fresh_offset.py`, `conftest.py`) → **append to row 20**, not a new row |
| `lane_armed` 3584 | 3 | one production reader `consult` 3781 — keep |

## 6. Doors

`agent.skill_utils.get_all_skills_dirs` 1728 (public, FIRST), `utils.atomic_json_write` 228 (FIRST), `_upstream_doors.{default_hermes_home, profiles_root}` 1675 (already through the door). W0-G6 private rows: none. No widening.

## 7. Commits

1. **MOVE** `refactor(core_cache): core_cache.py → agent_runtime/core_cache/ (14 modules; prose to the design note)` — spans byte-identical; the 36 `setattr(core_cache, "_name", …)` sites retargeted to the module that BINDS each name (an H2-style script; a patch on the package attribute would not reach a submodule's global — the trap H3 recorded as "AST pins read the package"); `harness.py`'s capture function moves in (its one test retargeted). **Mutation for the MOVE:** re-point one `setattr` at the package → its test reds (the submodule still runs the original).
2. **CHANGE** `refactor(core_cache): DemoteReason/Receipt enums, DEMOTE_CHECKS, INPUT_CLASSES; WriteBack phases; contract_versions off the snapshot import` — §2–§4 with each red pasted; `[ds-size]` −1.

## 8. Lane and what it must not touch

R3, third of five (after `serve_rpc`, `serve_socket`; before `profile_runner`, `snapshot`). Must not edit in parallel: `core_cache_census.py`, `stream.py`, `snapshot.py` (same lane, later), `hermes_cli/harness_parts/serve/{boot,session}.py` (retarget-only). `hermes_cli/harness.py` is touched for ONE deletion (the capture function moves out) — coordinate with nothing: no other Wave 2 lane opens it.
