# Layout sheet — `hermes_cli/harness_parts/serve.py` (lane H4)

Base: `main` @ `78501db796` · 6,646 raw / 4,041 code / 46 top-level defs · longest `serve_loop` 3,760 (2508–6267) with **39 nested defs** (listed in §4) · `str==` 27 · `isinstance` 30 · owner doc `docs/agent-runtime-harness/03-transport-and-wire.md`. LAST of the harness lanes (09-21 §2 H4, kept): waits on H1–H3 so nothing else is moving in the boot path; the operator's one boot (program §7) gates its CHANGE. Already a real module (not exec'd); 46 test files import it by path, so `serve/__init__.py` is the ONE place a re-export is allowed until the CHANGE retargets them.

## 1. Section map → target modules (package `hermes_cli/harness_parts/serve/`)

| lines | what is there | → module | layer |
|---|---|---|---|
| 1–425 | imports, constants, the protocol docstring | `serve/__init__.py` (map) + `serve/constants.py` | wiring |
| 426–551, 959–986 | `ops_manifest` (43), `_pairing_block` (57), `_is_gateway` (22), `_credential_kind` (28) | `serve/manifest.py` (~200) | policy |
| 554–943 | `gateway_listen_config` (37), `gateway_block_when_no_listener` (54), `start_gateway_listener` (101), `_gateway_authenticator` (181) | `serve/gateway_listener.py` (~400); the authenticator's four-hello dispatch → `agent_runtime/serve_gateway_auth` (§2) | lanes |
| 1054–1362 | `_install_service_stop_signal`, `_restore_service_stop_signal`, `_end_reason_is_known`, `_ServeEndReason` (64), `_console_ctrl_reason_callback`, `_install_console_ctrl_reason_handler`, `_install_signal_reason_handlers` | `serve/end_reason.py` (~330) | I/O |
| 1401–1456, 1587–1737, 2308–2505 | `_repoint_logging_root_stderr`, `_maybe_inject_boot_fault`, `_stat_board_tree`, `_stat_turn_store_tree`, `_runtime_state_fingerprint` (101), `_prewarm_read_model_snapshot`, `_prewarm_provider_runtime`, `_prewarm_persona_chat_actors`, `install_harness_skills_at_boot` (60), `_annotate_import_tax` | `serve/boot.py` (~560) | lanes |
| 1740–2030 | `_PollResponseCacheEntry`, `_PollResponseCache`, `current_serve_request_id`, `_FrameWriter` (48), `_LineFrameProxy` (101), `_SafeSink`, `_emit_deferred_reply` | `serve/frames.py` (~300) | I/O |
| 2033–2107, 2186–2305 | `_ArgvRequest` (75), `_build_harness_parser`, `_system_exit_code`, `_clean_argv_root`, `HandlerExit`, `ArgvRootUnsupported`, `dispatch_argv` (33) | `serve/argv_lane.py` (~230; shrinks under 09-21 §4.2) | lanes |
| 2110–2183 | `_DrainState` (54), `_drain_deadline_seconds` | `serve/drain.py` (~90 now; +`_drain_monitor` 5048, `_finish_drain` 4939, `_force_exit_after_drain` 5026 as methods in the CHANGE → ~280) | lanes |
| 2508–6267 | `serve_loop` | MOVE whole to `serve/loop.py` (grandfathered for exactly one commit); CHANGE → `ServeSession` (§4) | lanes |
| 6270–6646 | `_raw_fd_lines`, `_claim_protocol_pipes`, `_cmd_serve` (109), `_cmd_serve_connect` (194) | `serve/commands.py` (~380); `serve/__init__.py` re-exports the 46 test files' names until the CHANGE retargets them | wiring |

Result after the MOVE: 9 modules, one of them (`loop.py`) over the ceiling by design for one commit. After the CHANGE: `loop.py` → `session.py` + `handle_message.py` + `lanes.py` + `subscriptions.py` + `drain.py` (§4), every one ≤ 500. The 09-21 H4 table stands; this sheet adds the line ranges and moves `_credential_kind` next to `ops_manifest` (they read the same manifest).

## 2. Routing sites → dispatch tables (the CHANGE commit)

