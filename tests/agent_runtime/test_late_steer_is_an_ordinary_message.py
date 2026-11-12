"""A too-late steer at your own message is an ordinary chat message, answered where it was typed.

``RT-LATE-STEER-AT-YOUR-OWN-MESSAGE-CARRIES-ITS-ATTACHMENTS-AGAIN``: a steer typed at an operator's own turn that
arrives after the turn's last tool round runs next as ``steer-next-<id>``. Until 2026-11-12 that turn was
queued from a copy of the FIRST message's send, so the model was sent the first message's file (its ``FILE:``
line) and one-message skill again, and the steer's stored row read as spoken because the first one was —
reproduced as whole turns by lane w1112b-hm-turnfu before the fix.

``RT-LATE-STEER-TYPED-ON-A-PAIRED-DEVICE-IS-NOT-ANSWERED-THERE``: the steer's ledger record did not keep who
sent it, so the late turn's origin was the FIRST message's sender (or nobody, at a Work turn) and a steer typed
on a paired device was answered on the desktop only — the serve sends a queued turn's frames and its
``turn_settled`` to a device only when the turn's origin names that device's connection.

Owner ruling 2026-11-12: a too-late steer is "an ordinary chat message" — what was typed with it, from whoever
typed it. Whole turns on ``held_model_turn``: the first message is held at the model, the steer goes through the
steer DOOR (``chat_coordinator._cmd_mission_chat_steer``) on a serve request from a paired device's connection,
the first turn ends, and the queued late turn is run.

Killing mutations (each run, seen red, restored — recorded in the commit body):
* ``leftover_steer._next_turn_send`` keeps ``dict(send_args)`` for an operator's turn → both whole-turn tests red;
* the steer door drops ``origin=send_origin()`` → the device test red;
* ``mission_chat_steer._process_request`` drops the origin from the accepted record → the device test red;
* ``_operators_own_send`` keeps no chat choice → the chat-choices test red.
"""

from __future__ import annotations

import contextlib
import functools
import json
import threading
from types import SimpleNamespace

import pytest

from agent_runtime import chat_root_send_queue as send_queue
from agent_runtime import chat_root_send_runner, mission_chat_steer, operator_files
from agent_runtime.chat_turn import OPERATOR_REQUESTED_BY
from agent_runtime.persona_assignments import PersonaInstanceStore
from agent_runtime.work_store.persona_turn import _turn_args
from hermes_cli.harness_parts.persona import chat_coordinator
from hermes_cli.harness_parts.persona.chat_turn_commit import leftover_steer
from hermes_cli.harness_parts.serve import queued_turn_origin
from hermes_cli.harness_parts.serve.frames import _request_id, _request_sink
from hermes_cli.harness_parts.serve.manifest import GATEWAY_TRANSPORT
from tests.agent_runtime.held_model_turn import Running, operator_call, operator_params
from tests.agent_runtime.test_serve_rpc_open_chat import PERSONA, WORKSPACE, placed_agent, qa_persona  # fixtures
from tests.agent_runtime.test_work_turn_takes_a_steer import chat, chat_head, model  # fixtures

pytestmark = pytest.mark.timeout(180)

FIRST = "cm-first"
STEER_ID = "steer-a"
LATE_TURN = "steer-next-" + STEER_ID
STEER_TEXT = "also water the roses"
DESK = {"owner": "desk-1", "gateway": False}
PHONE = {"owner": "phone-1", "gateway": True}


@contextlib.contextmanager
def _screen(_entry):
    yield SimpleNamespace(finish=lambda exit_code, payload: None)


@contextlib.contextmanager
def _serve_request(sender: dict):
    """The serve request a steer arrives on (``ArgvLanes._run``): its sink targets the sender's connection."""

    connection = SimpleNamespace(key=sender["owner"], transport=GATEWAY_TRANSPORT if sender["gateway"] else "local")
    rid, sink = _request_id.set("rid-steer"), _request_sink.set(SimpleNamespace(_target=connection))
    try:
        yield
    finally:
        _request_sink.reset(sink)
        _request_id.reset(rid)


def _steer_at_the_door(monkeypatch, root: str, sender: dict) -> dict:
    """``runtime.chat.steer`` lowered to ``harness mission-chat steer``, run on ``sender``'s serve request."""

    printed: list[str] = []
    with monkeypatch.context() as patch:
        patch.setattr(chat_coordinator, "submit_mission_chat_steer",
                      functools.partial(mission_chat_steer.submit_mission_chat_steer, timeout_seconds=20))
        patch.setattr("builtins.print", lambda *items, **_kw: printed.append(" ".join(map(str, items))))
        with _serve_request(sender):
            chat_coordinator._cmd_mission_chat_steer(SimpleNamespace(
                session_id=root, client_message_id=STEER_ID, message=STEER_TEXT, persona_id=None,
                persona_instance_id=None, json=True))
    return json.loads(printed[-1])


