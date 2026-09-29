# The argv census — hermes half (2026-09-29, lane h10b-refac)

Plan: `downstream-god-file-refactor.md` §4.2. Dead-code queue row "The argv census". This is the HERMES half only: every handler the `harness` argv tree can reach, the method twin that carries the same verb (if any), and its callers inside this repository. Whether the launcher still LOWERS a verb to argv is read in `EterniaLauncher`; that half is the launcher queue's row. No handler is deleted on this note alone.

How it was taken (a runtime read, not a source walk): `hermes_cli.harness_parts.parser.build_parser` was built into a fresh `argparse` root and every sub-parser walked for its `func` default — 156 handlers over 157 argv paths (`gateway` has one alias). Method twins: the §4.4 table's seven hand-matched rows, plus a name match of the argv words against `agent_runtime.serve_rpc.registry._METHODS` (118 methods) — the name match is a lead, not a proof. Callers: `git grep -nw <handler>` minus the defining module, the parser package and `tests/`, keeping only lines that import, call or attribute-access the name, and dropping files that define their own same-named function (`_cmd_status` in `agent/lsp/cli.py`, `_cmd_init` in `hermes_cli/kanban.py`, … are collisions, not callers). "Tests" counts test FILES naming the handler.

Summary: 18 handlers have a method twin; 11 have a production caller outside the parser; 35 are named by no test file. Every handler without a twin is carried only by argv, so it can be deleted only if BOTH no launcher lowering AND no operator/script use remains — the second is a product ruling, not a grep.