| site (base line) | shape today | replacement | killing mutation |
|---|---|---|---|
| `_handle_message` 5183–~5850 (op ladder) | eleven `if op == "…":` guard blocks in sequence — `ping` 5191 · `hello` 5194 · `version` 5210 · `connections` 5287 · `subscribe` 5290 (250 lines) · `unsubscribe` 5540 · `drain` 5555 · `stacks` 5694 · `shutdown` 5714 · `cancel` 5733 · then the argv fall-through — each block returning; the `elif` probe counts it as 0 chains, the `str==` column as 11 | `ServeSession._OPS: Mapping[str, Callable[[ServeSession, message, sink, connection], str | None]]` frozen at class scope, one method per op (`_op_ping`, `_op_hello`, …), `_handle_message` = validate → `self._OPS.get(op, self._op_argv)`; the op vocabulary is `OPS: Final[tuple[str, ...]]` in `serve/constants.py` and `ops_manifest` reads it (today the manifest and the ladder are two copies of the same list — rule 12's "one vocabulary, one reader") | swap the `subscribe` and `unsubscribe` entries → `tests/hermes_cli/test_serve_subscribe*.py` red on the first subscribe (`unsubscribe` answers with no subscription) |
| `_gateway_authenticator` 763–943 (`kind` ladder) | `if kind == "pairing_code"` 839 · `if kind == "peer_code"` 856 · `if kind == "peer_install_id"` 895 after `_credential_kind` (959) has already classified the frame — the classifier and the ladder are two readers of one vocabulary | `CREDENTIAL_KINDS: Mapping[str, Callable[[store_root, message, outcome], AuthOutcome]]` in `agent_runtime/serve_gateway_auth` (R3 owns the module; H4 owns the call), `_credential_kind` returns a `CredentialKind` Enum and is the table's only key source; a frame naming two kinds stays the FIRST guard (that is a boundary, not routing) | swap `pairing_code` and `peer_code` → `test_serve_gateway_auth*` reds on the pairing redeem |
| `_handle_message` subscribe arm 5290–5540 | `declared_raw = message.get("fold_entities")` → `if None / elif isinstance(list) and all(str) / else refuse` (5305–5312, the routed chain the probe found) | `patch_coverage.parse_fold_entities_option` already exists (12 lines) — the arm calls it and refuses on its typed `FoldEntitiesInvalid` reason | make the parser accept an empty string → the fold-negotiation test reds |
| `_ServeEndReason` 1196–1259 + the three installers | reason strings (`"console_ctrl"`, `"signal"`, `"service_stop"`, …) set from three handlers | `EndReason` Enum (closed vocabulary, rule 14); `_end_reason_is_known` becomes membership | add a fourth reason without an Enum member → the `end_reason_is_known` test reds |
| `_cmd_serve_connect` 6453–6646 (194) | argv shape checks in sequence (`--root`, `--socket`, `--pipe`) | `ConnectTarget` value object with one parser; the function becomes ≤ 60 lines | swap socket/pipe → `test_serve_connect*` reds |

Density goal at review: `str==` 27 → ≤ 8 (payload-key guards), `isinstance` 30 → unchanged (boundary validation).

## 3. Helpers that unify

| here | duplicate of | authority |
|---|---|---|
| `_emit` inside `serve_loop` (a frame writer) | NOT `store_events.emit_store_event` — named so the R1 fold does not take it | stays in `frames.py` as `FrameWriter.emit` |
| `_stat_board_tree` 1587 / `_stat_turn_store_tree` 1615 | one walker, two roots | `boot.stat_tree(root, pattern)`; `_runtime_state_fingerprint` calls it twice |
| `_prewarm_*` ×3 (2308–2412) | three functions with the same shape (import lazily, time it, record a receipt) | `boot.Prewarm` table: `PREWARMS: tuple[(name, callable)]`; one runner, one receipt shape |
| `_system_exit_code` 2198 | `persona_commands._safe_exit_code_value`, `profile_runner._safe_exit_code` | `serde.safe_int` |
| `_build_harness_parser` 2186 | `harness.build_parser`/`build_cli_parser` | calls `harness.populate_parser` directly (H2 deletes `build_parser`) |

## 4. `serve_loop` → `ServeSession` (the CHANGE; 39 closures become methods on five modules)

Fields = the 21 enclosing locals `_handle_message` reads (09-21 H4 list) + the 4 `nonlocal`s (`drain_state` at 5188 and three the review lane lists by AST). The closures, by target module (base lines):

| module | closures |
|---|---|
| `serve/session.py` (`ServeSession.run`, the boot order, `_note_end` 2885, `_write_end` 2891, `_busy_frame` 2933, `_report_quiet_requests` 2966, `_service_log` 3020, `_liveness_pump` 4040, `_unregister_instance` 4148, `_detach_stdio_owner` 6081, `_park_until_service_stop` 6104) | 11 |
| `serve/handle_message.py` (`_handle_line` 5158, `_handle_message` 5183 → the `_OPS` table and one `_op_*` method per op, `_on_drop` 5400, `_handle_socket_line` 4934, `_hello_ok_frame` 4803, `_connections_frame` 4887, `_build_mismatch` 4782) | 7 + 11 op methods |
| `serve/lanes.py` (`_run` 3036 — the argv lane, ~950 lines today with its own `_prewarm_worker` 3984; becomes `ArgvLane.run` split at its `# ----` mark 3722 into `admit` / `execute` / `reply`; `_spawn_chat_turn` 5851, `_spawn_reply` 5907) | 5 |
| `serve/subscriptions.py` (`_emit_safely` 4210, `_sink_for` 4216, `_owner_of` 4234, `_deny_subscribe` 4237, `_accepted_fold_entities` 4300, `_room_fold_declarations` 4350, `_promoted_fold_entities` 4369, `_room_wants_stale_first` 4399, `_stream_source` 4442 + `_generate` 4513, `_ensure_stream_hub` 4550, `_release_subscription` 4597, `_reclaim_abandoned_streams` 4641, `_on_connection_closed` 4694, `_broadcast_lanes` 4705, `_close_socket_lane` 4724) | 16 |
| `serve/drain.py` (`_finish_drain` 4939, `_force_exit_after_drain` 5026, `_drain_monitor` 5048 → `DrainState` methods) | 3 |

`serve_loop(...)` survives as a ≤ 20-line function that builds `ServeSession` and runs it — the two field tools (`mission_runtime_timeline`, the RO-1 sidecar) and every test see the same entry point. **Behaviour contract:** RB-7 and RO-9 green both arms; the boot timeline's receipts byte-identical for a fixture boot; the operator's boot (program §7). **Killing mutation for the session:** reorder `_unregister_instance` before `_write_end` → the restart-fence test (`restart-drain-fence-field-notes-2026-09-07.md`'s gate) reds.

## 5. Dead code found while reading

| symbol | lines | evidence |
|---|---|---|
| `_build_harness_parser` 2186–2195 | 10 | wraps `hermes_cli.harness.build_parser` for the argv lane; after H2 retargets to `populate_parser` the wrapper is one call — inline in the MOVE, not a deletion row |
| the argv lane's `_run` 3036–~3980 | ~950 | NOT dead — but the 09-21 §4.2 argv census (which `_cmd_*` the launcher still lowers to argv) decides how much of it survives; the row is the ORDER 2 row's §4.2 item, unchanged |
| `_maybe_inject_boot_fault` 1440 | 17 | env-driven fault seam (boot-sweep plan); production reads it once at boot — KEEP, rowed as "test seam?" with `_persona_chat_fault_injection` (one decision for both) |

The by-name census found nothing unreferenced in this file; every top-level def is imported by a test or called from `serve_loop`.

## 6. Doors (upstream imports; all FIRST — public names)

`tools.process_registry` (the 2026-09-24 `notify_on_complete` ruling: the fork's second door is already deleted; the remaining import is the public registry read) · `model_tools` · `hermes_cli.config` · `agent.ssl_guard` · `agent.process_bootstrap`. Through `harness_parts/_upstream_doors.py`; no widening.

## 7. Commits

1. **MOVE** `refactor(serve): serve.py → harness_parts/serve/ (9 modules; serve_loop moved whole)` — spans byte-identical; `serve/__init__.py` re-exports; `[ds-size]` unchanged (loop.py grandfathered one commit).
2. **CHANGE** `refactor(serve): ServeSession; _OPS and CREDENTIAL_KINDS tables; EndReason; drain methods` — §2 + §3 + §4 with each red pasted; re-exports deleted and the 46 test files retargeted; `[ds-size]` → 0 for this lane. Reverted (MOVE stands) if the operator's boot disagrees with the receipts.
