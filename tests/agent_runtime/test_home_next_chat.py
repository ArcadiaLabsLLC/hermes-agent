"""Home keeps one hidden chat ready for the picked agent (row RT-HOME-KEEPS-ONE-HIDDEN-CHAT-READY-FOR-THE-PICKED-AGENT).

Owner 2026-11-23: a Home first message started a NEW chat and waited for that chat's agent setup
(7.6 s on the owner's serve, 21:43). Home now asks hermes for ONE ready chat when the agent is set
(``runtime.home.next_chat.ensure``); hermes mints it hidden, prewarms it, and the send promotes it.

Read through the real path: the RPC dispatcher, the open-chat seam, the session store and the
send's own ``promote_on_send`` hook; the prewarm request is recorded, not run.

Killing mutations (recorded in the CHANGE commit): ``_chat_db`` opening the process store
(``open_chat_session_db(access=...)`` without the conversation scope) -> the per-profile test
reddens; drop ``db.set_session_hidden(session_id, True)``
in ``_mint`` -> ``test_a_ready_chat_is_in_no_list_until_its_first_message`` reddens; replace
``_retire``'s ``delete_session_if_empty`` with a no-op -> ``test_switching_agent_deletes_the_empty_old_chat``
reddens; drop the ``rewarm_if_ready`` call in ``select_model`` -> ``test_a_model_pick_on_the_ready_chat_rewarms_it``
reddens.
"""

from __future__ import annotations

import pytest

from agent_runtime import home_next_chat, serve_rpc
from agent_runtime.call_authorization import LOCAL_CONSOLE, TIER_CONSOLE
from agent_runtime.serve_rpc import RpcContext
from tests.agent_runtime.test_serve_rpc_open_chat import PERSONA, placed_agent, qa_persona  # noqa: F401 (fixtures)

SCOPE = "a" * 64


def _call(method: str, params: dict) -> dict:
    return serve_rpc.handle_request({"jsonrpc": "2.0", "id": "h-1", "method": method, "params": params},
                                    context=RpcContext(caller=LOCAL_CONSOLE))


def _session(session_id: str):
    with home_next_chat._chat_db(session_id) as db:
        return db.get_session(session_id)


def _listed_ids() -> set[str]:
    """The ids Eternia's chat list shows: ``runtime.operator.conversation.list`` (every chat store, ``hidden=0``)."""

    from agent_runtime import paths
    from agent_runtime.gateway_identity import ensure_install_identity

    reply = _call("runtime.operator.conversation.list", {
        "install_id": ensure_install_identity(paths.store_root()).install_id, "client_scope": SCOPE, "limit": 100})
    assert "result" in reply, reply
    return {row["session_id"] for row in reply["result"]["conversations"]}


@pytest.fixture
def prewarms(monkeypatch):
    calls: list[str] = []
    from agent_runtime import persona_chat_actor_prewarm

    monkeypatch.setattr(persona_chat_actor_prewarm, "request_chat_actor_prewarm",
                        lambda root, **_: calls.append(root) or "queued")
    return calls


@pytest.fixture
def second_persona(placed_agent):
    from agent_runtime.models import AgentPersona
    from agent_runtime.store import AgentStore

    from tests.agent_runtime.test_serve_rpc_open_chat import WORKSPACE

    AgentStore().save(AgentPersona(id="dev", display_name="Dev Agent", role="dev", model=None, provider=None,
                                   api_mode=None, system_prompt_path=""))
    reply = serve_rpc.handle_request({"jsonrpc": "2.0", "id": "seed-dev", "method": "runtime.agent.create", "params": {
        "persona_id": "dev", "placement_id": "dev_home_agent_2", "workspace_id": WORKSPACE, "position": [3.0, 4.0],
        "idempotency_key": "home-dev-seed", "display_name": "Home Dev seed"}})
    assert "result" in reply, reply
    return reply["result"]


def _ensure(persona: str, instance: str | None = None) -> dict:
    params = {"persona_id": persona, "client_scope": SCOPE}
    if instance:
        params["persona_instance_id"] = instance
    reply = _call("runtime.home.next_chat.ensure", params)
    assert "result" in reply, reply
    return reply["result"]


def test_both_verbs_are_registered_at_the_console_tier():
    for name in ("runtime.home.next_chat.ensure", "runtime.home.next_chat.get"):
        assert name in serve_rpc.manifest()["methods"]
        assert serve_rpc.method_tier(name) == TIER_CONSOLE


