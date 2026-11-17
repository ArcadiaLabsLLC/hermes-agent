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
3. the call cannot be undone (only a file write whose before image Lens took, :data:`UNDOABLE_TOOLS` and
   ``undo.capture``) -> **proposal**;
4. the rules check (``rules_check.check_action``, Lens's guardian): ``approve`` -> the call runs;
   ``deny`` -> refused, the model reads that this monitor's rules refused it; ``escalate`` or a failed
   check -> **proposal**.

An owner-approved proposal's follow-up turn (``trigger.LensForge._follow_up``, row
``RT-LENS-PROPOSAL-APPROVE-DENY``) arms its ``ActTurn`` with ``preadmitted = (tool, arguments digest)``:
that one call runs before step 1 (``decided_by: owner``, ``why: owner_approved``), ONCE; any other call
of the follow-up is judged as above.

The monitor's OWN text is not outside text (row ``RT-LENS-ACT-CANNOT-OVERWRITE-AN-UNREAD-FILE``): a
:data:`OWN_TEXT_READS` read of a file whose last Lens write was this monitor's ``ran`` write, and that still
hashes to the digest that write's receipt kept when it finished (``store_actions.own_text_digest``), does
not taint — so the monitor can read its own notes file (which upstream's write guard demands before an
overwrite) and edit it. The file is hashed again when the read finishes; a change in between taints. Any
other read taints, that same file after anyone else edited it included.

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

from ..tool_permissions import FILE_WRITE_TOOLS
from .rules_check import DECIDED_BY_RULES, RulesVerdict, check_action
from .store import LensStore, to_ms
from .store_actions import (ActionResult, arguments_digest, finish_action, own_text_digest, record_action,
                            set_after_digest)

__layer__ = "lanes"

logger = logging.getLogger(__name__)

