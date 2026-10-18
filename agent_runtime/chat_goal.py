"""The goal door — upstream's ``GoalManager`` on a persona chat root (dispatcher plan §5, stage B3).

``RT-GOAL-ENGINE-DOOR``: one goal vocabulary serves chat and Work. The goal state is upstream's own
(``hermes_cli.goals.GoalManager(session_id)``, persisted in SessionDB ``state_meta``); this module
adds two things the runtime needs and upstream does not hold:

* the five operator verbs ``set | status | pause | resume | clear`` as one table (:data:`OPS`),
  behind ``runtime.chat.goal.<op>`` (``serve_rpc/chat_goal.py``);
* a :class:`GoalBinding` per root — which Work run owns the root's goal, the turn template its
  continuations are forged from, and where its gates run — so the after-turn hook
  (``work_store/persona_turn.py``) can continue or settle the run after a restart.

``arm`` is ``GoalManager.set`` with a ``GoalContract`` drawn from the brief's acceptance, then one
``add_gate`` per test command (owner ruling 2026-10-18: gates from the brief's test commands, on by
default for ``UNTIL_DONE``). Refusals are ``WorkRefused`` with ``invalid_request`` or ``no_goal``.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, field, replace
from enum import StrEnum
from typing import Any

from . import paths
from .serde import write_json_atomic
from .work_store.reasons import Reason, WorkRefused

__layer__ = "stores"
__all__ = [
    "OPS",
    "GoalBinding",
    "GoalOp",
    "arm",
    "bind",
    "binding",
    "bindings",
    "execute",
    "manager",
    "unbind",
    "wire",
]

_CONTRACT_KEYS = ("outcome", "verification", "constraints", "boundaries", "stop_when")
_MAX_GATES = 8


class GoalOp(StrEnum):
    SET = "set"
    STATUS = "status"
    PAUSE = "pause"
    RESUME = "resume"
    CLEAR = "clear"


def manager(session_id: str) -> Any:
    """``GoalManager(session_id)`` — imported on use: the goal engine is upstream's, loaded per call."""

    from hermes_cli.goals import GoalManager

    return GoalManager(session_id)


def _contract(fields: Mapping[str, Any]) -> Any:
    from hermes_cli.goals import GoalContract

    return GoalContract(**{key: " ".join(str(fields.get(key) or "").split()) for key in _CONTRACT_KEYS})


def arm(root_session_id: str, objective: str, *, acceptance: str = "", gates: tuple[str, ...] = (),
        max_turns: int | None = None, goals: Callable[[str], Any] = manager) -> Any:
    """Set the root's goal: the objective, the acceptance as its contract, one gate per test command."""

    goal = goals(root_session_id)
    verification = "; ".join(gates)
    goal.set(objective, max_turns=max_turns,
             contract=_contract({"outcome": acceptance, "verification": verification}))
    _add_gates(goal, gates)
    return goal


def _add_gates(goal: Any, gates: Any) -> None:
    for command in [str(c) for c in gates if str(c).strip()][:_MAX_GATES]:
        goal.add_gate(command)


def wire(session_id: str, goal: Any) -> dict[str, Any]:
    """The goal's state as the reply's ``goal`` block; ``status: none`` when the root holds none."""

    state = goal.state
    bound = binding(session_id)
    if state is None:
        return {"session_id": session_id, "status": "none", "run": bound.request_id if bound else None}
    return {
        "session_id": session_id, "status": state.status, "goal": state.goal, "turns_used": state.turns_used,
        "max_turns": state.max_turns, "paused_reason": state.paused_reason, "last_verdict": state.last_verdict,
        "last_reason": state.last_reason, "contract": state.contract.to_dict(),
        "gates": [{"command": g.command, "last_exit_code": g.last_exit_code, "attempts": g.attempts}
                  for g in state.gates],
        "status_line": goal.status_line(), "run": bound.request_id if bound else None,
    }


# ── the operator verbs, one table ─────────────────────────────────────────


