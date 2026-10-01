"""``hermes harness query`` — the CLI door onto the harness query core.

The serve answers when one is live (it alone observes hot/busy/cold); otherwise
this process reads directly. ``--direct`` is what the serve itself runs, and the
operator's way to skip the dial. The reply is the core's small typed answer plus
``answered_by``. Core: :mod:`agent_runtime.harness_query`.
"""

from __future__ import annotations

from agent_runtime.cli_format import emit_json

__layer__ = "lanes"
__all__ = ["_cmd_query"]


def _cmd_query(args) -> int:
    from agent_runtime.harness_query import answer_routed
    from agent_runtime.root_observability import attach_root_observability

    payload = answer_routed(
        args.question,
        instance=getattr(args, "target", None),
        limit=getattr(args, "limit", None),
        direct=bool(getattr(args, "direct", False)),
    )
    # The CLI process's own root resolution, beside the core's ``observer``
    # (which names the process that ANSWERED — the serve, when it did).
    print(emit_json(attach_root_observability(payload)))
    return 0 if payload.get("ok") else 2
