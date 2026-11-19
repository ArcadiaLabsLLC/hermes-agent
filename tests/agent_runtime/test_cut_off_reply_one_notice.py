"""``RT-CUT-OFF-REPLY-ALSO-SAYS-NOT-PROCESSED``: a reply the model cut off shows one notice.

Seen live 2026-11-12 (Eternia lane w1112b-turn3, picture 12): a reply cut at the output limit drew the
core's failed-turn bubble ("Your request was not processed…") above the turn's own "The model's reply was
cut off before it finished…".

Reproduced whole (``held_model_turn``: an operator send whose model answers a tool call cut mid-argument,
``finish_reason: length``, on every continuation). What that found: the turn SETTLES with the loop's
cut-off words as its reply (the journal's ``stored_reply``, what the console draws live), while the only
stored row is the core's boundary row, ``display_kind: failed_turn``, carrying the generic sentence. So
the live chat said both, and a reloaded chat said only the generic one — the cut-off notice was gone.

Decided (w1112b-hm-turn2): a cut-off reply is a failed model call, not a stop — the core row keeps
closing the tail for every host; the Harness chat stops drawing it as a second bubble. The persona
history now reads that row as the turn's own settled words: one notice, live and after a reload. A failed
turn that settled no reply keeps the core's sentence.

Killing mutations (reds recorded in the commit body):
* ``CurationState.curate`` drops its ``_failed_turn_reply`` line → the cut-off test red (the generic sentence is
  the stored chat's only word for the turn);
* ``_failed_turn_reply`` answers for a record with no ``stored_reply`` by hiding the row → the control red;
* ``_failed_turn_reply`` answers for any agent row → the ordinary-reply control red.
"""

from __future__ import annotations

import pytest

from agent.turn_failure_copy import FAILED_TURN_DISPLAY_KIND, FAILED_TURN_NOTICE
from agent_runtime.operator_channels.conversation import _conversation_contract
from agent_runtime.persona_chat_history import curation
from tests.agent_runtime.held_model_turn import OWNER, HeldModel, operator_call, operator_params, operator_turn
from tests.agent_runtime.test_serve_rpc_open_chat import (  # placed_agent / qa_persona are fixtures
    PERSONA, WORKSPACE, _call, placed_agent, qa_persona,
)

pytestmark = pytest.mark.timeout(180)
CUT_OFF = "The model's reply was cut off before it finished"
#: A tool call cut mid-argument: what the QA fixture's truncated stream is to the loop.
CUT_TOOL_CALL = {"role": "assistant", "tool_calls": [{
    "index": 0, "id": "call_1", "type": "function",
    "function": {"name": "terminal", "arguments": '{"command": "sle'}}]}


@pytest.fixture(autouse=True)
def chat_head(monkeypatch, isolate_agent_runtime_root):
    from hermes_constants import get_hermes_home

    monkeypatch.setenv("HERMES_HEAD_HOME", str(get_hermes_home()))


@pytest.fixture
def model():
    from hermes_constants import get_hermes_home

    held = HeldModel()
    held.hold = False
    held.configure(get_hermes_home())
    yield held
    held.close()


def _agent_words(instance: str, root: str) -> dict[str, list[str]]:
    """What the agent says in the stored chat, by projection."""

    history = operator_call("read", operator_params(instance, root, None, persona=PERSONA,
                                                    workspace=WORKSPACE))["result"]
    conversation = _conversation_contract(
        channel_id="channel-1", persona_id=PERSONA, persona_instance_id=instance, session_id=root, goal_id=None,
        title="Chat", state="idle", history=history, trace=None)
    return {
        "persona history": [m["text"] for m in history["messages"] if str(m["role"]) == "agent"],
        "operator conversation": [m["display_text"] for m in conversation["messages"] if m["kind"] == "reply"],
    }


def _new_chat(placed) -> tuple[str, str]:
    instance = placed["persona_instance_id"]
    root = _call(dict(persona_id=PERSONA, persona_instance_id=instance, new_session=True,
                      idempotency_key="chat-1", client_scope=OWNER))["result"]["session_id"]
    return instance, root


def test_a_cut_off_reply_reads_as_one_notice_the_cut_off_one(placed_agent, model):
    instance, root = _new_chat(placed_agent)
    model.reply = lambda body: (CUT_TOOL_CALL, "length")

    _code, payload = operator_turn(instance, root, "msg-1", "Run the long job.").join(120)

    assert payload["reply"].startswith(CUT_OFF), payload["reply"]  # what the console draws live
    from hermes_state import SessionDB

    stored = [row for row in SessionDB().get_messages(root) if row["role"] == "assistant"]
    assert [row.get("display_kind") for row in stored] == [FAILED_TURN_DISPLAY_KIND]  # the tail stays closed
    assert stored[0]["content"] == FAILED_TURN_NOTICE
    for name, said in _agent_words(instance, root).items():
        assert said == [payload["reply"]], f"{name}: the cut-off turn does not read as its one notice: {said}"


