"""Fork-owned tests moved out of ``tests/hermes_cli/test_managed_uv.py`` (seam Stage 5).

Same names, same bodies; the upstream file keeps only upstream's tests.
"""

from __future__ import annotations

from unittest.mock import patch


class TestExplicitPosixInstaller:
    def test_posix_sets_uv_unmanaged_install(self, tmp_path):
        target = tmp_path / "bin" / "uv"
        # _install_uv() dispatches on platform.system(): _install_uv_windows on
        # Windows, _install_uv_posix everywhere else. Pin the branch this test
        # is named for instead of asserting it from whichever host runs.
        with patch("hermes_cli.managed_uv.platform.system", return_value="Linux"), \
             patch("hermes_cli.managed_uv._install_uv_posix") as mock_posix:
            from hermes_cli.managed_uv import _install_uv
            _install_uv(target)
            mock_posix.assert_called_once()
            call_env = mock_posix.call_args[0][0]
            assert call_env["UV_UNMANAGED_INSTALL"] == str(tmp_path / "bin")
