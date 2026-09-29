"""Owner 2026-09-29: harness processes keep upstream's startup venv sync off.

The eternia-harness plugin setdefault()s ``HERMES_DISABLE_LAZY_INSTALLS=1``; upstream's
``hermes_cli.venv_sync`` reads it and skips its sync-and-relaunch. The operator's own
value is the opt-out.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path


def _register_plugin():
    path = Path(__file__).resolve().parents[2] / "plugins" / "eternia-harness" / "__init__.py"
    spec = importlib.util.spec_from_file_location("_eternia_harness_venv_sync", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    class _NullCtx:
        def __getattr__(self, name):
            return lambda *a, **k: None

    module.register(_NullCtx())


def test_the_plugin_keeps_startup_venv_sync_off(monkeypatch):
    import os

    monkeypatch.delenv("HERMES_DISABLE_LAZY_INSTALLS", raising=False)
    _register_plugin()
    assert os.environ["HERMES_DISABLE_LAZY_INSTALLS"] == "1"


def test_the_operator_value_wins(monkeypatch):
    """Positive control: same registration, operator set ``0`` first -> kept."""
    import os

    monkeypatch.setenv("HERMES_DISABLE_LAZY_INSTALLS", "0")
    _register_plugin()
    assert os.environ["HERMES_DISABLE_LAZY_INSTALLS"] == "0"
