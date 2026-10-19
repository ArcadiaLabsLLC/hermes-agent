"""Lens L2 — the exit door (plan ``p10-agent-2026-10-19.md`` §5.3).

An Episode the poller opened is owed ONE forged chat turn (``investigate``) or a
notification (``notify``); either way the door writes a RECEIPT, and the receipt
is written before the turn so a second admission never forges a second turn.

No serve is started and no model is called: the turn runs through a fake handler
bound on ``mission_chat_door.bind_mission_chat_turn``; the clock is fixed; the
home is the test's isolated ``HERMES_HOME``.

Gates and their killing mutations (each red was recorded in the stage's commit):

* receipts: a second ``save_receipt`` for one Episode is refused — killed by
  dropping the existing-row check (sqlite then raises IntegrityError, not False);
  ``receipts_today`` counts only the UTC day's capped outcomes — killed by
  adding ``skipped_severity`` to ``CAPPED_OUTCOMES`` or dropping the day's start
  bound (3 == 2 either way);
  ``runtime.lens.receipt`` on an unknown Episode is NOT_FOUND — killed by
  dropping ``RECEIPT_NOT_FOUND`` from ``NOT_FOUND_REFUSALS`` (a conflict frame).
* provenance: the persisted user row types as ``lens_episode:`` — killed by
  removing the Lens branch in ``_resolve_relay_sender_marker`` (marker None);
  the history row reads as Lens, never as the operator — killed by dropping the
  ``_lens_episode_shape`` rule (kind ``operator_message``).
"""

from __future__ import annotations

from datetime import datetime, timedelta, UTC

import pytest

from agent_runtime.lens.store import LensStore, LensStoreError, ReceiptOutcome, StoreRefusal, to_ms

T0 = datetime(2026, 10, 19, 12, tzinfo=UTC)
EPISODE_A = "a" * 64
EPISODE_B = "b" * 64


def _receipt(episode_id: str = EPISODE_A, *, outcome: str = ReceiptOutcome.FORGED.value,
             at: datetime = T0, monitor_id: str = "status") -> dict:
    return {"episode_id": episode_id, "monitor_id": monitor_id, "turn_id": f"lens-episode-{episode_id}",
            "started_ms": to_ms(at), "outcome": outcome, "tool_admission": "full"}


def _rpc(method: str, params: dict) -> dict:
    from agent_runtime import serve_rpc

    return serve_rpc.handle_request({"jsonrpc": "2.0", "id": 1, "method": method, "params": params})


# --- L2.1 receipts ----------------------------------------------------------------


def test_a_receipt_is_written_once_per_episode():
    store = LensStore()

    assert store.save_receipt(_receipt()) is True
    assert store.save_receipt(_receipt(outcome=ReceiptOutcome.NOTIFIED.value)) is False
    assert store.receipt(EPISODE_A)["outcome"] == "forged"


def test_a_forging_receipt_settles_with_what_the_turn_left():
    store = LensStore()
    store.save_receipt(_receipt(outcome=ReceiptOutcome.FORGING.value))

    settled = store.finish_receipt(EPISODE_A, outcome="forged", finished_ms=to_ms(T0) + 5,
                                   session_id="persona_chat_x", files=[{"name": "report.md"}])

    assert (settled["outcome"], settled["session_id"], settled["files"]) == (
        "forged", "persona_chat_x", [{"name": "report.md"}])
    assert settled["artifact_handles"] == []


def test_receipts_today_counts_the_utc_day_and_only_capped_outcomes():
    store = LensStore()
    store.save_receipt(_receipt(EPISODE_A))
    store.save_receipt(_receipt(EPISODE_B, outcome=ReceiptOutcome.SKIPPED_SEVERITY.value))
    store.save_receipt(_receipt("c" * 64, at=T0 - timedelta(days=1)))
    store.save_receipt(_receipt("d" * 64, outcome=ReceiptOutcome.NOTIFIED.value))
    store.save_receipt(_receipt("e" * 64, monitor_id="other"))

    assert store.receipts_today("status", T0) == 2


