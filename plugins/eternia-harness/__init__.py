"""The Eternia Agent Runtime Harness, registered as a Hermes plugin (seam Stages 1-2).

``register(ctx)`` registers the harness CLI and the harness's system-prompt
guidance. Every import of the harness is LAZY — inside the setup or render call
— so loading this plugin costs nothing until its own command is being built or
a prompt is being rendered. ``plugin.yaml`` declares both commands under
``cli_commands:`` so the CLI attaches them without running plugin discovery.
"""

from __future__ import annotations

import time

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
    the prompt with. The lines are the T6b policy moved OFF the brief wire
    descriptions, so the section renders only in a session that runs that wire —
    one that carries ``tool_describe`` — and then one line per gating tool present.
    Anything else gets an empty section, which core skips.
    """
    from agent_runtime import prompt_guidance

    tools = set(str(session_info.get("tool_names") or "").split(","))
    if "tool_describe" not in tools:
        return ""
    return "\n".join(getattr(prompt_guidance, attr) for tool, attr in _TOOL_GUIDANCE if tool in tools)


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
    """``llm_request`` middleware: the fork's short tool descriptions on the wire.

    The registry keeps upstream's full text (``tool_describe`` serves it); this swaps
    ``description`` by tool name in the final provider kwargs, for the chat, Responses
    and Anthropic payload shapes. Parameters are never touched.
    """
    from tools.downstream_schema import brief_request_tools

    rewritten = brief_request_tools(request)
    if rewritten is None:
        return None
    return {"request": rewritten, "source": "eternia-harness", "reason": "tool wire briefs"}


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


def record_usage_ledger_row(**kwargs):
    """``post_api_request`` hook: one per-call usage row for a bound persona-turn ledger."""
    from agent_runtime.usage_ledger import on_post_api_request

    on_post_api_request(**kwargs)


def register(ctx) -> None:
    ctx.register_system_prompt_section("eternia-harness.tool-guidance", render_tool_guidance)
    ctx.register_middleware("llm_request", brief_tool_descriptions)
    ctx.register_middleware("tool_request", default_background_notify)
    ctx.register_hook("post_api_request", record_usage_ledger_row)
    # Joins the built-in `skills` toolset by registry membership; the platform bundles
    # still name it in toolsets.py until a register-toolset PR lets a plugin join them.
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
