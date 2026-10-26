"""``runtime.skills.pending.list`` / ``.approve`` / ``.reject`` — staged skill writes (RT-REVIEW-STAGED-SKILL-DOOR).

A background review's write to a SHARED skill is staged in the agent profile's
``pending/skills/`` (:mod:`agent_runtime.review_skill_gate`); these three methods are the
owner's door onto every profile's staged writes from Mission Control. The argv twin is
``hermes harness skills pending list|approve|reject``; both call
:mod:`agent_runtime.review_skill_pending`.

=========  =====================================================================
verb       params -> result
=========  =====================================================================
list       {profile?} -> {pending: [{profile, id, summary, origin, action, skill,
           created_at, diff, diff_truncated}], count, profiles_scanned}
approve    {profile, id} -> {profile, id, applied: true, result} (upstream's replay,
           ``apply_skill_pending``; the record is dropped only when it applied)
reject     {profile, id} -> {profile, id, rejected: true}
=========  =====================================================================

Tier ``console`` for all three: a diff carries skill text, and approve writes the shared
skill every agent of the account loads. Every refusal carries ``data.reason`` (a
``SkillPendingRefusal`` value).
"""

from __future__ import annotations

from typing import Any, Callable

from agent_runtime.call_authorization import TIER_CONSOLE
from agent_runtime.serve_rpc.protocol import (
    ERR_HANDLER_FAILED,
    ERR_INVALID_PARAMS,
    ERR_NOT_FOUND,
    RpcContext,
    err,
    ok,
)
from agent_runtime.serve_rpc.registry import method

__layer__ = "lanes"

__all__ = [
    "_runtime_skills_pending_approve",
    "_runtime_skills_pending_list",
    "_runtime_skills_pending_reject",
]


def _pending_call(rid: Any, body: Callable[[], dict]) -> dict:
    from agent_runtime.review_skill_pending import SkillPendingError, SkillPendingRefusal

    try:
        return ok(rid, body())
    except SkillPendingError as exc:
        code = {
            SkillPendingRefusal.NOT_FOUND: ERR_NOT_FOUND,
            SkillPendingRefusal.UNKNOWN_PROFILE: ERR_NOT_FOUND,
            SkillPendingRefusal.INVALID_ID: ERR_INVALID_PARAMS,
        }.get(exc.code, ERR_HANDLER_FAILED)
        return err(rid, code, "The staged skill write was refused.",
                   {"reason": exc.code.value, "detail": exc.detail})


@method("runtime.skills.pending.list", tier=TIER_CONSOLE)
def _runtime_skills_pending_list(rid: Any, params: dict, context: RpcContext | None = None) -> dict:
    from agent_runtime.review_skill_pending import list_staged

    profile = (params or {}).get("profile")
    return _pending_call(rid, lambda: list_staged(profile=str(profile) if profile else None))


@method("runtime.skills.pending.approve", tier=TIER_CONSOLE)
def _runtime_skills_pending_approve(rid: Any, params: dict, context: RpcContext | None = None) -> dict:
    from agent_runtime.review_skill_pending import approve_staged

    params = params or {}
    return _pending_call(rid, lambda: approve_staged(profile=params.get("profile"), pending_id=params.get("id")))


@method("runtime.skills.pending.reject", tier=TIER_CONSOLE)
def _runtime_skills_pending_reject(rid: Any, params: dict, context: RpcContext | None = None) -> dict:
    from agent_runtime.review_skill_pending import reject_staged

    params = params or {}
    return _pending_call(rid, lambda: reject_staged(profile=params.get("profile"), pending_id=params.get("id")))
