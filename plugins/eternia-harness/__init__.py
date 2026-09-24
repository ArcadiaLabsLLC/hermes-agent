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


def register(ctx) -> None:
    ctx.register_system_prompt_section("eternia-harness.tool-guidance", render_tool_guidance)
    # handler_fn=None: every harness subparser sets its own func= (behind _harness_entry).
    ctx.register_cli_command("harness", help=_HARNESS_HELP, setup_fn=_setup_harness_parser, handler_fn=None)
    ctx.register_cli_command(
        "postinstall", help=_POSTINSTALL_HELP, description=_POSTINSTALL_DESCRIPTION,
        setup_fn=_setup_postinstall_parser, handler_fn=_cmd_postinstall,
    )
