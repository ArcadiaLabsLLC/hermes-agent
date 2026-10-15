# `main`'s named reds, classified — 2026-09-23 (lane ORDER0)

**Base:** `origin/main` at `bcf8012e6a`, worktree `X:/wt/h-reds`. Every file was
run once, directly: `python -m pytest -q -p no:cacheprovider <file>` with the
shared test venv. Nothing was baselined, skipped or re-timed.

Classes: **(a)** code defect in fork code · **(b)** fixture/contract drift ·
**(c)** environmental · **(d)** upstream-owned. No red was class (a), so this
lane landed no test fix.

## Classification

| Test | Class | Evidence | Next owner |
|---|---|---|---|
| `tests/agent_runtime/test_serve_rpc_office.py::test_the_envelope_itself_is_validated_with_upstreams_codes` | (b) | Hand-typed `serve_rpc.method_names()` literal pins 35 names; the live set is 78. First divergence is `runtime.discussion.capabilities`; the `runtime.discussion.*`, `runtime.level.*`, `runtime.map.*` families and nine newer `runtime.local_llama.*` verbs joined the manifest without the pins moving. No generator exists: the literal is edited by hand. | Serve RPC manifest owner — refresh the pins or derive them from one shared expected-manifest fixture. |
| `test_serve_rpc_office.py::test_stdio_learns_the_method_set_from_ready_and_can_re_ask_version` | (b) | Same drift through `serve_rpc.manifest()` — `methods` and `tiers` differ; `contract` agrees. | as above |
| `test_serve_rpc_office.py::test_the_method_surface_is_transport_agnostic_and_answers_on_the_socket` | (b) | Same `manifest()` drift, socket leg. | as above |
| `tests/agent_runtime/test_serve_rpc_office_upsert.py::test_the_method_set_grew_and_the_contract_integer_did_not_move` | (b) | Same `manifest()` drift. | as above |
| `test_serve_rpc_office_upsert.py::test_the_write_method_is_transport_agnostic_and_answers_on_the_socket` | (b) | Same `manifest()` drift, socket leg. | as above |
| `tests/agent_runtime/test_serve_rpc_office_subscribe.py::test_the_reclaim_pair_joins_the_manifest_without_moving_the_contract_version` | (b) | Same `method_names()` literal drift. | as above |
| `tests/agent_runtime/test_snapshot_contract_version_authority.py::test_no_other_module_states_the_contract_version` | (b) | `agent_runtime/discussions/contract.py` (fork-only, absent from `upstream/main`) declares its own independent `CONTRACT_VERSION = 1` for the Discussion RPC lane, and `tests/agent_runtime/discussion_wire_cases.py::wire_cases` states `"contract_version": 1` as a literal. The gate's `LANE_CONTRACT_ALLOWLIST` registers every other lane integer (`ACTIONS_`, `RPC_`, `OPS_`, `HELLO_CONTRACT_VERSION`); the discussion lane landed without an entry. | Discussions lane — add the allowlist entry with its reason, and make `wire_cases` import `CONTRACT_VERSION` rather than restate it. |
| `tests/hermes_cli/test_placement_id_discriminability.py::test_the_pattern_is_byte_identical_to_the_launchers` | (b) | The test reads the launcher's `lib/features/mission_control/data/mission_agent_identity.dart`, which W4 S1b-P1 turned into an `export` shim; `_deliberatePlacementSuffix` now lives in `data/snapshot/mission_agent_identity.dart`. The patterns still AGREE (`_agent_(\d+|[0-9a-f]{8})$` on both sides, checked by hand against the new path) — only the path is stale. | Fork test owner — point `test_the_pattern_is_byte_identical_to_the_launchers` at `data/snapshot/`. |
| `tests/scripts/test_doc_cite_adjacency.py::test_the_live_canon_is_capped_by_its_baseline` | (b) | 8 unwaived line-cite failures (`02-runtime-data-and-shapes.md`, `03-transport-and-wire.md`, `04-boot-and-lifecycle.md`, `06-office-and-board.md`, three in `07-observability.md`, `harness-skills/…/operations.md`) plus 5 STALE waivers (`serve.py` cites in `03-` and `04-`). Code moved under the cites. Regen command, NOT run: `python scripts/doc_cite_adjacency.py --root docs/agent-runtime-harness --exclude archive/ --exclude planned/ --write-baseline` — but the right repair is re-anchoring the 8 cites to their symbols and deleting the 5 stale waivers. | Docs owner of `docs/agent-runtime-harness/`. |
| `test_doc_cite_adjacency.py::test_a_waiver_that_has_stopped_failing_turns_the_gate_red` | (b) | Consequence of the row above: the test plants ONE stale waiver over the live baseline and asserts the count is 1; the live baseline already carries 5, so it reads 6. | Closes with the row above. |
| `test_doc_cite_adjacency.py::test_the_live_canon_carries_no_foreign_line_cite` | (b) | Same probe, same 8 unwaived failures (arm 1 itself is clean: 0 foreign cites). | Closes with the row above. |
| `tests/agent_runtime/test_harness_serve.py` (7: `test_ready_line_and_exit_frames`, `test_a_drain_that_cannot_start_does_not_take_the_runtime_down`, `test_boot_reports_the_dispatches_it_settled`, `test_ready_frame_attributes_every_boot_phase`, `test_a_slow_boot_phase_shows_up_in_its_own_stamp`, `test_no_prewarm_is_started_when_none_is_injected`, `test_ready_is_emitted_before_either_prewarm_completes`) | (c) | `agent_runtime/serve_registry.py::_looks_like_serve` requires both `_SERVE_CMDLINE_TOKENS` (`hermes`, `serve`) in the process command line; the worktree path `X:/wt/h-reds` has no `hermes`, so a `stderr` frame lands before `ready`. **Positive control:** the same command with one harmless argument added — `-p no:hermes_cmdline_control` — runs both serve files **41 passed, exit 0**. | Fork suite — the queue row's design question: the boot must not classify its own row by command line, or the tests pin the probe. |
| `tests/agent_runtime/test_serve_boot_skill_install.py` (2: `test_boot_skill_install_is_off_unless_the_entry_point_turns_it_on`, `test_a_failed_boot_install_is_loud_but_never_fatal`) | (c) | Same cause; same control (included in the 41). | as above |
| `tests/test_no_frozen_hermes_home.py::test_no_new_frozen_hermes_home_values` | (d) | The two frozen names are upstream-authored: `gateway/mirror.py` is byte-identical to `upstream/main` (blob `513bf882da` both sides); `tui_gateway/server.py`'s `_HERMES_HOME_AT_IMPORT` line is identical in `upstream/main`, and the fork's only delta to that file since the merge base is one docstring line. | Fork suite — scope the ratchet with `tests/_fork_scope.py::is_fork_authored`, never by editing upstream. |

