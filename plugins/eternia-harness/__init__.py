"""The Eternia Agent Runtime Harness, registered as a Hermes plugin (seam Stages 1-2).

``register(ctx)`` registers the harness CLI, the harness's system-prompt
guidance and its request/session hooks. Every import of the harness is LAZY — inside the setup or render call
— so loading this plugin costs nothing until its own command is being built or
a prompt is being rendered. ``plugin.yaml`` declares both commands under
``cli_commands:`` so the CLI attaches them without running plugin discovery.
"""

from __future__ import annotations


__layer__ = "wiring"

_HARNESS_HELP = "Experimental Agent Runtime Harness"
_POSTINSTALL_HELP = "Bootstrap non-Python deps for pip installs (node, browser, ripgrep, ffmpeg)"
_POSTINSTALL_DESCRIPTION = (
    "One-shot post-install for pip users. Installs system dependencies that "
    "pip cannot provide, then runs setup if needed."
)


def _setup_harness_parser(parser) -> None:
    from agent_runtime.plugin_doors.harness import setup_harness_parser

    setup_harness_parser(parser)


def _setup_postinstall_parser(parser) -> None:
    from agent_runtime.plugin_doors.harness import add_postinstall_arguments

    add_postinstall_arguments(parser)


def _cmd_postinstall(args):
    from agent_runtime.plugin_doors.harness import cmd_postinstall

    return cmd_postinstall(args)


def _work_clause_gate() -> tuple[str, ...]:
    from agent_runtime.plugin_doors.harness import WORK_SUBMIT_TOOLS

    return ("delegate_task", "agent_chat_send", *sorted(WORK_SUBMIT_TOOLS))


# (gate, guidance attribute, read through the plugin's door from ``agent_runtime.prompt_guidance``), in render order. A gate
# is one tool name or a tuple of them; the line renders when EVERY name is present.
_TOOL_GUIDANCE = (
    ("tool_describe", "TOOL_DESCRIBE_GUIDANCE"),
    ("terminal", "SHELL_TOOL_PREFERENCE_GUIDANCE"),
    ("clarify", "CLARIFY_CHOICES_GUIDANCE"),
    ("skill_manage", "SKILL_MANAGE_CONFIRM_GUIDANCE"),
    (("delegate_task", "agent_chat_send"), "DELEGATION_HANDOFF_GUIDANCE"),
    (_work_clause_gate(), "DELEGATION_HANDOFF_WORK_CLAUSE"),
)

# clause attribute -> the line it extends, joined in place of that line's final period.
_JOINED_CLAUSES = {"DELEGATION_HANDOFF_WORK_CLAUSE": "DELEGATION_HANDOFF_GUIDANCE"}


def _gate_open(gate: str | tuple[str, ...], tools: set[str]) -> bool:
    return all(name in tools for name in ((gate,) if isinstance(gate, str) else gate))


def _fixed_guidance_lines(tools: set[str]) -> list[str]:
    from agent_runtime.plugin_doors import harness as prompt_guidance

    lines: dict[str, str] = {}
    for gate, attr in _TOOL_GUIDANCE:
        if not _gate_open(gate, tools):
            continue
        target = _JOINED_CLAUSES.get(attr)
        if target is None:
            lines[attr] = getattr(prompt_guidance, attr)
        elif target in lines:
            lines[target] = lines[target].removesuffix(".") + getattr(prompt_guidance, attr)
    return list(lines.values())


def render_tool_guidance(session_info) -> str:
    """The harness's tool-conditional guidance: one line per tool present in the session.

    ``session_info["tool_names"]`` is the comma-joined sorted tool set core renders
    the prompt with. The fixed lines are the T6b policy moved OFF the brief wire
    descriptions, so they render only in a session that runs that wire — one that
    carries ``tool_describe`` — and then one line per gate whose every tool is present
    (``_gate_open``; the hand-off line needs both hand-off tools). The
    Launcher's app-function ``guidance`` lines render for any session whose list
    holds the tool. Nothing present gets an empty section, which core skips.
    """
    from agent_runtime.plugin_doors.harness import app_function_guidance_lines

    tools = set(str(session_info.get("tool_names") or "").split(","))
    lines = _fixed_guidance_lines(tools) if "tool_describe" in tools else []
    # The host's own WHEN rules (the Launcher's app-function ``guidance``), one
    # line per offered tool present in this session: the rule, the tool brief
    # and any skill then derive from one text the host owns.
    lines.extend(app_function_guidance_lines(tools))
    # RT-SAFETY-BLOCK-CLASS-FIELD: what each block_class asks of the model -- on the T6b wire only,
    # like the fixed lines, so a session without `tool_describe` keeps upstream's exact prompt bytes.
    if "terminal" in tools and "tool_describe" in tools:
        from agent_runtime.plugin_doors.harness import SAFETY_BLOCK_GUIDANCE

        lines.append(SAFETY_BLOCK_GUIDANCE)
    return "\n".join(lines)


