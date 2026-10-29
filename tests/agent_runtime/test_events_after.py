"""``runtime.events.after`` — events after a durable cursor (row RT-LAUNCHER-EVENT-CURSOR).

Plan ``docs/agent-runtime-harness/planned/launcher-event-cursor-2026-10-28.md`` §6. Autouse
conftest fixtures isolate the runtime root.
"""

from __future__ import annotations

from hermes_time import now

from agent_runtime import event_cursor, event_rotation
from agent_runtime.events import EventLog
from agent_runtime.models import Event
from agent_runtime.serve_rpc import handle_request

_CAP_ENV = "HERMES_EVENT_LOG_ROTATION_CAP_BYTES"


def _append(event_type: str, **payload) -> None:
    EventLog().append(Event(ts=now(), type=event_type, task_id=None, run_id=None, persona_id=None, payload=payload))


def _episode(n: int, **extra) -> None:
    _append("lens.episode.changed", monitor_id="status", episode_id=f"{n:064x}", state="active",
            rule_id="cpu_hot", ordinal=n, **extra)


def _turn_ended() -> None:
    _append("persona_chat.turn_ended", persona_instance_id="personainst_a", root_chat_session_id="root_a",
            client_message_id="cm_1", turn_id="turn_1", state="completed")


def _receipt() -> None:
    _append("lens.receipt.changed", monitor_id="status", episode_id="e" * 64, outcome="forged")


def _call(**params) -> dict:
    reply = handle_request({"jsonrpc": "2.0", "id": 1, "method": "runtime.events.after", "params": params})
    assert "result" in reply, reply
    return reply["result"]


def _refusal_reason(**params) -> str:
    reply = handle_request({"jsonrpc": "2.0", "id": 1, "method": "runtime.events.after", "params": params})
    return reply["error"]["data"]["reason"]


def test_no_cursor_starts_at_the_tail_and_replays_no_history():
    _episode(1)
    page = _call()
    assert page["events"] == [] and page["at_tail"] is True
    assert page["next_cursor"] == f"{event_cursor.journal_id()}:{event_rotation.log_end_offset()}"


def test_a_span_produced_while_no_launcher_ran_is_returned_once_in_order():
    start = _call()["next_cursor"]
    _episode(1)
    _turn_ended()
    _receipt()

    first = _call(cursor=start)
    assert [event["type"] for event in first["events"]] == [
        "lens.episode.changed", "persona_chat.turn_ended", "lens.receipt.changed"]
    assert first["at_tail"] is True
    ids = [event["event_id"] for event in first["events"]]
    assert len(set(ids)) == 3 and ids[-1] == first["next_cursor"]

    assert _call(cursor=first["next_cursor"])["events"] == []
    _episode(2)  # positive control: a later event is returned from the same cursor
    again = _call(cursor=first["next_cursor"])
    assert [event["payload"]["ordinal"] for event in again["events"]] == [2]


def test_kinds_outside_the_allow_list_never_leave_and_cannot_be_asked_for():
    start = _call()["next_cursor"]
    _append("office.surface.created", workspace_id="ws_1")
    _append("persona_chat.send_refused", root_chat_session_id="root_a", client_message_id="cm_1",
            error_kind="busy")
    _episode(1)

    assert [event["type"] for event in _call(cursor=start)["events"]] == ["lens.episode.changed"]
    assert _refusal_reason(cursor=start, types=["office.surface.created"]) == "unknown_event_type"
    narrowed = _call(cursor=start, types=["persona_chat.turn_ended"])
    assert narrowed["events"] == [] and narrowed["at_tail"] is True


def test_a_payload_key_the_contract_does_not_declare_is_projected_away():
    start = _call()["next_cursor"]
    _episode(1, operator_note="private words")

    [event] = _call(cursor=start)["events"]
    assert event["payload"] == {"monitor_id": "status", "episode_id": f"{1:064x}", "state": "active",
                                "rule_id": "cpu_hot", "ordinal": 1}


def test_a_page_of_no_matches_still_moves_the_cursor(monkeypatch):
    monkeypatch.setattr(event_cursor, "SCAN_BUDGET_BYTES", 2_000)
    start = _call()["next_cursor"]
    for n in range(40):
        _append("office.surface.created", workspace_id=f"ws_{n}")
    _episode(1)

    cursor, pages, found = start, 0, []
    while pages < 50:
        page = _call(cursor=cursor)
        pages += 1
        found += page["events"]
        assert page["next_cursor"] != cursor or page["at_tail"]
        cursor = page["next_cursor"]
        if page["at_tail"]:
            break
    assert pages > 1
    assert [event["type"] for event in found] == ["lens.episode.changed"]


def test_a_cursor_below_a_removed_slice_is_refused_with_the_floor(monkeypatch):
    monkeypatch.setenv(_CAP_ENV, "1")  # rotate on every append after the first
    start = _call()["next_cursor"]
    for n in range(3):
        _episode(n)
    sealed = [sl for sl in event_rotation.slices() if not sl.live]
    sealed[0].path.unlink()
    floor = event_rotation.resume_floor_offset()
    assert floor and floor > int(start.rsplit(":", 1)[1])

    page = _call(cursor=start)
    assert page["events"] == []
    assert page["refused"]["reason"] == "journal_truncated"
    assert page["refused"]["floor_cursor"] == f"{event_cursor.journal_id()}:{floor}"
    assert page["refused"]["lost_bytes"] == floor - int(start.rsplit(":", 1)[1])
    assert page["next_cursor"] == start
    assert _call(cursor=page["refused"]["floor_cursor"])["events"]  # the floor itself reads


def test_a_cursor_from_another_journal_reads_nothing_from_this_one():
    _episode(1)
    _episode(2)
    page = _call(cursor="0123456789abcdef0123456789abcdef:0")
    assert page["events"] == []
    assert page["refused"]["reason"] == "journal_mismatch"
    assert page["refused"]["tail_cursor"] == f"{event_cursor.journal_id()}:{event_rotation.log_end_offset()}"


def test_a_cursor_past_the_tail_is_refused_and_bad_params_are_named():
    journal = event_cursor.journal_id()
    page = _call(cursor=f"{journal}:{event_rotation.log_end_offset() + 10}")
    assert page["refused"]["reason"] == "cursor_ahead_of_journal"
    assert _refusal_reason(cursor="nope") == "cursor_invalid"
    assert _refusal_reason(limit=0) == "limit_invalid"
    assert _refusal_reason(limit=True) == "limit_invalid"
    assert _refusal_reason(types=[]) == "types_invalid"


def test_the_journal_id_is_minted_once():
    assert event_cursor.journal_id() == event_cursor.journal_id()
