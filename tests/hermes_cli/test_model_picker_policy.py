"""Route provenance at the descriptor seam; no fixed upstream model counts."""
import json
from pathlib import Path

import pytest

from hermes_cli import codex_models, provider_catalog
from hermes_cli.model_picker_policy import model_picker_policy_for


def test_descriptor_projection_matches_shared_wire_fixture(monkeypatch):
    fixture = json.loads((Path(__file__).parents[1] / "fixtures/model_picker_policy_v1.json").read_text())
    ids = fixture["policies"]["openai-codex"]["model_ids"]
    calls = []

    def discovery(*args, **kwargs):
        calls.append((args, kwargs))
        return list(ids)

    monkeypatch.setattr(codex_models, "get_codex_model_ids", discovery)
    # The override-only rows exercise the same _emit seam without importing
    # optional provider plugins or credentials as part of the fixture setup.
    monkeypatch.setattr(provider_catalog, "provider_catalog", lambda: [])
    rows = {row["id"]: row for row in provider_catalog.provider_login_catalog()}
    for slug, policy in fixture["policies"].items():
        assert rows[slug]["model_picker"] == policy
    assert calls == [((), {})]  # no token argument, not even a credential read
    assert rows["anthropic"]["flows"] == ["external"]
    assert rows["anthropic"]["model_picker"]["billing_mode"] == "catalog"

    def fail():
        raise RuntimeError("secret-token-must-not-leave-this-process")

    monkeypatch.setattr(codex_models, "get_codex_model_ids", fail)
    failed = {row["id"]: row for row in provider_catalog.provider_login_catalog()}
    policy = failed["openai-codex"]["model_picker"]
    assert policy["catalog_mode"] == "unavailable"
    assert "model_ids" not in policy
    assert policy["error"] == "RuntimeError"
    assert "secret-token" not in json.dumps(failed)
    assert failed["anthropic"] == rows["anthropic"]


@pytest.mark.parametrize("ids, mode", [(None, "unavailable"), ([""], "unavailable"), ([1], "unavailable"), ([], "compatibility")])
def test_malformed_discovery_is_not_an_empty_or_reference_catalog(monkeypatch, ids, mode):
    monkeypatch.setattr(codex_models, "get_codex_model_ids", lambda: ids)
    policy = model_picker_policy_for("openai-codex")
    assert policy["catalog_mode"] == mode
    assert ("model_ids" in policy) == (mode == "compatibility")


def test_offline_canonical_catalog_resolves_codex_home_at_call_time(tmp_path, monkeypatch):
    # Real discovery, real imports and temp files. No account, token, network,
    # or production HOME. This catches a process-global policy cache as well
    # as a wrapper that silently switched to live discovery.
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))
    network_calls = []

    def unexpected_network(*args, **kwargs):
        network_calls.append((args, kwargs))
        raise AssertionError("offline projection must not call the API")

    monkeypatch.setattr(codex_models, "_fetch_models_from_api", unexpected_network)
    homes = [tmp_path / "a", tmp_path / "b"]
    for home in homes:
        home.mkdir()
        (home / "config.toml").write_text(f'model = "example-{home.name}"\n')
        (home / "models_cache.json").write_text(json.dumps({"models": [{"slug": f"cache-{home.name}"}]}))
    for home, other in [(homes[0], homes[1]), (homes[1], homes[0]), (homes[0], homes[1])]:
        monkeypatch.setenv("CODEX_HOME", str(home))
        expected = codex_models.get_codex_model_ids()
        actual = model_picker_policy_for("openai-codex")
        assert actual["catalog_mode"] == "compatibility"
        assert actual["model_ids"] == expected
        assert f"example-{home.name}" in actual["model_ids"]
        assert f"cache-{home.name}" in actual["model_ids"]
        assert f"example-{other.name}" not in actual["model_ids"]
        assert f"cache-{other.name}" not in actual["model_ids"]
    assert not network_calls
