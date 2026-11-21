"""``agent_chat_send`` checks a local target BEFORE accepting the send (``tools/agent_chat/addressing.py``).

RT-AGENT-CHAT-SEND-DISPLAY-NAME-ACCEPTED (found live 2026-11-06, Eternia w1106b-live-a): a display name
("QA Agent A") passed, dispatched, and only the background delivery refused ``unknown persona QA_Agent_A``.
"""

import json

import pytest
from hermes_cli.harness_parts.persona import chat_turn_message

from tools.agent_chat_tool import agent_chat_send

pytestmark = pytest.mark.usefixtures("persisted_persona_samples")

#: The placed instances in reach. Reading the roster no longer mints the hidden copies, and a bare
#: persona is no longer sent to one (RT-A-SEND-TO-AN-AGENT-WITH-NO-INSTANCE-IN-REACH-IS-PLACED-OR-REFUSED).
QA = "personainst_qa_agent_2"
DEV = "personainst_dev_agent_2"


@pytest.fixture(autouse=True)
def _placed():
    from tests.agent_runtime.persona_instance_mint import mint_placed_instance

    mint_placed_instance("qa", display_name="QA Agent")
    mint_placed_instance("dev", display_name="Dev Agent")


@pytest.fixture
def handled(monkeypatch):
    """The CLI lane's handler, faked: records the target it was handed."""

    seen: list[tuple[str, str | None]] = []

    def fake_handler(args):
        seen.append((args.persona_id, args.persona_instance_id))
        args.payload_sink({"ok": True, "reply": "ack"})
        return 0

    monkeypatch.setattr(chat_turn_message, "_cmd_mission_chat_message", fake_handler)
    return seen


def test_a_display_name_is_resolved_to_its_instance_handle(handled):
    """Killing mutation: ``local_target`` returns None without resolving -> the handler gets "QA Agent"."""

    data = json.loads(agent_chat_send(persona_id="  qa   AGENT ", message="hi"))
    assert data["ok"] is True
    assert handled == [(QA, QA)]


def test_an_unknown_name_is_refused_now_listing_the_addressable_handles(handled):
    """Killing mutation: drop the refusal (return ``persona_id, None``) -> it reaches the handler."""

    data = json.loads(agent_chat_send(persona_id="QA Agent A", message="hi", wait=False))
    assert (data["ok"], data["error_kind"]) == (False, "unsupported_persona")
    handles = [row["handle"] for row in data["addressable"]]
    assert QA in handles and QA in data["error"]
    assert handled == []


def test_a_persona_id_and_an_instance_handle_pass_as_given(handled):
    assert json.loads(agent_chat_send(persona_id="dev", message="hi"))["ok"] is True
    assert json.loads(agent_chat_send(persona_id="personainst_dev", message="hi"))["ok"] is True
    assert handled == [("dev", None), ("personainst_dev", "personainst_dev")]


def test_an_invented_profile_handle_is_refused_now_not_in_the_background(handled):
    """RT-AGENT-CHAT-SEND-ACCEPTS-AN-AGENT-WITH-NO-PROFILE (seen live 2026-11-15): Base's send to the
    invented ``personainst_profile_charsheet`` answered ``dispatched: true`` and failed later "Hermes
    profile 'charsheet' does not exist". Killing mutation: ``_unreachable_handle`` returns None -> the
    send reaches the handler."""

    for target in ("personainst_profile_charsheet", "@personainst_profile_charsheet"):  # the second, seen live
        data = json.loads(agent_chat_send(persona_id=target, message="hi", wait=False))
        assert (data["ok"], data["error_kind"]) == (False, "unsupported_persona"), target
        assert "'charsheet' does not exist" in data["error"]
        assert QA in [row["handle"] for row in data["addressable"]]
    assert handled == []


