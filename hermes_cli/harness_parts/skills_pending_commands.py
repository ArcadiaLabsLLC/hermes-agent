"""``hermes harness skills pending list|approve|reject`` — the argv twin of ``runtime.skills.pending.*``.

Both lanes call :mod:`agent_runtime.review_skill_pending` (RT-REVIEW-STAGED-SKILL-DOOR); a
refusal prints ``{ok: false, reason, detail}`` and exits 1.
"""

from __future__ import annotations

from typing import Any, Callable

from agent_runtime.cli_format import emit_json

__layer__ = "lanes"
__all__ = [
    "_cmd_skills_pending_approve",
    "_cmd_skills_pending_list",
    "_cmd_skills_pending_reject",
]

_REFUSED = 1


def _run_pending_command(args, body: Callable[[], dict[str, Any]], plain: Callable[[dict[str, Any]], None]) -> int:
    from agent_runtime.review_skill_pending import SkillPendingError

    try:
        payload = body()
    except SkillPendingError as exc:
        print(emit_json({"ok": False, "reason": exc.code.value, "detail": exc.detail}))
        return _REFUSED
    if getattr(args, "json", False):
        print(emit_json({"ok": True, **payload}))
    else:
        plain(payload)
    return 0


def _print_listing(payload: dict[str, Any]) -> None:
    if not payload["pending"]:
        print(f"No staged skill writes ({len(payload['profiles_scanned'])} profiles scanned).")
    for row in payload["pending"]:
        print(f"{row['profile']}  {row['id']}  [{row['origin']}]  {row['summary']}")


def _cmd_skills_pending_list(args) -> int:
    from agent_runtime.review_skill_pending import list_staged

    return _run_pending_command(args, lambda: list_staged(profile=getattr(args, "profile", None)), _print_listing)


def _cmd_skills_pending_approve(args) -> int:
    from agent_runtime.review_skill_pending import approve_staged

    return _run_pending_command(args, lambda: approve_staged(profile=args.profile, pending_id=args.id),
                lambda payload: print(f"Applied staged skill write {payload['id']} ({payload['profile']})."))


def _cmd_skills_pending_reject(args) -> int:
    from agent_runtime.review_skill_pending import reject_staged

    return _run_pending_command(args, lambda: reject_staged(profile=args.profile, pending_id=args.id),
                lambda payload: print(f"Rejected staged skill write {payload['id']} ({payload['profile']})."))
