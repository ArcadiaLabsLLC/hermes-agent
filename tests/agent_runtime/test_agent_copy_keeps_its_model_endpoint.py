"""A new copy of an agent answers through the same model endpoint as its source, and never takes a credential.

Row ``RT-AGENT-COPY-DROPS-ITS-SOURCES-MODEL-ENDPOINT`` (seen live 2026-11-19, w1118a-mcscope):
a fresh independent copy of Base answered its first message "custom is not signed in on this
Harness (custom)". The copy's profile got only ``model.default`` and ``model.provider``; a source on a
custom endpoint (local, Ollama, vLLM, llama.cpp) lost its ``base_url``. Review w1118a.46 D2: a copy
(and a duplicate) carries ``default``, ``provider``, ``base_url``, ``api_mode`` and, for a
``custom:<name>`` provider, that named endpoint entry — never a credential value.

Driven through the two doors the app uses: ``runtime.persona.instance.create`` with
``independent_agent`` (Create independent copy) and ``runtime.agent.duplicate`` (Duplicate agent).
"""

from __future__ import annotations

import pytest

from agent_runtime import serve_rpc, yaml_io
from agent_runtime.store import AgentStore
from agent_runtime.models import AgentPersona
from hermes_cli.profiles import get_profile_dir

#: Long and short secret values: the long one is secret-SHAPED, the short one only secret-NAMED.
LONG_KEY = "sk-endpoint-0123456789abcdefghij"
SHORT_KEY = "pw-short"
ENDPOINT = "http://127.0.0.1:11434/v1"


@pytest.fixture
def source():
    """An agent on its own profile, the shape of the shipped Base the live read copied."""

    get_profile_dir("src").mkdir(parents=True, exist_ok=True)
    AgentStore().save(AgentPersona(
        id="src", display_name="Source Agent", role="agent", model=None, provider=None, api_mode=None,
        system_prompt_path="", hermes_profile="src",
    ))


def _rpc(method: str, **params) -> dict:
    return serve_rpc.handle_request({"jsonrpc": "2.0", "id": method, "method": method, "params": params})


def _copy_by_create() -> str:
    reply = _rpc(
        "runtime.persona.instance.create",
        persona_id="src", display_name="Scout", independent_agent=True, client_message_id="copy-endpoint",
    )
    return reply["result"]["persona_id"]


def _copy_by_duplicate() -> str:
    return _rpc("runtime.agent.duplicate", persona_id="src", name="Scout Beta")["result"]["persona_id"]


DOORS = pytest.mark.parametrize("make_copy", [_copy_by_create, _copy_by_duplicate], ids=["copy", "duplicate"])


def _source_config(config: dict) -> None:
    path = get_profile_dir("src") / "config.yaml"
    path.write_text(yaml_io.dump(config), encoding="utf-8")


def _copy_home(persona_id: str):
    return get_profile_dir(AgentStore().get(persona_id).hermes_profile)


def _copy_config(persona_id: str) -> dict:
    return yaml_io.load((_copy_home(persona_id) / "config.yaml").read_text(encoding="utf-8")) or {}


def _no_secret_anywhere(persona_id: str) -> None:
    for path in _copy_home(persona_id).rglob("*"):
        if path.is_file() and not path.is_symlink():
            text = path.read_text(encoding="utf-8", errors="ignore")
            assert LONG_KEY not in text and SHORT_KEY not in text, path


@DOORS
def test_a_copy_of_an_agent_on_a_custom_endpoint_keeps_the_endpoint(source, make_copy):
    # Mutation: ``_CARRIED_MODEL_KEYS = ("default", "provider")`` in
    # persona_assignments/independent.py (the helper back to two keys) -> red:
    # the copy's model block has no base_url and no api_mode.
    _source_config({"model": {
        "default": "llama3.1:8b", "provider": "custom", "base_url": ENDPOINT, "api_mode": "chat_completions",
    }})

    copy = make_copy()

    assert _copy_config(copy)["model"] == {
        "default": "llama3.1:8b", "provider": "custom", "base_url": ENDPOINT, "api_mode": "chat_completions",
    }


@DOORS
def test_a_copy_never_takes_the_sources_key(source, make_copy):
    # Mutation: add "api_key" to ``_CARRIED_MODEL_KEYS`` -> red: the short key
    # (secret-named, not secret-shaped) reaches the copy's model block.
    # Mutation: drop the ``payload_refusal`` filter in ``_credential_free`` ->
    # red: a key pasted into the base_url's query string reaches the copy.
    _source_config({"model": {
        "default": "llama3.1:8b", "provider": "custom", "api_key": SHORT_KEY, "api": LONG_KEY,
        "base_url": f"{ENDPOINT}?api_key={LONG_KEY}",
    }})

    copy = make_copy()

    assert _copy_config(copy)["model"] == {"default": "llama3.1:8b", "provider": "custom"}
    _no_secret_anywhere(copy)


@DOORS
def test_a_copy_on_a_named_endpoint_keeps_that_entry_without_its_credentials(source, make_copy):
    # Mutation: ``_named_endpoint`` returns {} -> red: the copy names
    # ``custom:my-box`` with no providers entry to resolve it.
    # Mutation: add "api_key" to ``_CARRIED_ENDPOINT_KEYS`` -> red: the key
    # reaches the copy. Mutation: ``_without_credential_names`` returns its
    # value unchanged -> red: the short key nested under ``models`` reaches it.
    _source_config({
        "model": {"default": "qwen", "provider": "custom:my-box"},
        "providers": {
            "my-box": {
                "name": "My Box", "api": ENDPOINT, "transport": "chat_completions", "default_model": "qwen",
                "models": {"qwen": {"context_length": 32768, "api_key": SHORT_KEY}},
                "api_key": SHORT_KEY, "key_env": "MY_BOX_KEY", "key_cmd": "pass show box",
                "extra_headers": {"Authorization": f"Bearer {LONG_KEY}"},
            },
            "other-box": {"name": "Other", "api": "http://127.0.0.1:9000/v1"},
        },
    })

    copy = make_copy()

    config = _copy_config(copy)
    assert config["model"] == {"default": "qwen", "provider": "custom:my-box"}
    assert config["providers"] == {"my-box": {
        "name": "My Box", "api": ENDPOINT, "transport": "chat_completions", "default_model": "qwen",
        "models": {"qwen": {"context_length": 32768}},
    }}
    _no_secret_anywhere(copy)


def test_a_copy_on_a_legacy_named_endpoint_keeps_that_entry(source):
    # Mutation: drop the ``custom_providers`` loop in ``_named_endpoint`` ->
    # red: a copy of an agent on an older config loses its endpoint.
    _source_config({
        "model": {"default": "qwen", "provider": "custom:lab"},
        "custom_providers": [{"name": "lab", "base_url": ENDPOINT, "api_key": LONG_KEY}],
    })

    copy = _copy_by_create()

    # The copy's profile layout migrates the carried legacy entry to ``providers:``, as for any config.
    assert _copy_config(copy).get("providers") == {"lab": {"name": "lab", "api": ENDPOINT}}
    _no_secret_anywhere(copy)
