"""Creation must join the existing native owner, never adopt legacy history.

Kill mutation: omit client_scope at the existing add_instance call. The
SessionDB read and suggestion subject validation then fail, despite a good ack.
"""
from contextlib import closing
import os

import pytest

from agent_runtime import paths
from agent_runtime.agent_create import perform_agent_create
from agent_runtime.conversation_access import validate_conversation_access
from agent_runtime.conversation_owner import ConversationOwnerError, session_client_scope
from agent_runtime.gateway_identity import ensure_install_identity
from agent_runtime.persona_chat_durability import default_persona_session_db
from agent_runtime.persona_chat_history.suggestion_context import suggestion_context
from tests.agent_runtime.test_agent_create_service import qa_persona, _seed_workspace, _params, _reservation_record


@pytest.fixture(autouse=True)
def authoritative_head(monkeypatch):
    monkeypatch.setenv("HERMES_HEAD_HOME", os.environ["HERMES_HOME"])


def test_created_default_chat_uses_the_native_owner_for_sends_and_suggestions(qa_persona):
    _seed_workspace()
    owner = "a" * 64
    params = _params(client_scope=owner, placement_id="qa_owned_agent_2")
    outcome = perform_agent_create(params)
    assert outcome.refusal is None
    result = outcome.result
    session = result["default_chat_session_id"]
    with closing(default_persona_session_db()) as db:
        assert session_client_scope(db.get_session(session)) == owner
    target = dict(install_id=ensure_install_identity(paths.store_root()).install_id,
                  workspace_id=params["workspace_id"], persona_id="qa", persona_instance_id=result["persona_instance_id"],
                  session_id=session, client_scope=owner)
    validate_conversation_access(target)
    assert suggestion_context(target, 4)["reason"] == "turn_active"
    with pytest.raises(Exception, match="conversation_owner_changed"):
        suggestion_context({**target, "client_scope": "b" * 64}, 4)
    with pytest.raises(ConversationOwnerError, match="conversation_owner_changed"):
        validate_conversation_access({**target, "client_scope": "b" * 64})
    receipt = _reservation_record(params["idempotency_key"])
    replay = perform_agent_create(params)
    assert replay.result["idempotent_replay"] is True
    assert replay.result["client_scope"] == owner
    assert _reservation_record(params["idempotency_key"]) == receipt
    for scope in ("b" * 64, None):
        refused = perform_agent_create({**params, "client_scope": scope} if scope else
                                      {k: v for k, v in params.items() if k != "client_scope"})
        assert refused.refusal is not None
        assert _reservation_record(params["idempotency_key"]) == receipt


def test_scoped_replay_cannot_adopt_legacy_default_chat(qa_persona):
    _seed_workspace()
    params = _params(placement_id="qa_legacy_agent_2")
    original = perform_agent_create(params).result
    assert perform_agent_create({**params, "client_scope": "a" * 64}).refusal is not None
    with closing(default_persona_session_db()) as db:
        assert session_client_scope(db.get_session(original["default_chat_session_id"])) is None
