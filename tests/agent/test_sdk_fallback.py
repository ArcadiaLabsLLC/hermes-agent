"""register_sdk_fallback: a host without the provider SDK can supply a client."""

import sys
from types import SimpleNamespace

import pytest

from agent import anthropic_adapter, auxiliary_client, process_bootstrap


class _FakeOpenAI:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.api_key = kwargs.get("api_key")
        self.base_url = kwargs.get("base_url")


class _FakeAsyncOpenAI(_FakeOpenAI):
    pass


@pytest.fixture
def no_openai(monkeypatch):
    monkeypatch.setitem(sys.modules, "openai", None)  # `import openai` raises ImportError
    monkeypatch.setattr(process_bootstrap, "_OPENAI_CLS_CACHE", None)
    monkeypatch.setattr(process_bootstrap, "_ASYNC_OPENAI_CLS_CACHE", None)
    monkeypatch.setattr(process_bootstrap, "_SDK_FALLBACKS", {})


def _register_openai():
    process_bootstrap.register_sdk_fallback(
        "openai", lambda: SimpleNamespace(OpenAI=_FakeOpenAI, AsyncOpenAI=_FakeAsyncOpenAI))


def test_proxy_builds_the_fallback_client_when_openai_is_absent(no_openai):
    _register_openai()
    client = process_bootstrap.OpenAI(api_key="k", base_url="http://x")
    assert type(client) is _FakeOpenAI
    assert client.kwargs == {"api_key": "k", "base_url": "http://x"}
    assert isinstance(client, process_bootstrap.OpenAI)
    assert auxiliary_client._load_openai_cls() is _FakeOpenAI  # one owner, one cache


def test_async_twin_comes_from_the_fallback(no_openai):
    _register_openai()
    sync_client = process_bootstrap.OpenAI(api_key="k", base_url="http://x")
    async_client, model = auxiliary_client._to_async_client(sync_client, "m")
    assert type(async_client) is _FakeAsyncOpenAI
    assert model == "m"


def test_anthropic_fallback_is_never_lazily_installed_over(monkeypatch):
    fallback = SimpleNamespace(Anthropic=object, AsyncAnthropic=object)
    calls = []
    monkeypatch.setitem(sys.modules, "anthropic", None)
    monkeypatch.setattr(process_bootstrap, "_SDK_FALLBACKS", {})
    monkeypatch.setattr(anthropic_adapter, "_anthropic_sdk", ...)
    monkeypatch.setattr("pm.ensure_import", lambda extra: calls.append(extra))
    process_bootstrap.register_sdk_fallback("anthropic", lambda: fallback)
    assert anthropic_adapter._require_sdk("x") is fallback
    assert calls == []


def test_nothing_registered_still_raises_import_error(no_openai):
    with pytest.raises(ImportError):
        process_bootstrap.OpenAI(api_key="k", base_url="http://x")
    with pytest.raises(ImportError):
        process_bootstrap.load_async_openai_cls()


def test_second_registration_replaces_the_first_with_a_warning(no_openai, caplog):
    process_bootstrap.register_sdk_fallback("openai", lambda: SimpleNamespace(OpenAI=int))
    _register_openai()
    assert "replaced" in caplog.text
    assert process_bootstrap.load_openai_cls() is _FakeOpenAI
