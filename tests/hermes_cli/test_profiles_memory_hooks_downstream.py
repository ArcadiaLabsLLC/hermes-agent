"""Fork half of upstream's ``test_an_unreadable_config_backend_never_fails_create``.

Upstream's test makes ``hermes_cli.config.load_config_readonly`` raise
``ConfigBackendUnavailable`` for the whole ``create_profile`` call, meaning to reach the
memory hook's effective-config read. In the fork, plugin discovery reads its enable/disable
lists through ``load_config_readonly`` too (upstream-footprint ledger,
``hermes_cli/plugins_discovery.py``: reader moved), and v0.23.1's ``create_profile`` runs
plugin discovery before the hook (``profile_channels.strip_channel_settings``), so the
backend error escapes there instead (a ``SystemExit``, not caught by ``except Exception``).
The upstream id carries an xfail row in ``tests/_downstream/id_markers/fork_marks.py``;
here the backend is unreadable only while the memory hook runs, which is the claim.

Killing mutation (applied, red recorded, reverted): narrow the hook's
``except (Exception, SystemExit)`` in ``profile_memory_config.notify_memory_provider`` to
``except Exception`` -> this test reds (the SystemExit escapes create).
"""

from __future__ import annotations

from tests.hermes_cli.test_profiles_memory_hooks import _select, profile_env  # noqa: F401  upstream fixture


def test_an_unreadable_config_backend_in_the_hook_never_fails_create(profile_env, monkeypatch, caplog):  # noqa: F811
    import hermes_cli.config as config_mod
    import hermes_cli.profile_memory_config as hook_mod
    from hermes_cli.config_backend import ConfigBackendUnavailable
    from hermes_cli.profiles import create_profile

    readable = config_mod.load_config_readonly
    in_hook: list[bool] = []

    def backend(*a, **k):
        if in_hook:
            raise ConfigBackendUnavailable("backend down")
        return readable(*a, **k)

    notify = hook_mod.notify_memory_provider

    def hook(*a, **k):
        in_hook.append(True)
        try:
            return notify(*a, **k)
        finally:
            in_hook.pop()

    monkeypatch.setattr(config_mod, "load_config_readonly", backend)
    monkeypatch.setattr(hook_mod, "notify_memory_provider", hook)
    _select(profile_env, "recorder")  # an external provider, so the hook reaches the effective-config read
    with caplog.at_level("WARNING", logger="hermes_cli.profile_memory_config"):
        assert create_profile("work", clone_config=True, no_alias=True).is_dir()
    assert "profile hook failed" in caplog.text
