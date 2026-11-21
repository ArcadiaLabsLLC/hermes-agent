"""``plugins/eternia-harness``'s door: every runtime name the harness plugin uses (its dashboard has its own,
``harness_dashboard.py``, at the dashboard's lower layer).

LAZY (:func:`agent_runtime.plugin_doors.lazy_door`): the plugin imports from here inside its setup,
render and hook bodies, and a name's module is imported only when that name is read, so loading the
plugin still costs nothing until its own command is built or a hook runs. A name is read at CALL time,
so a test that replaces the runtime function on its own module is what the hook calls. Published in
``hermes_cli/data/plugin_api_fork.json``. The fork-only modules that sit in upstream packages
(``hermes_cli.harness_*``, ``hermes_cli._downstream_cli``, ``hermes_cli.subcommands.postinstall``,
``tools.downstream_schema``) and the upstream names the plugin reads (
``tools.skills_tool.check_skills_requirements``, ``tools.terminal_scope.terminal_env``) are reached here,
in fork core, so no plugin file names them.
"""

from __future__ import annotations

from agent_runtime.plugin_doors import lazy_door

__layer__ = "wiring"

_PROMPT_GUIDANCE = "agent_runtime.prompt_guidance"

#: door name -> ``"<module>"`` (same name there) or ``"<module>:<attr>"``.
DOOR: dict[str, str] = {
    # CLI: the harness verb and postinstall (fork-only modules in upstream packages)
    "setup_harness_parser": "hermes_cli.harness_cli_setup",
    "add_postinstall_arguments": "hermes_cli.subcommands.postinstall",
    "cmd_postinstall": "hermes_cli._downstream_cli",
    "run_start_time_setup": "hermes_cli.harness_parts.start_time_setup",
    # system-prompt sections
    "WORK_SUBMIT_TOOLS": _PROMPT_GUIDANCE,
    "TOOL_DESCRIBE_GUIDANCE": _PROMPT_GUIDANCE,
    "SHELL_TOOL_PREFERENCE_GUIDANCE": _PROMPT_GUIDANCE,
    "CLARIFY_CHOICES_GUIDANCE": _PROMPT_GUIDANCE,
    "SKILL_MANAGE_CONFIRM_GUIDANCE": _PROMPT_GUIDANCE,
    "DELEGATION_HANDOFF_GUIDANCE": _PROMPT_GUIDANCE,
    "DELEGATION_HANDOFF_WORK_CLAUSE": _PROMPT_GUIDANCE,
    "WINDOWS_NATIVE_TOOLING_HINT": _PROMPT_GUIDANCE,
    "rewrite_request_safety_sentence": _PROMPT_GUIDANCE,
    "app_function_guidance_lines": "agent_runtime.launcher_app_functions",
    "offered_to_bound_link": "agent_runtime.launcher_app_functions",
    "SAFETY_BLOCK_GUIDANCE": "agent_runtime.terminal_block_class",
    "classify_terminal_block": "agent_runtime.terminal_block_class",
    "terminal_env": "tools.terminal_scope",
    # tools
    "skill_search": "agent_runtime.skill_search",
    "check_skills_requirements": "tools.skills_tool",
    "SCHEDULE_MANAGE_SCHEMA": "agent_runtime.work_store.schedule_tool",
    "SCHEDULE_TOOLSET": "agent_runtime.work_store.schedule_tool",
    "handle_schedule_manage": "agent_runtime.work_store.schedule_tool",
    # request / turn hooks
    "route_persona_cache": "agent_runtime.cache_routing",
    "drop_blocked_request_tools": "agent_runtime.tool_blocks",
    "reprune_turn_agent": "agent_runtime.tool_blocks",
    "blocked_tools_for": "agent_runtime.tool_blocks",
    "blocked_call_message": "agent_runtime.tool_blocks",
    "brief_request_tools": "tools.downstream_schema",
    "capture_final_request_tools": "agent_runtime.persona_turn_binding",
    "current_persona_turn_agent": "agent_runtime.persona_turn_binding",
    "settle_turn_tool_form": "agent_runtime.chat_lane_tool_form",
    "arm_review_prompts": "agent_runtime.review_prompts",
    "fold_review_timing": "agent_runtime.review_prompts:on_post_tool_call",
    "record_review_skill_change": "agent_runtime.review_skill_changes:on_post_tool_call",
    "fold_turn_outcome": "agent_runtime.turn_outcome:on_post_tool_call",
    "generated_tree_write_refusal": "agent_runtime.generated_tree_teach",
    "generated_tree_read_result": "agent_runtime.generated_tree_teach",
    "flutter_build_refusal": "agent_runtime.flutter_build_guard",
    "gate_tool_call": "agent_runtime.lens.act",
    "finish_tool_call": "agent_runtime.lens.act",
    "review_shared_skill_write": "agent_runtime.review_skill_gate",
    "attribute_commits": "agent_runtime.agent_commit_attribution",
    "default_background_notify": "agent_runtime.background_completion",
    "remember_stream_agent": "agent_runtime.codex_observability",
    "install_stream_observers": "agent_runtime.codex_observability",
    "time_provider_dispatch": "agent_runtime.conversation_observability",
    "transform_skill_view_result": "agent_runtime.skill_view_result",
    "on_post_api_request": "agent_runtime.usage_ledger",
    "answer_queue_status": "agent_runtime.gateway_queue_status",
    "classify_challenge_refusal": "agent_runtime.provider_challenge",
    # registration
    "register_suggestion_task": "agent_runtime.console_suggestions.generation",
    "register_summary_tasks": "agent_runtime.text_summary",
    "SharedProviderAccess": "agent_runtime.provider_access",
}

__all__ = sorted(DOOR)
__getattr__ = lazy_door(__name__, DOOR)
