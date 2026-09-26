"""The isolation fixtures' guarantee is about the NEXT test — so each is pinned by a PAIR.

``tests/_downstream/hermes_cli_conftest/isolation.py`` promises that no test's
state outlives it. Nothing exercised two of those fixtures before lane B5
(2026-09-25). Each case below is two tests in FILE ORDER: the first leaves the
pollution behind on purpose, the second asserts it did not survive. Run alone,
the second test proves only the negative; the pair is the positive control.
"""

from __future__ import annotations

import sys
import types

from hermes_cli import web_server

# A synthetic package + child module, present in sys.modules BEFORE any test
# runs — the shape ``import pkg.child`` leaves: a sys.modules row AND an
# attribute on the parent package. Synthetic so the pair costs no real import.
_PKG = types.ModuleType("_b5_isolation_pkg")
_PKG.__path__ = []
_CHILD = types.ModuleType("_b5_isolation_pkg.child")
_PKG.child = _CHILD
sys.modules["_b5_isolation_pkg"] = _PKG
sys.modules["_b5_isolation_pkg.child"] = _CHILD

_STATE_BEFORE: dict = {}


def test_1_a_test_replaces_a_module_and_its_parent_binding():
    """Pollution, on purpose: what a del-then-reimport leaves behind."""

    replacement = types.ModuleType("_b5_isolation_pkg.child")
    sys.modules["_b5_isolation_pkg.child"] = replacement
    _PKG.child = replacement
    assert sys.modules["_b5_isolation_pkg.child"] is not _CHILD


def test_2_the_next_test_sees_the_original_module_by_both_spellings():
    """Both halves restored: the sys.modules row AND the parent attribute
    (``from pkg import child`` reads the attribute, not sys.modules)."""

    assert sys.modules["_b5_isolation_pkg.child"] is _CHILD
    assert _PKG.child is _CHILD


def test_3_a_test_flips_the_shared_app_state():
    """Pollution, on purpose: the gate tests leave ``auth_required`` set."""

    _STATE_BEFORE.update(dict(web_server.app.state._state))
    web_server.app.state.auth_required = True
    assert web_server.app.state._state != _STATE_BEFORE


def test_4_the_next_test_starts_on_the_pristine_app_state():
    """The reset happens at SETUP, so this test starts on the baseline."""

    assert dict(web_server.app.state._state) == _STATE_BEFORE
