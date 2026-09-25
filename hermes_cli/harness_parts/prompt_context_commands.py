"""``hermes harness prompt-context show``: the prompt context a persona turn would see.

Separate because it is a read of ``agent_runtime.prompt_observability`` with no
verb family of its own.
"""

from __future__ import annotations

from agent_runtime.cli_format import emit_json
from hermes_cli.harness_support import emit_harness_error

__layer__ = "lanes"
__all__ = [
    "_cmd_prompt_context_show",
]


def _cmd_prompt_context_show(args) -> int:
    """S8: show one persisted prompt-observability context by id (frame-evicted
    historical rows stay on disk and are fetched here; C2 retention MOVES older
    rows to the archive dir, which this verb resolves too — archive-never-delete
    means the fetch lane keeps working). Honest miss on absence."""

    from agent_runtime.prompt_observability import load_persisted_context_row

    token = str(getattr(args, "context_id", "") or "").strip()
    if not token:
        return emit_harness_error(ValueError("--context-id is required"), args=args, code="invalid_request")
    data = load_persisted_context_row(token)
    if data is None:
        return emit_harness_error(
            ValueError(f"prompt context '{token}' not found on disk"),
            args=args,
            code="not_found",
        )
    if getattr(args, "json", False):
        print(emit_json(data))
        return 0
    print(f"prompt context {token}: persona={data.get('persona_id')} session={data.get('session_id')}")
    return 0
