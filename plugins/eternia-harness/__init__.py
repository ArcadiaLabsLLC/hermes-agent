"""The Eternia Agent Runtime Harness, registered as a Hermes plugin (seam Stages 1-2).

``register(ctx)`` registers the harness CLI, the harness's system-prompt
guidance and its request/session hooks. Every import of the harness is LAZY — inside the setup or render call
— so loading this plugin costs nothing until its own command is being built or
a prompt is being rendered. ``plugin.yaml`` declares both commands under
``cli_commands:`` so the CLI attaches them without running plugin discovery.
"""

from __future__ import annotations

import logging
import os
import time

__layer__ = "wiring"

_HARNESS_HELP = "Experimental Agent Runtime Harness"
_POSTINSTALL_HELP = "Bootstrap non-Python deps for pip installs (node, browser, ripgrep, ffmpeg)"
_POSTINSTALL_DESCRIPTION = (
    "One-shot post-install for pip users. Installs system dependencies that "
    "pip cannot provide, then runs setup if needed."
)


def _record_harness_parser_ms(started: float) -> None:
    """The fork's boot-clock field (``harness_parser_ms``: harness import + tree build)."""
    try:
        from hermes_cli import _boot_clock
    except ImportError:  # stock upstream has no boot clock
        return
    _boot_clock.record_harness_parser_ms(int(max(0.0, time.monotonic() - started) * 1000))


def _setup_harness_parser(parser) -> None:
    started = time.monotonic()
    try:
        from hermes_cli.harness import build_cli_parser

        build_cli_parser(parser)
    finally:
        _record_harness_parser_ms(started)


def _setup_postinstall_parser(parser) -> None:
    from hermes_cli.subcommands.postinstall import add_postinstall_arguments

    add_postinstall_arguments(parser)


def _cmd_postinstall(args):
    from hermes_cli._downstream_cli import cmd_postinstall

    return cmd_postinstall(args)


# (tool that gates the line, guidance attribute in ``agent_runtime.prompt_guidance``), in render order.
_TOOL_GUIDANCE = (
    ("tool_describe", "TOOL_DESCRIBE_GUIDANCE"),
    ("terminal", "SHELL_TOOL_PREFERENCE_GUIDANCE"),
    ("clarify", "CLARIFY_CHOICES_GUIDANCE"),
    ("browser_navigate", "BROWSER_PRECONDITION_GUIDANCE"),
    ("skill_manage", "SKILL_MANAGE_CONFIRM_GUIDANCE"),
)


def render_tool_guidance(session_info) -> str:
    """The harness's tool-conditional guidance: one line per tool present in the session.

    ``session_info["tool_names"]`` is the comma-joined sorted tool set core renders
    the prompt with. The fixed lines are the T6b policy moved OFF the brief wire
    descriptions, so they render only in a session that runs that wire — one that
    carries ``tool_describe`` — and then one line per gating tool present. The
    Launcher's app-function ``guidance`` lines render for any session whose list
    holds the tool. Nothing present gets an empty section, which core skips.
    """
    from agent_runtime import prompt_guidance
    from agent_runtime.launcher_app_functions import app_function_guidance_lines

    tools = set(str(session_info.get("tool_names") or "").split(","))
    lines = (
        [getattr(prompt_guidance, attr) for tool, attr in _TOOL_GUIDANCE if tool in tools]
        if "tool_describe" in tools
        else []
    )
    # The host's own WHEN rules (the Launcher's app-function ``guidance``), one
    # line per offered tool present in this session: the rule, the tool brief
    # and any skill then derive from one text the host owns.
    lines.extend(app_function_guidance_lines(tools))
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
    from tools.terminal_scope import terminal_env

    if is_wsl() or (terminal_env("TERMINAL_ENV", "local") or "local").strip().lower() != "local":
        return ""
    from agent_runtime.prompt_guidance import WINDOWS_NATIVE_TOOLING_HINT

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
    from agent_runtime.skill_search import skill_search

    return skill_search(
        query=args.get("query", ""),
        source=args.get("source", "all"),
        limit=args.get("limit", 10),
        include_installed=args.get("include_installed", True),
        task_id=kw.get("task_id"),
    )


