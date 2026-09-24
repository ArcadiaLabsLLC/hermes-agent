"""Fork-owned half of ``tests/gateway/test_mirror.py``.

Upstream's ``test_fallback_follows_active_profile_home`` ends with
``monkeypatch.undo()``, which unwinds the root conftest's hermetic pins with its
own and is red under the fork's ``_shared_monkeypatch_pin_tripwire``; it is a
skip row in ``tests/_downstream/id_markers.py``. This is the same test with the
env pins in a scoped context. ``_write_index`` is upstream's.
"""

from __future__ import annotations

import importlib

import pytest

import gateway.mirror as mirror_mod
from tests.gateway.test_mirror import TestSessionsIndexProfileScoping as _UpstreamProfileScoping


class TestSessionsIndexProfileScoping:
    _write_index = staticmethod(_UpstreamProfileScoping._write_index)

    def test_fallback_follows_active_profile_home(self, tmp_path, monkeypatch):
        """A profile switched in after import must be read, not the launch profile's index.

        The module captures ``sessions.json`` under the home that was live at import. Under the
        multiplexed gateway one process serves every profile, so a lookup for another profile
        must not resolve against the launch profile's index and return its session id.
        """
        launch_home, active_home = tmp_path / "launch", tmp_path / "active"
        self._write_index(launch_home, "sess_launch")
        self._write_index(active_home, "sess_active")

        # A SCOPED context, not ``monkeypatch.undo()``: ``undo()`` takes no argument and
        # drops every patch on the shared per-test instance, including the root conftest's
        # autouse hermetic pins (HERMES_HOME redirected to a tempdir, credential env vars
        # blanked). Everything after it would run against the operator's live root — the
        # 2026-08-17 leak. ``tests/agent_runtime/test_no_midtest_monkeypatch_undo.py`` gates it.
        try:
            with pytest.MonkeyPatch.context() as patched:
                # Re-import the module with the launch home live: the import-time capture.
                patched.setenv("HERMES_HOME", str(launch_home))
                importlib.reload(mirror_mod)
                # A request for a different profile is now served by the same process.
                patched.setenv("HERMES_HOME", str(active_home))
                assert mirror_mod._find_session_id("telegram", "12345") == "sess_active"
        finally:
            importlib.reload(mirror_mod)
