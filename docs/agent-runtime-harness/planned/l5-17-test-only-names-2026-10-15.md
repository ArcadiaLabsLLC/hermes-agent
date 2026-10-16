# The 51 test-only names from the L5.17 census: a ruling per bucket (design)

Status: PLAN — written 2026-10-15; owner approval owed. Row:
dead-code-burn-down-queue, "The post-v0.21.6 census slice: 14 names confirmed
dead … and 51 test-only names to DECIDE". The 14 dead names are already deleted
(lane w1015e-fh-h); this plan is only the 51.

## In plain English

51 production names are used only by tests. Some are deliberate test handles
(cache resets), some are lists of allowed values the tests check against, some
are RPC verbs the census could not see were registered, and some are real
production code that nothing in production calls any more. Deciding them one by
one across many module owners stalls; instead, rule each **bucket** once and let
a single lane apply the ruling.

## Evidence

- Census: `Harness_Brain/20 — Active Initiatives/queue-sweep-2026-10-10/L5-outcomes.md`
  § "L5.17 census" (`scripts/refactor_census.py`, tree 751532d1bf).
- Slice rules: dead-code-burn-down-queue § "Working a slice" — DELETE lands with
  its tombstone row and `git grep -nw` proof; a TEST SEAM row moves the name
  under `tests/_downstream/_seams.py`.
- Re-checked 2026-10-15: the three `serve_rpc/console_operations.py` names are
  `@method(...)`-registered verbs (`runtime.persona.permission.preview`,
  `.permission.set`, `runtime.persona.instance.detail`, l.75–98) — reached by
  registration, a census false positive like the 46 it already struck.

## The buckets (51 = 3 + 13 + 17 + 18)

| Bucket | Names | Proposed ruling |
| --- | --- | --- |
| **A. Registered verbs** (3) | `console_operations.permission_preview`, `permission_set`, `instance_detail` | STRIKE from the census; separately check a client calls each verb (launcher grep `runtime.persona.permission.`); an uncalled verb is a DEAD-verb row, not this slice |
| **B. Seams by intent** (13) | `demote_core_reuse.reset_process_state`, `events._event_view_cache_clear`, `parse_cache.clear_parse_cache`, `profile_readiness._provider_issue_cache_clear`, five in `skill_resolution.py`, `tool_defs_observability.tool_defs_cache_hits_this_thread`, `ClientRequests.open_count`, `QueuedSendRunner.busy_roots`, `snapshot_build_ledger.builds_in_flight` | KEEP IN PLACE (they reach module privates, so a move is impossible) and register each in `tests/_downstream/_seams.py` as an allowlisted in-module seam the census reads |
| **C. Closed vocabularies** (17) | `builds/vocabulary.py` ×12, `agent_retire.CONFLICT_REASONS`, `flag_binding.ABSENCE_PRESERVING_READERS`, `gateway_home_receipt.RESOLUTION_FLAG` / `RESOLUTION_ACTIVE_PROFILE_MARKER`, `redaction.ALL_SECRET_ASSIGNMENT_PATTERNS` | CHANGE, not delete: production must spell its values FROM the set (validator or `Literal`) so the test's enumeration is "from the thing itself"; where production cannot, delete set + test |
| **D. Production code with no production caller** (18) | `palette_colors`, `DirectionScheme.is_mirrored`, `builds/detect.detection_enabled`, `recognizer_flutter.recognize_transcript`, `builds/registry.write_record`, `capture_create_subphases`, `run_queued_sends_once`, `read_settle`, `level_sync.workspace_token_for_published_path`, `mcp_lane.set_entry_point_lane`, `next_free_slot_for_kind`, `PoolRotationMixin.select_without_persisting_rotation`, `redaction.redact_transport_tree`, `build_span_scope`, `build_flag_inventory`, `build_postinstall_parser`, `windows_env.set_user_env`, `toolset_manifest.builtin_modules` | DELETE with their tests, by default; a module owner may veto one by naming its planned production caller and a date |

## Owner decisions (recommendation first)

1. **Bucket B: in-place seams + allowlist** (recommended) vs move-or-delete.
   Moving cache clears out of their module would need a public hook — a worse
   seam than the one that exists.
2. **Bucket C: make production use the set** (recommended) vs keep sets as
   test-only documentation. A set nothing enforces is the "set typed in the
   same expression as the actual" class `CLAUDE.md` names.
3. **Bucket D: delete by default** (recommended), with a one-wave veto window
   for module owners. `detection_enabled` waits for the process-global fixture
   (fork-hygiene "Process-global state, the CLASS") if that fixture needs it.
4. **Lane shape:** one lane, four commits (one per bucket), not 51 rows.

## Slices (build order)

- **S1 — bucket A strike + verb check.** Census reads `@method` as a reach.
  Killing mutation: remove the `@method` reach from the census → the three
  reappear in its test fixture → red.
- **S2 — bucket B allowlist.** `_seams.py` gains `IN_MODULE_SEAMS`; census skips
  them. Killing mutation: drop one entry → census test lists it → red.
- **S3 — bucket C, one set at a time.** For each, production validates against
  the set. Killing mutation per set: add a value to production only → the
  existing enumeration test reds (it now reads production's spelling).
- **S4 — bucket D deletes**, each with its tombstone row and grep proof;
  reintroduce one symbol → `test_tombstone_registry.py` reds naming it.

Done when the census reports 0 test-only names outside the allowlist.

## Blast radius

About 30 production files, their tests, `tests/_downstream/_seams.py`,
`scripts/refactor_census.py`, the tombstone registry. Fork-owned files only; no
upstream file is touched (all 51 are under fork-owned paths per the census).

## What it retires

The 51-name DECIDE backlog, the census's blindness to registered verbs and
in-module seams, and test enumerations over sets production never reads.
