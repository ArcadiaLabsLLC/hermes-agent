"""Behavioral controls for optional, persona-independent Console suggestions."""
from copy import deepcopy
from threading import Event
from types import SimpleNamespace
import time

import pytest

from agent_runtime.console_suggestions.generation import clean_suggestion, register_suggestion_task
from agent_runtime.console_suggestions.settings import SuggestionRefused, SuggestionSettings, suggestion_home
from agent_runtime.console_suggestions.store import SuggestionStore
from agent_runtime.console_suggestions import service as lifecycle


@pytest.mark.parametrize("text", ["好", "[foo] を説明して", "NULL handling needs a test", "Show me `x[0]`", "Can we try another approach?", "ありがとう"])
def test_free_form_short_and_code_suggestions_survive(text):
    assert clean_suggestion(text) == text


@pytest.mark.parametrize("text", ["NULL", "", "x" * 161, "Use [your token]", "<your name>"])
def test_empty_placeholder_or_oversized_output_is_not_a_draft(text):
    assert clean_suggestion(text) is None


def test_policy_default_off_atomic_cas_and_independent_disable(tmp_path):
    settings = SuggestionSettings(tmp_path)
    first = settings.read()
    assert first["enabled"] is False
    assert not (tmp_path / "state").exists()
    current = settings.write({"expected_revision": first["settings_revision"], "enabled": True,
        "auxiliary_override": {"provider": "openai", "model": "example"}, "cooldown_seconds": 100000})
    assert current["enabled"] is True
    with pytest.raises(SuggestionRefused, match="stale_revision"):
        settings.write({"expected_revision": first["settings_revision"], "enabled": False})
    disabled = settings.write({"expected_revision": current["settings_revision"], "enabled": False})
    assert disabled["enabled"] is False
    assert disabled["auxiliary_override"] == current["auxiliary_override"]


def test_route_reset_keeps_host_timeout_and_other_plugin_values(tmp_path):
    (tmp_path / "config.yaml").write_text("auxiliary:\n  console_next_prompt:\n    timeout: 123\n    provider: openai\n    model: example\nplugins:\n  entries:\n    eternia-harness:\n      settings:\n        other: untouched\n", encoding="utf-8")
    settings = SuggestionSettings(tmp_path)
    settings.write({"expected_revision": settings.read()["settings_revision"], "auxiliary_override": None})
    from hermes_cli.config import read_user_config_raw
    with suggestion_home(tmp_path):
        raw = read_user_config_raw()
    assert raw["auxiliary"]["console_next_prompt"]["timeout"] == 123
    assert "model" not in raw["auxiliary"]["console_next_prompt"]
    assert raw["plugins"]["entries"]["eternia-harness"]["settings"]["other"] == "untouched"


def test_invalid_saved_tuning_still_allows_independent_disable(tmp_path):
    (tmp_path / "config.yaml").write_text("plugins:\n  entries:\n    eternia-harness:\n      settings:\n        console_suggestions_enabled: true\n        console_suggestions_cooldown_seconds: bad\n", encoding="utf-8")
    settings = SuggestionSettings(tmp_path)
    current = settings.read()
    assert current["enabled"] is False and current["cooldown_seconds"] == 3
    assert current["reason"] == "config_invalid" and current["writable"]
    assert settings.write({"expected_revision": current["settings_revision"], "enabled": False})["enabled"] is False


def test_malformed_config_fail_closed_without_overwrite(tmp_path):
    path = tmp_path / "config.yaml"
    original = "plugins: [broken"
    path.write_text(original, encoding="utf-8")
    settings = SuggestionSettings(tmp_path)
    assert settings.read()["enabled"] is False
    with pytest.raises(Exception):
        settings.write({"expected_revision": "invalid", "enabled": True})
    assert path.read_text(encoding="utf-8") == original


def test_receipts_prevent_repeat_calls_after_payload_eviction_and_restart(tmp_path):
    store = SuggestionStore(tmp_path / "derived.db", payload_limit=1)
    for number in range(3):
        assert store.claim(str(number), {"session_id": str(number)}, time.time()) == "claimed"
        store.finish(str(number), text="What next?")
    reopened = SuggestionStore(store.path)
    assert reopened.read("0")["state"] == "none"
    assert reopened.claim("0", {"session_id": "0"}, time.time()) == "existing"
    assert reopened.read("2")["text"] == "What next?"


def test_capacity_retains_live_receipts_and_provider_slots(tmp_path):
    store = SuggestionStore(tmp_path / "derived.db", receipt_limit=2)
    assert store.claim("a", {"session_id": "a"}, time.time()) == "claimed"
    assert store.claim("b", {"session_id": "a"}, time.time()) == "capacity_limited"
    assert store.claim("b", {"session_id": "b"}, time.time()) == "claimed"
    assert store.claim("c", {"session_id": "c"}, time.time()) == "capacity_limited"
    store.finish("a", text="Next?")
    assert store.claim("c", {"session_id": "c"}, time.time()) == "capacity_limited"
    assert store.claim("a", {"session_id": "a"}, time.time()) == "existing"