def render_windows_tooling(session_info=None) -> str:
    """The Windows-native tooling hint: a session carrying the ``terminal`` tool, on native
    Windows (not WSL) with a local terminal backend — the host whose bash terminal can reach
    ``powershell.exe`` / ``cmd.exe``. The hint is about invoking programs FROM that
    terminal, so a session without it gets an empty section, which core skips."""
    import sys

    if "terminal" not in str((session_info or {}).get("tool_names") or "").split(","):
        return ""
    if sys.platform != "win32":
        return ""
    from hermes_constants import is_wsl
    from agent_runtime.plugin_doors.harness import terminal_env

    if is_wsl() or (terminal_env("TERMINAL_ENV", "local") or "local").strip().lower() != "local":
        return ""
    from agent_runtime.plugin_doors.harness import WINDOWS_NATIVE_TOOLING_HINT

    return WINDOWS_NATIVE_TOOLING_HINT


SKILL_SEARCH_SCHEMA = {
    "name": "skill_search",
    "description": "Search installed skills + the Hermes Skills Hub by query without loading SKILL.md bodies (compact ids/descriptions). Disambiguator: skill_view loads an installed match; `hermes skills install` fetches an external one.",
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search query, e.g. 'flutter qa', 'github review', or 'kubernetes'.",
            },
            "source": {
                "type": "string",
                "enum": [
                    "all",
                    "installed",
                    "official",
                    "hermes-index",
                    "skills-sh",
                    "well-known",
                    "github",
                    "clawhub",
                    "claude-marketplace",
                    "lobehub",
                    "browse-sh",
                ],
                "description": "Optional source filter. Default 'all'. Use 'installed' to avoid remote hub search.",
            },
            "limit": {
                "type": "integer",
                "description": "Maximum results to return; capped at 50.",
            },
            "include_installed": {
                "type": "boolean",
                "description": "When true, include installed local/profile skills before hub results. Default true.",
            },
        },
        "required": ["query"],
    },
}


def _handle_skill_search(args, **kw):
    from agent_runtime.plugin_doors.harness import skill_search

    return skill_search(
        query=args.get("query", ""),
        source=args.get("source", "all"),
        limit=args.get("limit", 10),
        include_installed=args.get("include_installed", True),
        task_id=kw.get("task_id"),
    )


def _check_skill_search() -> bool:
    from agent_runtime.plugin_doors.harness import check_skills_requirements

    return check_skills_requirements()


def brief_tool_descriptions(request=None, **_context):
    """``llm_request`` middleware: the run's blocked tools off the wire, the fork's short tool
    descriptions on it, the fork's execution-guidance Safety sentence in the system text
    (``agent_runtime.prompt_guidance.rewrite_request_safety_sentence``), then the persona
    prompt-cache routing (``agent_runtime.cache_routing.route_persona_cache``).

    The block is the one the run bound for this session (``agent_runtime.tool_blocks``).
    The registry keeps upstream's full text (``tool_describe`` serves it); the briefs swap
    ``description`` by tool name in the final provider kwargs, for the chat, Responses
    and Anthropic payload shapes. Parameters are never touched.
    """
    from agent_runtime.plugin_doors.harness import (
        brief_request_tools, drop_blocked_request_tools, reprune_turn_agent, rewrite_request_safety_sentence,
        route_persona_cache,
    )

    # A registry refresh since the last request may have put blocked names back on the agent.
    reprune_turn_agent(_context.get("session_id"))

    # ONE callback, every rewrite: upstream feeds every llm_request callback the same
    # original request and keeps the LAST result, so two callbacks would drop the first.
    # Block, briefs and the Safety sentence first, so the persona cache key hashes the final wire.
    unblocked = drop_blocked_request_tools(request, session_id=_context.get("session_id"))
    current = unblocked if unblocked is not None else request
    briefed = brief_request_tools(current)
    current = briefed if briefed is not None else current
    safety = rewrite_request_safety_sentence(current)
    current = safety if safety is not None else current
    routed = route_persona_cache(current, **_context)
    current = routed if routed is not None else current
    from agent_runtime.plugin_doors.harness import capture_final_request_tools
    capture_final_request_tools(current)
    steps = (
        ("blocked tools dropped", unblocked), ("tool wire briefs", briefed),
        ("execution-guidance Safety sentence", safety), ("persona cache routing", routed),
    )
    reasons = [reason for reason, done in steps if done is not None]
    if not reasons:
        return None
    return {"request": current, "source": "eternia-harness", "reason": " + ".join(reasons)}


