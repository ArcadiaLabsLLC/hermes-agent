# Agent console subagents — Step 6 settings and spawning

Status: implementation staged; qualification in progress; native footprint approval pending.
Step 7 and the full live smoke remain separate from this slice.

The existing Subagents viewer gains a Settings tab. Hermes remains the only configuration
writer and execution authority. Launcher holds drafts and confirmed observations only.
No setting rewrites running children or a parent's cached prompt/tool schema.

## Connections and values

Both console-only families expose the same four operations:
`runtime.conversation.subagents.{settings,settings.set,spawning,spawning.set}` and
`runtime.operator.conversation.subagents.{settings,settings.set,spawning,spawning.set}`.
The route captures the existing account/install/conversation/profile owner; caller paths,
worker identities and arbitrary config keys cannot be supplied as authority.

| Value | Native connection / meaning |
| --- | --- |
| `model`, `provider` | `config.yaml` → `delegation` → `tools/delegate_tool_config.py::delegation_defaults`; empty inherits parent; edits validated by `hermes_cli.model_switch.switch_model`. Advanced endpoint/credential routes stay in provider settings |
| `reasoning_effort` | Native `parse_reasoning_effort`; empty inherits parent, `none` disables |
| `max_iterations` | Native delegation iteration budget for a new child |
| `max_concurrent_children` | Native `_get_max_concurrent_children`; per-batch/background capacity, minimum 1 |
| `max_spawn_depth` | Native `_get_max_spawn_depth`; minimum 1 |
| `orchestrator_enabled` | Native `_get_orchestrator_enabled`; new children may orchestrate |
| `child_timeout_seconds` | Native `_get_child_timeout`; inactivity cap, 0 off, otherwise at least 30 seconds |
| `worktree_isolation` | Native `_get_worktree_isolation`; supported local Git workspaces only |
| `independent_completions` | Native `_get_independent_completions`; start a new parent session for its tool-schema change |
| `oneshot_max_children` | Native `_get_oneshot_max_children`; finite one-shot budget, 0 unlimited |
| `compression_threshold_tokens` | Native `_child_compression_cap_tokens`; 0 off, otherwise at least 16,000 |
| `surface_child_process_notifications` | Native `ProcessRegistry._surface_child_process_notifications`; next notification |
| `inherit_mcp_toolsets` | Native `_get_inherit_mcp_toolsets`; permission checks still apply |
| `version`, `generation`, `observed_at` | Existing signed owner generation and observation envelope |
| `revision` | HMAC of owned path and full raw/resolved configuration plus managed policy; required by `settings.set` |
| `profile_label`, `advanced_route` | Owned profile label; advanced routing disables model/provider edits here |
| Each field's `value`, `configured`, `default`, `writable`, `source`, `applies` | Native projection plus editing metadata in `subagents/settings.py`; no credentials returned. `changes[key]=null` removes an override |
| `scope=execution_host`, `host_kind`, `host_ref`, `paused` | `subagents/spawning.py` calls native `is_spawn_paused` / `set_spawn_paused` in the actual worker, isolated compute host, or operator runtime |
| `expected_generation`, `host_ref`, `paused` | Absolute guarded pause request; no toggle retry. Lost acknowledgement is unknown and requires readback |

Profile writes use `require_readable_config_before_write`, `load_config_readonly`, the
native managed policy, `CONFIG_WRITE_LOCK`, and `save_config`. The lock is Hermes' existing
in-process RLock, not a cross-process filesystem CAS. External editor changes observed before
commit refuse stale; concurrent uncoordinated editors are subject to native writer semantics.
Unknown settings, secrets and comments pass through the native writer. Native managed-key
stripping remains authoritative. Malformed profiles refuse writes.

Pause is process-wide, affects new spawning including other chats sharing that process,
leaves running children alone, and resets at process restart. It never creates a host.

## Per-seam footprint register

| Seam | Extension / single owner | Retirement and proof |
| --- | --- | --- |
| Service borrow mode | `ConversationService.subagents` validates `_owned_route`; `subagent_settings.py` binds the owned home without worker acquisition. Spawning retains existing-only borrow | Retain until an equivalent native owned settings route exists; reserved-route test uses zero workers |
| Worker-entry registration | `conversations/worker_subagents.py` registers exactly two spawning verbs through the existing registrar/contracts; settings remain service-owned | Replace only with equivalent owner-bound native RPCs; generation, transport and host-ref tests |
| Operator RPC family | Existing console dispatcher and `operator_session_read`, persona/home context, same shared settings/spawning implementations | Exact install/workspace/persona/instance/session/client scope remains required; foreign/device/unknown-caller tests |
| Native configuration lock | `hermes_cli/config.py` adds public access to existing `_CONFIG_LOCK`; two mechanical type annotations normalized by commit checks | Retire when native guarded-update API exists; no alternate lock or writer |
| Native default readers | `tools/delegate_tool_config.py` exposes a public projection that calls native knob readers | Retire in favor of an equivalent upstream public projection; no fork copy of effective-value resolution |
| Compute supervisor classification | `tui_gateway/host_supervisor.py` allows exactly `eternia.subagents.spawning.set` as concurrent control | Retire when native classification supports the same route; existing-only lost-ack test |
| Compute dispatch | `tui_gateway/compute_host.py` adds the exact spawning observer/control paths to existing allowlists | Retire with equivalent native owned routing; real process topology test covers native, compute, in-process |
| Launcher typed port | Same `AgentConversationSubagents` port, owner-validating adapter and controller; Settings tab owns draft presentation only | No independent runtime/config registry; stale draft, hidden view, managed field and confirmed pause tests |

Native delta against the claim base: four files, 35 additions / 4 removals.
The footprint fixture is intentionally not raised without the pending owner ruling.

## Qualification evidence and baseline blockers

- Clean baseline `b9e7e77cc7` reproduces gateway import failure at
  `tui_gateway/methods_onboarding.py:71`: `Path` is evaluated before the handler module
  receives its bound globals. Existing worker, compute and all six process round trips
  fail before Step 6 routing. This is outside the four reviewed seams.
- Any run temporarily postponing that annotation is diagnostic only; the file must be
  restored byte for byte. Such a run does not establish an unmodified release pass.
- Live UI QA and the full smoke are deferred by the user. No claim of live qualification.
- With only the temporary annotation fix, all 54 focused subagent tests pass, including
  real native-worker, isolated-compute and in-process round trips; the original onboarding
  file is restored byte for byte. The six process tests also pass during fixture capture.
- On the unmodified baseline file, settings tests pass 12/12, including every writable
  field, native provider validation against a loopback model endpoint, and a subsequent
  native child consuming the saved iteration budget without changing its parent.
  Owner/manifest tests pass 17/17,
  import-layer tests 15/15, and code health has zero blocking/advisory findings.
- Named killing mutation: replace the settings write's revision comparison with `False`.
  `test_external_change_managed_policy_and_malformed_config_refuse` fails at the expected
  stale refusal (`DID NOT RAISE SubagentError`, exit 1). Restore the guard; 10/10 pass again.
- Footprint measures `files=223 deleted_lines=1033 heavy=4` versus recorded
  `222/1032/4`. The ledger is complete; the remaining footprint failure is intentional
  pending the explicit owner ruling, not a waived test or fabricated approval.
