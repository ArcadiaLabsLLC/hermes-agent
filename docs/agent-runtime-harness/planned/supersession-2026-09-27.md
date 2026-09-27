# Supersession pass — fork-only modules against upstream (2026-09-27)

Lane SUPERSEDE, docs only. Question: which fork-only modules has upstream made redundant?
Rule: `Harness_Brain/10 — Programs/Upstream Sync.md` § "Each merge — the supersession pass" — a fork implementation
upstream now provides is adopted from upstream; an unavoidable parallel is a recorded ledger row.

- Merge base `067fa1a257`; fork `origin/main` `857b8c9b94`; upstream `upstream/main` `062dc1e7f0f`.
- **Population: 760 files** — `git diff --name-only --diff-filter=A 067fa1a257 origin/main` minus `Harness_Brain/`, `docs/`, `tests/`
  — grouped into **57 units**.
- **Upstream side read:** the 1,339 commits `067fa1a257..upstream/main` (two days; 457 after dropping desktop, catalog,
  attribution and test-only subjects, all read by subject; candidate diffs read); the two new upstream modules
  (`agent/runtime_self_protection.py`, `gateway/turn_executor.py`); the plugin surface diffed base→tip
  (`hermes_cli/plugins.py`, `hermes_cli/middleware.py`, `hermes_cli/plugins_dispatch.py` unchanged, no new `invoke_hook` site,
  `model_tools.py` +2 lines for todo aliases — so nothing in `plugin-fit-2026-09-26.md` moves); and one whole-tree AST
  scan of every non-test upstream `.py` for definitions byte-identical (docstrings stripped) to, or sharing a public name
  with, a fork-only definition. The scan is what found rows U39 and U40: both parallels predate the base, and the
  2026-09-24 pass did not record them.
- Strictness: a unit is SUPERSEDED/PARTIAL only where the upstream code answers the same question for the same call
  sites. Same-named hooks and look-alike features are KEEP, and the row says what was compared.

## Table