def settle_turn_tools(session_id=None, **_context):
    """``pre_llm_call`` hook: the persona's tool form, settled BEFORE the turn's first request.

    Upstream's between-turns refresh (``agent/turn_context.py::_refresh_mcp_tools_between_turns``)
    re-derives the profile-wide eager list and appends the persona's deferred tools at the tail;
    the ``llm_request`` re-prune runs only after that request was built, so turn 1 shipped the
    deferred tools eager AND the bridge the actor was built with (a prewarm's catalog), while
    turn 2 shipped the bridge the re-prune re-assembled: two prompt-cache keys, turn 2 cold
    (lane h-cache-hit). This hook runs after the refresh and before the request is assembled,
    so every turn's wire is the same re-assembly of the same catalog. The form has one owner
    (``agent_runtime.chat_lane_tool_form.settle_turn_tool_form``): derived once from a
    content-keyed memo, published and pinned only when its bytes moved.
    """
    from agent_runtime.plugin_doors.harness import blocked_tools_for, current_persona_turn_agent, reprune_turn_agent, settle_turn_tool_form

    agent = current_persona_turn_agent()
    if agent is not None:
        settle_turn_tool_form(agent, blocked=blocked_tools_for(session_id or getattr(agent, "session_id", None)))
        from agent_runtime.plugin_doors.harness import arm_review_prompts

        arm_review_prompts(agent)  # the harness review prompts, before any tool call (RT-REVIEW-WRITE-BIAS-UPSTREAM)
    reprune_turn_agent(session_id)


def refuse_blocked_tool(tool_name=None, session_id="", **_context):
    """``pre_tool_call`` hook: refuse a tool the run blocked, ``tool_call``-unwrapped names included."""
    from agent_runtime.plugin_doors.harness import blocked_call_message

    message = blocked_call_message(tool_name, session_id=session_id)
    return None if message is None else {"action": "block", "message": message}


def _generated_tree_write(tool_name, args):
    if tool_name not in ("write_file", "patch"):
        return None
    from agent_runtime.plugin_doors.harness import generated_tree_write_refusal, offered_to_bound_link, terminal_env

    host_paths = terminal_env("TERMINAL_ENV", "local").strip().lower() in ("", "local")
    return generated_tree_write_refusal(tool_name, args, offered=offered_to_bound_link, host_paths=host_paths)


def refuse_tool_call(tool_name=None, args=None, task_id="", session_id="", tool_call_id="", **_context):
    """``pre_tool_call`` hook: a blocked tool, a bundled install's write to the namespace root's or another
    profile's config (``agent_runtime.namespace_config_guard``), a Lens ``act`` turn's mutating call its monitor's rules
    did not allow (``agent_runtime.lens.act``), a background review's write to a SHARED skill
    (staged for the owner, ``agent_runtime.review_skill_gate``), a host write to a generated-document
    path (``agent_runtime.generated_tree_teach``), then a ``flutter build`` that collides with the live
    Launcher (``agent_runtime.flutter_build_guard``); a paused profile's new ``delegate_task`` spawn
    (``agent_runtime.subagents.spawning``) right after the block. One callback for all seven.
    """
    from agent_runtime.plugin_doors.harness import (
        flutter_build_refusal, gate_tool_call, review_shared_skill_write, spawn_pause_refusal,
    )

    blocked = refuse_blocked_tool(tool_name=tool_name, session_id=session_id)
    if blocked is not None:
        return blocked
    from agent_runtime.plugin_doors.harness import namespace_config_write_refusal

    config_write = namespace_config_write_refusal(tool_name, args, task_id)  # bundled installs only
    if config_write is not None:
        return config_write
    paused = spawn_pause_refusal(tool_name, args)  # a paused profile's worker, in the serve's process
    if paused is not None:
        return {"action": "block", "message": paused}
    lens = gate_tool_call(tool_name, args, tool_call_id, task_id)
    if lens is not None:
        return {"action": "block", "message": lens}
    staged = review_shared_skill_write(tool_name, args)
    if staged is not None:
        return staged
    taught = _generated_tree_write(tool_name, args)
    if taught is not None:
        return taught
    message = flutter_build_refusal(tool_name, args, task_id=task_id)
    return None if message is None else {"action": "block", "message": message}


