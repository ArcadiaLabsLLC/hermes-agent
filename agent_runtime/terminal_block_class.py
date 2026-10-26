"""A blocked terminal result says which class it is (RT-SAFETY-BLOCK-CLASS-FIELD).

Plan ``docs/agent-runtime-harness/planned/safety-block-recovery-2026-10-25.md`` §2.2-2.3. The
self-repo guard's refusal is an ordinary tool result (``{"exit_code": 1, "error": …, "status":
"blocked"}``); its envelope did not say whether the model can fix it, so neither the model nor the
Launcher could branch on it. The eternia-harness plugin's ``transform_tool_result`` hook adds
``block_class: "fixable" | "final"`` (``tools.self_repo_guard_vars.block_class``) and the
tool-guidance section carries :data:`SAFETY_BLOCK_GUIDANCE`, which tells the model what each class
asks of it. No retry loop in the runtime: the model respells a fixable block once, itself.
"""

from __future__ import annotations

import json
from typing import Any

__layer__ = "policy"
__all__ = ["SAFETY_BLOCK_GUIDANCE", "classify_terminal_block"]

#: The terminal guard status this classifies; every other guard result is left alone.
BLOCKED_STATUS = "blocked"

SAFETY_BLOCK_GUIDANCE = (
    "A terminal result with `status: blocked` carries `block_class`: on `fixable`, respell the command "
    "once in this same turn as its error says (spell the directory out, or assign the variable in an "
    "earlier statement); on `final`, do not retry or reword it -- say in your reply what was blocked and "
    "why, and offer to continue in a new turn."
)


def classify_terminal_block(tool_name: Any = None, result: Any = None, **_kwargs: Any) -> str | None:
    """``transform_tool_result`` hook: the blocked terminal result with ``block_class`` added, else None."""

    if tool_name != "terminal" or not isinstance(result, str) or BLOCKED_STATUS not in result:
        return None
    try:
        payload = json.loads(result)
    except ValueError:
        return None
    if not isinstance(payload, dict) or payload.get("status") != BLOCKED_STATUS or "block_class" in payload:
        return None
    from tools.self_repo_guard_vars import block_class

    payload["block_class"] = block_class(payload.get("error"))
    return json.dumps(payload, ensure_ascii=False)
