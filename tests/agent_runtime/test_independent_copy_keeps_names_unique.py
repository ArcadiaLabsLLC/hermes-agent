"""An independent copy never takes a name an agent already has.

Row ``RT-INDEPENDENT-AGENT-COPY-HAS-ONE-ACTION`` (w1118a-hcopy, seen 2026-11-19
in a lane namespace on hermes 0faac6b423): Eternia's "Create independent copy"
reached ``runtime.persona.instance.create`` with ``independent_agent: true`` (now ``runtime.agent.create``) and
the name "<source> copy". Two copies of Base made two agents both called "Base
Agent copy", while ``runtime.agent.create`` refuses a taken name
``agent_name_taken`` (review w1118a.41 D8). The copy door now keeps the same
rule, under the same lock, and a same-key retry still answers its own agent.
"""

from __future__ import annotations

from agent_runtime import serve_rpc
from tests.agent_runtime.test_serve_rpc_agent_create import (
    _instances,
    qa_persona,  # noqa: F401 — the fixture, re-exported for this file
)


def _copy(key: str, name: str) -> dict:
    return serve_rpc.handle_request({
        "jsonrpc": "2.0", "id": key, "method": "runtime.agent.create",
        "params": {
            "persona_id": "qa",
            "display_name": name,
            "idempotency_key": key,
        },
    })


def _personas() -> set[str]:
    from agent_runtime.store import AgentStore

    return {p.id for p in AgentStore().list_all()}


def test_a_second_copy_with_a_taken_name_is_refused_and_writes_nothing(qa_persona):
    # Mutation: pass ``refuse_taken_name=False`` from
    # ``lifecycle_commands._cmd_persona_instance_create`` -> red: the second
    # copy answers a result and a second "QA Agent copy" persona is minted.
    first = _copy("copy-1", "QA Agent copy")
    assert "result" in first, first
    before = (_personas(), set(_instances()))

    second = _copy("copy-2", "qa agent   COPY")

    assert "result" not in second, second
    assert "agent_name_taken" in str(second["error"])
    assert (_personas(), set(_instances())) == before


def test_a_copy_named_like_its_source_is_refused(qa_persona):
    # Same mutation -> red: a copy called "QA Agent" is minted beside the source.
    before = (_personas(), set(_instances()))

    reply = _copy("copy-src", "QA Agent")

    assert "agent_name_taken" in str(reply["error"])
    assert (_personas(), set(_instances())) == before


def test_a_same_key_retry_answers_its_own_copy(qa_persona):
    # Mutation: move the ``name_is_taken`` check in ``create_independent_agent``
    # above the ``existing`` lookup -> red: the retry meets its own agent's
    # name and is refused.
    first = _copy("copy-once", "Scout")["result"]

    again = _copy("copy-once", "Scout")

    assert "result" in again, again
    assert again["result"]["persona_id"] == first["persona_id"]
