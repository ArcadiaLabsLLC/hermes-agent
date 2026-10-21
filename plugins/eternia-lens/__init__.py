"""Eternia Lens, registered as a Hermes plugin (plan ``eternia-lens-in-hermes.md``).

The plugin is the packaging switch: a bundle ships Lens by listing this directory.
Lens's method lane (``runtime.lens.*``) registers through the fork-owned
``agent_runtime/serve_rpc/lens.py`` seam, and its poller runs under ``harness
serve`` (stage L1). On a session it registers the PULL DOOR (plan
``p10-agent-2026-10-19.md`` §5.5): the persona tools, in the opt-in ``lens``
toolset — a persona reaches them only when its profile declares ``lens``.
"""

from __future__ import annotations

__layer__ = "wiring"


def register(ctx) -> None:
    """The pull-door tools, in the opt-in ``lens`` toolset (never ``harness_core``)."""

    from agent_runtime.lens.tool import (
        LENS_PROPOSE_SCHEMA, LENS_READ_SCHEMA, LENS_TOOLSET, handle_lens_propose, handle_lens_read,
    )

    ctx.register_tool("lens_read", toolset=LENS_TOOLSET, schema=LENS_READ_SCHEMA, handler=handle_lens_read)
    ctx.register_tool("lens_propose", toolset=LENS_TOOLSET, schema=LENS_PROPOSE_SCHEMA, handler=handle_lens_propose)
