"""``mission-chat queue-skill`` / ``runtime.chat.queue_skill`` — load skills on the next turn only.

Every skill is resolved and checked for mission-chat compatibility BEFORE the
queue is touched, so one unloadable skill refuses the whole request and nothing
is half-queued.
"""

from __future__ import annotations

from typing import Any, Iterable

__layer__ = "lanes"
__all__ = ["QUEUE_SKILL_CAPABILITY", "queue_skills_next_turn"]

QUEUE_SKILL_CAPABILITY = "mission.chat.queue_skill_for_next_turn"


def _skill_tokens(skills: Iterable[Any]) -> list[str]:
    from ..persona_assignments import safe_assignment_token

    return list(dict.fromkeys(token for item in skills if (token := safe_assignment_token(item))))


def _rejected_skills(skills: list[str]) -> dict[str, str]:
    from ..skill_resolution import resolve_skill, skill_runtime_compatibility

    resolutions = {skill: resolve_skill(skill) for skill in skills}
    rejected = {skill: result.status for skill, result in resolutions.items() if result.status != "resolved"}
    for skill, result in resolutions.items():
        compatibility = skill_runtime_compatibility(result.candidate, surface="mission_chat", root_node_mode=False)
        if not compatibility["compatible"]:
            rejected[skill] = compatibility["reason"]
    return rejected


def queue_skills_next_turn(
    *, persona_id: Any, session_id: Any, skills: Iterable[Any], persona_instance_id: Any = None
) -> dict:
    """The verb's row. Refusals: ``invalid_request`` (a missing persona,
    session or skill) and ``skills_not_loadable`` (with ``rejected_skills``:
    slug -> the resolver's or the compatibility check's reason)."""
    from ..persona_assignments import safe_assignment_token
    from ..queued_skills import queue_skills_for_next_turn

    persona = safe_assignment_token(persona_id)
    session = safe_assignment_token(session_id)
    # "Flag absent" and "flag given empty" reach the same refusal: at least one
    # skill must survive tokenising, and no store can tell the two apart.
    tokens = _skill_tokens(skills)
    if not persona or not session or not tokens:
        return {"ok": False, "error_kind": "invalid_request",
                "error": "persona, session-id, and at least one skill are required"}
    rejected = _rejected_skills(tokens)
    if rejected:
        return {"ok": False, "error_kind": "skills_not_loadable",
                "error": "one or more skills are not loadable", "rejected_skills": rejected}
    queued = queue_skills_for_next_turn(
        persona_id=persona, session_id=session, persona_instance_id=persona_instance_id, skills=tokens)
    return {
        "ok": True,
        "capability_id": QUEUE_SKILL_CAPABILITY,
        "persona_id": persona,
        "persona_instance_id": safe_assignment_token(persona_instance_id),
        "session_id": session,
        "skills": tokens,
        "queued_skills": queued.get("skills", []),
        "next_expected": "send the next Mission Control chat message; queued skills will be preloaded for that turn only",
    }
