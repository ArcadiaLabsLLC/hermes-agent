# Agent Console subagent settings — Step 6

Row `RT-AGENT-CONSOLE-STEP-6`; plan `docs/agent-runtime-harness/planned/p10-agent-2026-10-19.md` §1.
The owner approved Step 6 on October 16, 2026. Two authorities join the existing owned
subagent port: a profile's delegation defaults (profile state, served by the serve process)
and the spawning pause of one execution host process. Nothing spawns, schedules or stores
anything new; the native knob getters and `tools.delegate_tool_registry.set_spawn_paused`
remain the only implementations. The pause scope is the execution host process (owner
ruling pending, plan §6 decision 3, built on the recommended path).

## Wire values

Both families gain four operations: `runtime.conversation.subagents.{settings, settings.set,
spawning, spawning.set}` and the same four under `runtime.operator.conversation.subagents.`.
`subagents/model.py::REQUIRED_PARAMS` is the one table; `subagents/params.py::METHOD_PARAMS`
publishes it and the manifest fixture gained exactly these eight methods (console tier).

| Value | Source and meaning |
| --- | --- |
| identity | echoed exactly as Steps 1–5 (native: `install_id`, `session_id`, `client_scope`, `profile`; operator: the six operator keys) |
| `version`, `generation`, `observed_at` | the existing envelope. `settings`' generation binds the route and its recorded home; `spawning`'s binds the conversation owner, as `list` does |
| `scope` | `profile_defaults` or `execution_host` |
| `profile_label` | `hermes_constants.profile_name_for_home(home)`, else the home's directory name |
| `revision` | sha256 of the canonical `fields[]`; `settings.set` with another revision refuses `subagent_reference_stale` |
| `advanced_route` | always `false` (no fork-only knobs are exposed) |
| `fields[]` | the launcher fixture's fourteen keys in its order (`subagents/settings.py::DELEGATION_FIELDS`): `key`, `value` (what the next child gets: upstream's own getter under the route's home, via `_upstream_doors.py::delegation_knobs`; the merged config for the six keys with no getter), `configured` (the raw `delegation.<key>` of the profile's `config.yaml`, null when unset or ill-typed), `default` (upstream `DEFAULT_CONFIG`), `writable`, `source` (`managed` / `profile` / `native_default`), `applies` (`next_child`; `independent_completions` `new_session`; `surface_child_process_notifications` `next_notification`) |
| `changes` | `settings.set` only: `{key: value \| null}`; keys outside the fourteen, ill-typed values and an empty map refuse `subagent_request_invalid`; `null` deletes the key; written with `hermes_cli.config.save_config` under the home (explicit keys preserved even when equal to the default) |
| managed key | `delegation.<key>` pinned by the managed scope (`_upstream_doors.py::delegation_managed_keys` over the public `managed_scope.managed_config_keys`) is `writable:false`, `source: managed`; a write naming it, or any write on a package-managed install, refuses `subagent_setting_managed` (`Refusal.MANAGED`, code 4606) |
| `host_kind` | `native_worker` (the conversation's worker process), `isolated_compute` (the compute host process), `operator_runtime` (the serve itself: every persona turn in it) |
| `host_ref` | `references.generation(("execution_host", host_kind, pid, boot stamp))` in the answering process; a restarted host (new pid, boot stamp and reference key) refuses every older `host_ref` as stale |
| `paused` | `spawning.set` only, a bool; the reply's `paused` is the process's state after the write |

Routing: `settings` / `settings.set` never borrow or start a worker — native through
`ConversationService.subagents` → `conversations/subagents.py::inspect_settings_route` with
`route.home`; operator through `subagents/operator.py::inspect_operator` with the binding's
profile home (or the recorded `head_home` of an inherited profile). `spawning` /
`spawning.set` are delivered to the process that owns the pause: native → the worker peer verbs
`eternia.subagents.spawning{,.set}` (`worker_subagents.py`), dispatched by
`subagents/native.py::inspect_native` before any registry read; isolated compute → the worker's
forwarder `subagents/compute.py::observe` (read on `supervisor.observe`, write on
`supervisor.control(existing_only=True)`, `host_kind` stamped by the forwarder); operator →
in-process `subagents/spawning.py::inspect_spawning`.

## Per-seam footprint ledger

| Seam | Connection and disposition | Retirement condition |
| --- | --- | --- |
| Compute observer allowlist | `ComputeHost._handle_observe` admits `eternia.subagents.spawning` (+1 line, additive) | Public owned-child observation registrar (the Step 1 row) |
| Compute control receiver | `ComputeHost._control_ack` hands `eternia.subagents.spawning.set` to `subagents.compute.control_ack` (+1 line: the fork-added set now spans two lines) | Public classified control extension (the Step 4 row) |
| Compute control sender | `host_supervisor.MUTATOR_ROUTE_TABLE` classifies `eternia.subagents.spawning.set` `run-concurrent` (+1 line) | Public non-creating control dispatch (the Step 4 row) |
| Knob getters door | `_upstream_doors.py::delegation_knobs` reads `tools/delegate_tool_config.py` `_get_*` getters and `_cfg`, and `tools/delegate_tool.py::_child_compression_cap_tokens` | HELD widening candidate: a public `delegation_settings()` reader returning the effective values a child gets. The ten reads are grandfathered in `tests/fixtures/import_layers_grandfathered.json` (`private_upstream_attributes`) and recorded in the ledger's private-name table |
| Managed keys door | `_upstream_doors.py::delegation_managed_keys` over the public `hermes_cli.managed_scope.managed_config_keys` | none needed (public name); kept as a door so the `delegation.` projection has one owner |

Measured `[up-fp]`: before `files=230 deleted_lines=1035 heavy=1`; after
`files=230 deleted_lines=1035 heavy=1` (unchanged). Per file: `tui_gateway/compute_host.py`
+56/-5 → +58/-5; `tui_gateway/host_supervisor.py` +79/-10 → +80/-10; both under the heavy
threshold, no upstream line deleted. The fixture does not move.

## Measured while building

The knob env fallbacks (`DELEGATION_MAX_CONCURRENT_CHILDREN`, `DELEGATION_CHILD_TIMEOUT_SECONDS`)
never take effect when the config loads: `load_config` merges `DEFAULT_CONFIG`, whose
`delegation` section carries both keys, so `_knob` returns the config value first
(`HERMES_HOME=<empty> DELEGATION_MAX_CONCURRENT_CHILDREN=7` → `_get_max_concurrent_children() == 10`,
2026-10-19). The plan's `source: environment` is therefore never true and is not emitted;
`value` is the getter's result, which is what the next child gets.

## Killing mutations (observed reds)

| Test | Mutation → red |
| --- | --- |
| `test_subagent_settings.py::test_managed_key_is_read_only_and_refuses_write` | `delegation_managed_keys` returns `frozenset()` → `assert (True, 'native_default', 3) == (False, 'managed', 3)` |
| `::test_stale_revision_refuses` | revision compare removed from `write_settings` → `DID NOT RAISE SubagentError` |
| `::test_unknown_key_refuses_and_writes_nothing` | allow-list dropped (`key in _BY_KEY and …`) → `KeyError: 'subagent_auto_approve'` |
| `::test_value_is_the_getter_result_not_the_file_or_env` | merged config read instead of the getter → `assert (0, 0, 'profile') == (1, 0, 'profile')` |
| `test_subagent_spawning_native.py::test_paused_worker_refuses_spawn` | `spawning` answered in the serve process instead of the worker peer → `assert not True` (`is_spawn_paused()` in the serve) |
| `test_subagent_spawning_compute.py::test_isolated_compute_pause_round_trip` | `MUTATOR_ROUTE_TABLE` line removed → `ValueError: unclassified host mutator route: eternia.subagents.spawning.set`; `_handle_observe` name removed → `4604 … subagent_unavailable` (`Unsupported observation`) |
| `::test_stale_host_ref_after_restart` | `host_ref` compare skipped → `KeyError: 'error'` (the old reference paused the new host) |
| `test_serve_rpc_office.py` manifest pin | a ninth operation (`settings.reset`) → the manifest list differs at `runtime.conversation.subagents.settings.reset` |

Live smoke is Step 7 (`MC-SUBAGENT-SMOKE`, launcher).