@pytest.fixture
def service(tmp_path, monkeypatch):
    monkeypatch.setattr(lifecycle, "validate_operator_conversation", lambda subject: None)
    monkeypatch.setattr(lifecycle, "authorize_call", lambda *a, **kw: SimpleNamespace(ok=True))
    source = {"source_turn_id": "turn", "source_revision": "revision", "source_time": time.time(),
        "messages": [{"role": "user", "content": "Question"}, {"role": "assistant", "content": "Answer"}]}
    svc = lifecycle.ConsoleSuggestions(tmp_path, context_reader=lambda *a: deepcopy(source),
        generator=lambda messages: {"text": "[foo] を説明して", "usage": {}})
    yield svc, source
    svc.close()


def subject(session="chat"):
    return dict(zip(lifecycle.IDENTITY_KEYS, ("install", "workspace", "persona", "instance", session, "account")))


def caller(connection="connection"):
    return SimpleNamespace(connection_key=connection, caller=None, emit=lambda frame: None, push=lambda *a: None)


def enable(svc):
    return svc.settings_write({"expected_revision": svc.settings_read()["settings_revision"], "enabled": True, "cooldown_seconds": 0})


def observed(svc, who):
    sub = lifecycle.Subscription("sub", caller(), who)
    svc.subscriptions[sub.id] = sub


def test_off_never_reads_context_or_creates_cache_or_worker(service):
    svc, _ = service
    svc.context_reader = lambda *a: pytest.fail("off read history")
    assert svc.subscribe(caller(), subject())["state"] == "disabled"
    assert svc.read(subject())["state"] == "disabled"
    assert svc.pool is None
    assert not svc.store.path.exists()
    assert svc.subscribe(caller())["enabled"] is False
    assert svc.pool is None


def test_disable_during_context_read_does_not_dispatch(service):
    svc, source = service
    enable(svc)
    observed(svc, subject())
    def read(*args):
        svc.settings_write({"expected_revision": svc.settings_read()["settings_revision"], "enabled": False})
        return deepcopy(source)
    svc.context_reader = read
    svc.generator = lambda *a: pytest.fail("disabled before dispatch")
    svc._work(subject())
    assert svc.settings_read()["enabled"] is False


def test_shared_observer_recovers_and_off_releases_it(service):
    svc, _ = service
    attaches, releases = [], []
    def observe(frame, dropped):
        attaches.append(dropped)
        return lambda: releases.append(True)
    svc.observe = observe
    svc.context_reader = lambda *a: {"reason": "turn_active"}
    enable(svc)
    svc.subscribe(caller(), subject())
    assert len(attaches) == 1
    attaches[0]()
    assert len(releases) == 1
    svc.settings_read()
    assert len(attaches) == 2
    svc.settings_write({"expected_revision": svc.settings_read()["settings_revision"], "enabled": False})
    assert len(releases) == 2
    assert not svc.store.path.exists()
    assert svc.subscribe(caller())["enabled"] is False


def test_completed_source_generates_once_and_read_rechecks_revision(service):
    svc, source = service
    enable(svc)
    observed(svc, subject())
    calls = []
    svc.generator = lambda messages: calls.append(messages) or {"text": "好", "usage": {}}
    svc._work(subject())
    ready = svc.read(subject())
    assert ready["state"] == "ready" and ready["text"] == "好"
    svc._work(subject())
    assert len(calls) == 1
    source["source_revision"] = "rewound"
    assert svc.read(subject())["state"] == "none"


def test_disable_during_call_discards_result_and_keeps_attempt_receipt(service):
    svc, _ = service
    enable(svc)
    observed(svc, subject())
    def generate(messages):
        svc.settings_write({"expected_revision": svc.settings_read()["settings_revision"], "enabled": False})
        return {"text": "Should never appear", "usage": {}}
    svc.generator = generate
    svc._work(subject())
    assert svc.read(subject())["state"] == "disabled"
    assert not svc.subscriptions
    with svc.store.transaction() as db:
        row = db.execute("SELECT state,text FROM attempts").fetchone()
        assert tuple(row) == ("none", None)


def test_dismiss_revision_does_not_write_transcript(service):
    svc, _ = service
    enable(svc)
    observed(svc, subject())
    svc._work(subject())
    entry = svc.read(subject())
    with pytest.raises(SuggestionRefused, match="stale_revision"):
        svc.dismiss(subject(), {"entry_id": entry["entry_id"], "expected_revision": 99})
    result = svc.dismiss(subject(), {"entry_id": entry["entry_id"], "expected_revision": entry["entry_revision"]})
    assert result["state"] == "none" and "text" not in result
    assert not (svc.home / "state.db").exists()


def test_task_registration_uses_host_defaults_without_model_override(tmp_path):
    calls = []
    context = SimpleNamespace(register_auxiliary_task=lambda *a, **kw: calls.append((a, kw)), on_unload=lambda callback: callback())
    with suggestion_home(tmp_path):
        register_suggestion_task(context)
    assert calls[0][0] == ("console_next_prompt",)
    assert "defaults" not in calls[0][1]