def test_a_stored_profile_backed_instance_whose_profile_is_gone_is_refused(handled, monkeypatch):
    """The roster's own rule (``roster_reach.profile_missing``), asked at admission."""
    from agent_runtime import roster_reach
    from agent_runtime.config import ensure_persisted_personas, load_agent_runtime_config
    from agent_runtime.persona_assignments import PersonaInstanceStore

    PersonaInstanceStore().ensure_for_personas(list(ensure_persisted_personas(load_agent_runtime_config())))
    monkeypatch.setattr(roster_reach, "profile_missing", lambda instance: "gone")
    data = json.loads(agent_chat_send(persona_id="personainst_dev", message="hi"))
    assert (data["ok"], data["error_kind"]) == (False, "unsupported_persona")
    assert "'gone' does not exist" in data["error"]
    assert handled == []


def test_an_invented_handle_is_refused_when_the_sender_has_no_teammates(handled, monkeypatch):
    """Seen live 2026-11-15 (w1115e-h4): Base, alone on its roster, still had its send to
    ``personainst_profile_charsheet`` accepted — an empty roster deferred the handle to the handler.
    Killing mutation: defer a handle again when the roster is empty -> it reaches the handler."""
    from tools.agent_chat import addressing

    real = addressing._addressable
    monkeypatch.setattr(addressing, "_addressable", lambda session: (*real(session)[:2], []))
    data = json.loads(agent_chat_send(persona_id="personainst_profile_charsheet", message="hi", wait=False))
    assert (data["ok"], data["error_kind"]) == (False, "unsupported_persona")
    assert "none are addressable" in data["error"]
    assert handled == []



def test_an_at_handle_is_forwarded_as_the_clean_instance_id(handled):
    """MC-RUNNING-NOW-AN-AGENT-REQUEST-NAMES-ITS-TARGET-BY-A-RAW-HANDLE (reported by the owner 2026-11-20):
    a request addressed "@personainst_…" was owned by that raw spelling, so Running now read the handle
    instead of the agent's name. ``Send.relay_args`` forwards the clean handle; the detached dispatch
    reads the same ``target_instance_id`` (its dispatch row's owner key). Killing mutation: forward
    ``self.persona_id`` there when it looks like a handle -> the handler gets "@personainst_dev", red."""

    assert json.loads(agent_chat_send(persona_id="@personainst_dev", message="hi"))["ok"] is True
    assert [instance for _, instance in handled] == ["personainst_dev"]


def test_an_at_handle_is_judged_and_sent_on_clean_by_addressing(handled):
    """Review w1118a.64 D9: addressing judges the "@…" handle and forwards the value it judged, with
    no strip of its own. Killing mutation: ``resolve_send_target`` returns ``persona_id`` for a reachable
    handle -> the handler's persona slot gets "@personainst_dev", red."""

    from tools.agent_chat.addressing import resolve_send_target

    assert resolve_send_target("@personainst_dev") == ("personainst_dev", None)
    assert json.loads(agent_chat_send(persona_id="@personainst_dev", message="hi"))["ok"] is True
    assert handled == [("personainst_dev", "personainst_dev")]


def test_an_at_spelled_invented_profile_handle_is_refused_too(handled):
    """The reach check reads the clean handle it is handed. Killing mutation: hand ``_unreachable_handle``
    the raw ``persona_id`` -> "@personainst_profile_…" misses the profile-channel test and the send reaches
    the handler, red."""

    data = json.loads(agent_chat_send(persona_id="@personainst_profile_charsheet", message="hi", wait=False))
    assert data["ok"] is False
    assert "charsheet" in data["error"]
    assert handled == []


def test_an_at_handle_opens_that_agents_thread():
    """RT-FU-AN-AGENTS-THREAD-READ-OF-AN-AT-HANDLE-MISSES-THAT-AGENTS-THREAD (read in code 2026-11-20): the
    thread read judged "@personainst_…" a handle but forwarded the raw spelling as the instance id.
    Killing mutation: in ``threads.resolve_chat_lane_target`` forward ``target`` when it is a handle ->
    the lane's instance is "@personainst_dev", red."""

    from tools.agent_chat.threads import resolve_chat_lane_target

    clean, refusal = resolve_chat_lane_target("personainst_dev")
    target, refusal_at = resolve_chat_lane_target("@personainst_dev")

    assert refusal is None and refusal_at is None
    assert target.instance_id == "personainst_dev"
    assert (target.handle, target.default_session) == (clean.handle, clean.default_session)


