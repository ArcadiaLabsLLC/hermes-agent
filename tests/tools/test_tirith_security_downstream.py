"""Fork-owned tests moved out of ``tests/tools/test_tirith_security.py``.

The fork's ``tools.tirith_security`` keeps ALLOWING on a platform tirith ships
no build for, but says so when ``security.tirith_fail_open`` is false — once,
in the log and on the result. Upstream's autouse ``_reset_resolved_path`` is
imported by name.
"""

from __future__ import annotations

import logging
from unittest.mock import patch

import tools.tirith_security as _tirith_mod
from tests.tools.test_tirith_security import (  # noqa: F401 — upstream autouse fixture
    _reset_resolved_path,
)
from tools.tirith_security import check_command_security


class TestUnsupportedPlatform:
    @patch("tools.tirith_security._load_security_config")
    def test_fail_closed_is_still_allowed_but_says_so(self, mock_cfg, caplog):
        """An operator who set tirith_fail_open: false must be able to find
        out that it is not binding here.

        The platform arm deliberately keeps ALLOWING — tirith ships no build
        for this OS+arch, so there is nothing to fail closed against and
        blocking every command would take the machine offline rather than
        make it safer. What is not acceptable is the setting evaporating in
        silence, which is what happened while this arm returned before the
        flag was read: config said fail-closed, behaviour was fail-open, and
        nothing anywhere reported the divergence."""
        mock_cfg.return_value = {"tirith_enabled": True, "tirith_path": "tirith",
                                 "tirith_timeout": 5, "tirith_fail_open": False}
        with _tirith_mod._warned_lock:
            _tirith_mod._warned_messages.clear()
        with caplog.at_level(logging.WARNING, logger="tools.tirith_security"), \
             patch("tools.tirith_security.is_platform_supported", return_value=False), \
             patch("tools.tirith_security.subprocess.run") as mock_run:
            result = check_command_security("rm -rf /")

        assert result["action"] == "allow"
        mock_run.assert_not_called()
        # The override is carried on the result, not only in the log.
        assert "tirith_fail_open" in result["summary"]
        assert "unscanned" in result["summary"]
        # ...and named in the log, with the flag and the platform.
        messages = [r.getMessage() for r in caplog.records]
        assert any(
            "security.tirith_fail_open is false" in m and "no build" in m
            for m in messages
        ), messages
    @patch("tools.tirith_security._load_security_config")
    def test_fail_closed_override_is_logged_once_not_per_command(
        self, mock_cfg, caplog,
    ):
        """This arm sits on the per-command hot path, so an un-deduped
        warning would emit once per tool call and drown errors.log — the
        same failure mode the spawn warnings already dedupe against."""
        mock_cfg.return_value = {"tirith_enabled": True, "tirith_path": "tirith",
                                 "tirith_timeout": 5, "tirith_fail_open": False}
        with _tirith_mod._warned_lock:
            _tirith_mod._warned_messages.clear()
        with caplog.at_level(logging.WARNING, logger="tools.tirith_security"), \
             patch("tools.tirith_security.is_platform_supported", return_value=False):
            for _ in range(5):
                check_command_security("echo hi")

        overrides = [
            r for r in caplog.records
            if "security.tirith_fail_open is false" in r.getMessage()
        ]
        assert len(overrides) == 1, [r.getMessage() for r in overrides]
    @patch("tools.tirith_security._load_security_config")
    def test_default_fail_open_stays_completely_silent(self, mock_cfg, caplog):
        """The default is fail-open, and on this arm that is the intended,
        unremarkable behaviour: no warning, no summary. Only the operator who
        explicitly asked for something else gets told."""
        mock_cfg.return_value = {"tirith_enabled": True, "tirith_path": "tirith",
                                 "tirith_timeout": 5, "tirith_fail_open": True}
        with _tirith_mod._warned_lock:
            _tirith_mod._warned_messages.clear()
        with caplog.at_level(logging.WARNING, logger="tools.tirith_security"), \
             patch("tools.tirith_security.is_platform_supported", return_value=False):
            result = check_command_security("rm -rf /")

        assert result == {"action": "allow", "findings": [], "summary": ""}
        assert caplog.records == []
