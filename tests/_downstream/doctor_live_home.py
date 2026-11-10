"""Keep ``hermes_cli.doctor``'s home names live between tests (FH-FOOTPRINT-FORK-TEST-HUNKS-OUT).

The fork's doctor serves ``HERMES_HOME`` and ``_DHH`` through a module ``__getattr__`` (PR #125260:
the home is resolved at call time), so upstream's helpers read the live home through
``from hermes_cli.doctor import HERMES_HOME`` and upstream's tests still reach it with
``monkeypatch.setattr(doctor, "HERMES_HOME", ...)``. The undo of that patch, though, re-binds the
LIVE value it read as a real module attribute, freezing a dead tmp home for every later test in the
process. Dropping both names from the module dict before each test hands the lookup back to
``__getattr__``; a test's own patch lands after this hook and is unaffected.
"""

from __future__ import annotations

import sys

import pytest

_LIVE_NAMES = ("HERMES_HOME", "_DHH")


@pytest.hookimpl(specname="pytest_runtest_setup", tryfirst=True)
def pytest_runtest_setup_doctor_live_home(item):  # pytest hook
    doctor = sys.modules.get("hermes_cli.doctor")
    if doctor is not None and getattr(doctor, "_LIVE_HOME_NAMES", None):
        for name in _LIVE_NAMES:
            doctor.__dict__.pop(name, None)