def _check_skill_search() -> bool:
    from tools.skills_tool import check_skills_requirements

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
    from agent_runtime.cache_routing import route_persona_cache
    from agent_runtime.prompt_guidance import rewrite_request_safety_sentence
    from agent_runtime.tool_blocks import drop_blocked_request_tools, reprune_turn_agent
    from tools.downstream_schema import brief_request_tools

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
    from agent_runtime.persona_turn_binding import capture_final_request_tools
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
    so every turn's wire is the same re-assembly of the same catalog.
    """
    from agent_runtime.tool_blocks import reprune_turn_agent

    reprune_turn_agent(session_id)
    return None


def refuse_blocked_tool(tool_name=None, session_id="", **_context):
    """``pre_tool_call`` hook: refuse a tool the run blocked, ``tool_call``-unwrapped names included."""
    from agent_runtime.tool_blocks import blocked_call_message

    message = blocked_call_message(tool_name, session_id=session_id)
    return None if message is None else {"action": "block", "message": message}


def refuse_tool_call(tool_name=None, args=None, task_id="", session_id="", **_context):
    """``pre_tool_call`` hook: a blocked tool, then a ``flutter build`` that collides with the live Launcher.

    One callback for both refusals (``agent_runtime.flutter_build_guard`` for the second).
    """
    from agent_runtime.flutter_build_guard import flutter_build_refusal

    blocked = refuse_blocked_tool(tool_name=tool_name, session_id=session_id)
    if blocked is not None:
        return blocked
    message = flutter_build_refusal(tool_name, args, task_id=task_id)
    return None if message is None else {"action": "block", "message": message}


def default_background_notify(tool_name=None, args=None, **_context):
    """``tool_request`` middleware: a background ``terminal`` spawn notifies on exit by default.

    Owner ruling 2026-09-24 — completion is decided once, at spawn, through upstream's own
    ``notify`` parameter; an explicit ``notify`` (``false`` included) is left alone.
    """
    from agent_runtime.background_completion import default_background_notify as _default

    rewritten = _default(tool_name, args)
    if rewritten is None:
        return None
    return {"args": rewritten, "source": "eternia-harness", "reason": "background notify default"}


def time_provider_dispatch(**kwargs):
    """``llm_execution`` middleware: request-assembled mark + provider-dispatch span.

    It runs in the turn's thread, so it also names the bound persona agent for the
    stream observers below, which run on upstream's hook dispatcher thread."""
    from agent_runtime.codex_observability import remember_stream_agent
    from agent_runtime.conversation_observability import time_provider_dispatch as _time

    remember_stream_agent()
    return _time(**kwargs)


def skill_view_result(**kwargs):
    """``transform_tool_result`` hook: the runtime-compat refusal and the three stamps on ``skill_view``."""
    from agent_runtime.skill_view_result import transform_skill_view_result

    return transform_skill_view_result(**kwargs)


def record_usage_ledger_row(**kwargs):
    """``post_api_request`` hook: one per-call usage row for a bound persona-turn ledger."""
    from agent_runtime.usage_ledger import on_post_api_request

    on_post_api_request(**kwargs)


async def answer_queue_status(**kwargs):
    """``pre_gateway_dispatch`` hook: answer ``/queue-status`` (``/qstatus``), busy path included."""
    from agent_runtime.gateway_queue_status import answer_queue_status as _answer

    return await _answer(**kwargs)


def route_blocked_kanban_cards(**kwargs):
    """``on_kanban_dispatch_tick`` hook: route the ticking board's new ``blocked`` cards to PM."""
    from hermes_cli.kanban_blocked_pm_tick import on_kanban_dispatch_tick

    on_kanban_dispatch_tick(**kwargs)


def record_kanban_crash_evidence(**kwargs):
    """``on_kanban_worker_exited`` hook: a redacted crash artifact for the reclaimed run."""
    from hermes_cli.kanban_crash_evidence import on_kanban_worker_exited

    on_kanban_worker_exited(**kwargs)


#: The harness's kanban claim lifetime. Long supervisor-style cards can spend more than
#: upstream's 15 minutes inside one external call before they can `kanban_heartbeat`.
KANBAN_CLAIM_TTL_SECONDS = 45 * 60


