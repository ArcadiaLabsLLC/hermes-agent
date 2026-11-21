"""RT-DELIVERY-BLOCK-SAYS-A-MESSAGE-NEVER-RAN-AS-A-TYPED-FIELD.

Read in code 2026-11-20 (Eternia lane mc-delivered-result): a message to a
teammate that stayed busy for the whole wait settles ``state=error`` with the
words "Not delivered: … never ran", and its ``error_kind`` (``chat_busy``) was
dropped before the delivery — so Eternia could tell "never ran" from a real
failure only by matching those words.

Pinned through the real chain, with only the dispatched turn's door and the
forge's chat turn faked: the supervisor (``local._run_dispatch``) records the
turn's typed refusal on the row, the drain (``drain_once``) forges the delivery with
``state="not_delivered"``, the chat handler's marker carries it, and the
history projection's delivery block says it. A real failure (positive control)
still delivers ``error``.

Named sabotage (each red recorded in the landing commit):

* ``outcome.payload_completion``: drop the ``error_kind`` field → the first test
  red (the block says ``error``).
* ``vocabulary.delivery_outcome_state``: return the row's state unchanged →
  the first test red.
* ``vocabulary.never_ran_error_kinds``: an empty set → the first test red; the
  positive control stays green either way, so neither sabotage is masked by an
  ``error`` that every row would say.
"""

from __future__ import annotations

import json

import pytest

from agent_runtime import dispatch_delivery
from agent_runtime.dispatch_delivery import DrainPolicy, drain_once
from agent_runtime.dispatch_delivery.vocabulary import (
    DELIVERY_STATE_NOT_DELIVERED,
    delivery_outcome_state,
)
from agent_runtime.dispatch_store import STATE_ERROR, get_dispatch, mint_dispatch_id, record_dispatch
from agent_runtime.operator_channels import _conversation_history_message
from agent_runtime.persona_chat_history import PERSONA_HARNESS_DELIVERY_KIND
from agent_runtime.relay_policy import parse_harness_delivery_marker
from hermes_cli.harness_parts.persona import chat_history_writes
from tests.agent_runtime.dispatch_turn_stub import StubTurn, bind_stub_turn
from tools import agent_chat_dispatch
from tools.agent_chat_dispatch import local

SENDER_ROOT = "persona_chat_personainst_neko_aaaaaaaaaaaa"
TARGET_ROOT = "persona_chat_personainst_dev_agent_8b319ebf_564c80cf8806"


@pytest.fixture
def store_home(tmp_path, monkeypatch):
    home = tmp_path / "bg-home"
    home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setenv("HERMES_HEAD_HOME", str(home))
    monkeypatch.setattr(local, "BUSY_TARGET_POLL_SECONDS", 0.0)
    monkeypatch.setattr(local, "chat_root_is_busy", lambda root, probe_owner: True)
    return home


def _refused(error_kind: str, error: str) -> StubTurn:
    return StubTurn(
        {
            "ok": False,
            "capability_id": "mission.chat.message",
            "error_kind": error_kind,
            "root_chat_session_id": TARGET_ROOT,
            "session_id": TARGET_ROOT,
            "error": error,
        },
        exit_code=2,
    )


class _Forge:
    def __init__(self):
        self.calls: list[dict] = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        return True, {"ok": True}


def _delivered_block(monkeypatch, turn: StubTurn) -> tuple[dict, dict]:
    """Run one dispatch whose native turn answers as *turn*, deliver it, and project the
    delivered row the way the history read does. Returns (row, delivery block)."""

    bind_stub_turn(monkeypatch, turn)
    dispatch_id = mint_dispatch_id()
    record_dispatch(
        dispatch_id=dispatch_id,
        sender_session_id=SENDER_ROOT,
        target_persona="@personainst_dev_agent_8b319ebf",
        ask="STOP order: commit what you have and stop.",
    )
    agent_chat_dispatch._run_dispatch(
        dispatch_id, {"persona_id": "dev", "message": "STOP order", "max_seconds": 0.05}
    )

    forge = _Forge()
    tally = drain_once(
        policy=DrainPolicy(
            sender_persona=lambda root: ("neko_supervisor", "personainst_neko") if root == SENDER_ROOT else None,
            sender_is_idle=lambda root: True,
        ),
        forge=forge,
    )
    assert tally["delivered"] == 1, tally
    call = forge.calls[0]

    # The forge's provenance -> the chat handler's marker -> the persisted row's fields.
    requested_by = dispatch_delivery.delivery_requested_by(
        call["dispatch_id"],
        notify_operator=call["notify_operator"],
        state=call["state"],
        target_session_id=call["target_session_id"],
        target_name=call["target_name"],
    )

    class _Store:
        def list_all(self):
            return []

    marker = chat_history_writes._resolve_relay_sender_marker(
        requested_by, instance_store=_Store(), relay_chain_in=()
    )
    origin = parse_harness_delivery_marker(marker)
    message = _conversation_history_message(
        {
            "id": "row-1",
            "role": "operator",
            "text": call["message"],
            "timestamp": "2026-11-20T10:00:00+00:00",
            "redaction_status": "safe",
            "kind": PERSONA_HARNESS_DELIVERY_KIND,
            "delivery_dispatch_id": origin.dispatch_id,
            "delivery_notify_operator": origin.notify_operator,
            "delivery_state": origin.state,
        },
        channel_id="chan-1",
        index=0,
        persona_id="neko_supervisor",
        persona_instance_id="personainst_neko",
        display_names={},
    )
    return get_dispatch(dispatch_id), message["delivery"]


def test_a_message_that_never_ran_is_delivered_as_not_delivered(store_home, monkeypatch):
    row, block = _delivered_block(
        monkeypatch, _refused("chat_busy", f"persona chat root is busy: {TARGET_ROOT}")
    )

    # The dispatch row keeps the store's own word; only the delivery says more.
    assert row["state"] == STATE_ERROR
    assert row["result"]["error_kind"] == "chat_busy"
    assert block["state"] == DELIVERY_STATE_NOT_DELIVERED == "not_delivered"


def test_a_real_failure_is_still_delivered_as_an_error(store_home, monkeypatch):
    """Positive control: the same chain, a refusal that is not "never ran"."""

    row, block = _delivered_block(
        monkeypatch, _refused("model_error", "the provider returned 500")
    )

    assert row["state"] == STATE_ERROR
    assert block["state"] == "error"


def test_a_row_written_before_the_kind_was_recorded_keeps_its_error():
    assert delivery_outcome_state({"state": "error", "result": {"error": "Not delivered: …"}}) == "error"
    assert delivery_outcome_state({"state": "completed", "result": {"error_kind": "chat_busy"}}) == "completed"
    assert delivery_outcome_state({"state": "cancelled"}) == "cancelled"
