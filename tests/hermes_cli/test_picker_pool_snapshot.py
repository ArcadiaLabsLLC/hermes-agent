"""One model-picker build loads each provider's credential pool once (``pool_snapshot``)."""

from agent import credential_pool
from hermes_cli import auth


def _count_auth_reads(monkeypatch):
    reads = []
    real = auth._load_auth_store

    def counted(*args, **kwargs):
        reads.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(auth, "_load_auth_store", counted)
    monkeypatch.setattr(credential_pool, "_load_auth_store", counted)
    return reads


def test_a_snapshot_answers_repeat_checks_without_rereading_auth(monkeypatch):
    from hermes_cli.model_switch_providers import _credential_pool_is_usable

    reads = _count_auth_reads(monkeypatch)
    _credential_pool_is_usable("openrouter", for_picker=True, pool_snapshot={})
    per_check = len(reads)
    assert per_check >= 1

    reads.clear()
    snapshot: dict = {}
    for _ in range(20):
        _credential_pool_is_usable("OpenRouter", for_picker=True, pool_snapshot=snapshot)
    assert len(reads) == per_check
    assert list(snapshot) == ["openrouter"]

    reads.clear()
    for _ in range(20):
        _credential_pool_is_usable("openrouter", for_picker=True)
    assert len(reads) >= 20 * per_check


def test_one_picker_build_loads_each_provider_pool_once(monkeypatch):
    from hermes_cli.model_switch import list_authenticated_providers
    from hermes_cli import model_switch_providers

    real_check = model_switch_providers._credential_pool_is_usable
    real_load = credential_pool.load_pool
    asked, loaded, inside = [], [], []

    def check(provider, **kwargs):
        asked.append(provider.strip().lower())
        inside.append(1)
        try:
            return real_check(provider, **kwargs)
        finally:
            inside.pop()

    def load(provider, *args, **kwargs):
        if inside:  # loads the pool checks cause; token paths elsewhere read live
            loaded.append(provider.strip().lower())
        return real_load(provider, *args, **kwargs)

    monkeypatch.setattr(model_switch_providers, "_credential_pool_is_usable", check)
    monkeypatch.setattr(credential_pool, "load_pool", load)
    list_authenticated_providers(for_picker=True, non_blocking_catalogs=True,
                                 probe_custom_providers=False)
    assert len(asked) > len(set(asked)), "no provider was checked twice: the build proves nothing"
    assert loaded, "the checks loaded no pool"
    assert len(loaded) == len(set(loaded)), sorted(p for p in set(loaded) if loaded.count(p) > 1)


def test_one_picker_build_reads_auth_json_once_for_its_store_probes(monkeypatch):
    """The ``auth.json`` presence probes (``_auth_store_has_provider`` / ``_raw_pool_usable``) ask
    once per provider row; one build answers them all from one read (``_PickerBuild.auth_store``)."""
    import sys

    from hermes_cli.model_switch import list_authenticated_providers

    probes = {"_auth_store_has_provider", "_raw_pool_usable", "loaded_auth_store"}
    callers = []
    real = auth._load_auth_store

    def counted(*args, **kwargs):
        callers.append(sys._getframe(1).f_code.co_name)
        return real(*args, **kwargs)

    monkeypatch.setattr(auth, "_load_auth_store", counted)
    list_authenticated_providers(for_picker=True, non_blocking_catalogs=True,
                                 probe_custom_providers=False)
    probe_reads = [c for c in callers if c in probes]
    assert len(probe_reads) == 1, len(probe_reads)


def test_a_given_store_answers_the_probes_without_reading(monkeypatch):
    from hermes_cli.model_switch_providers import _auth_store_has_provider, _raw_pool_usable

    reads = _count_auth_reads(monkeypatch)
    store = {"providers": {"nous": {}}, "credential_pool": {}}
    assert _auth_store_has_provider("nous", store=store)
    assert not _auth_store_has_provider("zai", store=store)
    assert not _raw_pool_usable("openrouter", store=store)
    assert reads == []
