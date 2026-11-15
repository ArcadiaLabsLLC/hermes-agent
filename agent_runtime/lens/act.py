"""Lens ACT: an ``act`` turn's mutating tool calls, each judged by the monitor's rules (design
``planned/lens-act-and-safe-investigate.md`` §4, row ``RT-LENS-ACT-LEVEL``).

``act`` is investigate's next step: the door (``trigger.LensForge._forge``) forges the same turn, holds
its chat at ``bounded`` instead of ``read_only``, and ARMS an :class:`ActTurn` for the turn's client
message id (:func:`armed_act_turn`). The eternia-harness ``pre_tool_call`` hook hands every call to
:func:`gate_tool_call`; read-only calls pass untouched (the token budget bounds them). A MUTATING call —
the names ``read_only`` blocks (``tool_permissions.extra_blocked_tools_for_permission_mode``, the one
definition) — is decided in this order:

1. the Episode carries untrusted free text, or the turn already made any read outside
   :data:`TYPED_ONLY_READS` -> **proposal** (W9: such an Episode never acts alone, whatever the rules say);
2. the tool is not on the monitor's ``automation.actions`` list -> **proposal**;
3. the call cannot be undone (only checkpointed file writes can, :data:`UNDOABLE_TOOLS`) -> **proposal**;
4. the rules check (``rules_check.check_action``, Lens's guardian): ``approve`` -> the call runs;
   ``deny`` -> refused, the model reads that this monitor's rules refused it; ``escalate`` or a failed
   check -> **proposal**.

An owner-approved proposal's follow-up turn (``trigger.LensForge._follow_up``, row
``RT-LENS-PROPOSAL-APPROVE-DENY``) arms its ``ActTurn`` with ``preadmitted = (tool, arguments digest)``:
that one call runs before step 1 (``decided_by: owner``, ``why: owner_approved``), ONCE; any other call
of the follow-up is judged as above.

A proposal is refused in the turn too — the model reads that it went to the owner, and carries on
without it. Every decision is an action receipt (``store_actions.py``); an allowed call's receipt moves
from ``running`` to ``ran`` / ``failed`` on its ``post_tool_call`` (:func:`finish_tool_call`). The
check's tokens are charged to the turn's armed token budget.

Unarmed processes pay one dict test per tool call. Nothing here raises into the turn: a gate that
fails refuses the call as a proposal it could not record (fail closed).
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Callable

from .rules_check import DECIDED_BY_RULES, RulesVerdict, check_action
from .store import LensStore, to_ms
from .store_actions import ActionResult, arguments_digest, finish_action, record_action

__layer__ = "lanes"

logger = logging.getLogger(__name__)

#: File writes the turn's checkpoints can restore (``operator_undo.py``): the only calls that can be undone.
UNDOABLE_TOOLS = frozenset({"apply_patch", "edit_file", "file.edit", "file.write", "patch", "write_file"})
#: The only non-mutating calls that bring no outside text into the turn: Lens's own typed reads, the tool
#: catalog bridge and a question to the owner. ANY other read (a web or browser read, an MCP read,
#: ``read_file``, ``skill_view`` ...) may carry an instruction, so after it nothing acts alone (W9,
#: RT-LENS-ACT-TAINT-ONLY-WEB-AND-BROWSER: a prefix list missed every read it did not name).
TYPED_ONLY_READS = frozenset({"clarify", "lens_read", "tool_call", "tool_describe", "tool_search"})
DECIDED_BY_OWNER = "owner"

WHY_UNTRUSTED_TEXT = "untrusted_text"
WHY_NOT_LISTED = "not_listed"
WHY_CANNOT_BE_UNDONE = "cannot_be_undone"
WHY_RULES_UNSURE = "rules_unsure"
WHY_RULES_DENIED = "rules_denied"
#: The one call an owner-approved proposal pre-admits in its follow-up turn (RT-LENS-PROPOSAL-APPROVE-DENY).
WHY_OWNER_APPROVED = "owner_approved"

REFUSED_TEXT = ("Refused by this monitor's rules: '{tool}' did not run. Carry on without it; do not retry it "
                "in another form.")
PROPOSED_TEXT = ("Sent to the owner as a proposal ({why}): '{tool}' did not run. The owner approves or denies it "
                 "in Eternia. Carry on without it and say in your report what you proposed and why.")


@dataclass
class ActTurn:
    """One armed ``act`` turn: what its mutating calls are judged against."""

    episode_id: str
    monitor_id: str
    turn_id: str
    actions: frozenset[str]
    guidance: str
    episode: dict[str, Any]
    free_text: bool = False
    budget: Any = None
    store_factory: Callable[[], LensStore] = LensStore
    clock: Callable[[], datetime] = field(default=lambda: datetime.now(UTC))
    check: Callable[..., Any] = check_action
    tainted: bool = False
    #: ``(tool, arguments_digest)`` of the owner-approved call: admitted ONCE, then gone (one-shot).
    preadmitted: tuple[str, str] | None = None
    _running: dict[str, str] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def decide(self, tool: str, arguments: Any, tool_call_id: str | None) -> str | None:
        """None: the call runs. Else the message the model reads instead of a result."""

        undoable = tool in UNDOABLE_TOOLS
        if self.preadmitted is not None and self.preadmitted == (tool, arguments_digest(arguments)):
            self.preadmitted = None  # one-shot: the same call again is judged like any other
            self._allow(tool, arguments, None, DECIDED_BY_OWNER, WHY_OWNER_APPROVED, undoable, tool_call_id)
            return None
        why = (WHY_UNTRUSTED_TEXT if self.free_text or self.tainted
               else WHY_NOT_LISTED if tool not in self.actions
               else WHY_CANNOT_BE_UNDONE if not undoable else None)
        verdict = None
        if why is None:
            checked = self.check(guidance=self.guidance, monitor_name=self.monitor_id, tool=tool,
                                 arguments=arguments, undoable=undoable, episode=self.episode)
            verdict = checked.verdict.value
            if self.budget is not None:
                self.budget.charge(checked.tokens or 0)  # the check counts against the Episode (design §2)
            if checked.verdict is RulesVerdict.APPROVE:
                self._allow(tool, arguments, verdict, DECIDED_BY_RULES, None, undoable, tool_call_id)
                return None
            if checked.verdict is RulesVerdict.DENY:
                self._record(tool, arguments, verdict, DECIDED_BY_RULES, ActionResult.REFUSED, WHY_RULES_DENIED,
                             undoable, tool_call_id)
                return REFUSED_TEXT.format(tool=tool)
            why = WHY_RULES_UNSURE
        self._record(tool, arguments, verdict, DECIDED_BY_OWNER, ActionResult.PROPOSED, why, undoable, tool_call_id)
        return PROPOSED_TEXT.format(tool=tool, why=why.replace("_", " "))

    def _allow(self, tool: str, arguments: Any, verdict: str | None, decided_by: str, why: str | None,
               undoable: bool, tool_call_id: str | None) -> None:
        row = self._record(tool, arguments, verdict, decided_by, ActionResult.RUNNING, why, undoable, tool_call_id)
        if tool_call_id:
            with self._lock:
                self._running[tool_call_id] = row["action_id"]

    def finish(self, tool_call_id: str, ok: bool) -> None:
        with self._lock:
            action_id = self._running.pop(tool_call_id, None)
        if action_id is not None:
            finish_action(self.store_factory(), action_id, result=ActionResult.RAN if ok else ActionResult.FAILED,
                          finished_ms=to_ms(self.clock()))

    def _record(self, tool: str, arguments: Any, verdict: str | None, decided_by: str, result: str,
                why: str | None, undoable: bool, tool_call_id: str | None) -> dict[str, Any]:
        return record_action(self.store_factory(), episode_id=self.episode_id, monitor_id=self.monitor_id,
                             turn_id=self.turn_id, tool=tool, arguments=arguments, verdict=verdict,
                             decided_by=decided_by, result=result, why=why, undoable=undoable,
                             created_ms=to_ms(self.clock()), tool_call_id=tool_call_id)


_ARMED: dict[str, ActTurn] = {}
_ARMED_LOCK = threading.Lock()


@contextmanager
def armed_act_turn(turn: ActTurn) -> Iterator[ActTurn]:
    """Bind ``turn`` to its client message id (``turn.turn_id``) for the ``with`` block."""

    with _ARMED_LOCK:
        _ARMED[turn.turn_id] = turn
    try:
        yield turn
    finally:
        with _ARMED_LOCK:
            if _ARMED.get(turn.turn_id) is turn:
                del _ARMED[turn.turn_id]


def _current() -> ActTurn | None:
    from ..persona_turn_binding import current_persona_turn_agent

    agent = current_persona_turn_agent()
    key = str(getattr(agent, "_persona_chat_client_message_id", None) or "")
    with _ARMED_LOCK:
        return _ARMED.get(key) if key else None


def _mutating() -> frozenset[str]:
    from ..permission_modes import PERMISSION_MODE_READ_ONLY
    from ..tool_permissions import extra_blocked_tools_for_permission_mode

    return frozenset(extra_blocked_tools_for_permission_mode(PERMISSION_MODE_READ_ONLY))


def gate_tool_call(tool_name: Any = None, args: Any = None, tool_call_id: Any = None) -> str | None:
    """The ``pre_tool_call`` gate: None lets the call run; a string is the refusal the model reads."""

    if not _ARMED:
        return None
    turn = None
    try:
        turn = _current()
        if turn is None:
            return None
        name = str(tool_name or "")
        if name not in _mutating():
            if name not in TYPED_ONLY_READS:
                turn.tainted = True  # outside text may now be in the turn
            return None
        return turn.decide(name, args if isinstance(args, dict) else {}, str(tool_call_id or "") or None)
    except Exception:
        logger.warning("lens act gate failed", exc_info=True)
        return None if turn is None else PROPOSED_TEXT.format(tool=tool_name, why="the check failed")


def finish_tool_call(tool_call_id: Any = None, status: Any = None) -> None:
    """The ``post_tool_call`` tap: an allowed call's receipt reads ``ran`` or ``failed``."""

    if not _ARMED or not tool_call_id:
        return
    try:
        turn = _current()
        if turn is not None:
            turn.finish(str(tool_call_id), status == "ok")
    except Exception:
        logger.debug("lens act finish failed", exc_info=True)
