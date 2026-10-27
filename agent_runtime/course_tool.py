"""``course_checkout`` / ``course_commit`` / ``course_pull_request`` — a persona authors a git course.

Plan ``docs/agent-runtime-harness/planned/course-turn-credential-2026-10-25.md`` §2.4 (row
``RT-COURSE-PERSONA-TOOLS``). Each tool calls the shipped :mod:`agent_runtime.course_authoring` verb with the
CURRENT turn's ``course_credential`` — the one the Launcher brokered on ``mission.chat.message``, held by
:mod:`agent_runtime.turn_secrets` for the turn's duration and never in argv. With no credential the tool
refuses :data:`REASON_CREDENTIAL_MISSING`; the credential is never echoed, and its ``git_authorization``
never reaches an answer (the verbs' receipts carry none).

The tools live in the ``course`` toolset, a member of the ``harness_core`` composite
(``agent_runtime.harness_toolset``): every persona sees them, and only a turn started from the course editor
can use them. The persona is read from the turn binding (``live_turns``), never from the tool call: the
branch is ``agent/<persona_id>/<branch>`` and the commit is authored by that persona.
"""

from __future__ import annotations

import json
from typing import Any, Callable

from .course_authoring import VERB_LOCK, CourseRefusal, CourseRefused

__layer__ = "lanes"
__all__ = [
    "COURSE_CHECKOUT_SCHEMA",
    "COURSE_COMMIT_SCHEMA",
    "COURSE_PULL_REQUEST_SCHEMA",
    "COURSE_TOOLSET",
    "REASON_CREDENTIAL_MISSING",
    "REASON_PERSONA_UNKNOWN",
    "handle_course_checkout",
    "handle_course_commit",
    "handle_course_pull_request",
]

COURSE_TOOLSET = "course"
#: The ``turn_secrets`` name the method lane holds the parsed credential under (``chat_turn``).
CREDENTIAL_SECRET = "course_credential"
REASON_CREDENTIAL_MISSING = "course_credential_missing"
#: A call outside a persona's live turn: no persona to author the branch.
REASON_PERSONA_UNKNOWN = "course_persona_unknown"
_MISSING_DETAIL = "this turn carries no course credential; ask the operator to start the turn from the course editor"

_COURSE_ID = {"type": "string", "description": "The course's public id (the course editor names it)."}
_BRANCH = {"type": "string", "description": "The branch slug; the branch is agent/<your persona id>/<slug>."}

COURSE_CHECKOUT_SCHEMA: dict[str, Any] = {
    "name": "course_checkout",
    "description": (
        "Clone or fetch an Eternia course's git repository at its default branch. Works only in a turn the "
        "operator started from the course editor (it carries the course's credential)."
    ),
    "parameters": {"type": "object", "properties": {"course_public_id": _COURSE_ID},
                   "required": ["course_public_id"]},
}

COURSE_COMMIT_SCHEMA: dict[str, Any] = {
    "name": "course_commit",
    "description": (
        "Write files into a checked-out course on your authoring branch, commit them as you, and push the "
        "branch (never forced). `files` maps a repo-relative path to its full new text; `deletes` lists paths "
        "to remove. Check the course out first."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "course_public_id": _COURSE_ID,
            "branch": _BRANCH,
            "message": {"type": "string", "description": "The commit message."},
            "files": {"type": "object", "additionalProperties": {"type": "string"},
                      "description": "{repo-relative path: full text}."},
            "deletes": {"type": "array", "items": {"type": "string"}, "description": "Repo-relative paths."},
        },
        "required": ["course_public_id", "branch", "message"],
    },
}

COURSE_PULL_REQUEST_SCHEMA: dict[str, Any] = {
    "name": "course_pull_request",
    "description": (
        "Open (or answer the already-open) pull request for your pushed authoring branch against the course's "
        "default branch."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "course_public_id": _COURSE_ID,
            "branch": _BRANCH,
            "title": {"type": "string"},
            "body": {"type": "string"},
        },
        "required": ["course_public_id", "branch", "title"],
    },
}


