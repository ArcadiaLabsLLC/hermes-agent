# L6 outcomes (lane/1010-L6, 2026-10-10)

L6.01 · ALREADY-DONE test_doctor_structural_corruption.py 2 passed, test_clean_close_residual_poison.py 5 passed (scripts/run_tests.sh, lane base 751532d1bf)
L6.02 · RETURNED too big: all eight files are upstream (lane may not edit them); making hunks additive / moving fork tests out of upstream test files plus a sync-job ledger writer is a footprint lane with upstream-edit licence; `_posix_match_forms` still lives in both tools/file_tools.py and tools/file_tools_paths.py
L6.03 · ALREADY-DONE test_duplicate_helper_bodies.py 5 passed (run_tests.sh, 751532d1bf)
L6.04 · ALREADY-DONE test_harness_cli.py 62 passed incl. both named nodes (run_tests.sh, 751532d1bf)
L6.05 · FIXED 3e1ec1dddc (brief skeleton carries a per-lane Scratch line)
L6.06 · FIXED c4466d52b0 (fork door in conftest_plugin denies HERMES_TEST_REAL_ROOT; tests/conftest.py untouched)
L6.07 · RETURNED workstation hazard: not reproduced, 12/12 green alone under eight-lane load; the reproducing condition (12 workers) is off the ruled default of 8, so a repro needs an idle box at 12 workers
L6.08 · FIXED f8e473b846 (generator pins build detection off; a serve boot's enable_detection() leaked `no_slots_declared` into hydrate.json byte 3123)
L6.09 · RETURNED workstation hazard: finding the freezing file needs a watchdog/VM, never this desktop; docs half FIXED 2419aa4d7f (handoffs name the fork gate; CLAUDE.md already did)
L6.10 · FIXED 35d13f9ec6 (one git log walk; 8.62 s -> 0.81 s, gate file 28.3 s -> 5.7 s)
L6.11 · ALREADY-DONE `changed_line_mutation_check.py --list --base origin/main` exits 0 on 751532d1bf; both named claims resolve
L6.12 · RETURNED upstream: hermes_cli/_launchers.py Windows expose path lacks the POSIX ownership guard (w5-fh verdict (a)); upstream PR, draft not opened
L6.13 · RETURNED workstation hazard: needs a disposable Windows VM (owner parked 2026-09-29)
L6.14 · RETURNED too big: still unnamed second release path; measured today: a 0.5 s delay inserted between `_connections.pop` and `close`, and between `close` and `on_disconnect`, in serve_socket/server.py::_drop_connection both stay green with the count-only poll, so the subscriber is released before socket teardown; a both-halves wait has no killing mutation until that path is named
L6.15 · RETURNED upstream: waits on upstream PR #128843 (config_switch keys)
L6.16 · RETURNED owner decision: PART 2 (upstream runner PR series) is on hold until the owner's explicit go, and needs an exclusive idle box for the upstream wall
L6.17 · RETURNED upstream: test body is upstream bytes; answer is an upstream PR (read to EOF / smaller body) or an id-mark after a second logged red
L6.18 · RETURNED upstream: product half waits on upstream PR #114597; runner half done e0dafc4e27
L6.19 · ALREADY-DONE the shared test venv (<test venv>) imports snowballstemmer and truststore; test_tool_call_incremental_persistence.py 21 passed, test_auth_nous_provider.py 48 passed (run_tests.sh)
L6.20 · FIXED b96dc66372 (worktree reads the primary's durations and run record; 27 -> 4,328 duration entries here)
L6.21 · ALREADY-DONE test_httpx_responses.py 9 passed, test_token_authority.py 26 passed, test_codex_runtime_plugin_migration.py 20 passed (run_tests.sh, 751532d1bf)
L6.22 · FIXED f8e473b846 (same leak as L6.08)
L6.23 · RETURNED upstream: #128650 and #129582 are still OPEN and v0.21.6 took neither; bringing da0ccd09bb / 47028bf432 onto main edits two upstream files (agent/pet/generate/atlas.py, tests/_fixtures/live_system_guard.py), the next release-merge lane's call
L6.24 · ALREADY-DONE test_native_conversation_roundtrip.py 4 passed (245 s), test_discussion_group_compute.py 1 passed (run_tests.sh, 751532d1bf)
L6.25 · RETURNED owner decision: reproduced (turn 0 571 > 402+100). Nine runs under eight-lane load: turn 0 minus slowest warm turn ranged from -181 to +169 ms; the absolute 600 ms warm bound red 2/8 (670, 883). Widening either loosens a perf guard. Question: give it a load-aware margin, or keep the absolute budgets and run the file only on an idle box (serial mark)?
L6.26 · RETURNED owner decision: confirm the loosened phone-wheel registration check (69f8d72ae3)
L6.27 · FIXED 84b8518ef7 (UTF-8 reads and git decodes; red under cp1252 -> 29 passed)
L6.28 · FIXED c2dc5293ac (post-merge hook runs --check only in a linked worktree)
L6.29 · ALREADY-DONE d2b6dbec62 (plugin register() no longer writes HERMES_KANBAN_CLAIM_TTL_SECONDS; test_profiles_describe_secret_scope.py 1 passed)
L6.30 · FIXED 276fba379b (live-registry arm runs in a fresh interpreter; the same ordered prefix now gives 116 passed)
L6.31 · FIXED 65fe6c822e (scripts/sort_uv_lock_options.py plus a Step 3 entry plus a sorted-lock gate)
L6.32 · RETURNED too big: needs a design call on which live profile-config shapes count as "representative" (ten operator profiles, which legacy keys) and which producer entry the test drives (hydrate_frame vs the serve snapshot rebuild); the refusal itself is fixed (a40612b68c, 5c02a698ae)
L6.33 · ALREADY-DONE test_harness_core_ratchet.py 19 passed (run_tests.sh, 751532d1bf)
L6.34 · RETURNED too big: upstream itself calls load_config_readonly in ~196 files, so a blanket read-through for the 46 upstream test files that patch load_config changes upstream semantics. The structural rule needs the set of readers the fork moved (a fork-vs-upstream diff of call sites), joined against the test files that import them; that is a design lane
L6.35 · RETURNED too big: measured on the v0.21.6 merge df4e36a52a: `--since v0.21.6` selects 949 fork plus 5,571 upstream files through conftest reach (tests/conftest.py differs from the tag), the same as the release diff. The proposed fix does not shrink the gate. Release-merge reach needs its own rule (design)
