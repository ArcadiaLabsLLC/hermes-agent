"""Unpin ``hermes_state.DEFAULT_DB_PATH`` for the ids the table marks (lane 1011-M4, row L7.01).

``tests/conftest.py`` step 3b pins ``hermes_state.DEFAULT_DB_PATH`` at the hermetic home's
store, but only when ``hermes_state`` is ALREADY imported when the fixture runs. The pin
wins over ``get_hermes_home()`` inside ``hermes_state._default_db_path()``, so a test that
proves an argless ``SessionDB()`` resolves through a PROFILE scope passes alone (nothing
imported ``hermes_state`` yet) and reds after any earlier test in the same process did
(measured 2026-10-10, red on pure tag v0.21.6 ``818c13be1d`` too: the multiplex
residue-parity and routing-authz files, each red after the other, green alone).

For a marked test this fixture restores the import-time sentinel, so the store resolves
at call time through ``get_hermes_home()`` -- which the hermetic fixture has already
redirected -- exactly as upstream's own ``tests/gateway/test_housekeeping_profile_scope.py``
``two_homes`` fixture does. The fence keeps its other half: an unpinned store that does
not resolve inside the hermetic home fails the test before its body runs.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from tests._downstream.id_markers.reasons import (
    STATE_DB_RESOLVES_THROUGH_SCOPE_MARK as _MARK,
)


@pytest.fixture(autouse=True)
def _state_db_resolves_through_scope(request, monkeypatch, _hermetic_environment):
    if request.node.get_closest_marker(_MARK) is None:
        return
    hermes_state = sys.modules.get("hermes_state")
    if hermes_state is None:
        return  # not imported yet: step 3b pinned nothing, the import computes a live default
    monkeypatch.setattr(hermes_state, "DEFAULT_DB_PATH", hermes_state._IMPORT_DEFAULT_DB_PATH)
    home = Path(os.environ["HERMES_HOME"]).resolve()
    resolved = Path(hermes_state._default_db_path()).resolve()
    assert resolved.is_relative_to(home), f"unpinned store escaped the hermetic home: {resolved}"