| unit | files (n) | what it does | upstream equivalent (commit / module) | verdict | why |
|---|---|---|---|---|---|
| U01 `agent_runtime` leaves (`serde`, `clock`, `file_locks`, `git_cmd`, `yaml_io`, `subprocess_pumps`, `store_file_io`, `parse_cache`, `_upstream_doors`, models/errors/events…) | 22 | One-owner helpers every fork module shares (program rule 15) and the door onto upstream privates | `hermes_yaml` (base), `_subprocess_compat.expose_pm_git` (`305072f4a6`), `tui_gateway/git_probe.run_git` (base) | KEEP | `yaml_io.dump` already IS `hermes_yaml.safe_dump`; `load` is a documented YAML-1.1 parallel. `git_cmd` builds argv; `expose_pm_git` provisions PATH for explicit user actions only. `git_probe.run_git` is a TUI probe, not an argv owner |
| U02 roots & profile home (`profile_home`, `machine_roots*`, `root_anchor`, `root_observability`, `config/`, `profile_context`…) | 18 | Head/shared homes, the machine-root token chokepoint, root anchoring and root stamps | none | KEEP | Nothing in the window touches profile-home resolution except `54e3691926` (gateway session cwd by bound profile backend), which is a different question |
| U03 stores & event log (`store/`, `store_conflicts`, `store_events`, `event_rotation`, `checkpoint`, `task_store_stub`, `incidents`) | 11 | Persona/workspace/realm stores, conflict sidecars, the domain event log and its rotation | none | KEEP | No upstream store for these domains |
| U04 personas & instances (`persona_assignments/`, `agent_create/`, `blueprints/`, `personas`, `persona_*` binding/lifecycle/identity, `agent_retire`…) | 35 | The persona-instance roster, the one agent-create/retire sequence, profile binding | none | KEEP | Upstream profiles commits (`78de8f5322`…) are skill-distribution merges, not a roster |
| U05 persona chat (`persona_chat_history/`, `persona_chat_continuity/`, `chat_live_log/`, `chat_session_scope`, `transcript_order`, `auxiliary_chat`, `native_persistence`…) | 31 | Persona chat roster, transcripts, continuity, the operator-visible SessionDB, live log | `2e43498413` sessions.show_subagents; `f81bb4c485` created_source | KEEP | Upstream lists delegate runs in its own session listing; the fork's history is keyed on persona/instance. `created_source` is a column, not the fork's ownership keys |
| U06 SessionDB extensions (`session_extensions`, `compression_metadata`) | 2 | Delete a chat root with its compression continuation chain; purge retired scratch rows; carry persona keys into compression children | `hermes_state_common._non_continuation_child_sql` (`2759f0fe97`, one owner for the continuation predicate) | PARTIAL | `delete_compression_lineage` re-derives "is this child a continuation" in Python: it presence-matches `_branched_from`/`_delegate_from` and skips `_reset_from` and `source='tool'`, so a reset fork or tool child of a compression-ended root is deleted as lineage, and a continuation that inherited a marker naming another row is left behind. Upstream now owns that predicate (parent-bound markers, all four exclusions). The delete itself has no upstream equivalent (`delete_session` orphans compression children). `compression_metadata`: no equivalent |
| U07 mission-chat turn lane (`mission_chat_*`, `mission_chat_turns/`, `chat_turn*`, `turn_*`, `run_budget`, `volatile_tail`, `chat_lane_*`…) | 27 | The mission-chat turn: admission, context, prompts, steer, clarify bridge, budgets, journal | `9fc7f17906` (gateway steer keeps silence fallback) | KEEP | Upstream steer/clarify commits are gateway/desktop lanes; no mission-chat turn |
| U08 `profile_runner/` | 15 | One agent run under a profile's runtime | none | KEEP | — |
| U09 prompt & usage observability (`prompt_observability/`, `usage_ledger`, `cache_policy`, `cache_routing`, `codex_observability`, `*_observability`, `boot_timeline`…) | 24 | What the model was sent, per-call usage, cache policy/routing, timing receipts | `9f27e75a77` usage anchors, `d159b6e0c3` xAI fork cache scope, `a2a19bcc77` clean-EOF stream labels | KEEP | Upstream's usage anchor/display clamp and fork cache scope serve its own status bar and forks; the fork's ledger/routing are per persona turn. `codex_observability` already reads upstream's stream observer hooks |
| U10 tool policy (`tool_blocks`, `tool_permissions`, `tool_visibility`, `toolset_names`, `permission_modes`, `coordinator_permissions`…) | 7 | Per-run tool blocks and chat-lane tool permissions, through the plugin surface | none | KEEP | Plugin surface unchanged since base |
| U11 terminal envelope (`terminal_envelope/`, `terminal_envelope_explain`, `terminal_policy`) | 8 | Operator-governed decision point for envelope-gated commands | `agent/runtime_self_protection.py` (`541e4dc0ba`), `c42c90552e` | KEEP | Upstream's new floor protects the runtime's own interpreter from deletes; it is not an operator envelope and has no persona scope |
| U12 MCP lane (`mcp_admission/`, `mcp_lane`, `mcp_environment`) | 8 | Per-run declared MCP admission; lane accounting; `HERMES_MCP_ENV_*` and machine-root overlays | `a052836559` (config-added servers connect on next build), `79dbb1450e` (managed Node on MCP PATH), `678a4762b8` | KEEP | Upstream changes discovery/PATH, not selective admission or env overlays |
| U13 skills (`skill_*`, `skills_inventory`, `queued_skills`, `external_skill_links`) | 12 | Shared-skill resolution, promotion, publishability, search, `skill_view` result via `transform_tool_result` | `22127999be`, `55a93d8f70` (read-dedup reset); curator purge `bade8387c4`… | KEEP | Dedup-cache resets and curator TTL do not touch resolution/promotion or the `skill_view` rider |
| U14 realm sync (`realm_sync/`, `persona_instance_sync/`, `sync_*`, level/map/flow-graph/persona-config/profile-artifact sync, workspace scope/template) | 32 | Three-way realm sync families and workspace scoping | none | KEEP | — |
| U15 Mission Board (`board_store/`, `board_models`, `board_order`, `board_sync`) | 9 | Board store, order keys, board sync | none (upstream kanban is a task runner) | KEEP | Kanban commits in window are dispatcher/gc fixes |
| U16 Mission Office (`office_store/`, `office_*`, `serve_office_subscriptions`, `flow_graph`) | 18 | Office store, layout policy, re-key guard, office push, flow graph | none | KEEP | — |
| U17 read model (`snapshot/`, `core_cache/`, `state_patches/`, `parity`, `projection_accountant`, `decision_contract_registry`…) | 38 | Snapshot build, persisted core cache, patch lane, projection accounting | none | KEEP | — |
| U18 stream & projections (`stream/`, `operator_channels/`, `runtime_hud/`, `running_work/`, `stream_resume`, `serve_stream_hub`) | 30 | Stream frames, fan-out hub, console/HUD/running-work projections | none | KEEP | Upstream `stream` commits are provider streaming |
| U19 serve transport (`serve_rpc/`, `serve_socket/`, `serve_auth`, `serve_registry`, `request_control`, `build_stamp`, `build_identity`, `call_authorization`) | 34 | Method lane, socket lane, discovery, build identity | `41de397af6` (serve ready tokens), `15e26c76f3` (dashboard `--port 0` backends) | KEEP | Both concern upstream's dashboard serve, not `hermes harness serve` |
| U20 cross-install gateway (`gateway_endpoints/`, `gateway_peers/`, `gateway_*`, `serve_gateway_*`, `peer_directory`, `media_handles`, `media_proxy`) | 22 | Paired devices and peers, TLS, pairing codes, peer directory, media handles/proxy | none (`gateway/hosted_room_peer.py`, `gateway/pairing.py` predate base, different protocol) | KEEP | No gateway pairing/peer change in window |
| U21 agent→agent dispatch (`dispatch_store/`, `dispatch_delivery/`, `dispatch_session_policy`, `relay_policy`, `target_policy`, `child_events`) | 16 | Durable detached dispatches and their serve-hosted delivery drain | `fa655b2980` (A2A no auto-TTS), `d9ef15dd3c` (async delegation handoff ends turns) | KEEP | Upstream A2A is a gateway platform; delegation handoff is `delegate_task`, not persona→persona dispatch |
| U22 `tools/agent_chat*` (tool, handlers, detached dispatch, remote client) | 13 | The six `agent_chat_*` tools, detached children, cross-install leg | `0cd93f0268` (Windows MCP tree-kill in `process_identity`) | KEEP | Tree-kill already goes through upstream's `ProcessRegistry._terminate_host_pid` door |
| U23 `conversations/` + `discussions/` | 34 | Native conversations on the authenticated service; discussion-table authoring | none | KEEP | — |
| U24 `local_llama_adapter/` | 8 | Launcher `runtime.local_llama.*` contract over upstream's managed runtime | `9c1ef17550`, `3582c17cbc` (engine and models move into the PM store/machine dir) | KEEP | Upstream still has no `executable_path`, per-model preset override or extra model roots, the three gaps the adapter's docstring names |
| U25 `harness_doctor/`, `doctor_extensions` | 6 | The chat runtime health report | `3ddf06867f` (doctor reconciles Windows gateway autostart) | KEEP | Different checks |
| U26 credentials (`auth_extensions`, `pool_rotation`, `provider_probes`, `provider_health`) | 4 | Credential selection sidecars, non-persisting selection, readiness | nous pool fixes `6a3db7c487`, `e7bab8eb18`… | KEEP | Upstream fixes nous refresh-pool ownership; the fork owns selection state, not pools |
| U27 process completion (`background_completion`, `process_notifications`, `delivery_capability`) | 3 | Notify-on by default at spawn; wait ceiling; explicit durable completion restore; async-delivery declarations | `8cb4fdc925`, `ede966b347`, `10938a7cf9`, `7550800d8b` | KEEP | Heartbeat gating, CLI drain honour and PID re-adopt are different mechanisms; the terminal `notify` default is unchanged upstream; `restore_undelivered_completions` is upstream's (base), the fork only moves when it runs |
| U28 plugin hook riders (`gateway_queue_status`, `kanban_blocked_pm_tick`, `kanban_blocked_pm`, `kanban_crash_evidence`) | 4 | `/queue-status` via `pre_gateway_dispatch`; blocked-card PM router; worker crash evidence | `63e44332f5` (kanban self-registering worker) | KEEP | Our `/queue-status` PR #123976 is still open |
| U29 prompt & misc policy (`prompt_guidance`, `redaction`, `redaction_mode`, `patch_diff_artifacts`, `repo_context`, `continuity`, `delivery_directive`) | 7 | Tool guidance lines, redaction modes, patch diff artifacts, worktree janitor | `fb86bc708d` (context redaction of tool args) | KEEP | Compressor-side redaction is not the fork's SessionDB/publish redaction |
| U30 `agent_runtime/docs/` | 5 | Package-local design notes | — | KEEP | Docs |
| U31 CLI door (`hermes_cli/harness.py`, `harness_support`, `harness_parts/_upstream_doors`, `parser/`) | 11 | The plugin's parser door, envelopes, error taxonomy | none | KEEP | No CLI-registration change upstream |
| U32 `harness_parts/persona/` | 21 | Persona chat verbs, turn commit, instance/lifecycle commands | none | KEEP | — |
| U33 `harness_parts/serve/` | 15 | `harness serve` boot, lanes, drain, frames | `gateway/turn_executor.py` (`fb992c84bc`) | KEEP | Upstream's executor serves `GatewayRunner` turn bodies only |
| U34 gateway verbs (`gateway_commands/`, `gateway_identity_commands`) | 8 | Pair/join/peers/devices verbs | none | KEEP | — |
| U35 character sheets (`agent/charsheet/`, `agent/pet/generate/encoding`, `harness_parts/characters/`, `charsheet_payload_contract`) | 37 | Sprite-sheet pipeline and payload contract | `agent/pet/generate/atlas.atlas_to_webp_bytes` (base) | KEEP | The identical helper is a fork move out of an upstream file (footprint row), not new upstream capability |
| U36 `harness_parts/usage/` | 6 | Provider usage detection/lanes | `agent/account_usage.py` (base) | KEEP | Not touched in window |
| U37 remaining harness verbs (agent, board, checkpoint, doctor, flow, init, level, map, office, pets, realm, roots, runtime, skills, workspace…) | 19 | argv handlers for the harness verb families | none | KEEP | — |
| U38 boot seams (`_boot_clock`, `_bytecode_sweep`, `_profile_bootstrap`, `_downstream_cli`, `flag_binding`, `subcommands/postinstall`) | 6 | Pre-argparse profile bootstrap, boot clock, bytecode sweep, postinstall | `hermes_cli/main.py` (base) | KEEP | The seven identical `_profile_bootstrap` helpers are the P1 extraction PR's carry, already on the ledger |
| U39 `hermes_cli/install_method.py` | 1 | Code-scoped `.install_method` stamp for postinstall | `hermes_cli.config.stamp_install_method` + `_install_method_project_root` (at base; a `COMPAT_MANIFEST` restored-def) | SUPERSEDED | Byte-identical to upstream's (AST equal, docstrings included). One caller, `_downstream_cli.py:58`. The fork's `config.py` still carries upstream's copy |
| U40 pip-channel PATH (`path_setup`, `windows_env`) | 2 | Shim `hermes` onto PATH for the pip/Mission Control channel; registry-safe User env writes | `hermes_cli._launchers._register_windows_user_path`, `_merge_user_path`, `_broadcast_environment_change` (at base) | PARTIAL | `windows_env.add_user_path_entry` + `broadcast_environment_change` do what upstream's three privates do: segment-wise case-insensitive dedupe, prepend, preserve `REG_EXPAND_SZ`, `WM_SETTINGCHANGE`. `set_user_env` and the pip shim have no equivalent: `expose_cli` returns `no-store-python` for a non-PM venv |
| U41 `update_history` | 1 | Fork history guard: a failed fast-forward never resets a fork branch | `ff46826872` (detached-HEAD rescue ref), `78ee5e96db` | KEEP | Upstream parks detached commits; the fork refuses to rewrite a diverged fork branch. Our PR #125265 is open |
| U42 runtime health (`venv_integrity`, `runtime_environment`, `gateway_home_receipt`) | 3 | Venv-corruption shapes, typed dependency health, which home a gateway booted under | `1d6e53eb05`, `954d94c3b0`, `878d902147` | KEEP | Relaunch path compare, Smart App Control hint and update-time gateway ownership are different questions |
| U43 auth CLI (`auth_noninteractive`, `provider_browser_login`, `model_picker_policy`) | 3 | Machine-drivable auth verbs, browser sign-in, picker provenance | auth fixes `b085de8e3c`… | KEEP | — |
| U44 `config_read_scope`, `tirith_config` | 2 | Context-local read projection; tirith flag authority | `hermes_cli.config.load_config_readonly` (base) | KEEP | A projection is not a read-only load; no tirith commits upstream (PR #121646 open) |
| U45 `tools/board_tool.py` | 1 | Board cards as chat tools | none | KEEP | — |
| U46 tool schema & manifest (`downstream_schema`, `tool_full_descriptions`, `toolset_manifest.*`, `toolset_scan`) | 5 | Short wire descriptions, full-description mirror, import-free toolset names | `b4410b4bad` (MCP result spill) | KEEP | Unrelated |
| U47 `tools/path_identity.py` | 1 | One authority on path spelling and same-file identity | `agent/runtime_self_protection._normalize_path` (`541e4dc0ba`) | KEEP | Upstream's new module adds a PRIVATE second copy of the `/c/…` and `/mnt/c/…` spelling map for its own floor, so the parallel runs the other way. Worth naming in our PR #125262 |
| U48 `gateway/downstream_extensions.py` | 1 | Fork gateway policy beside upstream dispatch | `10938a7cf9` | KEEP | `run_notifications.py` carry already re-dispositioned when PR #125266 closed |
| U49 `plugins/eternia-harness/` | 5 | The plugin: `register(ctx)`, dashboard routes | — | KEEP | The vehicle itself |
| U50 `mobile_core/` | 45 | Mobile core with vendored upstream shims and freshness gates | vendored sources changed upstream (`c0cb1d7a34` transports) | KEEP | Vendor freshness, not supersession; `test_vendor_fresh.py` owns the drift |
| U51 test runner & env (`run_tests_bundled*`, `_bundle_plugin/`, unattended suite, `check_test_env_drift`, `ensure_fork_dev_deps`, `requirements-fork-dev.txt`, `conftest.py`) | 10 | Bundled pytest runner and fork test-env tooling | none (`scripts/run_tests_parallel.py` untouched) | KEEP | Our runner PR #125263 is open |
| U52 mutation gate (`changed_line_mutation_check`, `mutation_check/`, `unreachable_branch_report`, `tool/test_quality/`) | 9 | Changed-line mutation claims | none | KEEP | — |
| U53 contract dumps & fixtures (`dump_*`, `emit_harness_*`, `generate_agent_runtime_*_fixtures`) | 7 | Launcher-facing contract artifacts | none | KEEP | — |
| U54 boundary instruments (`upstream_footprint`, `upstream_sync_gate`, `god_file_*`, `refactor_*census`, `doc_cite_*`, `core_cache_demote_census`) | 10 | Footprint ratchet, sync gate, census and doc-cite tools | none | KEEP | — |
| U55 one-shot ops (`migrate_codex_scope_ids`, `office_actor_rekey_to_instance`, `backend_postgres_proof`, `install-mission-control-hermes.ps1`, `verify_harness_skill_install`) | 5 | Migrations, proofs, installer, skill-install gate | none | KEEP | — |
| U56 CI & hooks (`.github/workflows/fork-*.yml`, `.githooks/`) | 4 | Fork gates and CI-red notify; post-merge hook | none | KEEP | — |
| U57 repo meta & litter (`CLAUDE.md`, `LICENSE-CONTRIBUTIONS.md`, 9 `contributors/emails`, `.launcher_run.log`, `htasks_open.json`, `qa-artifacts/`, `qa_artifacts/…`, one desktop test) | 19 | Fork docs/licence, contributor mappings, stray artifacts | none (upstream carries none of these paths) | KEEP | Not supersession. `.launcher_run.log`, `htasks_open.json` and `qa_artifacts/stage63_…` read as litter; that belongs to the footprint/litter lane, not here |

## Counts

| verdict | units | files |
|---|---|---|
| SUPERSEDED | 1 (U39) | 1 |
| PARTIAL | 2 (U06, U40) | 4 |
| KEEP | 54 | 755 |
| **total** | **57** | **760** |

In the two-day window upstream shipped no plugin-surface change and only two new modules, so nearly every verdict
is KEEP. Two of the three findings predate the base and came from the AST scan, not the commit log.

## Adoption lanes

1. **U39 — adopt `hermes_cli.config.stamp_install_method` (SUPERSEDED).**
   Goes: `hermes_cli/install_method.py` (`stamp_install_method`, `_install_method_project_root`).
   Replaces: `hermes_cli.config.stamp_install_method` (public; a `COMPAT_MANIFEST` restored-def, so upstream keeps it for callers).
   Call sites: `hermes_cli/_downstream_cli.py:58` (`from hermes_cli.install_method import …` → `from hermes_cli.config import …`).
   Tests: `tests/agent_runtime/test_tombstone_registry.py::test_deleted_test_coverage_follows_defining_module_not_plugin_pointer`
   asserts the opposite liveness and flips with the swap; drop `install_method.py` from `Harness_Brain/00 — Maps/Fork Boundary Map.md`.
   The adoption lane names the postinstall test that covers `_downstream_cli.py:58`, then records its red against the deleted module.
   **REFUTED (lane ADOPT 2026-09-27).** `hermes_cli.config.stamp_install_method` lives inside config.py's `PLUGIN-COMPAT` block (revert-scheduled; upstream deleted the def and has no caller). Repointing `_downstream_cli.py:58` there reds `scripts/check_compat_pointers.py` ("1 site(s)… `from hermes_cli.config import stamp_install_method`"), and the tombstone assertion the sheet would flip already records exactly this: coverage follows the defining module, not the plugin pointer. `install_method.py` is the fork's owner and stays.
2. **U06 — adopt upstream's continuation predicate in `delete_compression_lineage` (PARTIAL).**
   Goes: the Python marker check in `agent_runtime/session_extensions.py::delete_compression_lineage` (the `parent["end_reason"] == "compression"`
   plus the `_branched_from`/`_delegate_from` presence test).
   Replaces: `hermes_state_common._non_continuation_child_sql("c.", "p.id")` (private; reach it through `agent_runtime/_upstream_doors.py`),
   used in a recursive CTE `p.end_reason = 'compression'` + that clause, which is the same edge upstream prune uses (`hermes_state_maintenance._CONTINUATION_EDGE_SQL`).
   Stays: the delete-and-detach body. Upstream has no delete-with-lineage, because `SessionDB.delete_session` orphans compression children.
   Call site: `hermes_cli/harness_parts/persona/chat_delete.py:162-166`.
   Behaviour change to pin red-first: a `_reset_from=<root>` child and a `source='tool'` child of a compression-ended root must SURVIVE
   the delete. On today's code both are deleted as lineage.
3. **U40 — route the Windows User-PATH write through upstream's `_launchers` (PARTIAL).**
   Goes: `hermes_cli/windows_env.py::add_user_path_entry`, `_normalize_segment`, `broadcast_environment_change`.
   Replaces: `hermes_cli._launchers._register_windows_user_path` (which merges through `_merge_user_path` and broadcasts) — private names,
   so bind them through a door (`hermes_cli/harness_parts/_upstream_doors.py` pattern) or, if the owner rules privates out here,
   record the parallel as a ledger row naming the three shadowed symbols.
   Stays: `set_user_env` (User-scope `HERMES_HOME`) and the whole pip-channel shim in `path_setup.py`. Upstream's `expose_cli`
   declines a non-PM venv (`no-store-python`).
   Call site: `hermes_cli/path_setup.py:280-282`. Return contract differs: upstream returns `'present'|'added'` and raises `OSError`,
   while the fork returns `bool` and logs, so the door wraps the call.
