"""h-turn-wait: an accepted turn never waits on ANOTHER chat root's prewarm.

Live 2026-10-06 20:23:58 (serve 5c0f130723): turn 1 on the Neko root logged
``send_prep_receipt total_ms=18549 largest=agent_ready`` while the boot prewarm of the
dev-agent root ran 20:23:54 -> 20:24:16. That prewarm sat in MCP admission for the
persona's ``dart`` server (``connect_timeout_seconds: 20``) INSIDE
``AgentRunExecution.scopes`` -- holding ``_WORKDIR_LOCK`` -- and the turn's
``ProfileAgentRunner.run`` blocked on that lock until the admission timed out and the
construction finished (the turn's ``chat_turn_effort`` 0.9 s after the prewarm's).

Both stand-down reads in ``prewarm_chat_actor`` sit before the scope stack, so a turn
accepted after them was invisible. The prewarm now yields INSIDE the lock: at each phase
boundary and while it waits on MCP admission.

Killing mutation (recorded in the CHANGE commit): ``prewarm_yield`` left unset on the
prewarm's request -> the turn waits out the whole slow admission.
"""

from __future__ import annotations

import threading
import time

import pytest

from tests._downstream.split_package_source import patch_where_bound
from tests.agent_runtime.test_persona_chat_actor_prewarm import (  # noqa: F401 - fixture
    _Agent,
    _request,
    stub_runtime,
)

from agent_runtime import persona_chat_actor_prewarm as prewarm_module
from agent_runtime import persona_chat_continuity, turn_activity
from agent_runtime.mcp_admission import registration
from agent_runtime.mcp_admission.outcomes import McpAdmission
from agent_runtime.persona_chat_actor_prewarm import OUTCOME_SKIPPED_TURN_ACTIVE, prewarm_chat_actor
from agent_runtime.persona_chat_continuity import PersonaChatRuntimeRegistry
from agent_runtime.profile_runner import ProfileAgentRunner

#: The slow admission the prewarm sits in (live: 20 s). Long enough that a turn waiting it
#: out reads far past the budget below.
SLOW_ADMISSION_S = 4.0
#: The turn-cost guard's absolute warm bound (``WARM_ANCHOR_TO_REQUEST_SENT_MS``): a turn on
#: another root, anchored while the prewarm holds the run lock, gets its agent inside it.
TURN_BUDGET_MS = 600


@pytest.fixture
def slow_prewarm(stub_runtime, monkeypatch):  # noqa: F811
    """A prewarm of ``root_b`` whose MCP admission blocks until released (or 4 s)."""

    registry = PersonaChatRuntimeRegistry()
    patch_where_bound(monkeypatch, persona_chat_continuity, "persona_chat_runtime_registry", lambda: registry)
    runner = ProfileAgentRunner(agent_factory=_Agent)
    in_admission, release = threading.Event(), threading.Event()

    def registrar(servers):
        in_admission.set()
        release.wait(SLOW_ADMISSION_S)
        return []

    monkeypatch.setattr(registration, "_default_registrar", registrar)
    monkeypatch.setattr(registration, "_mcp_client_enabled", lambda: True)
    admission = McpAdmission(
        lane="mission_chat", role="dev", permission_mode="full", enabled=True,
        server_names=("dart",), server_configs={"dart": {"command": "dart.exe"}},
    )
    monkeypatch.setattr(prewarm_module, "_prepare", lambda root, instance: (
        _request(prewarm_only=True, registry=registry, root_chat_session_id=root, session_id=root,
                 mcp_admission=admission),
        runner,
    ))
    outcome: dict[str, str] = {}
    thread = threading.Thread(target=lambda: outcome.update(root_b=prewarm_chat_actor("root_b")), daemon=True)
    yield registry, runner, in_admission, thread, outcome
    release.set()
    thread.join(10)


@pytest.mark.timeout(60)
def test_a_turn_on_another_root_does_not_wait_on_a_prewarm_inside_the_run_lock(slow_prewarm):
    registry, runner, in_admission, prewarm, outcome = slow_prewarm
    # A warm turn first, as the live serve had run: the budget is for the wait, not a cold
    # process's first-run imports.
    runner.run(_request(prewarm_only=False, registry=registry, root_chat_session_id="root_warm",
                        session_id="root_warm"))
    constructed = _Agent.constructed
    prewarm.start()
    assert in_admission.wait(10), "the prewarm never reached MCP admission"

    with turn_activity.admitted_turn():  # the turn's anchor, after both stand-down reads
        started = time.monotonic()
        result = runner.run(_request(prewarm_only=False, registry=registry,
                                     root_chat_session_id="root_a", session_id="root_a"))
        waited_ms = int((time.monotonic() - started) * 1000)
    prewarm.join(SLOW_ADMISSION_S + 5)
    print(f"h-turn-wait: the root_a turn waited {waited_ms} ms on root_b's prewarm")

    assert result.final_response == "ok"
    assert waited_ms <= TURN_BUDGET_MS, (
        f"the root_a turn waited {waited_ms} ms on root_b's prewarm (budget {TURN_BUDGET_MS})"
    )
    assert outcome.get("root_b") == OUTCOME_SKIPPED_TURN_ACTIVE
    assert _Agent.constructed == constructed + 1, "only the turn built an actor; the yielded prewarm built none"


@pytest.mark.timeout(60)
def test_with_no_turn_the_slow_prewarm_runs_to_the_end(slow_prewarm):
    """Positive control: nothing to yield to, so the prewarm waits its admission out and warms."""

    _registry, _runner, in_admission, prewarm, outcome = slow_prewarm
    started = time.monotonic()
    prewarm.start()
    assert in_admission.wait(10)
    prewarm.join(SLOW_ADMISSION_S + 10)
    assert outcome.get("root_b") == "warmed"
    assert time.monotonic() - started >= SLOW_ADMISSION_S - 0.5