@pytest.fixture
def on_chain():
    """Run the send inside a turn whose relay chain is *speakers* (the sender's own turn sets it)."""
    from agent_runtime import relay_policy

    tokens = []

    def enter(*speakers):
        tokens.append(relay_policy.RELAY_CHAIN.set(tuple(speakers)))

    yield enter
    for token in reversed(tokens):
        relay_policy.RELAY_CHAIN.reset(token)


def test_a_send_to_the_sender_itself_is_refused_now(handled, on_chain):
    """RT-FU-A-SEND-TO-AN-UNPLACED-AGENT-GOES-BACK-TO-THE-SENDER-AND-A-REFUSED-SEND-SAYS-OK (seen live
    2026-11-21, dispatch-c58c34703868): Base's ``wait=false`` send to ``@personainst_base`` answered
    ``ok: true, dispatched: true`` and the background turn refused it ``relay_cycle``. Admission asks the
    turn's own resolver, so it is refused in the sending turn and never queued. Killing mutation:
    ``Send.local_target`` returns None instead of ``admit_send(...)`` -> the send goes on, red."""

    on_chain("personainst_dev")
    for wait in (False, True):
        data = json.loads(agent_chat_send(persona_id="@personainst_dev", message="hi", wait=wait))
        assert (data["ok"], data["error_kind"]) == (False, "relay_cycle"), wait
        assert "personainst_dev" in data["error"] and data["relay_chain"] == ["personainst_dev"]
    assert handled == []


def test_a_bare_persona_that_resolves_onto_the_sender_is_refused_now(handled, on_chain):
    """The cycle the bare key hides: ``dev`` names no instance, the turn's resolver lands it on dev's
    one placement in reach, which is the sender. Admission runs the turn's instance resolution
    and ``bind_turn_instance``, not just the persona-keyed check. Killing mutation: drop the
    ``bind_turn`` step in ``chat_turn_target.admit_turn_target`` -> admitted, red."""

    on_chain(DEV)
    data = json.loads(agent_chat_send(persona_id="dev", message="hi"))
    assert (data["ok"], data["error_kind"]) == (False, "relay_cycle")
    assert data["persona_instance_id"] == DEV
    assert handled == []


def test_a_send_to_another_agents_unplaced_instance_still_goes_through(handled, on_chain):
    """The other half of the row: a send to an instance placed nowhere reaches that instance."""

    on_chain("personainst_qa")
    assert json.loads(agent_chat_send(persona_id="@personainst_dev", message="hi"))["ok"] is True
    assert handled == [("personainst_dev", "personainst_dev")]


def test_admission_and_the_turn_refuse_with_the_same_words(on_chain):
    """One resolver: the refusal admission returns is the turn handler's own payload, for the cycle
    only the instance resolution finds (a bare ``dev`` landing on the speaking ``DEV`` placement).
    Killing mutation: ``admit_turn_target`` rewords ``bind_turn``'s refusal (a second judge's words)
    -> the texts part, red."""

    from types import SimpleNamespace

    from agent_runtime.mission_chat_door import TURN_TARGET_VERB, run_chat_verb, run_mission_chat_turn

    fields = dict(persona_id="dev", persona_instance_id=None, session_id=None,
                  clarify_token=None, requested_by_session=None, relay_chain=[DEV])
    _, admitted = run_chat_verb(TURN_TARGET_VERB, SimpleNamespace(**fields))
    turn_args = SimpleNamespace(
        **fields, message="hi", new_session=None, task_id=None, goal_id=None, title=None, provider=None,
        model=None, use_agent_default=False, surface_prompt="", intent_hint="chat",
        requested_by="agent-chat-relay", client_message_id="agent-relay-parity", stream=False,
        max_seconds=60.0, json=True, relay_deadline_epoch=None,
    )
    exit_code, turn = run_mission_chat_turn(turn_args)
    assert exit_code == 2 and admitted["ok"] is False and turn["persona_instance_id"] == DEV
    assert (admitted["error_kind"], admitted["error"]) == (turn["error_kind"], turn["error"])
