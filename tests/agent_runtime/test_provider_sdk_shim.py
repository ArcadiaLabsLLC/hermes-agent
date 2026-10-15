"""The phone's ``openai`` shim (``agent_runtime.provider_sdk_shim``): installed only where it must be,
and what upstream's SDK import sites read through it.

Killing mutations (applied, red recorded, reverted — see the commit message):

* ``ensure_provider_sdk_shim`` drops the ``provider_sdks_enabled()`` check  -> desktop test red.
* ``ensure_provider_sdk_shim`` drops the real-SDK check                    -> never-a-shadow test red.
* ``ProviderStreamError`` no longer subclasses ``APIError``               -> error-hierarchy test red.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from agent_runtime import provider_sdk_shim as shim
from agent.transports import httpx_client as sdk_free

_SHIM_NAMES = ("openai", "openai.types", "openai.types.chat", "openai.types.chat.chat_completion_message_tool_call")


def _sdk_free_profile() -> None:
    from hermes_constants import get_hermes_home

    home = Path(get_hermes_home())
    home.mkdir(parents=True, exist_ok=True)
    (home / "config.yaml").write_text(json.dumps({"agent": {"provider_sdks": False}}), encoding="utf-8")


@pytest.fixture
def clean_modules(monkeypatch):
    """Restore every ``openai`` entry afterwards; start with no SDK importable (the phone)."""
    for name in [m for m in sys.modules if m == "openai" or m.startswith("openai.")]:
        monkeypatch.delitem(sys.modules, name)
    for name in _SHIM_NAMES:
        monkeypatch.setitem(sys.modules, name, None)  # recorded, so teardown removes what the shim adds
        monkeypatch.delitem(sys.modules, name)
    monkeypatch.setattr(shim, "_real_openai_importable", lambda: False)
    yield monkeypatch


def test_the_desktop_profile_installs_nothing(clean_modules):
    assert shim.ensure_provider_sdk_shim() is False  # agent.provider_sdks defaults on
    assert "openai" not in sys.modules

    _sdk_free_profile()  # positive control: the same call on the phone profile installs it
    assert shim.ensure_provider_sdk_shim() is True
    assert shim.is_shim(sys.modules["openai"])


def test_a_real_sdk_is_never_shadowed(clean_modules):
    _sdk_free_profile()
    clean_modules.setattr(shim, "_real_openai_importable", lambda: True)
    assert shim.ensure_provider_sdk_shim() is False
    assert "openai" not in sys.modules


def test_the_shim_binds_the_sdk_free_classes_under_the_sdks_names(clean_modules):
    _sdk_free_profile()
    assert shim.ensure_provider_sdk_shim() is True
    assert sorted(m for m in sys.modules if shim.is_shim(sys.modules[m])) == sorted(_SHIM_NAMES)

    from openai import APIConnectionError, APIError, APIStatusError, APITimeoutError, AsyncOpenAI, OpenAI
    from openai.types.chat.chat_completion_message_tool_call import ChatCompletionMessageToolCall, Function

    assert (OpenAI, AsyncOpenAI) == (sdk_free.SdkFreeClient, sdk_free.AsyncSdkFreeClient)
    assert (APIStatusError, APIConnectionError, APITimeoutError) == (
        sdk_free.ProviderHTTPError, sdk_free.APIConnectionError, sdk_free.APITimeoutError)
    call = ChatCompletionMessageToolCall(id="c1", type="function", function=Function(name="f", arguments="{}"))
    assert (call.id, call.function.name) == ("c1", "f")
    # No __spec__: upstream's package probes (tools.tts_tool._package_installed) still read "not installed".
    with pytest.raises(ValueError):
        importlib.util.find_spec("openai")
    assert APIError is sdk_free.APIError


def test_every_sdk_free_request_error_is_the_shims_api_error():
    for error in (sdk_free.ProviderHTTPError(500, message="m", body=None, response=None),
                  sdk_free.ProviderStreamError("connection lost", body=None),
                  sdk_free.APIConnectionError(), sdk_free.APITimeoutError()):
        assert isinstance(error, sdk_free.APIError), type(error).__name__
    assert not isinstance(sdk_free.SdkFreeWireUnavailable("x"), sdk_free.APIError)  # control: not a request error


def test_the_sdk_free_client_refuses_audio_by_name():
    client = sdk_free.SdkFreeClient(api_key="k", base_url="https://p.example/v1")
    assert client.chat.completions.create  # control: the chat surface is there
    with pytest.raises(sdk_free.SdkFreeWireUnavailable, match="agent.provider_sdks: false"):
        client.audio  # noqa: B018 — the attribute access is the call under test
