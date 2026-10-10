# L5 outcomes (lane 1010-L5, branch lane/1010-L5, tip fd66fb365d)

L5.01 · RETURNED operator live proof: ~8 warm Neko/Dev turns on a rebuilt serve, read `turn-timing` (tool-form receipts, native-revision before/after, 400 ms warm budget); an agent cannot rebuild the operator's serve
L5.02 · RETURNED owner decision: the row is conditional ("stamp it if send-prep is worked again"); ~8 ms is below the 5 ms-per-part bar and this lane did not work send-prep. Question: stamp now, or keep it parked until a send-prep lane?
L5.03 · RETURNED too big: atomic ancestor-prefix clone across native compressed ancestry (lineage, tool correspondence, source lifecycle) is a design, not a fix; the design question is how a clone spans a compression boundary without copying a partial prefix
L5.04 · RETURNED too big: `retry_of` touches the chat send params, a same-session validation, the turn record, the projection on BOTH rows (a write to the original turn's record) and the launcher wire contract; design question: is "retried as …" projected from the new turn alone, or written back onto the old record?
L5.05 · RETURNED upstream: `hermes_state_search.py::search_messages` (upstream file) has no session-id filter; scoping to one session needs an upstream parameter (or a fork-side FTS query, which is the design question), and post-filtering breaks paging
L5.06 · RETURNED owner decision: the row itself says decide first whether turn-outcome derivation belongs to a plugin hook or the executor (`agent/tool_executor.py` is upstream)
L5.07 · RETURNED owner decision: measured 2026-10-10 on the lane tree, 2/2 green (48 s, 57 s file runs with 8 lanes on the box); question unchanged: is 600 ms after-idle anchor->request_sent a live-box contract or a load-aware budget?
L5.08 · FIXED c74ceb7c17 (apply_chat_lane_defer accounts the constructor form at construction; turn 1 / prewarmed actor has a receipt)
L5.09 · RETURNED too big: a list verb plus "re-arm" (a write) needs a parser verb (CLI contract re-vendor in the launcher), a serve RPC method and a re-arm semantics ruling (reset attempts? new settle_id?); design question: what does re-arm do to the record's attempts and state?
L5.10 · RETURNED owner decision: should only the socket owner push settle records it did not write (non-owner stdio child skips them)?
L5.11 · RETURNED owner decision: CLI one-shot queued send — does the CLI wait for the root and run the send itself, or answer "queued until the runtime starts"?
L5.12 · ALREADY-DONE d61247fdfa (fix(test): operator-lane fixture carries the settle-push surface); both files 38/38 green on the lane tree
L5.13 · FIXED 9204de94eb + 95d15e6351 (owner ruling 2026-10-10: origin persisted in persistable_args; queued turn binds the sender's direct-run link, gateway-rule fallback; new module serve/queued_turn_origin.py). Size: 298 insertions / 69 deletions across both commits, over the ~150 cap per the ruling; no file near 800, no grandfathered function grown
L5.14 · FIXED fd66fb365d (owner ruling 2026-10-10: queued, never refused; frames tee'd and settle sent once to the sending gateway connection). Size: 116 insertions / 12 deletions
L5.15 · RETURNED upstream: `tools/registry.py` is in tests/fixtures/upstream_manifest.txt; deleting `registry_epoch` is an edit of an upstream file (carried seam, KEEP-HELD branch `fix/tool-registry-probe-cache` per fix-triage-2026-09-26); it also still names the epoch in `launcher_app_functions` docstrings
L5.16 · RETURNED launcher side: the hermes half landed (`docs/agent-runtime-harness/planned/argv-census-2026-09-29.md`); DELETE rows wait on the launcher-half read of which of the 18 twin-carrying verbs `EterniaLauncher` still lowers to argv
L5.17 · FIXED (census run, rows below)
L5.18 · FIXED e188174d53 (deleted with its tests; tombstone row s-1010-l5; 07-observability corrected)

## L5.17 census — `scripts/refactor_census.py` over 883 fork-owned non-test .py files (tree 751532d1bf + this lane)

Raw: 60 unreferenced, 51 test-only. 46 of the 60 are decorator-registered (singledispatch `.register`, `@method(...)` RPC verbs, a FastAPI route, a `@property`) — reached by registration, not by name; false positives. The 14 below were re-checked with `git grep -w` over the whole tree (no other file names them). None of them is a Tirith / Skill Sync / Honcho / Home Assistant caller; v0.21.6 orphaned no fork helper the census can see.

DEAD (no reference anywhere outside the definition) — candidate DELETE rows for the dead-code queue:
- `agent_runtime/builds/registry.py::writer_registry_dir` (5 lines)
- `agent_runtime/builds/vocabulary.py`: `BUILD_TAIL_SOURCES`, `RESERVED_TOOLCHAINS`, `RECORD_STATUSES`, `RECORD_STOP_MODES`, `RECORD_RESTART_MODES` (1 line each; vocabulary constants — check the launcher contract before deleting)
- `agent_runtime/chat_lane_bundle.py::_registry_content_revision` (1 line; named only in planned/tool-form-one-owner-2026-10-08.md)
- `agent_runtime/discussions/run_store.py::LIVE_PHASES` (1 line)
- `agent_runtime/harness_settings.py::settings_path` (3 lines)
- `agent_runtime/map_sync.py::map_token_for_published_path` (15 lines; its twin `level_sync.workspace_token_for_published_path` is test-only)
- `agent_runtime/skill_activity.py::with_skill_evidence` (6 lines)
- `agent_runtime/workspace_slot_env.py::drop_slot_fill` (7 lines)
- `tools/downstream_schema.py::PROMOTED_BRIEF_DESCRIPTION_CHARS` (1 line)
- `tools/tool_search_downstream.py::_LAUNCHER_QA_CORE_TOOLS` (1 line)

TEST-ONLY (production function only tests call) — DECIDE rows (TEST SEAM move vs delete); cache-clear/reset helpers are seams by intent:
- agent/charsheet/palette.py::palette_colors; agent/charsheet/spec.py::DirectionScheme.is_mirrored
- agent_runtime/agent_retire.py::CONFLICT_REASONS; agent_runtime/builds/detect.py::detection_enabled; builds/recognizer_flutter.py::recognize_transcript; builds/registry.py::write_record; builds/vocabulary.py (12 constants: ARTIFACT_KINDS, BUILD_SOURCES, BUILD_LIVENESS, PROGRESS_SIGNALS, BUILD_TOOLCHAINS, BUILD_MODES, STARTED_BY_KINDS, ENV_SOURCE_ARMS, CONTROL_STATES, CONTROL_REASONS, DETECTED_SUB_REASONS, ANNOUNCED_SUB_REASONS)
- agent_runtime/agent_create_phases.py::capture_create_subphases; chat_root_send_runner.py::run_queued_sends_once, QueuedSendRunner.busy_roots; chat_turn_settles.py::read_settle; demote_core_reuse.py::reset_process_state; events.py::_event_view_cache_clear; launcher_client_requests.py::ClientRequests.open_count; level_sync.py::workspace_token_for_published_path; mcp_lane.py::set_entry_point_lane; office_layout_policy.py::next_free_slot_for_kind; parse_cache.py::clear_parse_cache; pool_rotation.py::PoolRotationMixin.select_without_persisting_rotation; profile_readiness.py::_provider_issue_cache_clear; redaction.py::ALL_SECRET_ASSIGNMENT_PATTERNS, redact_transport_tree; skill_resolution.py (5: skill_root_walks_this_thread, reset_skill_root_walks_for_tests, skill_root_rebuilds_this_thread, _skill_root_registry_cache_clear, _search_roots_cache_clear); snapshot_build_ledger.py::builds_in_flight, build_span_scope
- agent_runtime/serve_rpc/console_operations.py::permission_preview, permission_set, instance_detail (decorated @method but called by name only from tests — verify the method table registers them)
- hermes_cli/charsheet_payload_contract.py::build_flag_inventory; flag_binding.py::ABSENCE_PRESERVING_READERS; gateway_home_receipt.py::RESOLUTION_FLAG, RESOLUTION_ACTIVE_PROFILE_MARKER; subcommands/postinstall.py::build_postinstall_parser; windows_env.py::set_user_env
- tools/tool_defs_observability.py::tool_defs_cache_hits_this_thread; tools/toolset_manifest.py::builtin_modules
