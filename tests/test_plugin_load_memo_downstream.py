"""tests/_downstream/plugin_load_memo.py: one load-deadline config read per discovery sweep."""

from __future__ import annotations

from hermes_cli import plugins

from tests._downstream import plugin_load_memo as memo


def test_a_sweep_reads_the_deadline_once_and_the_next_sweep_reads_it_again():
    """Killing mutation: drop ``_SWEEP.set([])`` from ``_sweep_scope`` (every load reads config again)."""

    reads = []
    values = iter([3.0, 7.0, 9.0])

    def real():
        reads.append(1)
        return next(values)

    resolve = memo._memo_timeout(real)
    seen = []
    sweep = memo._sweep_scope(lambda self: seen.extend(resolve() for _ in range(5)))
    sweep(None)
    assert seen == [3.0] * 5 and len(reads) == 1
    sweep(None)
    assert seen[5:] == [7.0] * 5 and len(reads) == 2
    assert resolve() == 9.0 and len(reads) == 3  # outside a sweep: the real resolver, no memo


def test_a_real_discovery_reads_config_for_the_deadline_once(monkeypatch):
    """A real bundled discovery: the resolver's config reads are 1, not one per loaded plugin.
    Killing mutation: drop the ``_discover_and_load_inner`` wrap from ``install_if_imported``."""

    from hermes_cli import config

    assert memo.install_if_imported()
    real_read = config.load_config_readonly
    resolver_reads = []

    def counting():
        import inspect
        if inspect.stack()[1].function == "_resolve_plugin_load_timeout":
            resolver_reads.append(1)
        return real_read()

    monkeypatch.setattr(config, "load_config_readonly", counting)
    plugins._reset_plugin_managers_for_tests()
    plugins.discover_plugins()
    loaded = [p for p in plugins.get_plugin_manager()._plugins.values() if not p.deferred]
    assert len(loaded) > 2, "too few loads for the comparison to prove anything"
    assert len(resolver_reads) == 1
