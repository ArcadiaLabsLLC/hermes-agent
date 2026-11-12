"""``RT-STEER-NEXT-TURN-NAMES-THE-STEER-IT-DELIVERS``: a late steer's own turn says which steer it delivers.

A steer accepted too late to land inside the turn runs as the chat root's next turn, ``steer-next-<id>``.
The stored operator row of that turn carried the steer's id nowhere but inside the turn id, so the app
matched its own echo of the steer to the stored row by stripping the prefix (seen live 2026-11-12, Eternia
lane w1112b-turn6: the steered message drew twice until the client copied the naming rule). The queued send
now carries ``steer_of`` — the client message ids of the operator steers the turn delivers — and the turn's
journal record, its persona-history operator row and its operator-conversation message state it.

Whole turns (``held_model_turn``): a Work turn held in its one model call accepts a steer through
``submit_mission_chat_steer``, ends, and the queued ``steer-next-…`` entry is run by the send runner; the
stored rows are read as the app reads them (``runtime.operator.conversation.read`` and the conversation
contract over it). The other two minting sites (the settle's ledger sweep, the serve boot's) are read at the
queue entry they write — the entry's args are the turn's args (``chat_root_send_runner._turn_args``).

Killing mutations (reds recorded in the commit body):
* ``queue_leftover_steer`` stops writing ``steer_of`` → the whole-turn test and the handed-back test red;
* ``_requeue_from_ledger`` stops writing ``steer_of`` → the gap test and the boot test red;
* ``_write_ahead`` drops ``steer_of`` from the journal metadata → the whole-turn test red (both stores);
* ``history_messages._carry_retry_lineage`` drops ``steer_of`` → the whole-turn test red (operator conversation);
* ``curation``'s operator row drops ``steer_of`` → the whole-turn test red (persona history);
* ``steer_ids`` keeps a notice's id → the notice test red.
"""

from __future__ import annotations

import pytest

from agent.steering import PendingSteer, join_pending_steer
from agent_runtime import chat_root_send_queue as send_queue
from agent_runtime import chat_root_send_runner, paths
from agent_runtime.mission_chat_steer import submit_mission_chat_steer
from agent_runtime.operator_channels.conversation import _conversation_contract
from agent_runtime.persona_assignments import PersonaInstanceStore
from agent_runtime.work_store.persona_turn import _turn_args
from hermes_cli.harness_parts.persona.chat_turn_commit import leftover_steer
from tests.agent_runtime import test_dead_turn_steer_boot_requeue as boot
from tests.agent_runtime import test_steer_accepted_as_reply_ends as gap
from tests.agent_runtime.held_model_turn import Running, operator_call, operator_params
from tests.agent_runtime.test_chat_lease_finalization_tail import ROOT
from tests.agent_runtime.test_serve_rpc_open_chat import (  # placed_agent / qa_persona are fixtures
    PERSONA, WORKSPACE, placed_agent, qa_persona,
)
from tests.agent_runtime.test_work_turn_takes_a_steer import chat, chat_head, model  # fixtures: a chat, a held model

pytestmark = pytest.mark.timeout(180)
STEER_ID = "agent-chat-send-cadc7833"
STEER = "steer check: add the word pineapple"


def _stored_rows(instance: str, root: str) -> dict[str, list[dict]]:
    """The chat as the app reads it back: the persona history and the operator conversation over it."""

    history = operator_call("read", operator_params(instance, root, None, persona=PERSONA, workspace=WORKSPACE))["result"]
    conversation = _conversation_contract(
        channel_id="channel-1", persona_id=PERSONA, persona_instance_id=instance, session_id=root, goal_id=None,
        title="Chat", state="idle", history=history, trace=None)
    return {"persona history": history["messages"], "operator conversation": conversation["messages"]}