| argv (`harness …`) | handler | method twin | production callers outside the parser | test files |
|---|---|---|---|---|
| `` | `parser.harness_command` | — | — | 5 |
| `agent create` | `persona.lifecycle_commands._cmd_agent_create` | `runtime.agent.create` | — | 2 |
| `agent list` | `agent_commands._cmd_agent_list` | — | — | 2 |
| `agent retire` | `persona.lifecycle_commands._cmd_agent_retire` | `runtime.agent.retire` | — | 0 |
| `agent set-profile` | `agent_commands._cmd_agent_set_profile` | — | — | 1 |
| `board card add` | `board._cmd_board_card_add` | — | — | 1 |
| `board card archive` | `board._cmd_board_card_archive` | — | — | 1 |
| `board card edit` | `board._cmd_board_card_edit` | — | — | 1 |
| `board card move` | `board._cmd_board_card_move` | — | — | 1 |
| `board card restore` | `board._cmd_board_card_restore` | — | — | 1 |
| `board create` | `board._cmd_board_create` | — | — | 1 |
| `board list` | `board._cmd_board_list` | — | — | 1 |
| `board resolve-conflict` | `board._cmd_board_resolve_conflict` | — | — | 1 |
| `board show` | `board._cmd_board_show` | — | — | 1 |
| `board update` | `board._cmd_board_update` | — | — | 1 |
| `characters add-state` | `characters.commands._cmd_characters_add_state` | — | — | 0 |
| `characters approve-direction` | `characters.steps._cmd_characters_approve_direction` | — | — | 0 |
| `characters auto` | `characters.auto._cmd_characters_auto` | — | — | 0 |
| `characters backfill-home` | `characters.commands._cmd_characters_backfill_home` | — | — | 0 |
| `characters base` | `characters.commands._cmd_characters_base` | — | — | 0 |
| `characters compose` | `characters.steps._cmd_characters_compose` | — | — | 0 |
| `characters list` | `characters.commands._cmd_characters_list` | — | `hermes_cli/charsheet_payload_contract.py` | 1 |
| `characters migrate-home` | `characters.commands._cmd_characters_migrate_home` | — | — | 0 |
| `characters payload-contract` | `characters.commands._cmd_characters_payload_contract` | — | — | 1 |
| `characters reopen` | `characters.commands._cmd_characters_reopen` | — | — | 0 |
| `characters reroll-direction` | `characters.steps._cmd_characters_reroll_direction` | — | — | 0 |
| `characters reroll-row` | `characters.steps._cmd_characters_reroll_row` | — | — | 0 |
| `characters rows` | `characters.steps._cmd_characters_rows` | — | — | 0 |
| `characters sprite` | `characters.commands._cmd_characters_sprite` | — | `hermes_cli/charsheet_payload_contract.py` | 0 |
| `characters start` | `characters.commands._cmd_characters_start` | — | — | 0 |
| `characters status` | `characters.commands._cmd_characters_status` | — | `hermes_cli/charsheet_payload_contract.py` | 0 |
| `characters thumb` | `characters.commands._cmd_characters_thumb` | — | `hermes_cli/charsheet_payload_contract.py` | 0 |
| `characters turnaround` | `characters.steps._cmd_characters_turnaround` | — | — | 0 |
| `checkpoint classes` | `checkpoint_commands._cmd_checkpoint_classes` | — | — | 1 |
| `checkpoint fetch` | `checkpoint_commands._cmd_checkpoint_fetch` | — | — | 1 |
| `config show` | `runtime_commands._cmd_config` | — | — | 1 |
| `contracts dump` | `runtime_commands._cmd_contracts_dump` | — | — | 1 |
| `doctor` | `doctor_commands._cmd_doctor` | — | — | 1 |
| `execution-identity` | `parser.execution_identity.print_execution_identity` | — | — | 1 |
| `flow list` | `flow_commands._cmd_flow_list` | — | — | 1 |
| `flow set` | `flow_commands._cmd_flow_set` | — | — | 1 |
| `flow show` | `flow_commands._cmd_flow_show` | — | — | 1 |
| `gateway devices list` | `gateway_commands.devices.cmd_gateway_devices_list` | — | — | 1 |
| `gateway devices revoke` | `gateway_commands.devices.cmd_gateway_devices_revoke` | — | — | 0 |
| `gateway id` | `gateway_identity_commands._cmd_gateway_id` | — | — | 0 |
| `gateway introduce` | `gateway_commands.introduce.cmd_gateway_introduce` | — | — | 0 |
| `gateway pair` | `gateway_commands.devices.cmd_gateway_pair` | — | — | 0 |
| `gateway peers join` | `gateway_commands.join.cmd_gateway_peers_join` | — | `hermes_cli/harness_parts/gateway_commands/__init__.py` | 1 |
| `gateway peers list` | `gateway_commands.peers.cmd_gateway_peers_list` | `runtime.gateway.peers.list` | — | 1 |
| `gateway peers pair` | `gateway_commands.introduce.cmd_gateway_peers_pair` | — | — | 1 |
| `gateway peers revoke` | `gateway_commands.peers.cmd_gateway_peers_revoke` | — | — | 0 |
| `gateway rename` | `gateway_identity_commands._cmd_gateway_rename` | — | — | 0 |
| `health` | `runtime_commands._cmd_health` | — | — | 1 |
| `init` | `init_commands._cmd_init` | — | — | 1 |
| `install-harness-skills` | `init_commands._cmd_install_harness_skills` | — | — | 2 |
| `level clear` | `level._cmd_level_clear` | `runtime.level.clear` | — | 0 |
| `level set` | `level._cmd_level_set` | `runtime.level.set` | — | 0 |
| `level show` | `level._cmd_level_show` | — | — | 0 |
| `map clear` | `map._cmd_map_clear` | `runtime.map.clear` | — | 0 |
| `map list` | `map._cmd_map_list` | `runtime.map.list` | — | 0 |
| `map set` | `map._cmd_map_set` | `runtime.map.set` | — | 0 |
| `map show` | `map._cmd_map_show` | — | — | 0 |
| `migrate` | `runtime_commands._cmd_migrate` | — | — | 2 |
| `mission-chat clarify-tickets` | `persona.chat_tickets_commands._cmd_mission_chat_clarify_tickets` | — | — | 2 |
| `mission-chat dispatch redeliver` | `persona.chat_tickets_commands._cmd_mission_chat_dispatch_redeliver` | — | — | 1 |
| `mission-chat message` | `persona.chat_turn_message._cmd_mission_chat_message` | `runtime.chat.message` | `agent_runtime/chat_turn.py`, `agent_runtime/chat_turn_presence.py`, `agent_runtime/mission_chat_door.py`, `agent_runtime/mission_chat_outcome.py`, `agent_runtime/prompt_observability/mission_chat.py`, `hermes_cli/harness_parts/mission_chat_door_binding.py` | 31 |
| `mission-chat queue-skill` | `persona.chat_coordinator._cmd_mission_chat_queue_skill` | — | — | 2 |
| `mission-chat steer` | `persona.chat_coordinator._cmd_mission_chat_steer` | `runtime.chat.steer` | — | 1 |
| `mission-chat turn-resolve` | `persona.chat_tickets_commands._cmd_mission_chat_turn_resolve` | — | — | 2 |
| `observe` | `runtime_commands._cmd_observe` | — | — | 3 |
| `office actor-remove` | `office._cmd_office_actor_remove` | `runtime.office.remove` | — | 2 |
| `office actor-restore` | `office._cmd_office_actor_restore` | — | — | 1 |
| `office actor-upsert` | `office._cmd_office_actor_upsert` | `runtime.office.upsert` | — | 2 |
| `office archive-surface` | `office._cmd_office_archive_surface` | — | — | 0 |
| `office resolve-conflict` | `office._cmd_office_resolve_conflict` | `runtime.office.resolve_conflict` | — | 1 |
| `office set-folders` | `office._cmd_office_set_folders` | `runtime.office.surface.update` | — | 1 |
| `office show` | `office._cmd_office_show` | — | — | 1 |
| `persona assignments` | `persona.inspect_commands._cmd_persona_assignments` | — | — | 1 |
| `persona chat delete` | `persona.chat_delete._cmd_persona_chat_delete` | — | — | 5 |
| `persona chat history` | `runtime_commands._cmd_persona_chat_history` | — | — | 2 |
| `persona instance archive` | `persona.instance_commands._cmd_persona_instance_archive` | — | — | 0 |
| `persona instance close` | `persona.instance_commands._cmd_persona_instance_close` | — | — | 2 |
| `persona instance create` | `persona.lifecycle_commands._cmd_persona_instance_create` | — | — | 3 |
| `persona instance open-chat` | `persona.chat_open._cmd_persona_instance_open_chat` | `runtime.persona.instance.open_chat` | `agent_runtime/mission_chat_door.py`, `hermes_cli/harness_parts/mission_chat_door_binding.py` | 6 |
| `persona instance repair-steering` | `persona.instance_commands._cmd_persona_instance_repair_steering` | — | — | 2 |
| `persona instance delete` | `persona.instance_commands._cmd_persona_instance_retire` | — | — | 3 |
| `persona instance return-summary` | `persona.instance_commands._cmd_persona_instance_return_summary` | — | — | 4 |
| `persona instance set-model` | `persona.model_and_skills_commands._cmd_persona_instance_set_model` | — | — | 2 |
| `persona instance steer` | `persona.instance_commands._cmd_persona_instance_steer` | — | — | 3 |
| `persona instance update-profile` | `persona.instance_commands._cmd_persona_instance_update_profile` | — | — | 2 |
| `persona list` | `persona.inspect_commands._cmd_persona_list` | — | — | 3 |
| `persona migrate-assignment-task-ids` | `persona.inspect_commands._cmd_persona_assignment_task_id_migration` | — | — | 1 |
| `persona permission set` | `persona.inspect_commands._cmd_persona_permission_set` | — | — | 1 |
| `persona set-model` | `persona.model_and_skills_commands._cmd_persona_set_model` | — | — | 2 |
| `persona set-skills` | `persona.model_and_skills_commands._cmd_persona_set_skills` | — | — | 0 |
| `persona show` | `persona.inspect_commands._cmd_persona_show` | — | — | 1 |
| `persona tool-diff` | `persona.inspect_commands._cmd_persona_tool_diff` | — | — | 2 |
| `persona-instance chat-bindings` | `runtime_commands._cmd_persona_instance_chat_bindings` | — | — | 1 |
| `persona-instance detail` | `persona.inspect_commands._cmd_persona_instance_detail` | — | — | 1 |
| `persona-instance reconcile` | `runtime_commands._cmd_persona_instance_reconcile` | — | — | 2 |
| `pets gallery` | `pets_commands._cmd_pets_gallery` | — | — | 1 |
| `pets install` | `pets_commands._cmd_pets_install` | — | — | 1 |
| `pets sprite` | `pets_commands._cmd_pets_sprite` | — | — | 1 |
| `pets thumb` | `pets_commands._cmd_pets_thumb` | — | — | 1 |
| `prompt-context show` | `prompt_context_commands._cmd_prompt_context_show` | — | — | 1 |
| `providers` | `provider_visibility._cmd_providers` | — | — | 1 |
| `realm adopt` | `realm_commands._cmd_realm_adopt` | — | — | 1 |
| `realm agents set` | `realm_commands._cmd_realm_agents_set` | — | — | 1 |
| `realm agents show` | `realm_commands._cmd_realm_agents_show` | — | — | 1 |
| `realm bind-server` | `realm_commands._cmd_realm_bind_server` | — | — | 1 |
| `realm create` | `realm_commands._cmd_realm_create` | — | — | 1 |
| `realm default-scope` | `realm_commands._cmd_realm_default_scope` | — | — | 1 |
| `realm list` | `realm_commands._cmd_realm_list` | — | — | 1 |
| `realm show` | `realm_commands._cmd_realm_show` | — | — | 1 |
| `realm skills set` | `realm_commands._cmd_realm_skills_set` | — | — | 1 |
| `realm skills show` | `realm_commands._cmd_realm_skills_show` | — | — | 1 |
| `realm sync held` | `realm_commands._cmd_realm_sync_held` | — | — | 1 |
| `realm sync history` | `realm_commands._cmd_realm_sync_history` | — | — | 0 |
| `realm sync publish` | `realm_commands._cmd_realm_sync_publish` | — | — | 1 |
| `realm sync pull` | `realm_commands._cmd_realm_sync_pull` | — | — | 1 |
| `realm sync resolve` | `realm_commands._cmd_realm_sync_resolve` | — | — | 1 |
| `realm sync revert` | `realm_commands._cmd_realm_sync_revert` | — | — | 0 |
| `realm sync status` | `realm_commands._cmd_realm_sync_status` | — | — | 2 |
| `realm use` | `realm_commands._cmd_realm_use` | `runtime.realm.use` | — | 2 |
| `roots list` | `roots_commands._cmd_roots_list` | — | — | 1 |
| `roots migrate` | `roots_commands._cmd_roots_migrate` | — | — | 1 |
| `roots set` | `roots_commands._cmd_roots_set` | — | — | 1 |
| `roots unset` | `roots_commands._cmd_roots_unset` | — | — | 1 |
| `serve` | `parser.machine._cmd_serve` | — | `hermes_cli/harness_parts/serve/__init__.py` | 10 |
| `serve connect` | `parser.machine._cmd_serve_connect` | — | `hermes_cli/harness_parts/serve/__init__.py` | 1 |
| `skills catalog` | `skills_commands._cmd_skills_catalog` | — | — | 1 |
| `skills delete` | `skills_promotion_commands._cmd_skills_delete` | — | — | 1 |
| `skills inbox` | `skills_commands._cmd_skills_inbox` | — | — | 2 |
| `skills inventory` | `skills_commands._cmd_skills_inventory` | — | — | 1 |
| `skills link-external` | `skills_commands._cmd_skills_link_external` | — | — | 1 |
| `skills promote` | `skills_promotion_commands._cmd_skills_promote` | — | — | 1 |
| `skills publishable` | `skills_commands._cmd_skills_publishable` | — | — | 1 |
| `skills restore` | `skills_promotion_commands._cmd_skills_restore` | — | — | 1 |
| `snapshot` | `runtime_commands._cmd_snapshot` | — | `agent_runtime/core_cache/read.py` | 1 |
| `status` | `runtime_commands._cmd_status` | — | — | 9 |
| `stream` | `runtime_commands._cmd_stream` | — | — | 4 |
| `usage` | `usage.commands._cmd_usage` | — | `hermes_cli/harness_parts/usage/__init__.py` | 3 |
| `verify` | `runtime_commands._cmd_verify` | — | — | 1 |
| `work cancel` | `runtime_commands._cmd_work_cancel` | — | — | 1 |
| `work list` | `runtime_commands._cmd_work_list` | — | — | 1 |
| `work peek` | `runtime_commands._cmd_work_peek` | — | — | 1 |
| `workspace add-agent` | `workspace_commands._cmd_workspace_add_agent` | — | — | 1 |
| `workspace archive` | `workspace_commands._cmd_workspace_archive` | — | — | 1 |
| `workspace create` | `workspace_commands._cmd_workspace_create` | `runtime.workspace.create` | — | 1 |
| `workspace delete` | `workspace_commands._cmd_workspace_delete` | — | — | 1 |
| `workspace list` | `workspace_commands._cmd_workspace_list` | — | — | 1 |
| `workspace remove-agent` | `workspace_commands._cmd_workspace_remove_agent` | — | — | 1 |
| `workspace rename` | `workspace_commands._cmd_workspace_rename` | — | — | 1 |
| `workspace show` | `workspace_commands._cmd_workspace_show` | — | — | 1 |
| `workspace use` | `workspace_commands._cmd_workspace_use` | `runtime.workspace.use` | — | 3 |
| `worktree reap` | `runtime_commands._cmd_worktree_reap` | — | — | 1 |