class _ToolRefused(Exception):
    def __init__(self, reason: str, detail: str) -> None:
        super().__init__(detail)
        self.reason, self.detail = reason, detail


def _turn_credential(course_public_id: Any) -> Any:
    """The current turn's course credential, admitted for exactly ``course_public_id``."""

    from . import turn_secrets
    from .course_authoring import admit

    credential = turn_secrets.get(CREDENTIAL_SECRET)
    if credential is None:
        raise _ToolRefused(REASON_CREDENTIAL_MISSING, _MISSING_DETAIL)
    course = admit(credential)
    if str(course_public_id or "").strip() != course:
        raise CourseRefused(CourseRefusal.SUBJECT_MISMATCH, "this turn's credential is for another course")
    return credential


def _calling_persona() -> tuple[str, str | None]:
    """``(persona_id, display_name)`` of the persona whose live turn is calling, read from the turn binding."""

    from .live_turns import persona_instance_of
    from .persona_assignments import PersonaInstanceStore
    from .persona_turn_binding import current_persona_turn_agent

    agent = current_persona_turn_agent()
    instance_id = persona_instance_of(agent) if agent is not None else None
    if instance_id:
        try:
            instance = PersonaInstanceStore().get(instance_id)
        except Exception:  # an unreadable instance is "no persona", refused below
            instance = None
        persona_id = str(getattr(instance, "persona_id", "") or "")
        if persona_id:
            return persona_id, getattr(instance, "display_name", None)
    raise _ToolRefused(REASON_PERSONA_UNKNOWN, "course authoring runs only inside a persona's turn")


def _answer(body: Callable[[], dict[str, Any]]) -> str:
    try:
        with VERB_LOCK:
            return json.dumps(body(), sort_keys=True)
    except _ToolRefused as exc:
        return json.dumps({"error": exc.reason, "detail": exc.detail})
    except CourseRefused as exc:
        return json.dumps({"error": exc.reason.value, "detail": str(exc)})


def _checkout(args: dict[str, Any]) -> dict[str, Any]:
    from .course_authoring import checkout

    receipt = checkout(_turn_credential(args.get("course_public_id")))
    return {"course": receipt.course, "outcome": receipt.outcome, "branch": receipt.branch, "head": receipt.head}


def _commit(args: dict[str, Any]) -> dict[str, Any]:
    from .course_authoring import commit

    files, deletes = args.get("files") or {}, args.get("deletes") or []
    if not isinstance(files, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in files.items()):
        raise CourseRefused(CourseRefusal.INVALID_REQUEST, "files must be an object of path -> text")
    if not isinstance(deletes, list) or not all(isinstance(item, str) for item in deletes):
        raise CourseRefused(CourseRefusal.INVALID_REQUEST, "deletes must be a list of paths")
    credential = _turn_credential(args.get("course_public_id"))
    persona_id, persona_name = _calling_persona()
    receipt = commit(credential, persona_id=persona_id, persona_name=persona_name,
                     branch=str(args.get("branch") or ""), message=str(args.get("message") or ""),
                     files=files, deletes=deletes)
    return {"course": receipt.course, "branch": receipt.branch, "sha": receipt.sha, "files": list(receipt.files)}


def _pull_request(args: dict[str, Any]) -> dict[str, Any]:
    from .course_authoring import pull_request

    credential = _turn_credential(args.get("course_public_id"))
    persona_id, _name = _calling_persona()
    receipt = pull_request(credential, persona_id=persona_id, branch=str(args.get("branch") or ""),
                           title=str(args.get("title") or ""), body=str(args.get("body") or ""))
    return {"course": receipt.course, "branch": receipt.branch, "number": receipt.number,
            "html_url": receipt.html_url, "existing": receipt.existing}


def handle_course_checkout(args: dict[str, Any], **kwargs: Any) -> str:
    return _answer(lambda: _checkout(args or {}))


def handle_course_commit(args: dict[str, Any], **kwargs: Any) -> str:
    return _answer(lambda: _commit(args or {}))


def handle_course_pull_request(args: dict[str, Any], **kwargs: Any) -> str:
    return _answer(lambda: _pull_request(args or {}))