def test_a_late_steers_own_turn_names_the_steer_on_its_stored_operator_row(chat, model):
    instance, root = chat
    cmid = "work-BATCH-Q44PM7:L1"
    args = _turn_args(PersonaInstanceStore().get(instance), root, cmid, "Tidy the meadow.", "work:BATCH-Q44PM7:L1")
    entry, _position, _replay = send_queue.enqueue(root, cmid, send_queue.persistable_args(args))
    turn = Running(lambda: chat_root_send_runner._run_entry(entry, chat_root_send_runner.RunnerPolicy()))
    assert model.entered.wait(60), "the Work turn never reached the model"
    ack = submit_mission_chat_steer(runtime_root=paths.store_root(), session_id=root, message=STEER,
                                    client_message_id=STEER_ID, timeout_seconds=20)
    assert ack["ok"] is True and ack["execution_state"] == "accepted", ack
    model.hold = False
    model.release.set()
    turn.join(60)

    # The Work turn had one model call, so the steer landed in no tool round: it is the root's next turn.
    late = send_queue.find(root, "steer-next-" + STEER_ID)
    assert late is not None, [e.client_message_id for e in send_queue.entries(root)]
    assert late.args["steer_of"] == [STEER_ID]
    Running(lambda: chat_root_send_runner._run_entry(late, chat_root_send_runner.RunnerPolicy())).join(60)

    for name, messages in _stored_rows(instance, root).items():
        operator_rows = [m for m in messages if str(m.get("role")) == "operator"]
        by_turn = {str(m.get("client_message_id")): m for m in operator_rows}
        assert "steer-next-" + STEER_ID in by_turn, f"{name}: {sorted(by_turn)}"
        assert by_turn["steer-next-" + STEER_ID].get("steer_of") == [STEER_ID], f"{name}: {by_turn}"
        # A turn that delivers no steer says nothing: the Work turn's own row carries no such key.
        assert all("steer_of" not in m for cmid_, m in by_turn.items() if not cmid_.startswith("steer-next-")), name


def test_a_steer_accepted_as_the_reply_ends_is_queued_naming_itself(monkeypatch, isolate_agent_runtime_root,
                                                                    persisted_persona_samples):
    """The settle's ledger sweep (``_requeue_from_ledger``): accepted, in neither the transcript nor the hand-back."""

    gap._a_turn_returns_after_accepting(monkeypatch, [("cm-steer-gap", "also check the logs")])

    assert send_queue.find(ROOT, "steer-next-cm-steer-gap").args["steer_of"] == ["cm-steer-gap"]


def test_a_dead_turns_steer_is_queued_at_boot_naming_itself(monkeypatch, isolate_agent_runtime_root,
                                                            persisted_persona_samples):
    """The serve boot's sweep of a dead executor's ledger."""

    boot._a_turn_dies_holding_a_steer(monkeypatch)
    assert leftover_steer.requeue_dead_turn_steers() == ["steer-next-cm-steer-orphan"]

    assert send_queue.find(ROOT, "steer-next-cm-steer-orphan").args["steer_of"] == ["cm-steer-orphan"]


def test_a_handed_back_steer_is_queued_naming_every_operator_steer_and_no_notice(
        monkeypatch, isolate_agent_runtime_root, persisted_persona_samples):
    """``queue_leftover_steer``: two late steers and a background notice handed back together run as ONE turn;
    it names both steers, in order, and not the notice (a notice is not something the operator typed)."""

    from tools.process_registry_notifications import TimelineNotification

    pending = PendingSteer.from_text("first late steer", platform_id="cm-steer-a")
    pending = join_pending_steer(pending, PendingSteer.from_text(
        TimelineNotification("build done", "Background process update", "process_completed"), platform_id="proc-1"))
    pending = join_pending_steer(pending, PendingSteer.from_text("second late steer", platform_id="cm-steer-b"))
    gap._a_turn_returns_after_accepting(monkeypatch, [("cm-steer-a", "first late steer"),
                                                      ("cm-steer-b", "second late steer")], pending=pending)

    [entry] = send_queue.entries(ROOT)
    assert entry.client_message_id == "steer-next-cm-steer-a" and entry.args["steer_of"] == ["cm-steer-a", "cm-steer-b"]


def test_a_hand_back_that_kept_no_ids_names_no_steer(monkeypatch, isolate_agent_runtime_root,
                                                     persisted_persona_samples):
    """Upstream's plain join keeps no ids: the turn is ``steer-next-<the turn's own id>`` and names no steer —
    the case an id-prefix rule gets wrong (it would read the TURN's id as a steer's)."""

    gap._a_turn_returns_after_accepting(
        monkeypatch, [("cm-steer-late", "also check the logs")], pending="first thing\nalso check the logs")

    [entry] = send_queue.entries(ROOT)
    assert entry.client_message_id == "steer-next-cm-fine" and "steer_of" not in entry.args