def test_a_ready_chat_is_in_no_list_until_its_first_message(placed_agent, prewarms):
    ready = _ensure(PERSONA, placed_agent["persona_instance_id"])
    session_id = ready["session_id"]

    assert ready["created"] is True and ready["hidden"] is True
    assert prewarms and prewarms[-1] == session_id, "ensure did not queue the ready chat's prewarm"
    assert session_id not in _listed_ids(), "the empty ready chat shows in the chat list"
    assert _call("runtime.home.next_chat.get", {"client_scope": SCOPE})["result"]["session_id"] == session_id

    assert home_next_chat.promote_on_send(session_id) is True
    assert session_id in _listed_ids(), "the first message did not show the chat"
    assert _call("runtime.home.next_chat.get", {"client_scope": SCOPE})["result"] == {"session_id": None}


def test_the_same_agent_again_keeps_the_same_chat(placed_agent, prewarms):
    first = _ensure(PERSONA, placed_agent["persona_instance_id"])
    again = _ensure(PERSONA, placed_agent["persona_instance_id"])
    assert again["session_id"] == first["session_id"]
    assert again["created"] is False and again["repointed"] is False


def test_switching_agent_deletes_the_empty_old_chat(second_persona, placed_agent, prewarms):
    old = _ensure(PERSONA, placed_agent["persona_instance_id"])["session_id"]
    new = _ensure(second_persona["persona_id"], second_persona["persona_instance_id"])

    assert new["session_id"] != old and new["persona_id"] == second_persona["persona_id"]
    assert new["repointed"] is True
    assert _session(old) is None, "the retired empty ready chat was left behind"
    assert new["session_id"] not in _listed_ids()


def test_a_send_on_any_other_chat_promotes_nothing(placed_agent, prewarms):
    ready = _ensure(PERSONA, placed_agent["persona_instance_id"])
    assert home_next_chat.promote_on_send("not-the-ready-chat") is False
    assert home_next_chat.promote_on_send(None) is False
    assert _call("runtime.home.next_chat.get", {"client_scope": SCOPE})["result"]["session_id"] == ready["session_id"]


def test_a_model_pick_on_the_ready_chat_rewarms_it(placed_agent, prewarms, monkeypatch):
    from agent_runtime.serve_rpc import operator_inspection

    session_id = _ensure(PERSONA, placed_agent["persona_instance_id"])["session_id"]
    prewarms.clear()
    monkeypatch.setattr(operator_inspection, "select_operator_model", lambda request: {"ok": True})

    reply = _call("runtime.operator.conversation.model.select", {"session_id": session_id, "model_id": "m"})

    assert "result" in reply, reply
    assert prewarms == [session_id], "a pick on the ready chat did not re-queue its prewarm"
    prewarms.clear()
    _call("runtime.operator.conversation.model.select", {"session_id": "other", "model_id": "m"})
    assert prewarms == []


def test_ensure_refuses_without_an_account_scope(placed_agent):
    reply = _call("runtime.home.next_chat.ensure", {"persona_id": PERSONA})
    assert reply["error"]["data"]["reason"] == "client_scope_required"


def test_an_agent_with_its_own_profile_gets_its_ready_chat_hidden_in_that_profiles_store(second_persona, prewarms):
    """The bug read live on the QA serve: Neko's chats live in Neko's profile store, and a hide
    written to the serve's process store left the ready chat in ``conversation.list``."""

    ready = _ensure(second_persona["persona_id"], second_persona["persona_instance_id"])
    assert ready["session_id"] not in _listed_ids(), "the ready chat of a per-profile agent shows in the chat list"
    assert home_next_chat.promote_on_send(ready["session_id"]) is True
    assert ready["session_id"] in _listed_ids()


def test_an_unselected_ready_chat_is_prewarmed_for_its_owner(placed_agent, prewarms):
    """Read live on the QA serve: the ready chat is minted unselected, so no instance had it bound and
    its prewarm answered ``skipped_no_chat_root``; every first message rebuilt its agent."""

    from agent_runtime.persona_assignments import PersonaInstanceStore
    from agent_runtime.persona_chat_actor_prewarm import _instance_for_root

    instance_id = placed_agent["persona_instance_id"]
    session_id = _ensure(PERSONA, instance_id)["session_id"]
    assert PersonaInstanceStore().get(instance_id).session_id != session_id, "the ready chat was selected"
    owner = _instance_for_root(session_id)
    assert owner is not None and owner.id == instance_id
