"""A stand-in for the mission-chat door, for the native dispatch lane's tests.

A dispatched turn runs natively (``tools/agent_chat_dispatch/native.py``): the supervisor runs
``agent_runtime.mission_chat_door.run_mission_chat_turn`` on a thread of the serve. :class:`StubTurn`
is bound as the door's handler (:func:`bind_stub_turn`): it records the arguments it was called with,
hands a payload to ``args.payload_sink`` as the real handler does, and, when ``block`` is set, registers
in ``live_turns`` under the request id (the key ``native.interrupt_dispatch_turn`` falls back to) and
waits there until its agent is interrupted — or ``release`` is set — so a test can drive Stop and the
budget through the real interrupt seam.
"""

from __future__ import annotations

import threading
from types import SimpleNamespace
from typing import Any

from agent_runtime import live_turns, mission_chat_door
from agent_runtime.serde import safe_assignment_token

STOPPED_PAYLOAD = {"ok": True, "stopped": True, "execution_state": "stopped", "reply": "", "session_id": "s-dev"}


class StubTurn:
    def __init__(
        self,
        payload: dict[str, Any] | None = None,
        *,
        exit_code: int = 0,
        block: bool = False,
        ignore_interrupt: bool = False,
        raises: BaseException | None = None,
        payload_on_release: dict[str, Any] | None = None,
        register_after: float = 0.0,
    ) -> None:
        self.payload = payload
        self.exit_code = exit_code
        self.block = block
        self.ignore_interrupt = ignore_interrupt
        self.raises = raises
        self.payload_on_release = payload_on_release
        #: Seconds the turn takes before it registers in ``live_turns`` (a Stop sent sooner finds nothing).
        self.register_after = register_after
        self.calls: list[Any] = []
        self.observed: list[dict[str, Any]] = []
        self.started = threading.Event()
        self.release = threading.Event()
        self.interrupted = threading.Event()
        self.finished = threading.Event()

    def _interrupt(self) -> None:
        self.interrupted.set()
        if not self.ignore_interrupt:
            self.release.set()

    def __call__(self, args: Any) -> int:
        self.calls.append(args)
        from agent_runtime.profile_home import get_hermes_head_home
        from hermes_constants import get_hermes_home

        self.observed.append({"home": str(get_hermes_home()), "head": str(get_hermes_head_home()),
                              "thread": threading.current_thread().name})
        try:
            if self.raises is not None:
                raise self.raises
            if self.block:
                if self.register_after:
                    import time

                    time.sleep(self.register_after)
                key = safe_assignment_token(str(args.client_message_id or ""))
                agent = SimpleNamespace(interrupt=self._interrupt)
                with live_turns.live_turn(turn_id=key, session_id="s-dev", persona_instance_id="personainst_dev",
                                          agent=agent):
                    self.started.set()
                    self.release.wait(30)
                payload = STOPPED_PAYLOAD if self.interrupted.is_set() and not self.ignore_interrupt else (
                    self.payload_on_release if self.payload_on_release is not None else self.payload)
            else:
                self.started.set()
                payload = self.payload
            if payload is not None:
                args.payload_sink(dict(payload))
            return self.exit_code
        finally:
            self.finished.set()


def bind_stub_turn(monkeypatch, stub: StubTurn) -> StubTurn:
    """Bind ``stub`` as the door's turn handler for one test."""

    monkeypatch.setattr(mission_chat_door, "_turn", stub)
    return stub
