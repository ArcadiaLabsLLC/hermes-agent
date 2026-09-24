"""Fork-owned tests moved out of ``tests/tools/test_browser_orphan_reaper.py``.

They pin the reaper's environ binding as an IDENTITY question
(``path_identity.denotes_same_file``). ``_FakeProc`` / ``_run`` and the autouse
``_isolate_sessions`` fixture are upstream's, imported by name.
"""

from __future__ import annotations

import pytest

from tests.tools.test_browser_orphan_reaper import (  # noqa: F401 — upstream names the moved tests use
    TestReaperIdentityGuard as _UpstreamReaperIdentityGuard,
    _isolate_sessions,
)


class TestReaperIdentityGuard:
    _FakeProc = _UpstreamReaperIdentityGuard._FakeProc
    _run = _UpstreamReaperIdentityGuard._run

    def test_daemon_bound_via_a_symlinked_socket_dir_is_reapable(self, tmp_path):
        """The environ binding is an identity question, not a spelling one.

        The daemon publishes whatever spelling it was started with; the reaper
        builds its own. ``normpath(a) == normpath(b)`` folds neither symlinks
        nor (on Windows) case, so the reaper could refuse to clean up its own
        daemon and leave the socket dir behind forever. It now asks
        ``path_identity.denotes_same_file``.
        """
        real = tmp_path / "agent-browser-h_sess123456"
        real.mkdir()
        link = tmp_path / "linked-socket-dir"
        try:
            link.symlink_to(real, target_is_directory=True)
        except (OSError, NotImplementedError):
            pytest.skip("symlink creation unavailable for this user")

        proc = self._FakeProc(
            name="agent-browser-linux-x64",
            cmdline=["agent-browser-linux-x64", "daemon"],  # no dir in cmd
            environ={"AGENT_BROWSER_SOCKET_DIR": str(link)},
        )
        assert self._run(proc, str(real)) is True
    @pytest.mark.parametrize(
        "env_value,why",
        [
            ("", "no binding published at all"),
            ("/tmp/agent-browser-h_OTHER999", "another session's dir"),
            ("/tmp/agent-browser-h_sess123456-evil", "extends our name; not our dir"),
            ("/tmp/agent-browser-h_sess12345", "our name truncated; not our dir"),
            ("/tmp", "our dir's parent, not our dir"),
        ],
    )
    def test_environ_binding_rejection_table(self, env_value, why):
        """Nothing beyond the intended spelling became reapable.

        Resolution-based identity matches MORE spellings than a string compare
        by construction, so the whole refusal set is re-pinned here — including
        the two shapes a prefix-flavoured implementation would wave through
        (``<dir>-evil`` and a truncation of ``<dir>``), and the parent
        directory, which contains our dir but is not it.
        """
        socket_dir = "/tmp/agent-browser-h_sess123456"
        proc = self._FakeProc(
            name="agent-browser",
            cmdline=["agent-browser", "daemon"],  # deliberately no dir in cmd
            environ={"AGENT_BROWSER_SOCKET_DIR": env_value},
        )
        assert self._run(proc, socket_dir) is False, why
    def test_unreadable_environ_still_fails_closed(self):
        """``environ()`` can be denied even same-user; ambiguity means refuse."""
        socket_dir = "/tmp/agent-browser-h_sess123456"
        proc = self._FakeProc(
            name="agent-browser",
            cmdline=["agent-browser", "daemon"],
            raise_environ=True,
        )
        assert self._run(proc, socket_dir) is False
