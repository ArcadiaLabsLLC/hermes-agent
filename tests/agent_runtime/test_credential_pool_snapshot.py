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


def _counting_auth_reads(monkeypatch):
    import agent.credential_pool as credential_pool
    import hermes_cli.auth as auth

    reads = []
    real = auth._load_auth_store

    def counted(*args, **kwargs):
        reads.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(auth, "_load_auth_store", counted)
    if hasattr(credential_pool, "_load_auth_store"):
        monkeypatch.setattr(credential_pool, "_load_auth_store", counted)
    return reads


def test_load_pool_reads_auth_once_per_provider_inside_a_scope(monkeypatch):
    from agent.credential_pool import load_pool

    reads = _counting_auth_reads(monkeypatch)
    with credential_pool_snapshot():
        one_load = load_pool("openrouter")
    per_load = len(reads)
    assert per_load >= 1
    reads.clear()
    with credential_pool_snapshot():
        pools = [load_pool("openrouter") for _ in range(20)]
    assert len(reads) == per_load  # the first load reads; nineteen answer from the memo
    assert all(pool is pools[0] for pool in pools)
    assert pools[0] is not one_load  # each scope starts empty
    reads.clear()
    unscoped = [load_pool("openrouter") for _ in range(20)]
    assert len(reads) >= 20 * per_load
    assert unscoped[0] is not unscoped[1]
