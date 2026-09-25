"""Fork-owned tests moved out of ``tests/tools/test_local_env_blocklist.py`` (lane CARRY).

The upstream file is byte-identical to upstream again; upstream's verbatim
``Path`` equality is marked by id in ``tests/_downstream/id_markers/``.
"""

from unittest.mock import patch

import pytest


class TestSanePathIncludesHomebrew:
    @pytest.mark.windows_only
    def test_make_run_env_preserves_windows_mixed_case_path_key(self, monkeypatch):
        """The fork's real-host form of upstream's mixed-case ``Path`` test.

        The guarantee is about the KEY: completion writes back to the
        caller's own casing and never invents a second, differently-cased
        PATH. The VALUE is deliberately NOT preserved verbatim — on a real
        Windows host the fork's ``_augment_windows_system_path`` appends the
        system-tooling dirs. What holds everywhere is that the caller's own
        entries survive, in order.
        """
        from tools.environments import local as local_mod
        from tools.environments.local import _make_run_env
        windows_env = {"Path": r"C:\Windows\System32;C:\Program Files\Git\bin"}
        monkeypatch.setattr(local_mod, "_git_bash_bin_dirs", lambda: [])
        with patch.object(local_mod.os, "environ", windows_env):
            result = _make_run_env({})
        assert "PATH" not in result
        entries = result["Path"].split(";")
        original = windows_env["Path"].split(";")
        assert [e for e in entries if e in original] == original
