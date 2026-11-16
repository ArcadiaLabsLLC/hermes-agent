"""Tests run with the checkout-launcher pin OFF (``agent_runtime/terminal_pinned_hermes.py``).

``scripts/run-in-hermes-env`` publishes the checkout's own ``.hermes/bin``, so with the pin on every
test that fakes ``shutil.which`` for ``_resolve_hermes_bin_dir`` would be handed the test runner's
launchers instead. A sealed payload's pin is upstream's and stays on. Tests of the pin itself turn it
back on (``tests/tools/test_terminal_pinned_hermes.py``).
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _terminal_pinned_hermes_off(monkeypatch):
    monkeypatch.setattr("agent_runtime.terminal_pinned_hermes.PIN_OWN_LAUNCHERS", False)
