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
