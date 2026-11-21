"""An agent room's app-function request rides the Eternia connection that admitted its message.

Real path: ``DiscussionService.command`` admits the send under ``requesting_launcher`` (as
``discussions/rpc.py`` does for the connection the call came in on) → ``room_commands`` activates
that binding when the queued message's turn comes → ``discussions/native.py`` runs the member's
turn inside ``discussions/app_functions.py::discussion_launcher`` → the registered app-function
tool → ``LauncherLink.request`` → ``launcher_client_requests``. Only the model turn is injected.

Security pin (RT-FU-AN-AGENT-ROOMS-LAUNCHER-REQUESTS-HAVE-NO-TEST, review w1118a.79): the request
must go back on the admitting connection, never to another Eternia that declared it answers
(a second window, a paired device's Eternia) after the message was admitted, and it carries the
room/task invocation identity the runtime owns, never one the tool arguments forge.
Killing mutation (seen red 2026-11-21): ``DiscussionAppFunctions.request_for`` answering from the
most recent declarer (the last connection any room bound) instead of the admitting binding.
"""
from __future__ import annotations

import json
import threading

import pytest

from agent_runtime import launcher_app_functions as laf
from agent_runtime.discussions.app_functions import requesting_launcher
from agent_runtime.discussions.service import DiscussionService
from tests.agent_runtime.test_discussion_runtime import ExecutionContext, room_timings, settled, wait_until
from tests.agent_runtime.test_launcher_app_functions import _Launcher
from tests.agent_runtime.test_native_discussion_room import spec

pytestmark = pytest.mark.timeout(120)

_TOOL = "launcher_navigation_open"
_METHOD = "launcher.navigation.open"
_BUSY = "Think about the layout first"
_ASK = "Open the library page for me"
#: An account's opaque Launcher digest (``conversation_owner.client_scope``).
_SCOPE = "a" * 64


class ToolTurns(ExecutionContext):
    """The injected model. A turn on ``_BUSY`` holds until ``release``, so the next message
    queues behind it; a turn on ``_ASK`` calls the app-function tool the way a model's tool
    call does (the registry's handler), with a forged ``_meta`` in its arguments."""

    def __init__(self, tmp_path):
        self.release = threading.Event()
        self.busy = threading.Event()
        self.results = []
        super().__init__(tmp_path)

    def model(self, args):
        if _BUSY in args.message:
            self.busy.set()
            assert self.release.wait(60)
        if _ASK in args.message:
            from tools.registry import registry
            self.results.append(registry.get_entry(_TOOL).handler(
                {"page": "library", "_meta": {"invocation": {"session_id": "forged"}, "origin": "paired_device"}}))
        return super().model(args)


@pytest.fixture
def rooms(tmp_path):
    laf._reset_for_tests()
    context = ToolTurns(tmp_path)
    service = DiscussionService(context, **room_timings())
    service.start()
    yield service, context
    context.release.set()
    service.close()
    laf._reset_for_tests()


def send(service, room, key, message, member):
    current = service.runs.get(room["run_id"])
    service.command("ws", room["run_id"], "send", key=key, expect_revision=current["revision"],
                    body={"message": message, "response": {"mode": "reply", "members": [member]}},
                    actor_id="operator")


def calls(sink):
    return [frame for frame in sink.sent if frame.get("method") == _METHOD]


def test_an_agent_room_request_rides_the_admitting_connection_with_the_room_task_identity(rooms):
    service, context = rooms
    admitting, other = _Launcher(), _Launcher()
    laf.declare_answerer("admitting", True)
    with requesting_launcher(laf.LauncherLink(admitting, laf.ORIGIN_LOCAL).request):
        room = service.begin_room("ws", spec(), key="room", topic="Review", actor_id="operator",
                                  client_scope=_SCOPE)
    member = wait_until(lambda: settled(service, room))["members"][0]["member_id"]
    with requesting_launcher(laf.LauncherLink(admitting, laf.ORIGIN_LOCAL).request):
        send(service, room, "busy", _BUSY, member)
        assert context.busy.wait(60)
        send(service, room, "ask", _ASK, member)  # queued behind the busy turn

    # Before the queued message's turn starts, a second Eternia declares it answers and starts its
    # own room: it is now the most recent declarer and the last connection the room service bound.
    laf.declare_answerer("other", True)
    assert laf.latest_answerer({"admitting", "other"}) == "other"
    with requesting_launcher(laf.LauncherLink(other, laf.ORIGIN_LOCAL).request):
        second = service.begin_room("ws", spec(), key="second", topic="Elsewhere", actor_id="operator")
    wait_until(lambda: settled(service, second))
    assert context.results == []
    context.release.set()
    wait_until(lambda: context.results)

    sent = calls(admitting)
    assert len(sent) == 1, sent
    assert calls(other) == []
    asked = [t for t in service.view("ws", room["run_id"])["tasks"] if t["member_id"] == member][-1]
    meta = sent[0]["params"]["_meta"]
    assert meta == {"origin": laf.ORIGIN_LOCAL, "invocation": {
        "channel": "discussion", "session_id": room["run_id"], "turn_id": asked["task_id"], "client_scope": _SCOPE}}
    assert sent[0]["params"]["page"] == "library"
    # The tool result the turn saw is the admitting Eternia's answer.
    assert json.loads(context.results[0])["data"]["echo"]["_meta"] == meta
