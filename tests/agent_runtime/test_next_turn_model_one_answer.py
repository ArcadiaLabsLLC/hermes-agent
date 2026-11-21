"""The model a chat shows, and a lead reads for its helper, is the model its next turn runs.

RT-THE-MODEL-A-CHAT-SHOWS-IS-THE-MODEL-ITS-NEXT-REPLY-RUNS-ON / RT-FU-A-LEAD-CANNOT-READ-ITS-HELPERS-MODEL-
BEFORE-DISPATCHING (seen 2026-11-21: the operator picked gpt-6.2-sol on helper Launcher Dev Agent's console
chat; the helper's instance still carried a gpt-6-luna override; the lead read only the instance and
dispatched without knowing; the turn ran on sol). The turn folds the dispatch-lineage tiers
(``_resolve_turn_model_selection``); every reader now asks ``next_turn_model_selection``, which folds the
same tiers over the stored override and writes nothing.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

from agent_runtime.persona_chat_session import (
    _CHAT_MODEL_OVERRIDE_CONFIG_KEY,
    _resolve_turn_model_selection,
    next_turn_model_selection,
)

CONFIG = SimpleNamespace(default_provider=None, default_model=None)


class Sessions:
    def __init__(self, **rows: dict) -> None:
        self.rows = {sid: {"model_config": json.dumps(meta)} for sid, meta in rows.items()}
        self.writes: list[str] = []

    def get_session(self, session_id):
        return self.rows.get(session_id)

    def update_session_meta(self, session_id, model_config, model=None):
        self.writes.append(session_id)
        self.rows.setdefault(session_id, {})["model_config"] = model_config


def chose(provider: str, model: str) -> dict:
    return {_CHAT_MODEL_OVERRIDE_CONFIG_KEY: {"provider": provider, "model": model}}


def dispatched(predecessor: str) -> dict:
    return {"_dispatched_from": {"predecessor_chat_session_id": predecessor}}


#: The helper as seen live: its instance carries luna, its console chat was switched to sol.
HELPER = SimpleNamespace(model="gpt-6-luna-900k", provider="openai-codex", reasoning_effort=None, api_mode=None)


def _turn(db: Sessions, session_id: str) -> dict:
    return _resolve_turn_model_selection(session_db=db, session_id=session_id, requested_override=None,
                                         persona=None, config=CONFIG, instance=HELPER)


def _read(db: Sessions, session_id: str | None, **kw) -> dict:
    return next_turn_model_selection(session_db=db, session_id=session_id, persona=None, config=CONFIG,
                                     instance=HELPER, **kw)


def test_a_dispatched_threads_read_is_the_model_its_turn_runs():
    """*Killing mutation:* ``next_turn_model_selection`` folding the plain cascade
    (``_chat_effective_model_payload`` over the stored override) -> the read says luna, the turn runs sol."""

    db = Sessions(console=chose("openai-codex", "gpt-6.2-sol"), task=dispatched("console"))

    read = _read(db, "task")
    ran = _turn(db, "task")

    assert read["effective_model"] == ran["effective_model"] == "gpt-6.2-sol"
    assert read["model_source"] == ran["model_source"] == "dispatch_predecessor"


def test_a_lead_reads_the_model_a_dispatch_would_run_before_it_is_sent():
    """The thread a dispatch mints does not exist yet; its lineage is passed instead.

    *Killing mutation:* ignore ``dispatched_from`` (read the lineage off the session only) -> the preview
    says the instance's luna while the minted thread runs sol."""

    db = Sessions(console=chose("openai-codex", "gpt-6.2-sol"))

    preview = _read(db, None, dispatched_from={"predecessor_chat_session_id": "console"})
    db.rows["minted"] = {"model_config": json.dumps(dispatched("console"))}

    assert preview["effective_model"] == _turn(db, "minted")["effective_model"] == "gpt-6.2-sol"


def test_reading_writes_nothing_and_a_plain_chat_reads_its_own_tiers():
    db = Sessions(console=chose("openai-codex", "gpt-6.2-sol"), other={})

    assert _read(db, "console")["effective_model"] == "gpt-6.2-sol"
    assert _read(db, "other")["effective_model"] == "gpt-6-luna-900k"
    assert _read(db, "other")["model_source"] == "instance"
    assert db.writes == []


def test_the_lead_tool_answers_with_the_helpers_next_models(monkeypatch):
    """``harness_query(question="instance")`` carries ``next_models`` from the one resolver.

    *Killing mutation:* ``_next_models`` reading ``instance.model`` -> ``new_dispatch`` says luna."""

    from agent_runtime import chat_session_scope, config as config_module, persona_chat_durability
    from agent_runtime.harness_query import core
    from tests._downstream.split_package_source import patch_where_bound

    db = Sessions(console=chose("openai-codex", "gpt-6.2-sol"))
    helper = SimpleNamespace(**vars(HELPER), id="personainst_dev_agent_x", persona_id="dev",
                             default_chat_session_id="console")
    persona = SimpleNamespace(id="dev", provider=None, model=None, api_mode=None)
    patch_where_bound(monkeypatch, config_module, "load_agent_runtime_config", lambda: CONFIG)
    patch_where_bound(monkeypatch, config_module, "ensure_persisted_personas", lambda cfg: [persona])
    monkeypatch.setattr(chat_session_scope, "resolve_instance_chat_scope", lambda instance: None)
    monkeypatch.setattr(persona_chat_durability, "persona_session_db_for", lambda scope: db)
    import agent_runtime.models as models

    monkeypatch.setattr(models, "apply_instance_model_overrides", lambda p, i: p)
    monkeypatch.setattr("agent_runtime.profile_context.resolve_persona_profile", lambda p: None)

    answer = core._next_models(helper)

    assert answer["basis"] == "resolved_now", answer
    assert answer["default_chat"]["effective_model"] == "gpt-6.2-sol"
    assert answer["new_dispatch"]["effective_model"] == "gpt-6.2-sol"
    assert answer["new_dispatch"]["model_source"] == "dispatch_predecessor"
