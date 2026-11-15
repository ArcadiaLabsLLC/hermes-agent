"""Lens's own safety-check layer: the smart-approval guardian's one call, owned by the fork.

Owner ruling 2026-11-14: "shouldn't we have our own safety check layer on our owned files". The
upstream guardian (``tools/approval_smart.py::_smart_approve``) judges flagged shell commands with a
shell prompt; Lens needs the SAME guardian with its own prompt (design
``planned/lens-act-and-safe-investigate.md`` §2: "no second classifier"). This module is that call,
here instead of a seam split into the upstream file:

* the same auxiliary task (``approval``), so the same model, provider and timeout
  (``auxiliary.approval.*``; ``call_llm`` resolves the configured timeout when none is passed);
* the same request — temperature 0, 16 tokens out, the guardian's own reasoning setting (read through
  ``agent_runtime._upstream_doors.approval_verdict_reasoning``, never copied);
* the same answer handling — one word, ``APPROVE`` / ``DENY``, anything else, an empty answer or any
  failure is ``escalate``.

Callers (``rules_check``) own the prompts: the trusted system prompt carries the owner's rules, the
untrusted request is fenced in the user prompt.
"""

from __future__ import annotations

import logging
import time

__layer__ = "policy"

logger = logging.getLogger(__name__)

#: The guardian's task in ``auxiliary.*`` config — the shell guardian's own.
GUARDIAN_TASK = "approval"
#: A one-word verdict; the shell guardian's budget.
VERDICT_MAX_TOKENS = 16
_VERDICTS = {"APPROVE": "approve", "DENY": "deny"}


def guardian_verdict(system_prompt: str, user_prompt: str, *, usage: dict | None = None) -> str:
    """'approve', 'deny' or 'escalate' (uncertain, empty or failed). Never raises.

    ``usage`` (when given) receives the call's ``total_tokens`` (None when the provider reports none).
    """

    started = time.monotonic()
    try:
        from agent.auxiliary_client import call_llm

        from agent_runtime._upstream_doors import approval_verdict_reasoning

        response = call_llm(
            task=GUARDIAN_TASK, temperature=0, max_tokens=VERDICT_MAX_TOKENS,
            messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
            reasoning_config=approval_verdict_reasoning(),
        )
        if usage is not None:
            usage["total_tokens"] = getattr(getattr(response, "usage", None), "total_tokens", None)
        answer = (response.choices[0].message.content or "").strip().upper()
    except Exception as error:  # a failed or blocked guardian call is unsure: fail closed
        logger.warning("Lens guardian: call failed after %.1fs (%s: %s), escalating",
                       time.monotonic() - started, type(error).__name__, error)
        return "escalate"
    if not answer:
        logger.warning("Lens guardian: empty answer (finish_reason=%s), escalating",
                       getattr(response.choices[0], "finish_reason", None))
        return "escalate"
    return _VERDICTS.get(answer, "escalate")