def test_a_failed_turn_that_settled_no_words_keeps_the_core_sentence(placed_agent, model):
    """The control: the turn's journal holds no reply, so the boundary row is all there is to read."""

    from agent_runtime.persona_chat_history import history_evidence

    instance, root = _new_chat(placed_agent)
    model.reply = lambda body: (CUT_TOOL_CALL, "length")
    operator_turn(instance, root, "msg-1", "Run the long job.").join(120)
    real = history_evidence.history_turn_records

    def _without_reply(*args, **kwargs):
        return [{k: v for k, v in record.items() if k != "stored_reply"} for record in real(*args, **kwargs)]

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(history_evidence, "history_turn_records", _without_reply)
        said = _agent_words(instance, root)

    assert said["persona history"] == [FAILED_TURN_NOTICE], said


def test_an_ordinary_reply_row_is_read_as_stored_never_from_the_journal(placed_agent, model):
    """Only the core's boundary row borrows the journal's words: a reply row is its own text."""

    from agent_runtime.persona_chat_history import history_evidence

    instance, root = _new_chat(placed_agent)
    operator_turn(instance, root, "msg-1", "Hello.").join(120)
    real = history_evidence.history_turn_records

    def _other_words(*args, **kwargs):
        return [{**record, "stored_reply": "words the journal holds"} for record in real(*args, **kwargs)]

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(history_evidence, "history_turn_records", _other_words)
        said = _agent_words(instance, root)

    assert said["persona history"] == ["Thanks, noted."], said


def test_the_boundary_rows_kind_is_spelled_as_the_core_spells_it():
    assert curation._FAILED_TURN_DISPLAY_KIND == FAILED_TURN_DISPLAY_KIND
    from agent_runtime.persona_chat_history.vocabulary import PERSONA_FAILED_TURN_KIND

    assert PERSONA_FAILED_TURN_KIND == FAILED_TURN_DISPLAY_KIND


#: What the core writes for a refused turn (``agent.error_surface``): an out-of-usage refusal and its reset.
RATE_LIMIT_SURFACE = {"code": "rate_limit", "provider": "anthropic", "model": "claude-x", "resets_at": 1763337600,
                      "detail": "never travels"}


def test_a_failed_turn_row_carries_its_kind_and_surface(placed_agent, model):
    """RT-FAILED-TURN-ROW-DROPS-ITS-ERROR-SURFACE: seen 2026-11-16, an out-of-usage turn read "Your request was not
    processed" after a reload — the projection dropped the boundary row's kind and ``error_surface``. Both now
    ride the persona history row and the operator conversation message. KILLING MUTATIONS: return before the stamp
    in ``_carry_failed_turn`` -> no kind, red; drop the ``_failed_turn_shape`` rule -> the conversation reads
    ``reply``, red. A field the surface does not list (``detail``) never travels."""
    import json
    import sqlite3

    from hermes_state import SessionDB
    from agent_runtime.persona_chat_history import history_evidence
    from agent_runtime.persona_chat_history.vocabulary import PERSONA_FAILED_TURN_KIND

    instance, root = _new_chat(placed_agent)
    model.reply = lambda body: (CUT_TOOL_CALL, "length")
    operator_turn(instance, root, "msg-1", "Run the long job.").join(120)
    with sqlite3.connect(SessionDB().db_path) as db:
        db.execute("UPDATE messages SET display_metadata = ? WHERE session_id = ? AND display_kind = ?",
                   (json.dumps({"error_surface": RATE_LIMIT_SURFACE}), root, FAILED_TURN_DISPLAY_KIND))
    real = history_evidence.history_turn_records

    def _without_reply(*args, **kwargs):
        return [{k: v for k, v in record.items() if k != "stored_reply"} for record in real(*args, **kwargs)]

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(history_evidence, "history_turn_records", _without_reply)
        history = operator_call("read", operator_params(instance, root, None, persona=PERSONA,
                                                        workspace=WORKSPACE))["result"]
        conversation = _conversation_contract(
            channel_id="channel-1", persona_id=PERSONA, persona_instance_id=instance, session_id=root, goal_id=None,
            title="Chat", state="idle", history=history, trace=None)
    surface = {"code": "rate_limit", "provider": "anthropic", "model": "claude-x", "resets_at": 1763337600.0}
    [row] = [m for m in history["messages"] if str(m["role"]) == "agent"]
    assert (row["kind"], row["error_surface"], row["text"]) == (PERSONA_FAILED_TURN_KIND, surface, FAILED_TURN_NOTICE)
    [message] = [m for m in conversation["messages"] if str(m["role"]) == "agent"]
    assert (message["kind"], message["error_surface"]) == (PERSONA_FAILED_TURN_KIND, surface)


