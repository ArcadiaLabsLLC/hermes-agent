"""The first message in a new chat says what it waited on (lane w1123q-replytimings, 2026-11-23).

Owner 2026-11-23: "on the hermes reply it takes very long too ... i need every part counted". On the
owner's serve a Home turn's agent wait (``agent_ready`` 7.6 s after ``write_ahead``) was the chat's
prewarm holding the chat's run lock, and neither the turn nor the prewarm's stand-down line said so:
the prewarm's ``persona_chat_actor_prewarm_yielded`` named only its phase, the turn nothing at all.

Two receipts, read here through the real path (the prewarm's own ``prewarm_chat_actor`` in a thread,
the turn's own ``ProfileAgentRunner.run`` on the same root):

* ``turn_root_lock_wait ... stage=acquire waited_ms=<n> held_by=prewarm`` on the turn;
* ``persona_chat_actor_prewarm_yielded ... held_ms=<n> prepare_ms=<n> runtime_resolve_ms=<n> ...`` on the prewarm.

Killing mutations (recorded in the CHANGE commit): ``root_run_lock`` not recording the holder kind
(``held_by`` stays ``None``) -> the turn's receipt reads ``held_by=-``; ``OperatorTurn.yield_point``
raising ``PrewarmYielded`` without the run's timing -> the yield line reads ``runtime_resolve_ms=absent``.
"""

from __future__ import annotations

import logging
import re
import threading

import pytest

from tests.agent_runtime.test_prewarm_yields_to_turn_downstream import SLOW_ADMISSION_S, slow_prewarm  # noqa: F401 (fixture)
from tests.agent_runtime.test_persona_chat_actor_prewarm import _request, stub_runtime  # noqa: F401 (fixture)

from agent_runtime import turn_activity
from agent_runtime.profile_runner.workdir import last_root_lock_wait, root_run_lock


def _fields(message: str) -> dict[str, str]:
    return dict(re.findall(r"(\w+)=(\S+)", message))


@pytest.mark.timeout(60)
def test_a_turn_on_the_prewarms_own_chat_names_the_prewarm_it_waited_on(slow_prewarm, caplog):
    registry, runner, in_admission, prewarm, outcome = slow_prewarm
    caplog.set_level(logging.INFO)
    prewarm.start()
    assert in_admission.wait(10), "the prewarm never reached MCP admission"

    with turn_activity.admitted_turn():
        result = runner.run(_request(prewarm_only=False, registry=registry, root_chat_session_id="root_b",
                                     session_id="root_b", client_message_id="turn-b-1"))
    prewarm.join(SLOW_ADMISSION_S + 5)

    assert result.final_response == "ok"
    waits = [_fields(r.getMessage()) for r in caplog.records if r.getMessage().startswith("turn_root_lock_wait")]
    assert waits, "the turn that waited on the chat's prewarm left no turn_root_lock_wait receipt"
    first = waits[0]
    assert first["root"] == "root_b" and first["turn"] == "turn-b-1" and first["stage"] == "acquire", first
    assert first["held_by"] == "prewarm", first
    assert int(first["waited_ms"]) >= 5, first

    yields = [_fields(r.getMessage()) for r in caplog.records
              if r.getMessage().startswith("persona_chat_actor_prewarm_yielded")]
    assert yields, outcome
    assert int(yields[0]["held_ms"]) >= int(yields[0]["prepare_ms"]) >= 0, yields[0]
    assert yields[0]["runtime_resolve_ms"] != "absent", yields[0]


def test_a_free_lock_reads_no_wait_and_no_holder():
    with root_run_lock("root_free", holder="turn"):
        waited_ms, held_by = last_root_lock_wait()
    assert held_by is None and waited_ms < 50


def test_a_wait_names_the_kind_that_held_the_lock():
    held, release = threading.Event(), threading.Event()

    def hold():
        with root_run_lock("root_held", holder="prewarm"):
            held.set()
            release.wait(5)

    thread = threading.Thread(target=hold, daemon=True)
    thread.start()
    assert held.wait(5)
    threading.Timer(0.2, release.set).start()
    with root_run_lock("root_held", holder="turn"):
        waited_ms, held_by = last_root_lock_wait()
    thread.join(5)
    assert held_by == "prewarm"
    assert waited_ms >= 150
