"""Persona and skills actions Eternia sent as a command line have typed calls on the running Hermes.

Row ``RT-EVERY-ACTION-ETERNIA-SENDS-HAS-A-TYPED-CALL-ON-THE-RUNNING-HERMES``, family "persona and skills":
``runtime.persona.instance.update_profile``, ``runtime.persona.set_skills`` (the argv handlers run through the
operation-result sink: same write, same refusals), ``runtime.harness.skills.sync`` and ``runtime.flow.apply``.
Witnesses are the stores. Killing mutations are named per test.
"""

from __future__ import annotations

import json

import pytest

from agent_runtime import serve_rpc
from agent_runtime.persona_assignments import PersonaInstanceStore
from tests.agent_runtime.persona_instance_mint import mint_free_floating
from tests.agent_runtime.test_serve_rpc_agent_create import qa_persona  # noqa: F401  (fixture)


def _rpc(method, **params):
    return serve_rpc.handle_request({"jsonrpc": "2.0", "id": "p", "method": method, "params": params})


def test_update_profile_renames_and_sets_skills_on_the_instance():
    """Mutation: drop ``skills=params.get("skills")`` in ``update_profile_operation_result`` -> the overrides
    stay unset, red."""
    instance = mint_free_floating("profile:lead")
    reply = _rpc("runtime.persona.instance.update_profile", persona_instance_id=instance.id,
                 display_name="Lead Renamed", skills=["harness-qa-verdict"])
    assert "result" in reply, reply
    assert reply["result"]["ok"] is True and reply["result"]["persona_instance_id"] == instance.id
    stored = PersonaInstanceStore().get(instance.id)
    assert stored.display_name == "Lead Renamed"
    assert stored.skill_overrides == ["harness-qa-verdict"]


def test_update_profile_without_skills_leaves_them_alone():
    """Mutation: default ``skills`` to ``[]`` in the shim -> a rename clears the overrides, red."""
    instance = mint_free_floating("profile:lead")
    _rpc("runtime.persona.instance.update_profile", persona_instance_id=instance.id, skills=["a-skill"])
    _rpc("runtime.persona.instance.update_profile", persona_instance_id=instance.id, display_name="Only a rename")
    assert PersonaInstanceStore().get(instance.id).skill_overrides == ["a-skill"]


@pytest.mark.parametrize("params", [
    {}, {"persona_instance_id": ""}, {"persona_instance_id": "x", "skills": "a"},
    {"persona_instance_id": "x", "skills": [3]}, {"persona_instance_id": "x", "clear_skills": "yes"},
    {"persona_instance_id": "x", "model": "m"},
])
def test_update_profile_refuses_a_malformed_call(params):
    """Mutation: drop ``_skill_list`` -> a bare string reaches the store as one skill per character, red."""
    reply = _rpc("runtime.persona.instance.update_profile", **params)
    assert reply["error"]["code"] == serve_rpc.ERR_INVALID_PARAMS
    assert reply["error"]["data"]["reason"] == "invalid_parameters"


def test_update_profile_of_an_unknown_instance_is_the_argv_refusal():
    reply = _rpc("runtime.persona.instance.update_profile", persona_instance_id="personainst_nobody",
                 display_name="x")
    assert reply["error"]["code"] == serve_rpc.ERR_CONFLICT
    assert reply["error"]["data"]["ok"] is False and "not found" in reply["error"]["data"]["error"]


def test_set_skills_writes_the_template_and_refuses_nothing_to_write(qa_persona):  # noqa: F811
    """Mutation: drop ``skills=params.get("skills")`` in ``set_skills_operation_result`` -> refused
    ``nothing_to_write`` instead of applied, red."""
    from agent_runtime.store import AgentStore

    reply = _rpc("runtime.persona.set_skills", persona_id="qa", skills=["harness-qa-verdict"])
    assert reply["result"]["status"] == "applied" and reply["result"]["skills"] == ["harness-qa-verdict"]
    assert list(AgentStore().get("qa").skills) == ["harness-qa-verdict"]

    nothing = _rpc("runtime.persona.set_skills", persona_id="qa")
    assert nothing["error"]["code"] == serve_rpc.ERR_CONFLICT
    assert nothing["error"]["data"]["error_code"] == "nothing_to_write"

    cleared = _rpc("runtime.persona.set_skills", persona_id="qa", clear_skills=True)["result"]
    assert cleared["cleared"] is True and list(AgentStore().get("qa").skills) == []


def test_skills_sync_reports_every_package(monkeypatch):
    """Mutation: call ``install_harness_skills`` for every request -> the persona route is never taken, red."""
    from agent_runtime import skill_install
    from agent_runtime.skill_install import SkillInstallResult

    row = SkillInstallResult(skill="harness-qa-verdict", source="s", destination="d", source_hash="h",
                             installed_hash="h", installed=True, changed=False, ok=True)
    asked = []
    monkeypatch.setattr(skill_install, "install_harness_skills_for_personas",
                        lambda personas: asked.append("personas") or [row])
    monkeypatch.setattr(skill_install, "install_harness_skills", lambda: asked.append("active") or [row])
    reply = _rpc("runtime.harness.skills.sync")["result"]
    assert reply["all_ok"] is True and reply["installed"][0]["skill"] == "harness-qa-verdict"
    _rpc("runtime.harness.skills.sync", active_profile_only=True)
    assert asked == ["personas", "active"]


def test_flow_apply_stores_the_chart_and_reconciles_the_owner_edge():
    """Mutation: pass ``params`` instead of the graph text to ``ingest_flow_graph`` -> refused, red."""
    store = PersonaInstanceStore()
    lead = mint_free_floating("profile:lead", store=store)
    dev = mint_free_floating("profile:dev", store=store)
    graph = {"graph_id": lead.id, "nodes": [{"id": "n1", "agent": lead.id, "x": 0, "y": 0},
                                            {"id": "n2", "agent": dev.id, "x": 1, "y": 1}],
             "edges": [{"from": "n1", "to": "n2"}]}
    reply = _rpc("runtime.flow.apply", graph=graph)
    assert "result" in reply, reply
    assert reply["result"]["graph_id"] == lead.id
    from agent_runtime.flow_graph import FlowGraphStore

    assert FlowGraphStore().get(lead.id) is not None
    # The same document as JSON text answers the same graph.
    assert _rpc("runtime.flow.apply", graph=json.dumps(graph))["result"]["graph_id"] == lead.id


def test_an_invalid_chart_stores_nothing():
    reply = _rpc("runtime.flow.apply", graph={"nodes": "nope"})
    assert reply["error"]["code"] == serve_rpc.ERR_CONFLICT
    assert reply["error"]["data"]["reason"] == "invalid_flow_graph"
    assert _rpc("runtime.flow.apply")["error"]["data"]["reason"] == "invalid_parameters"


def test_sync_and_flow_are_local_console_and_all_four_are_on_the_manifest():
    """Mutation: drop either name from ``LOCAL_CONSOLE_METHODS`` -> red."""
    from agent_runtime.call_authorization import LOCAL_CONSOLE_METHODS
    from agent_runtime.serve_rpc.registry import manifest

    assert {"runtime.harness.skills.sync", "runtime.flow.apply"} <= LOCAL_CONSOLE_METHODS
    assert {"runtime.persona.instance.update_profile", "runtime.persona.set_skills",
            "runtime.harness.skills.sync", "runtime.flow.apply"} <= set(manifest()["methods"])
