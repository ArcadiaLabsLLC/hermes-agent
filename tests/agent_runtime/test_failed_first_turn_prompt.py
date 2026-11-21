"""RT-FU-A-CHAT-WHOSE-FIRST-TURNS-FAILED-SENDS-THE-AGENTS-FULL-PROMPT-AFTERWARDS.

The mint used to store a one-line placeholder as a chat's system prompt. Upstream reuses a stored
prompt verbatim once a chat has history, so a chat whose first turns failed after their user rows
were stored sent the placeholder, not its agent's prompt, on every turn after. The mint now stores
none, a chat still holding the placeholder is cleared at its next actor open, ownership reads from
``model_config``, and the context record never claims a workspace file the reused prompt lacks.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from agent.conversation_loop import _restore_or_build_system_prompt
from agent_runtime import operator_gateway_turn
from agent_runtime.persona_chat_continuity import PERSONA_CHAT_SESSION_SOURCE
from agent_runtime.persona_chat_durability import ensure_persona_chat_session
from agent_runtime.persona_chat_history.history_rows import _infer_persona_id
from agent_runtime.profile_runner.model_input_observability import _system_prompt_reuse
from agent_runtime.prompt_observability.turn_results import (
    NOT_IN_REUSED_PROMPT,
    attach_prompt_observability_turn_results,
)
from hermes_state import SessionDB

BUILT = "BUILT AGENT PROMPT\n\n## app — CLAUDE.md\nrepo rules"
STUB = "Mission Control persona chat for profile_neko"
CHAT = "chat_3f2a"  # an id that names no persona: ownership must come from model_config


def _agent(db: SessionDB, session_id: str) -> MagicMock:
    """The minimal agent the upstream restore-or-build needs (``tests/agent/test_system_prompt_restore.py``)."""

    agent = MagicMock()
    agent._cached_system_prompt = None
    agent.session_id = session_id
    agent.model, agent.provider, agent.platform = "test-model", "openrouter", "desktop"
    agent._session_db = db
    agent._use_prompt_caching = False
    agent._persist_disabled = False
    agent._build_system_prompt = MagicMock(return_value=BUILT)
    agent.enabled_toolsets = agent.disabled_toolsets = None
    return agent


def _failed_first_turn(db: SessionDB, session_id: str) -> list[dict]:
    """The first turn stored its user row, then failed before any prompt persisted."""

    db.append_message(session_id, role="user", content="hello")
    return [{"role": "user", "content": "hello"}]


def _mint(db: SessionDB, session_id: str = CHAT) -> None:
    assert ensure_persona_chat_session(
        session_db=db, session_id=session_id, persona_id="profile_neko", required=True
    )


def test_a_minted_chat_stores_no_prompt_and_its_owner_still_reads(tmp_path):
    db = SessionDB(tmp_path / "state.db")
    _mint(db)

    row = db.get_session(CHAT)

    # MUTATION: the placeholder back at the mint → the stored prompt is that one line.
    assert row["system_prompt"] is None
    assert _infer_persona_id(dict(row), session_id=CHAT) == "profile_neko"


def test_a_chat_whose_first_turn_failed_sends_its_agents_prompt_on_its_next_turn(tmp_path):
    db = SessionDB(tmp_path / "state.db")
    _mint(db)
    history = _failed_first_turn(db, CHAT)
    agent = _agent(db, CHAT)

    _restore_or_build_system_prompt(agent, "system message", history)

    # MUTATION: the placeholder back at the mint → the turn replays it (cached == STUB, built never called).
    assert agent._cached_system_prompt == BUILT
    assert agent._system_prompt_restored_from_session is False
    assert db.get_session(CHAT)["system_prompt"] == BUILT


def test_a_chat_already_holding_the_placeholder_heals_at_its_next_actor_open(tmp_path):
    db = SessionDB(tmp_path / "state.db")
    db.create_session(CHAT, source=PERSONA_CHAT_SESSION_SOURCE, system_prompt=STUB,
                      model_config={"source": PERSONA_CHAT_SESSION_SOURCE, "persona_id": "profile_neko"})
    history = _failed_first_turn(db, CHAT)
    execution = SimpleNamespace(runner=SimpleNamespace(_session_db=db))

    operator_gateway_turn._ensure_session_row(execution, Path(tmp_path), CHAT)
    agent = _agent(db, CHAT)
    _restore_or_build_system_prompt(agent, "system message", history)

    # MUTATION: drop the heal in ``_ensure_session_row`` → the turn replays STUB.
    assert agent._cached_system_prompt == BUILT
    assert db.get_session(CHAT)["system_prompt"] == BUILT
    assert _infer_persona_id(dict(db.get_session(CHAT)), session_id=CHAT) == "profile_neko"


def test_a_built_prompt_is_never_cleared_at_actor_open(tmp_path):
    db = SessionDB(tmp_path / "state.db")
    db.create_session(CHAT, source=PERSONA_CHAT_SESSION_SOURCE, system_prompt=BUILT)

    operator_gateway_turn._ensure_session_row(
        SimpleNamespace(runner=SimpleNamespace(_session_db=db)), Path(tmp_path), CHAT
    )

    assert db.get_session(CHAT)["system_prompt"] == BUILT


def test_ownership_reads_from_model_config_then_the_id_then_a_legacy_placeholder():
    owned = {"model_config": '{"source": "persona_chat", "persona_id": "profile_neko"}', "system_prompt": BUILT}
    # MUTATION: drop the model_config read → a built-prompt chat whose id names no persona has no owner.
    assert _infer_persona_id(owned, session_id=CHAT) == "profile_neko"
    assert _infer_persona_id({}, session_id="persona_chat_personainst_dev_0123456789ab") is not None
    # A legacy row that carries neither still reads through the old placeholder.
    assert _infer_persona_id({"system_prompt": "Mission Control persona chat for qa"}, session_id=CHAT) == "qa"
    assert _infer_persona_id({"system_prompt": BUILT}, session_id=CHAT) is None


def _record(included_file: str = "CLAUDE.md") -> dict:
    return {
        "workspace_context_receipt": {
            "kind": "workspace_context", "source": "assigned_slots", "primary_slot": "app",
            "slots": [
                {"slot": "app", "file": included_file, "included": True, "status": "loaded"},
                {"slot": "app", "file": "AGENTS.md", "included": False, "status": "not_default"},
            ],
        }
    }


def _reused_input(prompt: str) -> dict:
    agent = SimpleNamespace(_system_prompt_restored_from_session=True)
    return {"messages": [], **_system_prompt_reuse(agent, prompt)}


def test_a_reused_placeholder_prompt_claims_no_workspace_file():
    record = attach_prompt_observability_turn_results(_record(), final_model_input=_reused_input(STUB))

    receipt = record["workspace_context_receipt"]
    claude = receipt["slots"][0]
    # MUTATIONS: return early in ``_workspace_receipt_for_reused_prompt``, drop ``system_prompt_reuse`` from the
    # safe view, or never record a reused prompt in ``_system_prompt_reuse`` → CLAUDE.md stays claimed.
    assert claude["included"] is False
    assert claude["status"] == NOT_IN_REUSED_PROMPT and claude["built_status"] == "loaded"
    assert receipt["system_prompt"] == "reused_from_session"
    assert receipt["slots"][1]["status"] == "not_default"


def test_a_reused_prompt_that_carries_the_file_keeps_its_claim():
    record = attach_prompt_observability_turn_results(_record(), final_model_input=_reused_input(BUILT))

    # MUTATION: unclaim every included file on reuse (skip the heading check) → this file is unclaimed.
    assert record["workspace_context_receipt"]["slots"][0]["included"] is True


def test_a_built_prompt_leaves_the_receipt_as_resolved():
    agent = SimpleNamespace(_system_prompt_restored_from_session=False)
    final = {"messages": [], **_system_prompt_reuse(agent, STUB)}

    record = attach_prompt_observability_turn_results(_record(), final_model_input=final)

    assert record["workspace_context_receipt"]["slots"][0]["included"] is True
    assert "system_prompt" not in record["workspace_context_receipt"]
