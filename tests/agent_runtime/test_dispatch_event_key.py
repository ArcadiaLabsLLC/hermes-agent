"""The serve drain's per-event identity names the WHOLE id, never a 40-char cut of it.

``dispatch_delivery.accounting._event_key`` is the one expression the forged turn's
``client_message_id`` and the telemetry rows are derived from. It used to keep
``str(id)[:40]``, so two events whose ids shared a 40-char prefix were one replay and the
second turn was deduplicated away (``mcp_job_finished`` hit it; lane h-wakecap 2026-10-03).
"""

from __future__ import annotations

from agent_runtime.dispatch_delivery import _event_key


def test_ids_sharing_a_forty_char_prefix_are_two_keys():
    shared = "mcp_job:launcher_qa:qb-20261004T141100-build-"
    assert len(shared) >= 40, "the fixture must share the whole 40-char prefix"
    first = {"type": "mcp_job_finished", "session_id": shared + "aaaaaa"}
    second = {"type": "mcp_job_finished", "session_id": shared + "bbbbbb"}

    assert _event_key(first) != _event_key(second)
    assert _event_key(first) == _event_key(dict(first)), "the key must be stable per event"


def test_a_long_id_keeps_the_key_bounded_and_readable():
    key = _event_key({"type": "completion", "delegation_id": "d" * 200})
    kind, _, marker = key.partition(":")

    assert kind == "completion"
    assert len(marker) == 40
    assert marker.startswith("d" * 16 + "~")


def test_an_id_that_fits_is_kept_verbatim():
    # Positive control: the keys every pending event already carries do not move.
    assert _event_key({"session_id": "proc_5e591b91a09c"}) == "completion:proc_5e591b91a09c"
    exact = "x" * 40
    assert _event_key({"type": "t", "delegation_id": exact}) == f"t:{exact}"