def default_background_notify(tool_name=None, args=None, **_context):
    """``tool_request`` middleware — the plugin's ONE args rewriter, two rewrites in order.

    1. A background ``terminal`` spawn notifies on exit by default. Owner ruling 2026-09-24 —
       completion is decided once, at spawn, through upstream's own ``notify`` parameter; an
       explicit ``notify`` (``false`` included) is left alone.
    2. A persona turn's ``git commit`` gains ``Agent-Instance`` / ``Agent-Turn`` trailers
       (RT-AGENT-COMMIT-ATTRIBUTION, ``agent_runtime.agent_commit_attribution``).

    One callback, because upstream's chain hands every ``tool_request`` middleware the ORIGINAL
    args (``hermes_cli.middleware._apply_request_chain``): a second rewriter would silently
    replace the first one's result.
    """
    from agent_runtime.plugin_doors.harness import attribute_commits, current_persona_turn_agent
    from agent_runtime.plugin_doors.harness import default_background_notify as _default

    reasons = []
    current = args
    notified = _default(tool_name, current)
    if notified is not None:
        current, reasons = notified, ["background notify default"]
    attributed = attribute_commits(tool_name, current, current_persona_turn_agent())
    if attributed is not None:
        current, reasons = attributed, [*reasons, "agent commit trailers"]
    if not reasons:
        return None
    return {"args": current, "source": "eternia-harness", "reason": "; ".join(reasons)}


def time_provider_dispatch(**kwargs):
    """``llm_execution`` middleware: request-assembled mark + provider-dispatch span.

    It runs in the turn's thread, so it also names the bound persona agent for the
    stream observers below, which run on upstream's hook dispatcher thread."""
    from agent_runtime.plugin_doors.harness import remember_stream_agent
    from agent_runtime.plugin_doors.harness import time_provider_dispatch as _time

    remember_stream_agent()
    return _time(**kwargs)


def skill_view_result(**kwargs):
    """``transform_tool_result`` hook: the runtime-compat refusal and the three stamps on ``skill_view``."""
    from agent_runtime.plugin_doors.harness import transform_skill_view_result

    return transform_skill_view_result(**kwargs)


def terminal_block_result(**kwargs):
    """``transform_tool_result`` hook: a blocked terminal result says ``block_class`` (fixable / unanswered / final)."""
    from agent_runtime.plugin_doors.harness import classify_terminal_block

    return classify_terminal_block(**kwargs)


def generated_tree_result(**kwargs):
    """``transform_tool_result`` hook: a host miss on a generated-document path names the
    Launcher's tree verb (``agent_runtime.generated_tree_teach``); teach, never route."""
    from agent_runtime.plugin_doors.harness import generated_tree_read_result, offered_to_bound_link

    return generated_tree_read_result(**kwargs, offered=offered_to_bound_link)


def record_usage_ledger_row(**kwargs):
    """``post_api_request`` hook: one per-call usage row for a bound persona-turn ledger."""
    from agent_runtime.plugin_doors.harness import on_post_api_request

    on_post_api_request(**kwargs)


def record_turn_outcome(**kwargs):
    """``post_tool_call`` hook: a terminal call or file write folds into a bound persona turn's outcome,
    every call's measured ``duration_ms`` into the turn's review timings (``agent_runtime.review_prompts``),
    and a background review's skill write is recorded with its chat and turn (``agent_runtime.review_skill_changes``)."""
    from agent_runtime.plugin_doors.harness import finish_tool_call, fold_review_timing, fold_turn_outcome, record_review_skill_change

    fold_turn_outcome(**kwargs)
    fold_review_timing(**kwargs)
    record_review_skill_change(**kwargs)
    finish_tool_call(kwargs.get("tool_call_id"), kwargs.get("status"))  # a Lens act call's receipt: ran | failed


async def answer_queue_status(**kwargs):
    """``pre_gateway_dispatch`` hook: answer ``/queue-status`` (``/qstatus``), busy path included."""
    from agent_runtime.plugin_doors.harness import answer_queue_status as _answer

    return await _answer(**kwargs)