def _session(params: Mapping[str, Any]) -> str:
    session = str(params.get("session_id") or "").strip()
    if not session:
        raise WorkRefused(Reason.INVALID, "session_id is required")
    return session


def _require(goal: Any) -> Any:
    if not goal.has_goal():
        raise WorkRefused(Reason.NO_GOAL, goal.session_id)
    return goal


def _set(goal: Any, params: Mapping[str, Any]) -> None:
    text = str(params.get("goal") or "").strip()
    gates = params.get("gates") or []
    max_turns = params.get("max_turns")
    if not text or not isinstance(gates, list) or not all(isinstance(g, str) for g in gates) or (
            max_turns is not None and (not isinstance(max_turns, int) or max_turns < 1)):
        raise WorkRefused(Reason.INVALID, "goal text, gates as strings, max_turns >= 1")
    contract = params.get("contract") if isinstance(params.get("contract"), Mapping) else {}
    goal.set(text, max_turns=max_turns, contract=_contract(contract))
    _add_gates(goal, gates)


OPS: dict[GoalOp, Callable[[Any, Mapping[str, Any]], Any]] = {
    GoalOp.SET: _set,
    GoalOp.STATUS: lambda goal, _params: None,
    GoalOp.PAUSE: lambda goal, params: _require(goal).pause(str(params.get("reason") or "operator-paused")),
    GoalOp.RESUME: lambda goal, _params: _require(goal).resume(),
    GoalOp.CLEAR: lambda goal, _params: _require(goal).clear(),
}


def execute(op: str, params: Mapping[str, Any], *, goals: Callable[[str], Any] = manager) -> dict[str, Any]:
    """Run one goal verb on ``params["session_id"]``; the goal's state after it."""

    try:
        verb = GoalOp(op)
    except ValueError as exc:
        raise WorkRefused(Reason.INVALID, f"unknown goal verb {op!r}") from exc
    session = _session(params)
    goal = goals(session)
    OPS[verb](goal, params)
    return {"goal": wire(session, goals(session))}


# ── which Work run owns a root's goal ─────────────────────────────────────


@dataclass(frozen=True)
class GoalBinding:
    root_session_id: str
    request_id: str
    rows: tuple[tuple[str, str, str], ...]
    #: The persisted args of the run's first queued send; a continuation is these with a new message.
    turn_args: Mapping[str, Any] = field(default_factory=dict)
    #: The client message id of the run's latest queued send (its first, then each continuation's).
    cmid: str = ""
    turns: int = 0
    cwd: str | None = None
    #: An operator send was waiting when a turn ended; the next settle on the root continues.
    held: bool = False
    #: ``stop`` reached a running turn; its settle ends the run ``STOPPED``.
    stopping: bool = False

    def advanced(self, **changes: Any) -> GoalBinding:
        return replace(self, **changes)


def bind(record: GoalBinding) -> GoalBinding:
    write_json_atomic(paths.chat_goal_binding_path(record.root_session_id),
                      {**asdict(record), "rows": [list(r) for r in record.rows], "turn_args": dict(record.turn_args)})
    return record


def _read_binding(path: Any) -> GoalBinding | None:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return GoalBinding(**{**raw, "rows": tuple(tuple(map(str, r)) for r in raw.get("rows") or [])})
    except (OSError, ValueError, TypeError):
        return None


def binding(root_session_id: str) -> GoalBinding | None:
    return _read_binding(paths.chat_goal_binding_path(root_session_id))


def bindings() -> list[GoalBinding]:
    """Every root a Work run's goal is bound to (an unreadable record is skipped, as :func:`binding` does)."""

    directory = paths.chat_goal_bindings_dir()
    found = (_read_binding(path) for path in sorted(directory.glob("*.json"))) if directory.is_dir() else ()
    return [bound for bound in found if bound is not None]


def unbind(root_session_id: str) -> None:
    paths.chat_goal_binding_path(root_session_id).unlink(missing_ok=True)
