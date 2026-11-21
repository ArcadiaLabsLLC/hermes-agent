"""An agent with no instance yet publishes the model its first chat runs on, as Hermes works it out.

RT-AN-AGENT-WITH-NO-INSTANCE-YET-PUBLISHES-THE-MODEL-ITS-FIRST-CHAT-RUNS-ON (review w1118a.71). The persona row
(``snapshot/summaries.py::_agent_summary``, the one builder of the snapshot's agents section and the persona state
patch) published only the persona's own ``default_model`` / ``default_provider``, so for an agent with no instance
Eternia guessed the tiers itself and skipped the profile-config tier. The row now carries ``effective_model`` /
``effective_provider`` from ``next_turn_model_selection(instance=None)``, the resolver every turn folds.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

PROFILE_MODEL, PROFILE_PROVIDER = "profile-model-7", "profile-provider"


@pytest.fixture
def two_profiles(tmp_path, monkeypatch):
    """The serve on ``profiles/base`` whose config names no default model; profile ``neko`` names its own.

    The turn's cascade ranks the process config's default above the profile's (``_chat_effective_model_payload``
    reads the profile config only when no default is set), so the profile tier shows only when the serve's
    config is silent — the fresh-install case the Eternia guess got wrong."""

    from agent_runtime import profile_context

    root = tmp_path / ".hermes"
    base, neko = root / "profiles" / "base", root / "profiles" / "neko"
    for path in (root / "agent-runtime", base, neko):
        path.mkdir(parents=True, exist_ok=True)
    (base / "config.yaml").write_text("agent_runtime: {}\n", encoding="utf-8")
    (neko / "config.yaml").write_text(
        f"model:\n  default: {PROFILE_MODEL}\n  provider: {PROFILE_PROVIDER}\n", encoding="utf-8")
    monkeypatch.setenv("HERMES_AGENT_RUNTIME_ROOT", str(root / "agent-runtime"))
    monkeypatch.setenv("HERMES_HOME", str(base))
    monkeypatch.setenv("HERMES_HEAD_HOME", str(base))
    monkeypatch.setattr(profile_context, "profile_exists", lambda name: name == "neko")
    monkeypatch.setattr(profile_context, "get_profile_dir", lambda name: {"neko": neko}[name])
    return SimpleNamespace(base=base, neko=neko)


def _persona(**fields):
    from agent_runtime.models import AgentPersona

    return AgentPersona(**{"id": "neko", "display_name": "Neko", "role": "lead", "model": None, "provider": None,
                           "api_mode": None, "hermes_profile": "neko", **fields})


def _resolver_answer(persona) -> dict:
    from agent_runtime.config import load_agent_runtime_config
    from agent_runtime.persona_chat_session import next_turn_model_selection

    return next_turn_model_selection(session_db=None, session_id=None, persona=persona,
                                     config=load_agent_runtime_config(), instance=None)


def test_an_agent_with_no_model_of_its_own_publishes_its_profiles_model(two_profiles):
    """KILLING MUTATION (run 2026-11-21): ``_first_chat_model`` answering the persona's own model else the
    runtime default (Eternia's no-instance guess, the profile tier skipped) -> ``None`` is published where
    the resolver says ``profile-model-7``, red."""

    from agent_runtime.snapshot.summaries import _agent_summary

    persona = _persona()
    answer = _resolver_answer(persona)
    assert (answer["effective_model"], answer["effective_provider"]) == (PROFILE_MODEL, PROFILE_PROVIDER)

    row = _agent_summary(persona)

    assert (row["effective_model"], row["effective_provider"]) == (PROFILE_MODEL, PROFILE_PROVIDER)
    assert (row["default_model"], row["default_provider"]) == (None, None)  # the persona's own fields, unchanged


def test_positive_control_an_agent_with_its_own_model_publishes_it(two_profiles):
    """One variable changed: the persona names a model, which outranks its profile's, as a turn ranks it."""

    from agent_runtime.snapshot.summaries import _agent_summary

    persona = _persona(model="own-model-1", provider="own-provider")
    row = _agent_summary(persona)

    assert (row["effective_model"], row["effective_provider"]) == ("own-model-1", "own-provider")
    assert row["effective_model"] == _resolver_answer(persona)["effective_model"]


def test_the_persona_state_patch_carries_the_same_answer(two_profiles):
    """The persona patch is built by the same ``_agent_summary``, so Eternia reads one answer on both."""

    from agent_runtime.state_patches.persona import project_persona_wire_row

    row = project_persona_wire_row(_persona())

    assert (row["effective_model"], row["effective_provider"]) == (PROFILE_MODEL, PROFILE_PROVIDER)
