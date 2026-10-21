"""``runtime.course.*`` — agent authoring on a git course, on the method lane (no argv twin).

Each handler reads its params, calls :mod:`agent_runtime.course_authoring` and answers its receipt.
``credential`` (required on every verb) is the backend-minted ``course:<course_public_id>`` clone credential
OBJECT, schema v1, passed inline by the caller exactly as ``runtime.realm.sync.*`` takes one; it is parsed by
``course_authoring.parse_credential``, held for the call only and never echoed.

**Refusals.** ``data.reason`` is a ``course_authoring.CourseRefusal`` value; the JSON-RPC code is
:data:`REASON_CODES`'s. **Tier: ``console``** — every verb reaches a git host under a credential. Course verbs
run off the reader loop and one at a time (:data:`_COURSE_VERB_LOCK`): two verbs never share a clone at once.

Params per verb: :data:`agent_runtime.serve_rpc.twin_params.COURSE_METHOD_PARAMS`.
"""

from __future__ import annotations

import threading
from typing import Any, Callable

from agent_runtime.call_authorization import TIER_CONSOLE
from agent_runtime.course_authoring import CourseRefusal, CourseRefused
from agent_runtime.serve_rpc.protocol import (
    ERR_CONFLICT,
    ERR_HANDLER_FAILED,
    ERR_INVALID_PARAMS,
    ERR_NOT_FOUND,
    RpcContext,
    defer_or_inline,
    err,
    ok,
)
from agent_runtime.serve_rpc.registry import method

__layer__ = "lanes"

__all__ = ["COURSE_METHODS", "REASON_CODES"]

#: ``data.reason`` -> JSON-RPC code; a reason not listed answers ``ERR_HANDLER_FAILED``.
REASON_CODES: dict[CourseRefusal, int] = {
    CourseRefusal.INVALID_REQUEST: ERR_INVALID_PARAMS,
    CourseRefusal.CREDENTIAL_INVALID: ERR_INVALID_PARAMS,
    CourseRefusal.CREDENTIAL_EXPIRED: ERR_CONFLICT,
    CourseRefusal.SUBJECT_MISMATCH: ERR_CONFLICT,
    CourseRefusal.NOT_CHECKED_OUT: ERR_NOT_FOUND,
    CourseRefusal.URL_MISMATCH: ERR_CONFLICT,
    CourseRefusal.BRANCH_DIVERGED: ERR_CONFLICT,
}


def _credential(params: dict):
    from agent_runtime.course_authoring import parse_credential

    if params.get("credential") is None:
        raise CourseRefused(CourseRefusal.INVALID_REQUEST, "credential is required")
    return parse_credential(params["credential"])


def _checkout(p: dict) -> dict:
    """Params: ``credential``."""
    from agent_runtime.course_authoring import checkout

    receipt = checkout(_credential(p))
    return {"course": receipt.course, "outcome": receipt.outcome, "branch": receipt.branch, "head": receipt.head}


#: method name -> verb body. Registered by adding a row; the params each honours are on its body above.
COURSE_METHODS: dict[str, Callable[[dict], dict]] = {
    "runtime.course.checkout": _checkout,
}

_COURSE_VERB_LOCK = threading.Lock()


def _answer(rid: Any, body: Callable[[dict], dict], params: Any) -> dict:
    try:
        with _COURSE_VERB_LOCK:
            return ok(rid, body(params if isinstance(params, dict) else {}))
    except CourseRefused as exc:
        data = {"reason": exc.reason.value, "retryable": exc.reason is CourseRefusal.CREDENTIAL_EXPIRED}
        return err(rid, REASON_CODES.get(exc.reason, ERR_HANDLER_FAILED), str(exc), data)


def _register(name: str, body: Callable[[dict], dict]) -> None:
    @method(name, tier=TIER_CONSOLE)
    def _handler(rid: Any, params: dict, context: RpcContext | None = None) -> dict:
        return defer_or_inline(rid, name, context, lambda: _answer(rid, body, params))

    _handler.__name__ = "_runtime_" + name.removeprefix("runtime.").replace(".", "_")
    _handler.__doc__ = f"``{name}`` — see :mod:`agent_runtime.course_authoring`."


for _name, _body in COURSE_METHODS.items():
    _register(_name, _body)
