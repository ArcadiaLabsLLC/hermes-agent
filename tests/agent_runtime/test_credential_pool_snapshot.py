"""The credential-pool snapshot scope: memo inside, nothing outside (RT-PICKER-AUTH-REREAD)."""
from agent_runtime.credential_pool_snapshot import credential_pool_snapshot, snapshot_get, snapshot_put


def test_outside_a_scope_nothing_is_remembered():
    pool = object()
    assert snapshot_put("openrouter", pool) is pool
    assert snapshot_get("openrouter") is None


def test_inside_a_scope_put_then_get_returns_the_object_and_exit_clears_it():
    pool = object()
    with credential_pool_snapshot():
        snapshot_put("OpenRouter ", pool)
        assert snapshot_get("openrouter") is pool
        with credential_pool_snapshot():
            assert snapshot_get("openrouter") is pool  # nested scopes share the outer memo
    assert snapshot_get("openrouter") is None
    with credential_pool_snapshot():
        assert snapshot_get("openrouter") is None


def test_the_memo_is_per_hermes_home(tmp_path, monkeypatch):
    pool = object()
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "a"))
    with credential_pool_snapshot():
        snapshot_put("openrouter", pool)
        monkeypatch.setenv("HERMES_HOME", str(tmp_path / "b"))
        assert snapshot_get("openrouter") is None
