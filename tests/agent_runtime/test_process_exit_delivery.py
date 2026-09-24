"""A background ``terminal`` exit becomes a real delivery turn in the spawning thread.

Owner ruling 2026-09-24: completion is decided ONCE at spawn (upstream's ``notify``
parameter, defaulted on by the eternia-harness ``tool_request`` middleware); the late
``process notify`` request and its store are gone. This file pins the join: the event
the REAL producer (``ProcessRegistry._move_to_finished`` on a ``notify_on_complete``
session) publishes is consumed by the serve drain (``drain_background_completions``)
and forged into a turn in the owning thread — or DROPPED, loudly, when the persona
instance that owned that thread is gone. Never hand-rolled: a producer test and a
consumer test can both pass while the seam between them is broken.
"""

from __future__ import annotations

import logging
import time

import pytest

from agent_runtime import dispatch_delivery
from tools.process_registry import ProcessRegistry, ProcessSession

ROOT = "persona_chat_personainst_chara_a2_7b31d0e4_a238c5f9c4c2"
INSTANCE = "personainst_chara_a2_7b31d0e4"
PERSONA = "chara_a2"


@pytest.fixture()
def owners(monkeypatch):
    table = {ROOT: (PERSONA, INSTANCE)}
    monkeypatch.setattr(dispatch_delivery, "_sender_persona", lambda session_id: table.get(session_id))
    return table


def _exited_spawn_event(registry: ProcessRegistry) -> dict:
    session = ProcessSession(
        id="proc_rows",
        command="hermes harness characters rows --draft d1 --json",
        session_key=ROOT,
        started_at=time.time(),
        output_buffer="row 10/10 ok\n",
        notify_on_complete=True,
    )
    registry._running[session.id] = session
    session.exited = True
    session.exit_code = 0
    registry._move_to_finished(session)
    return registry.completion_queue.get_nowait()


def _drain_with(registry, monkeypatch, event, *, idle=True, forge=None):
    import tools.process_registry as registry_mod

    monkeypatch.setattr(registry_mod, "process_registry", registry)
    monkeypatch.setattr(dispatch_delivery, "_sender_is_idle", lambda root: idle)
    registry.completion_queue.put(event)
    return dispatch_delivery.drain_background_completions(forge=forge)


def test_the_exit_is_forged_into_a_turn_in_the_spawning_thread(owners, monkeypatch):
    registry = ProcessRegistry()
    forged: list[dict] = []

    def _forge(**kwargs):
        forged.append(kwargs)
        return True, {"ok": True, "reply": "thanks"}

    tally = _drain_with(registry, monkeypatch, _exited_spawn_event(registry), forge=_forge)

    assert tally["delivered"] == 1
    assert [call["root_session_id"] for call in forged] == [ROOT]
    assert forged[0]["persona_instance_id"] == INSTANCE
    assert forged[0]["persona_id"] == PERSONA
    assert "rows --draft d1" in forged[0]["message"]


def test_a_retired_instance_drops_the_completion_loudly_instead_of_requeueing(
    owners, monkeypatch, caplog
):
    registry = ProcessRegistry()
    event = _exited_spawn_event(registry)
    owners.clear()  # the instance that spawned it is gone

    with caplog.at_level(logging.WARNING, logger=dispatch_delivery.logger.name):
        tally = _drain_with(
            registry, monkeypatch, event,
            forge=lambda **kwargs: pytest.fail("an orphaned completion must not be forged"),
        )

    assert tally["dropped"] == 1
    assert registry.completion_queue.qsize() == 0
    assert any("no persona instance owns chat root" in r.getMessage() for r in caplog.records)


def test_an_unreadable_owner_lookup_is_not_proof_of_absence(owners, monkeypatch):
    """Positive control for the drop: same event, the lookup RAISES -> kept on the queue."""

    registry = ProcessRegistry()
    event = _exited_spawn_event(registry)

    def _raises(session_id):
        raise OSError("store unreadable")

    monkeypatch.setattr(dispatch_delivery, "_sender_persona", _raises)
    tally = _drain_with(
        registry, monkeypatch, event,
        forge=lambda **kwargs: pytest.fail("an unproven owner must not be forged"),
    )

    assert tally["dropped"] == 0
    assert registry.completion_queue.qsize() == 1


def test_a_busy_thread_requeues_rather_than_forging_a_second_turn(owners, monkeypatch):
    registry = ProcessRegistry()
    tally = _drain_with(
        registry, monkeypatch, _exited_spawn_event(registry), idle=False,
        forge=lambda **kwargs: pytest.fail("a busy thread must not be forged into"),
    )

    assert tally["delivered"] == 0
    assert tally["requeued"] == 1
    assert registry.completion_queue.qsize() == 1
