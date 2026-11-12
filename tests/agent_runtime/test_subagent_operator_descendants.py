"""``RT-SUBAGENT-ROSTER-OMITS-HELPERS-HELPER``: a helper's own helper is in its conversation's live roster.

Seen live 2026-11-12 (Eternia lane w1112b-worklive2, hermes 7bb8dbd9f6): a helper ran a helper of its own
for four minutes and the chat's Agents panel never listed it ("2 agents", then "1 agent"). The roster kept
only records whose ``owner_agent_session_id`` resolves to the conversation's own tip; a helper's helper is
owned by the HELPER's session.

The real harness dispatcher, the real SessionDB and the real native child registry; no model calls. The
helper's session is a real row carrying ``model_config._delegate_from`` — the edge upstream itself walks
to find who a delegate's work belongs to (``gateway/run_notifications_ownership.py``), and the edge the
History reader already follows (``history_store.owned_history_sessions``).

Killing mutation (recorded red in the commit body): ``operator._belongs`` stops at the record's own owner
session (the code as it was) → ``test_a_helpers_own_helper_is_listed_under_its_parent_and_can_be_addressed`` red.
"""
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent_runtime.persona_chat_durability import default_persona_session_db
from tools.delegate_tool_child_run import _register_child
from tools.delegate_tool_registry import _unregister_subagent
from tests.agent_runtime.test_operator_session_inspection import target, inspect
from tests.agent_runtime.test_serve_rpc_open_chat import qa_persona, placed_agent  # fixtures
from tests.agent_runtime.test_instance_conversation_owner import chat_head  # fixture
from tests.agent_runtime.test_subagent_worker_ownership import Child


@pytest.fixture
def roster(placed_agent):
    """``register(key, owner_session, parent=None)`` puts one live child in the registry; ``ids()`` reads
    the conversation's roster through the dispatcher."""

    params = target(placed_agent["persona_instance_id"])
    made = []
    with closing(default_persona_session_db()) as db:

        def register(key, owner_session, parent=None):
            child = Child(key)
            child._session_db = db
            child.logs_dir = Path(db.db_path).parent / "sessions"
            if parent is not None:
                child._parent_subagent_id, child._delegate_depth = parent._subagent_id, 2
            _register_child(child, SimpleNamespace(session_id=owner_session), f"goal of {key}",
                            owner_session_id=None, owner_transport=None, owner_session_record=None)
            made.append(child)
            return child

        def rows():
            reply = inspect("subagents.list", params)
            assert "result" in reply, reply
            return {row["subagent_id"]: row for row in reply["result"]["children"]}

        try:
            yield SimpleNamespace(params=params, db=db, register=register, rows=rows,
                                  conversation=params["session_id"])
        finally:
            for child in made:
                _unregister_subagent(child._subagent_id, agent=child)


def test_a_helpers_own_helper_is_listed_under_its_parent_and_can_be_addressed(roster):
    roster.db.create_session("helper-session", "test", parent_session_id=roster.conversation,
                             model_config={"_delegate_from": roster.conversation})
    helper = roster.register("helper", roster.conversation)
    roster.register("helpers-helper", "helper-session", parent=helper)

    rows = roster.rows()
    assert set(rows) == {"helper", "helpers-helper"}, "the helper's own helper is running and must be listed"
    nested = rows["helpers-helper"]
    assert (nested["parent_id"], nested["depth"]) == ("helper", 1), "the row says whose helper it is"
    assert nested["child_ref"] and nested["controllable"] is True
    tail = inspect("subagents.tail", {**roster.params, "child_ref": nested["child_ref"],
                                      "expected_generation": inspect("subagents.list", roster.params)["result"]["generation"]})
    assert "result" in tail and tail["result"]["subagent_id"] == "helpers-helper", tail


def test_a_helper_two_levels_down_is_listed_too(roster):
    roster.db.create_session("helper-session", "test", parent_session_id=roster.conversation,
                             model_config={"_delegate_from": roster.conversation})
    roster.db.create_session("deeper-session", "test", parent_session_id="helper-session",
                             model_config={"_delegate_from": "helper-session"})
    roster.register("deepest", "deeper-session")
    assert set(roster.rows()) == {"deepest"}


def test_only_a_delegation_edge_into_this_conversation_makes_a_helper_its_own(roster):
    """The controls: nothing is listed that the conversation did not, through its helpers, start."""

    roster.db.create_session("another-conversation", "test")
    roster.db.create_session("their-helper", "test", parent_session_id="another-conversation",
                             model_config={"_delegate_from": "another-conversation"})
    roster.db.create_session("a-branch", "test", parent_session_id=roster.conversation,
                             model_config={"_branched_from": roster.conversation})
    roster.db.create_session("a-loop", "test", model_config={"_delegate_from": "a-loop"})
    roster.register("of-another-conversation", "their-helper")
    roster.register("of-a-branch", "a-branch")
    roster.register("of-a-loop", "a-loop")
    roster.register("of-no-session", "never-created")
    assert roster.rows() == {}

    roster.db.create_session("helper-session", "test", parent_session_id=roster.conversation,
                             model_config={"_delegate_from": roster.conversation})
    other_profile = roster.register("other-profile", "helper-session")
    other_profile.logs_dir = Path(roster.db.db_path).parent / "elsewhere" / "sessions"
    assert roster.rows() == {}, "a child of another profile home stays out, whatever its lineage says"