#: File writes Lens can undo from the before image it takes (``undo.py``): the only calls that can be undone.
UNDOABLE_TOOLS = FILE_WRITE_TOOLS
#: The only non-mutating calls that bring no outside text into the turn: Lens's own typed reads, the tool
#: catalog bridge and a question to the owner. ANY other read (a web or browser read, an MCP read,
#: ``read_file``, ``skill_view`` ...) may carry an instruction, so after it nothing acts alone (W9,
#: RT-LENS-ACT-TAINT-ONLY-WEB-AND-BROWSER: a prefix list missed every read it did not name).
TYPED_ONLY_READS = frozenset({"clarify", "lens_read", "tool_call", "tool_describe", "tool_search"})
#: Reads that bring no outside text when the file is still the monitor's own last write (see the module doc).
OWN_TEXT_READS = frozenset({"read_file"})
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
    #: tool_call_id -> (action_id, the written host path or None)
    _running: dict[str, tuple[str, str | None]] = field(default_factory=dict)
    #: tool_call_id -> (host path, digest) of an own-text read, hashed again when it finishes
    _own_reads: dict[str, tuple[str, str]] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def decide(self, tool: str, arguments: Any, tool_call_id: str | None, task_id: str | None = None) -> str | None:
        """None: the call runs. Else the message the model reads instead of a result."""

        from .undo import capture

        # Undoable only when Lens holds the file's before image (``undo.py``): taken now, before the call.
        image = capture(arguments, task_id) if tool in UNDOABLE_TOOLS else None
        undoable = image is not None
        if self.preadmitted is not None and self.preadmitted == (tool, arguments_digest(arguments)):
            self.preadmitted = None  # one-shot: the same call again is judged like any other
            self._allow(tool, arguments, None, DECIDED_BY_OWNER, WHY_OWNER_APPROVED, image, tool_call_id)
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
                self._allow(tool, arguments, verdict, DECIDED_BY_RULES, None, image, tool_call_id)
                return None
            if checked.verdict is RulesVerdict.DENY:
                self._record(tool, arguments, verdict, DECIDED_BY_RULES, ActionResult.REFUSED, WHY_RULES_DENIED,
                             undoable, tool_call_id)
                return REFUSED_TEXT.format(tool=tool)
            why = WHY_RULES_UNSURE
        self._record(tool, arguments, verdict, DECIDED_BY_OWNER, ActionResult.PROPOSED, why, undoable, tool_call_id)
        return PROPOSED_TEXT.format(tool=tool, why=why.replace("_", " "))

    def _allow(self, tool: str, arguments: Any, verdict: str | None, decided_by: str, why: str | None,
               image: Any, tool_call_id: str | None) -> None:
        from .undo import keep_image

        row = self._record(tool, arguments, verdict, decided_by, ActionResult.RUNNING, why, image is not None,
                           tool_call_id, undo_handle=None if image is None else image.handle())
        if image is not None:
            keep_image(self.store_factory(), row["action_id"], image)
        if tool_call_id:
            with self._lock:
                self._running[tool_call_id] = (row["action_id"], None if image is None else image.path)

    def read(self, tool: str, arguments: Any, tool_call_id: str | None, task_id: str | None) -> None:
        """A non-mutating call outside :data:`TYPED_ONLY_READS`: taints the turn unless it reads this
        monitor's own, unchanged text (the module doc)."""

        if tool not in OWN_TEXT_READS or not tool_call_id or not self._own_text(arguments, tool_call_id, task_id):
            self.tainted = True  # outside text may now be in the turn

    def _own_text(self, arguments: Any, tool_call_id: str, task_id: str | None) -> bool:
        from pathlib import Path

        from .undo import file_digest, host_path

        try:
            path = host_path(arguments, task_id)
            if path is None:
                return False
            kept = own_text_digest(self.store_factory(), monitor_id=self.monitor_id, path=str(path))
            if kept is None or file_digest(Path(path)) != kept:
                return False
        except Exception:  # a read we cannot place is outside text
            logger.debug("lens act: own-text test failed", exc_info=True)
            return False
        with self._lock:
            self._own_reads[tool_call_id] = (str(path), kept)
        return True

    def finish(self, tool_call_id: str, ok: bool) -> None:
        from pathlib import Path

        from .undo import file_digest

        with self._lock:
            running = self._running.pop(tool_call_id, None)
            own_read = self._own_reads.pop(tool_call_id, None)
        if own_read is not None and file_digest(Path(own_read[0])) != own_read[1]:
            self.tainted = True  # the file changed while it was read: what the turn saw may not be ours
        if running is None:
            return
        action_id, path = running
        store = self.store_factory()
        finish_action(store, action_id, result=ActionResult.RAN if ok else ActionResult.FAILED,
                      finished_ms=to_ms(self.clock()))
        digest = file_digest(Path(path)) if ok and path else None
        if digest is not None:
            set_after_digest(store, action_id, digest)

    def _record(self, tool: str, arguments: Any, verdict: str | None, decided_by: str, result: str,
                why: str | None, undoable: bool, tool_call_id: str | None,
                undo_handle: dict[str, Any] | None = None) -> dict[str, Any]:
        return record_action(self.store_factory(), episode_id=self.episode_id, monitor_id=self.monitor_id,
                             turn_id=self.turn_id, tool=tool, arguments=arguments, verdict=verdict,
                             decided_by=decided_by, result=result, why=why, undoable=undoable,
                             created_ms=to_ms(self.clock()), tool_call_id=tool_call_id, undo_handle=undo_handle)


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


def gate_tool_call(tool_name: Any = None, args: Any = None, tool_call_id: Any = None,
                   task_id: Any = None) -> str | None:
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
                turn.read(name, args, str(tool_call_id or "") or None, str(task_id or "") or None)
            return None
        return turn.decide(name, args if isinstance(args, dict) else {}, str(tool_call_id or "") or None,
                           str(task_id or "") or None)
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
