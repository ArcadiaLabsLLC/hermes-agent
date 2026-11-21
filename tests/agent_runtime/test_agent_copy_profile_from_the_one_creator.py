"""A copied or newly made agent gets its profile from upstream's one profile creator.

Row ``RT-AN-AGENT-COPY-OR-NEW-AGENT-GETS-ITS-PROFILE-FROM-THE-ONE-PROFILE-CREATOR``
(seen 2026-11-21 by w1118a-onepath-profile through both doors): the duplicate and the
independent copy staged their profiles by hand, so ``hermes_cli.profiles.create_profile``'s
steps around the layout were skipped — a duplicate given a name ``hermes profile delete``
had tombstoned was born deleted, and neither the memory provider nor a running
multiplexer heard of the new profile. Both doors now go through
``agent_runtime.agent_profile_create.create_agent_profile``.

Driven through the two doors the app uses: ``runtime.persona.instance.create`` with
``independent_agent`` (Create independent copy) and ``runtime.agent.duplicate``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_runtime import agent_duplicate, serve_rpc, yaml_io
from agent_runtime.models import AgentPersona
from agent_runtime.store import AgentStore
from hermes_cli.profile_channels import channel_platforms_configured
from hermes_cli.profiles import get_profile_dir
from hermes_constants import mark_named_profile_deleted, named_profile_is_deleted

BOT_TOKEN = "123456:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi"


@pytest.fixture
def source():
    """An agent on its own profile with a bound Telegram channel."""

    home = get_profile_dir("src")
    home.mkdir(parents=True, exist_ok=True)
    (home / "config.yaml").write_text(yaml_io.dump({
        "model": {"default": "m", "provider": "openrouter"},
        "platforms": {"telegram": {"enabled": True, "token": BOT_TOKEN}},
    }), encoding="utf-8")
    (home / ".env").write_text(f"TELEGRAM_BOT_TOKEN={BOT_TOKEN}\n", encoding="utf-8")
    AgentStore().save(AgentPersona(
        id="src", display_name="Source Agent", role="agent", model=None, provider=None, api_mode=None,
        system_prompt_path="", hermes_profile="src",
    ))


@pytest.fixture
def hooks(monkeypatch):
    """The creator's two outward notices, recorded instead of sent."""

    import hermes_cli.profile_memory_config as memory_config
    import hermes_cli.profiles as profiles

    calls: list[tuple[str, object]] = []
    monkeypatch.setattr(memory_config, "notify_memory_provider", lambda home, call: calls.append(("memory", Path(home))))
    monkeypatch.setattr(profiles, "_notify_multiplexer", lambda canon: calls.append(("multiplexer", canon)))
    return calls


def _rpc(method: str, **params) -> dict:
    return serve_rpc.handle_request({"jsonrpc": "2.0", "id": method, "method": method, "params": params})


def _copy_by_create() -> str:
    reply = _rpc(
        "runtime.persona.instance.create",
        persona_id="src", display_name="Scout", independent_agent=True, client_message_id="one-creator",
    )
    return reply["result"]["persona_id"]


def _copy_by_duplicate(name: str = "Scout Beta") -> str:
    reply = _rpc("runtime.agent.duplicate", persona_id="src", name=name)
    assert "result" in reply, reply
    return reply["result"]["persona_id"]


DOORS = pytest.mark.parametrize("make_copy", [_copy_by_create, _copy_by_duplicate], ids=["copy", "duplicate"])


def _home(persona_id: str) -> Path:
    return get_profile_dir(AgentStore().get(persona_id).hermes_profile)


@DOORS
def test_the_memory_provider_and_the_multiplexer_hear_of_a_copy(source, hooks, make_copy):
    # Mutation: in agent_profile_create._create_seeded, replace ``create_profile(profile, soul=soul)``
    # with the old hand layout (mkdir + ``finish_profile_layout``) -> red: no notice is sent.
    home = _home(make_copy())

    assert ("memory", home) in hooks
    assert ("multiplexer", home.name) in hooks


def test_a_duplicate_on_a_deleted_profiles_name_is_alive(source):
    # Same mutation as above -> red: the tombstone ``hermes profile delete`` left stays,
    # and the copy's home is read as deleted (its turns refuse).
    mark_named_profile_deleted(get_profile_dir("scout-beta"))

    home = _home(_copy_by_duplicate())

    assert home.name == "scout-beta"
    assert not named_profile_is_deleted(home)


@DOORS
def test_a_copy_of_an_agent_with_a_bound_channel_has_none(source, make_copy):
    # Mutation: ``".env"`` added to ``agent_duplicate._AGENT_FILES`` -> red [duplicate]: the
    # copy's .env holds the bot token. Mutation: ``_carried_model_config`` returning the
    # source's whole config AND the hand layout of the first test (the creator's seed no
    # longer narrows it to the model block) -> red [copy]: the copy's config names Telegram.
    home = _home(make_copy())

    assert channel_platforms_configured(home) == []
    for path in home.rglob("*"):
        if path.is_file() and not path.is_symlink():
            assert BOT_TOKEN not in path.read_text(encoding="utf-8", errors="ignore"), path


def test_a_copy_named_like_a_reserved_profile_gets_a_free_profile(source):
    # Mutation: drop the ``validate_profile_name`` check in ``free_profile_name`` -> red:
    # the creator refuses the reserved ``hermes`` and the duplicate fails.
    home = _home(_copy_by_duplicate("Hermes"))

    assert home.name.startswith("hermes-")
    assert home.is_dir()


def test_a_copy_whose_files_fail_leaves_no_half_made_profile(source, monkeypatch):
    # Mutation: drop ``_retire_profile_home(home)`` in ``create_agent_profile`` -> red: the
    # published home stays, holding the name, with no agent pointing at it.
    def broken(_source: Path, _target: Path) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(agent_duplicate, "_copy_entry", broken)

    with pytest.raises(OSError):
        agent_duplicate.duplicate_agent("src", "Scout Beta")

    assert not get_profile_dir("scout-beta").exists()
    retired = get_profile_dir("scout-beta").parent / ".retired-independent-agents"
    assert [p.name for p in retired.glob("*/profile")] == ["profile"]