# Process-env defaults (kanban claim TTL, lazy installs) are NOT written here: plugin code
# writes no process env, because discovery runs at unpredictable points in any process.
# The serve and the conversation-worker composer apply
# ``agent_runtime.process_env_defaults`` instead (v0216 plan §2).


def register(ctx) -> None:
    from agent_runtime.plugin_doors.harness import register_suggestion_task

    register_suggestion_task(ctx)
    from agent_runtime.plugin_doors.harness import register_summary_tasks

    register_summary_tasks(ctx)  # runtime.text.summarize's auxiliary slots (message_digest)
    from agent_runtime.plugin_doors.harness import SharedProviderAccess

    ctx.register_provider_access(SharedProviderAccess())
    from agent_runtime.plugin_doors.harness import run_start_time_setup

    run_start_time_setup()  # the door, the start-time migrations, harness_core, process presence
    ctx.register_system_prompt_section("eternia-harness.tool-guidance", render_tool_guidance)
    ctx.register_system_prompt_section("eternia-harness.windows-tooling", render_windows_tooling)
    ctx.register_middleware("llm_request", brief_tool_descriptions)
    ctx.register_middleware("tool_request", default_background_notify)
    ctx.register_middleware("llm_execution", time_provider_dispatch)
    ctx.register_hook("pre_llm_call", settle_turn_tools)
    ctx.register_hook("pre_tool_call", refuse_tool_call)
    ctx.register_hook("post_api_request", record_usage_ledger_row)
    ctx.register_hook("post_tool_call", record_turn_outcome)
    from agent_runtime.plugin_doors.harness import classify_challenge_refusal

    # A 403 challenge page, typed (transport_mismatch / upstream_blocked) and named by its path.
    ctx.register_hook("transform_api_error_classification", classify_challenge_refusal)
    # The on_stream_* receipt observers register only while a persona turn runs: any
    # registered one makes upstream treat EVERY agent in the process as a stream consumer.
    from agent_runtime.plugin_doors.harness import install_stream_observers

    install_stream_observers(ctx.register_hook)
    ctx.register_hook("transform_tool_result", skill_view_result)
    ctx.register_hook("transform_tool_result", terminal_block_result)
    ctx.register_hook("transform_tool_result", generated_tree_result)
    ctx.register_hook("pre_gateway_dispatch", answer_queue_status)
    # Joins the built-in `skills` toolset by registry membership: a platform bundle reaches it through
    # `skills` (hermes_cli.tools_config._get_platform_tools maps a bundle onto its member toolsets), and
    # stays in the direct tool list through the never-defer set in tools/tool_search_downstream.py.
    ctx.register_tool(
        "skill_search", toolset="skills", schema=SKILL_SEARCH_SCHEMA, handler=_handle_skill_search,
        check_fn=_check_skill_search, emoji="🔎",
    )
    # The serve scheduler's one tool (dispatcher plan §4, B4), in the opt-in `schedule` toolset — never
    # harness_core: a persona schedules only when the operator opted its profile in.
    from agent_runtime.plugin_doors.harness import SCHEDULE_MANAGE_SCHEMA, SCHEDULE_TOOLSET, handle_schedule_manage

    ctx.register_tool("schedule_manage", toolset=SCHEDULE_TOOLSET, schema=SCHEDULE_MANAGE_SCHEMA,
                      handler=handle_schedule_manage, emoji="⏰")
    # A phone ships no upstream file tools (they run on the terminal backend): its agents read, search
    # and edit the phone's project folders through the fork's process-free ones, under upstream's names
    # (Eternia MC-PHONE-FILES-A-PHONE-AGENT-READS-AND-WRITES-ITS-PROJECT-FILES). A desktop registers none.
    from agent_runtime.phone_file_tools import register_phone_file_tools

    register_phone_file_tools(ctx.register_tool)
    # handler_fn=None: every harness subparser sets its own func= (behind _harness_entry).
    ctx.register_cli_command("harness", help=_HARNESS_HELP, setup_fn=_setup_harness_parser, handler_fn=None)
    ctx.register_cli_command(
        "postinstall", help=_POSTINSTALL_HELP, description=_POSTINSTALL_DESCRIPTION,
        setup_fn=_setup_postinstall_parser, handler_fn=_cmd_postinstall,
    )