def test_the_failed_turn_row_eternia_mirrors_is_the_runtimes():
    """The producer of Eternia's mirror (``tool/test_quality/hermes_mirrors.json``): the kind and the surface
    fields Eternia's decoder reads. Mutation: add a field to ``FAILED_TURN_SURFACE_FIELDS`` -> red."""
    import json
    from pathlib import Path

    from agent_runtime.persona_chat_history.vocabulary import FAILED_TURN_SURFACE_FIELDS, PERSONA_FAILED_TURN_KIND

    fixture = Path(__file__).resolve().parents[1] / "fixtures" / "failed_turn_row_v1.json"
    assert json.loads(fixture.read_text(encoding="utf-8")) == {
        "kind": PERSONA_FAILED_TURN_KIND, "error_surface_fields": list(FAILED_TURN_SURFACE_FIELDS)}


#: What a provider out of usage answers every chat call with (the Eternia QA fixture's ``[[qa:error 429 …]]``).
USAGE_LIMIT_429 = (429, {"error": {"message": "You have reached your usage limit", "type": "rate_limit_error",
                                   "code": "rate_limit_exceeded"}})


def _agent_row(instance: str, root: str) -> dict:
    history = operator_call("read", operator_params(instance, root, None, persona=PERSONA,
                                                    workspace=WORKSPACE))["result"]
    [row] = [m for m in history["messages"] if str(m["role"]) == "agent"]
    return row


def test_a_refused_turns_resend_keeps_its_refusal(placed_agent, model):
    """RT-FAILED-TURN-ROW-LOSES-ITS-SURFACE-ONCE-THE-TURN-SETTLES, reproduced whole: a usage-limit refusal, then
    the same id sent again. The resend's reply recovery took the core's boundary row for the turn's reply and
    walked the journal ``provider_refused`` -> ``projected`` with "Your request was not processed…" as its
    ``stored_reply``; the resend was answered that sentence, and the stored chat's row read as that reply with no
    kind and no ``error_surface``. Now the boundary row is no reply: the resend gets the turn's refusal and the
    row keeps its kind and surface. KILLING MUTATION: ``_is_failed_turn_boundary`` returns ``False`` -> red."""
    from agent_runtime.mission_chat_turns import mission_chat_turn_record
    from agent_runtime.persona_chat_history.vocabulary import PERSONA_FAILED_TURN_KIND

    instance, root = _new_chat(placed_agent)
    model.refuse = USAGE_LIMIT_429
    operator_turn(instance, root, "msg-1", "Hi.").join(150)
    _code, resend = operator_turn(instance, root, "msg-1", "Hi.").join(150)

    assert (resend.get("provider_refused"), resend.get("journal_state")) == (True, "provider_refused"), resend
    record = mission_chat_turn_record(session_id=root, client_message_id="msg-1")
    assert (record["state"], record.get("stored_reply")) == ("provider_refused", None), record
    row = _agent_row(instance, root)
    assert (row.get("kind"), (row.get("error_surface") or {}).get("code")) == (PERSONA_FAILED_TURN_KIND,
                                                                               "rate_limit"), row


def test_a_settled_boundary_sentence_keeps_the_rows_kind(placed_agent, model):
    """A journal settled before the fix holds the boundary sentence as the refused turn's ``stored_reply``: that
    is no reply of the turn's own, so the row keeps its kind and surface. KILLING MUTATION: drop the
    boundary-sentence check in ``_failed_turn_reply`` -> the row reads as a plain reply, red."""
    from agent_runtime.persona_chat_history import history_evidence
    from agent_runtime.persona_chat_history.vocabulary import PERSONA_FAILED_TURN_KIND

    instance, root = _new_chat(placed_agent)
    model.refuse = USAGE_LIMIT_429
    operator_turn(instance, root, "msg-1", "Hi.").join(150)
    real = history_evidence.history_turn_records

    def _settled_as_the_boundary(*args, **kwargs):
        return [{**record, "state": "projected", "stored_reply": FAILED_TURN_NOTICE}
                for record in real(*args, **kwargs)]

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(history_evidence, "history_turn_records", _settled_as_the_boundary)
        row = _agent_row(instance, root)

    assert (row.get("kind"), (row.get("error_surface") or {}).get("code"), row["text"]) == (
        PERSONA_FAILED_TURN_KIND, "rate_limit", FAILED_TURN_NOTICE), row
