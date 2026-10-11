"""Catalog identities survive branch apply, lost replies and saved history."""
from contextlib import closing

from hermes_state import SessionDB
from agent_runtime.persona_chat_history.vocabulary import canonical_chat_persona_id
from tests.agent_runtime.test_operator_conversation_attachment import call, fixture


def test_history_profile_identity_uses_catalog_spelling():
    assert canonical_chat_persona_id("profile_audit") == "profile_audit"


def test_history_persona_spelling_uses_the_shared_token_fold():
    # This boundary tokenizes arbitrary punctuation; it is not an alias lookup
    # or a promise that raw instance readers accept old persona spellings.
    assert canonical_chat_persona_id("profile:audit") == "profile_audit"
    assert canonical_chat_persona_id("team/audit") == "team_audit"
    assert canonical_chat_persona_id("team-audit.v2") == "team-audit.v2"


def test_stored_profile_persona_keeps_explicit_binding_and_exact_settings_target():
    from types import SimpleNamespace
    from agent_runtime.persona_assignments.identity import _profile_id_for_persona_or_template
    from agent_runtime.prompt_observability.context_budget import _profile_persona_from_instance
    from hermes_cli.harness_parts.persona.model_and_skills_commands import _template_write_store_target
    stored = SimpleNamespace(id="profile_audit", hermes_profile="rebound")
    sibling = SimpleNamespace(id="sibling", hermes_profile="audit")
    assert _profile_id_for_persona_or_template("profile_audit", roster=lambda: [stored, sibling]) == "rebound"
    target, refusal = _template_write_store_target(
        SimpleNamespace(list_all=lambda: [stored, sibling]), "profile_audit", what="Model")
    assert target is stored and refusal is None
    projected = _profile_persona_from_instance(
        SimpleNamespace(persona_id="profile_audit", profile_id="rebound"))
    assert projected.hermes_profile == "rebound"


def test_profile_branch_apply_status_replay_and_origin_match_catalog(tmp_path, monkeypatch):
    target = fixture(tmp_path / "home", monkeypatch, "Audit", persona_id="profile_audit")
    with closing(SessionDB(db_path=tmp_path / "home" / "state.db")) as db:
        row_id = db.get_messages(target["session_id"])[4]["id"]
    preview = call("history.preview", {**target, "action": "branch", "row_id": row_id})
    assert "result" in preview, preview
    request = {**target, "action": "branch", "row_id": row_id,
               "operation_id": "profile-branch-operation", "preview_token": preview["result"]["preview_token"]}
    applied = call("history.apply", request)
    assert "result" in applied, applied
    child = applied["result"]["result_session_id"]
    status = call("history.status", request)
    assert status["result"]["state"] == "applied", status
    for response in (applied, {"result": status["result"]["result"]}, call("history.apply", request)):
        assert "result" in response, response
        result = response["result"]
        assert result["branch"]["persona_id"] == target["persona_id"]
        assert result["branch"]["persona_instance_id"] == target["persona_instance_id"]
        assert result["result_session_id"] == child
    origin = call("history.origin", {**target, "session_id": child})
    assert "result" in origin, origin
    assert origin["result"]["origin"]["persona_id"] == target["persona_id"]