def _first_message(instance: str, root: str, sender: dict, *, attached: bool) -> send_queue.QueuedSend:
    args = _turn_args(PersonaInstanceStore().get(instance), root, FIRST, "Look at this file.", OPERATOR_REQUESTED_BY)
    args.max_seconds = None
    if attached:
        from hermes_constants import get_hermes_home

        skill = get_hermes_home() / "skills" / "meadow-skill"
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text("---\nname: meadow-skill\ndescription: How to mow.\n---\nMEADOWSKILLBODY\n")
        [ref] = operator_files.store_files([operator_files.OperatorFile("notes.txt", "text/plain", b"meadow notes")])
        args.files, args.skills, args.input_mode = [ref], ["meadow-skill"], "voice"
    entry, _position, _replay = send_queue.enqueue(root, FIRST, send_queue.persistable_args(args, origin=sender))
    return entry


def _late_steer(monkeypatch, model, instance: str, root: str, *, first_from: dict, steer_from: dict,
                attached: bool) -> send_queue.QueuedSend:
    policy = chat_root_send_runner.RunnerPolicy(stream=_screen)
    first = Running(lambda: chat_root_send_runner._run_entry(
        _first_message(instance, root, first_from, attached=attached), policy))
    assert model.entered.wait(60), "the first message never reached the model"
    ack = _steer_at_the_door(monkeypatch, root, steer_from)
    assert ack["ok"] is True and ack["execution_state"] == "accepted", ack
    model.hold = False
    model.release.set()
    first.join(60)
    late = send_queue.find(root, LATE_TURN)
    assert late is not None, [e.client_message_id for e in send_queue.entries(root)]
    return late


def test_a_late_steer_at_your_own_message_carries_only_what_was_typed_with_it(monkeypatch, chat, model):
    instance, root = chat
    late = _late_steer(monkeypatch, model, instance, root, first_from=DESK, steer_from=DESK, attached=True)
    # The premise: the first message's turn was sent its file and its one-message skill.
    first_prompt = str(model.requests[-1]["messages"])
    assert "FILE:" in first_prompt and "MEADOWSKILLBODY" in first_prompt

    assert late.args["message"] == STEER_TEXT and late.args["steer_of"] == [STEER_ID]
    for field in ("files", "images", "skills", "input_mode"):
        assert not late.args.get(field), (field, late.args.get(field))

    sent = len(model.requests)
    Running(lambda: chat_root_send_runner._run_entry(
        late, chat_root_send_runner.RunnerPolicy(stream=_screen))).join(60)
    [late_request] = model.requests[sent:]
    [*_, steer_text] = [str(m.get("content")) for m in late_request["messages"] if m.get("role") == "user"]
    assert steer_text.startswith(STEER_TEXT)
    assert "FILE:" not in steer_text and "skill_preload" not in steer_text, steer_text

    history = operator_call("read", operator_params(instance, root, None, persona=PERSONA, workspace=WORKSPACE))
    [row] = [m for m in history["result"]["messages"] if m.get("client_message_id") == LATE_TURN]
    assert row["text"] == STEER_TEXT and row.get("input_mode") is None, row


def test_a_late_steer_typed_on_a_paired_device_is_answered_there(monkeypatch, chat, model):
    instance, root = chat
    late = _late_steer(monkeypatch, model, instance, root, first_from=DESK, steer_from=PHONE, attached=False)

    assert late.args[send_queue.ORIGIN_ARG] == PHONE
    # The serve's queued-turn stream: the phone's live connection gets the late turn's frames and settle.
    phone_sink = object()
    session = SimpleNamespace(connection_sinks_lock=threading.Lock(), connection_sinks={"phone-1": phone_sink})
    assert queued_turn_origin.queued_turn_peer(session, late, "rid-late") is phone_sink


def test_a_late_steer_typed_on_the_desktop_at_the_phones_message_is_not_sent_to_the_phone(monkeypatch, chat, model):
    instance, root = chat
    late = _late_steer(monkeypatch, model, instance, root, first_from=PHONE, steer_from=DESK, attached=False)

    assert late.args[send_queue.ORIGIN_ARG] == DESK
    session = SimpleNamespace(connection_sinks_lock=threading.Lock(), connection_sinks={"phone-1": object()})
    assert queued_turn_origin.queued_turn_peer(session, late, "rid-late") is None


def test_a_late_steer_keeps_the_choices_made_for_the_chat():
    """The model picked for the chat and the surface's prompt are not the first message's: they stay."""

    send = {"persona_id": "p", "persona_instance_id": "personainst_1", "requested_by": OPERATOR_REQUESTED_BY,
            "max_seconds": 90.0, "model": "picked-for-this-chat", "provider": "prov", "surface_prompt": "be brief",
            "intent_hint": "chat", "files": ["sha256:x.txt"], "skills": ["s"], "input_mode": "voice",
            send_queue.ORIGIN_ARG: PHONE}

    late = leftover_steer._next_turn_send(send, session_id="root", text="one more thing", next_id=LATE_TURN,
                                          ids=[STEER_ID], sender=DESK)

    assert {k: late[k] for k in ("model", "provider", "surface_prompt", "intent_hint")} == {
        "model": "picked-for-this-chat", "provider": "prov", "surface_prompt": "be brief", "intent_hint": "chat"}
    assert late["max_seconds"] is None and late[send_queue.ORIGIN_ARG] == DESK
    assert not any(late.get(k) for k in ("files", "skills", "input_mode"))