Files that ran green and were in the "office manifest set" search:
`test_office_layout_policy.py`, `test_serve_rpc_office_remove.py`,
`test_serve_rpc_office_resolve.py`, `test_serve_rpc_office_surface_update.py`
(all exit 0).

**Counts:** (a) 0 · (b) 11 · (c) 9 · (d) 1 — 21 red tests in 9 files.

## Mutation inventory

`scripts/changed_line_mutation_check.py --list --base origin/main` exited 2 on
one entry only: `hh12-the-mis-kinded-test-over-claims-on-a-silent-item` named
`agent_runtime/harness_doctor.py::_desk_litter_reason`, deleted with the
desk-litter census (`f1268bd017`), and its claim test
`test_the_minted_kind_is_what_the_store_recorded_not_what_the_id_looks_like`
went with it. The entry is retired.

The three `ctp*` entries the queue row named as stale were NOT stale on
`bcf8012e6a`: each `find` resolves exactly once inside its symbol
(`agent_runtime/stream.py::_defer_demote_build_for_active_turns`,
`agent_runtime/stream.py::SNAPSHOT_DEMOTE_DEFERRAL_MAX_MS`,
`hermes_cli/harness_parts/persona_commands.py::_cmd_mission_chat_message`).
Each was proven to still KILL by applying its `find`→`replace` in the worktree,
running its own claim test, and restoring the bytes (restored run green):

| Claim | Mutated run | Red |
|---|---|---|
| `ctp5-demote-deferral-fires-on-every-lane` | KILLED | `test_a_non_demote_lane_never_defers`: `assert 3500 == 0` |
| `ctp5-deferral-bound-widened-to-a-starvation` | KILLED | `test_demote_bound_covers_two_seconds_but_releases_at_3500`: `assert 5000 == 3500` |
| `ctp4-plan-drops-the-session-db-measurement` | KILLED | `test_the_handlers_session_db_open_reaches_the_durable_record`: `'session_db_open_ms'` absent from the durable phases |

They were not re-anchored; they needed nothing.

## Retired 2026-09-24 (lane POLISH, `fork/suite-polish-2026-09-24`)

On `6e25c6753c` plus the lane, the class-(b) rows above run green; lanes in
between moved them. The class-(c) rows (`test_harness_serve.py` ×7 and
`test_serve_boot_skill_install.py` ×2) are fixed at the source: the boot's
prune no longer refuses its own row, matched by `boot_id`. It had been
classifying that row by command line. `tests/agent_runtime/test_serve_registry.py::test_the_pruning_boots_own_row_is_never_refused_whatever_its_command_line`
pins the fix whatever the checkout's path. The class-(d) row was also green on
this tree. Method and commits: `suite-cost-centres-2026-09-24.md` §11.