def test_the_receipt_verbs_are_on_the_method_lane():
    from agent_runtime import serve_rpc
    from agent_runtime.call_authorization import TIER_CONSOLE

    LensStore().save_receipt(_receipt())

    assert _rpc("runtime.lens.receipt", {"episode_id": EPISODE_A})["result"]["outcome"] == "forged"
    listed = _rpc("runtime.lens.receipts", {"monitor_id": "status", "limit": 5})["result"]["receipts"]
    assert [row["episode_id"] for row in listed] == [EPISODE_A]
    assert serve_rpc.method_tier("runtime.lens.receipt") == TIER_CONSOLE
    assert serve_rpc.method_tier("runtime.lens.receipts") == TIER_CONSOLE


def test_an_unknown_receipt_is_not_found_and_a_malformed_id_is_refused():
    from agent_runtime.serve_rpc.protocol import ERR_INVALID_PARAMS, ERR_NOT_FOUND

    LensStore().save_receipt(_receipt())

    missing = _rpc("runtime.lens.receipt", {"episode_id": EPISODE_B})["error"]
    assert (missing["code"], missing["data"]["reason"]) == (ERR_NOT_FOUND, "receipt_not_found")
    bad = _rpc("runtime.lens.receipt", {"episode_id": "../etc"})["error"]
    assert (bad["code"], bad["data"]["reason"]) == (ERR_INVALID_PARAMS, "invalid_digest")


def test_receipts_past_the_budget_are_refused(monkeypatch):
    from agent_runtime.lens import store as store_module

    monkeypatch.setattr(store_module, "MAXIMUM_RECEIPTS", 1)
    store = LensStore()
    store.save_receipt(_receipt())

    with pytest.raises(LensStoreError) as caught:
        store.save_receipt(_receipt(EPISODE_B))
    assert caught.value.code is StoreRefusal.RECEIPTS_FULL


# --- L2.2 provenance --------------------------------------------------------------


def _marker_for(requested_by):
    from hermes_cli.harness_parts.persona import chat_history_writes

    class _Store:
        def list_all(self):
            return []

    return chat_history_writes._resolve_relay_sender_marker(requested_by, instance_store=_Store(), relay_chain_in=())


def test_the_persisted_user_row_types_as_a_lens_episode():
    from agent_runtime.lens.provenance import lens_requested_by, parse_lens_requested_by
    from agent_runtime.relay_policy import parse_harness_delivery_marker, parse_lens_episode_marker,         parse_relay_sender_marker

    requested_by = lens_requested_by(EPISODE_A, "status")
    assert parse_lens_requested_by(requested_by).monitor_id == "status"

    marker = _marker_for(requested_by)

    assert marker == f"lens_episode:{EPISODE_A}"
    assert parse_lens_episode_marker(marker).episode_id == EPISODE_A
    # The vocabularies never answer for each other.
    assert parse_harness_delivery_marker(marker) is None and parse_relay_sender_marker(marker) is None
    assert parse_lens_episode_marker("harness_delivery:d:0:completed") is None
    for value in (None, "", "operator", "lens-episode", "lens-episode:", "agent:"):
        assert _marker_for(value) is None


def test_the_history_row_reads_as_lens_not_as_the_operator():
    from agent_runtime.operator_channels import _conversation_history_message
    from agent_runtime.persona_chat_history import PERSONA_LENS_EPISODE_KIND
    from agent_runtime.persona_chat_history.history_rows import _safe_recent_messages
    from agent_runtime.relay_policy import build_lens_episode_marker
    from tests.agent_runtime.test_persona_chat_history_curation import FakeSessionDB

    db = FakeSessionDB([{"id": "m1", "role": "user", "content": "Lens: status · cpu_hot · #1",
                         "finish_reason": build_lens_episode_marker(EPISODE_A),
                         "platform_message_id": f"lens-episode-{EPISODE_A}", "created_at": "2026-10-19T12:00:00Z"}])
    rows, status, _unread = _safe_recent_messages(db, session_id="persona_chat_personainst_qa_abc123def456")
    [row] = [row for row in rows if row.get("kind") == PERSONA_LENS_EPISODE_KIND]
    assert (status, row["lens_episode_id"]) == ("safe", EPISODE_A)
    assert "relay_sender_persona_id" not in row and "delivery_dispatch_id" not in row

    message = _conversation_history_message(row, channel_id="chan-1", index=0, persona_id="qa",
                                            persona_instance_id="personainst_qa", display_names={})
    assert (message["kind"], message["actor_persona_id"], message["actor_instance_id"]) == (
        PERSONA_LENS_EPISODE_KIND, "lens", None)
    assert message["role"] == "operator"
    assert message["lens"] == {"episode_id": EPISODE_A}

