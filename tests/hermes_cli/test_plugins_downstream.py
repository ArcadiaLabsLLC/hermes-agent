"""Fork-owned tests moved out of ``tests/hermes_cli/test_plugins.py`` (seam Stage 5).

Same names, same bodies; the upstream file keeps only upstream's tests.
"""

import logging
from hermes_cli.plugins import (
    PluginManager,
)

from tests.hermes_cli.test_plugins import (  # noqa: F401 — upstream names the moved tests use
    _make_plugin_dir,
)


class TestPluginDiscovery:
    def test_discovery_completion_line_reports_its_own_duration(
        self, tmp_path, monkeypatch, caplog
    ):
        """BW-0: the discovery sweep says what it cost.

        The 2026-08-17 cold Mission Control boot logged TWO full 54-plugin
        discovery passes — one per concurrently-spawned child, both on the import
        path, both before either child emitted its ``booting`` frame — and neither
        said how long it took. The share of that boot's 20.4 s import tax owed to
        discovery could only be bracketed from the wall-clock stamps of the first
        and last per-plugin registration lines, which is not the same number.

        Anti-vacuity. *Mutation:* drop the ``elapsed_ms`` argument (or the whole
        timing) from the completion line. *Probed field:* the ``elapsed_ms=``
        token in the emitted message — no other part of this sweep writes that
        token, and no other log line in the run carries it, so the mutant has no
        second way to satisfy the assertion. Deliberately NOT an assertion on the
        VALUE: any threshold would pass on a fast machine under a mutant that
        stamps a constant and fail spuriously on a loaded one.
        """
        plugins_dir = tmp_path / "hermes_test" / "plugins"
        _make_plugin_dir(plugins_dir, "timed_plugin")
        monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes_test"))

        mgr = PluginManager()
        with caplog.at_level(logging.INFO, logger="hermes_cli.plugins"):
            mgr.discover_and_load()

        completions = [
            record.getMessage()
            for record in caplog.records
            if "Plugin discovery complete" in record.getMessage()
        ]
        assert len(completions) == 1, completions
        assert "elapsed_ms=" in completions[0]


class TestPluginHooks:
    """Fork half of upstream's ``TestPluginHooks::test_request_hooks_are_invokeable``.

    The bundled eternia-harness plugin (kind ``backend``, auto-loaded) registers
    ``post_api_request`` for the usage ledger (seam MOVE-A group 12), so upstream's
    ``has_hook("post_api_request") is False`` cannot hold with the real bundled
    tree; the upstream id is a strict xfail in ``tests/_downstream/id_markers/``.
    """

    def _request_hook_manager(self, tmp_path, monkeypatch, *, bundled=None):
        from hermes_cli import plugins as plugins_mod

        plugins_dir = tmp_path / "hermes_test" / "plugins"
        _make_plugin_dir(
            plugins_dir, "request_hook",
            register_body=(
                'ctx.register_hook("pre_api_request", '
                'lambda **kw: {"seen": kw.get("api_call_count"), '
                '"mc": kw.get("message_count"), "tc": kw.get("tool_count")})'
            ),
        )
        monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes_test"))
        if bundled is not None:
            monkeypatch.setattr(plugins_mod, "get_bundled_plugins_dir", lambda: bundled)
        mgr = PluginManager()
        mgr.discover_and_load()
        return mgr

    def test_request_hooks_are_invokeable_without_the_bundled_tree(self, tmp_path, monkeypatch):
        """Upstream's assertions, verbatim, with the bundled plugins out of the sweep."""
        empty_bundled = tmp_path / "bundled"
        empty_bundled.mkdir()
        mgr = self._request_hook_manager(tmp_path, monkeypatch, bundled=empty_bundled)

        assert mgr.has_hook("pre_api_request") is True
        assert mgr.has_hook("post_api_request") is False
        results = mgr.invoke_hook(
            "pre_api_request",
            session_id="s1",
            task_id="t1",
            model="test",
            api_call_count=2,
            message_count=5,
            tool_count=3,
            approx_input_tokens=100,
            request_char_count=400,
            max_tokens=8192,
        )
        assert results == [{"seen": 2, "mc": 5, "tc": 3}]

    def test_the_harness_is_the_only_post_api_request_hook_in_the_bundled_tree(
        self, tmp_path, monkeypatch
    ):
        """Positive control: the real bundled tree adds exactly the harness's ledger hook."""
        mgr = self._request_hook_manager(tmp_path, monkeypatch)

        hooks = mgr._hooks.get("post_api_request", [])
        assert [hook.__name__ for hook in hooks] == ["record_usage_ledger_row"]