def default_kanban_claim_ttl() -> None:
    """Upstream reads ``HERMES_KANBAN_CLAIM_TTL_SECONDS`` for every claim AND the heartbeat
    extension; a default here, with the operator's own env as the opt-out."""
    os.environ.setdefault("HERMES_KANBAN_CLAIM_TTL_SECONDS", str(KANBAN_CLAIM_TTL_SECONDS))


def default_no_venv_lazy_installs() -> None:
    """Keep harness processes off upstream's startup venv sync. Upstream's
    ``hermes_cli.venv_sync`` skips its sync-and-relaunch when
    ``HERMES_DISABLE_LAZY_INSTALLS=1``, so a harness process never mutates or restarts the
    running venv on its own. Setting the env yourself (``0``) is the opt-out. (The lazy
    install door this env once shut, ``tools.lazy_deps``, is now a relaunch shim; owner
    2026-09-29: the env stays.)"""
    os.environ.setdefault("HERMES_DISABLE_LAZY_INSTALLS", "1")


def migrate_retired_local_llama_id() -> None:
    """Owner 2026-09-29: the one-shot startup rewrite of ``local-llama-hermes`` -> ``llamacpp``
    across every store and the user's config.yaml, per home (a marker makes it one-shot)."""
    try:
        from agent_runtime.local_llama_adapter.legacy_id_migration import migrate_retired_provider_id_once

        migrate_retired_provider_id_once()
    except Exception:  # a failed migration must not take plugin load down
        logging.getLogger(__name__).warning("local llama retired-id migration failed", exc_info=True)


def register(ctx) -> None:
    from agent_runtime.provider_access import SharedProviderAccess

    ctx.register_provider_access(SharedProviderAccess())
    from hermes_cli.harness_parts.mission_chat_door_binding import bind_mission_chat_door

    bind_mission_chat_door()  # ruling Q10: the runtime's door onto the CLI turn handler
    default_kanban_claim_ttl()
    default_no_venv_lazy_installs()
    migrate_retired_local_llama_id()
    from agent_runtime.harness_toolset import ensure_harness_core

    ensure_harness_core()  # the persona lane's composite, through upstream's create_custom_toolset
    ctx.register_system_prompt_section("eternia-harness.tool-guidance", render_tool_guidance)
    ctx.register_system_prompt_section("eternia-harness.windows-tooling", render_windows_tooling)
    ctx.register_middleware("llm_request", brief_tool_descriptions)
    ctx.register_middleware("tool_request", default_background_notify)
    ctx.register_middleware("llm_execution", time_provider_dispatch)
    ctx.register_hook("pre_llm_call", settle_turn_tools)
    ctx.register_hook("pre_tool_call", refuse_tool_call)
    ctx.register_hook("post_api_request", record_usage_ledger_row)
    # The on_stream_* receipt observers register only while a persona turn runs: any
    # registered one makes upstream treat EVERY agent in the process as a stream consumer.
    from agent_runtime.codex_observability import install_stream_observers

    install_stream_observers(ctx.register_hook)
    ctx.register_hook("transform_tool_result", skill_view_result)
    ctx.register_hook("on_kanban_dispatch_tick", route_blocked_kanban_cards)
    ctx.register_hook("on_kanban_worker_exited", record_kanban_crash_evidence)
    ctx.register_hook("pre_gateway_dispatch", answer_queue_status)
    # Joins the built-in `skills` toolset by registry membership: a platform bundle reaches it through
    # `skills` (hermes_cli.tools_config._get_platform_tools maps a bundle onto its member toolsets), and
    # stays in the direct tool list through the never-defer set in tools/tool_search_downstream.py.
    ctx.register_tool(
        "skill_search", toolset="skills", schema=SKILL_SEARCH_SCHEMA, handler=_handle_skill_search,
        check_fn=_check_skill_search, emoji="🔎",
    )
    # handler_fn=None: every harness subparser sets its own func= (behind _harness_entry).
    ctx.register_cli_command("harness", help=_HARNESS_HELP, setup_fn=_setup_harness_parser, handler_fn=None)
    ctx.register_cli_command(
        "postinstall", help=_POSTINSTALL_HELP, description=_POSTINSTALL_DESCRIPTION,
        setup_fn=_setup_postinstall_parser, handler_fn=_cmd_postinstall,
    )
