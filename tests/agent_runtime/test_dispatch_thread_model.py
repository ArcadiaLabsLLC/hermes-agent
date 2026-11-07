"""A dispatched thread runs on the model its lineage chose, never ``model_unset`` while one names a model.

RT-RELAY-DISPATCH-THREAD-NO-MODEL (found live 2026-11-06, Eternia w1106b-live-a): a relay addressed by
instance id minted a FRESH thread for its target (``dispatch_session_policy``); the operator had chosen the
target's model on its console thread (a chat override), the fresh thread held none, the instance and the
lane profile named none, and the turn refused "no model is chosen for this chat".
"""

from __future__ import annotations

import json
from types import SimpleNamespace

from agent_runtime.persona_chat_session import _CHAT_MODEL_OVERRIDE_CONFIG_KEY, _resolve_turn_model_selection

CONFIG = SimpleNamespace(default_provider=None, default_model=None)


class Sessions:
    """The two SessionDB calls the selection makes: ``get_session`` and ``update_session_meta``."""

    def __init__(self, **rows: dict) -> None:
        self.rows = {sid: {"model_config": json.dumps(meta)} for sid, meta in rows.items()}

    def get_session(self, session_id):
        return self.rows.get(session_id)

    def update_session_meta(self, session_id, model_config, model=None):
        self.rows.setdefault(session_id, {})["model_config"] = model_config


def chose(provider: str, model: str) -> dict:
    return {_CHAT_MODEL_OVERRIDE_CONFIG_KEY: {"provider": provider, "model": model}}


def dispatched(predecessor: str | None = None, requested_by: str | None = None) -> dict:
    return {"_dispatched_from": {key: value for key, value in (("predecessor_chat_session_id", predecessor),
                                                               ("requested_by_session", requested_by)) if value}}


def instance(model: str | None = None, provider: str | None = None):
    return SimpleNamespace(model=model, provider=provider, reasoning_effort=None, api_mode=None)


def selection(db: Sessions, session_id: str, *, agent=None) -> dict:
    return _resolve_turn_model_selection(session_db=db, session_id=session_id, requested_override=None, persona=None,
                                         config=CONFIG, instance=agent or instance())


def test_a_dispatched_thread_takes_the_model_chosen_on_the_thread_it_supersedes():
    """Killing mutation: ``inherited = None`` (no predecessor tier) -> effective_model is empty (model_unset)."""

    db = Sessions(console=chose("openai-codex", "gpt-6-luna"), task=dispatched("console", "sender"), sender={})
    picked = selection(db, "task")
    assert (picked["effective_provider"], picked["effective_model"]) == ("openai-codex", "gpt-6-luna")


def test_the_walk_reaches_the_console_thread_past_earlier_dispatched_threads():
    """Each dispatch repoints the default thread at itself, so the next one's predecessor holds no model.
    Killing mutation: one hop only (no ``while``) -> the third dispatch refuses model_unset."""

    db = Sessions(console=chose("openai-codex", "gpt-6-luna"), first=dispatched("console"),
                  second=dispatched("first"), third=dispatched("second"))
    assert selection(db, "third")["effective_model"] == "gpt-6-luna"


def test_the_dispatchers_model_is_the_last_tier():
    """No predecessor model: the dispatcher's chat model runs, but the instance's own still outranks it.
    Killing mutation: drop the dispatcher arm -> effective_model empty (model_unset)."""

    db = Sessions(sender=chose("anthropic", "claude-haiku-5-5"), task=dispatched(None, "sender"))
    assert selection(db, "task")["effective_model"] == "claude-haiku-5-5"
    assert selection(db, "task", agent=instance("gpt-6-luna", "openai-codex"))["effective_model"] == "gpt-6-luna"


def test_the_threads_own_choice_wins_and_a_cycle_ends_the_walk():
    db = Sessions(console=chose("openai-codex", "gpt-6-luna"),
                  task={**dispatched("console"), **chose("anthropic", "claude-haiku-5-5")},
                  a=dispatched("b"), b=dispatched("a"))
    assert selection(db, "task")["effective_model"] == "claude-haiku-5-5"
    assert not selection(db, "a")["effective_model"]
