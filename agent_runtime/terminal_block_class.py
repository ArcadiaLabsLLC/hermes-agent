"""A blocked terminal result says which class it is (RT-SAFETY-BLOCK-CLASS-FIELD).

Plan ``docs/agent-runtime-harness/planned/safety-block-recovery-2026-10-25.md`` §2.2-2.3. The
self-repo guard's refusal is an ordinary tool result (``{"exit_code": 1, "error": …, "status":
"blocked"}``); its envelope did not say whether the model can fix it, so neither the model nor the
Launcher could branch on it. The eternia-harness plugin's ``transform_tool_result`` hook adds
``block_class: "fixable" | "final"`` (``tools.self_repo_guard_vars.block_class``) and the
tool-guidance section carries :data:`SAFETY_BLOCK_GUIDANCE`, which tells the model what each class
asks of it. No retry loop in the runtime: the model respells a fixable block once, itself.

RT-FU-A-READ-ONLY-CHECK-IN-A-HELPERS-TERMINAL-WAITS-ON-AN-APPROVAL: an approval nobody answered
is its own class, ``unanswered``. It used to read ``final``, whose guidance ends the turn, and
upstream's timeout text told the agent to "Stop the current workflow", so a dispatched helper
whose one check timed out stopped its whole job. The command still never runs and is never
retried or worked around; only the rest of the job goes on.
"""

from __future__ import annotations

import json
from typing import Any

__layer__ = "policy"
__all__ = ["BLOCK_UNANSWERED", "SAFETY_BLOCK_GUIDANCE", "classify_terminal_block"]

#: The terminal guard status this classifies; every other guard result is left alone.
BLOCKED_STATUS = "blocked"

#: RT-FU-A-READ-ONLY-CHECK-IN-A-HELPERS-TERMINAL-WAITS-ON-AN-APPROVAL: an approval request that
#: timed out unanswered (``tools.approval``'s timeout texts, command and action gates alike).
BLOCK_UNANSWERED = "unanswered"
UNANSWERED_PREFIXES = (
    "BLOCKED: Command timed out without user response.",
    "BLOCKED: Action timed out without user response.",
)
#: Upstream's sentence that ends the whole job, and what an unanswered approval says instead.
STOP_WORKFLOW_SENTENCE = (
    "Stop the current workflow and wait for the user to respond before taking any further "
    "destructive or irreversible action."
)
CARRY_ON_SENTENCE = (
    "Only this step is blocked: carry on with the steps that do not need it, and name this command "
    "in your reply so the user can approve it later."
)

SAFETY_BLOCK_GUIDANCE = (
    "A terminal result with `status: blocked` carries `block_class`: on `fixable`, respell the command "
    "once in this same turn as its error says (spell the directory out, or assign the variable in an "
    "earlier statement); on `unanswered`, nobody answered its approval: that command did not run, do not "
    "retry or reword it or reach its result another way, carry on with the rest of the work and name it "
    "in your reply; on `final`, do not retry or reword it -- say in your reply what was blocked and "
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
    error = payload.get("error")
    if isinstance(error, str) and error.startswith(UNANSWERED_PREFIXES):
        payload["block_class"] = BLOCK_UNANSWERED
        payload["error"] = error.replace(STOP_WORKFLOW_SENTENCE, CARRY_ON_SENTENCE)
        return json.dumps(payload, ensure_ascii=False)
    from tools.self_repo_guard_vars import block_class

    payload["block_class"] = block_class(error)
    return json.dumps(payload, ensure_ascii=False)
