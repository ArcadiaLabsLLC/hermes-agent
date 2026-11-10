"""Fork-owned tests moved out of ``tests/tools/test_browser_orphan_reaper.py``.

They pin the reaper's binding of a live pid to its recorded profile dir as an IDENTITY
question, not a spelling one. Up to v0.22.5 the binding was the agent-browser daemon's
``AGENT_BROWSER_SOCKET_DIR`` environ entry, asked through ``path_identity.denotes_same_file``;
v0.23.1 retired that daemon and binds a recorded Chromium through its argv's
``--user-data-dir=`` token (``tools.browser_launcher._cmdline_names_dir``, ``realpath`` on both
sides). The same two guarantees are pinned on the new anchor: a symlinked spelling of our dir
binds, and nothing beyond it (a suffix, a truncation, the parent) does. ``_FakeProc`` / ``_run``
are upstream's, imported by name.
"""

from __future__ import annotations

import pytest

from tests.tools.test_browser_orphan_reaper import (  # upstream names the moved tests use
    TestReaperIdentityGuard as _UpstreamReaperIdentityGuard,
)


class TestReaperIdentityGuard:
    _FakeProc = _UpstreamReaperIdentityGuard._FakeProc
    _run = _UpstreamReaperIdentityGuard._run

    def test_browser_bound_via_a_symlinked_profile_dir_is_reapable(self, tmp_path):
        """The binding is an identity question, not a spelling one.

        The browser publishes whatever spelling it was started with; the reaper holds its own.
        A string compare folds neither symlinks nor (on Windows) case, so the reaper could refuse
        to clean up its own browser and leave the profile behind forever.
        """
        real = tmp_path / "chromium-abc"
        real.mkdir()
        link = tmp_path / "linked-profile-dir"
        try:
            link.symlink_to(real, target_is_directory=True)
        except (OSError, NotImplementedError):
            pytest.skip("symlink creation unavailable for this user")

        assert self._run(["chrome", f"--user-data-dir={link}"], str(real)) is True

    @pytest.mark.parametrize(
        "token,why",
        [
            ("", "no binding published at all"),
            ("--user-data-dir={base}-OTHER999", "another profile's dir"),
            ("--user-data-dir={base}-evil", "extends our name; not our dir"),
            ("--user-data-dir={trunc}", "our name truncated; not our dir"),
            ("--user-data-dir={parent}", "our dir's parent, not our dir"),
        ],
    )
    def test_binding_rejection_table(self, tmp_path, token, why):
        """Nothing beyond the intended spelling became reapable.

        Resolution-based identity matches MORE spellings than a string compare by construction,
        so the whole refusal set is re-pinned here — including the two shapes a prefix-flavoured
        implementation would wave through (``<dir>-evil`` and a truncation of ``<dir>``), and the
        parent directory, which contains our dir but is not it.
        """
        udd = tmp_path / "chromium-abc1234567"
        udd.mkdir()
        argv = ["chrome", "--remote-debugging-port=0"]
        if token:
            argv.append(token.format(base=udd, trunc=str(udd)[:-1], parent=tmp_path))
        assert self._run(argv, str(udd)) is False, why
