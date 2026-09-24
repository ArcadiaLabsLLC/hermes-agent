"""Fork-owned tests moved out of ``tests/tools/test_file_tools.py`` (seam Stage 5).

Same names, same bodies; the upstream file keeps only upstream's tests.
"""

import pytest


class TestSensitivePathCheck:
    def test_sensitive_root_rejection_table(self, monkeypatch):
        """Every sensitive root still refuses, in the spelling it is written in.

        This is the guard whose ``.startswith("/etc")`` returned False on
        Windows — ``os.path.normpath`` had rewritten the operand to
        ``\\etc\\hosts`` — so the guard answered ALLOW for exactly the paths it
        exists to refuse. The spelling reconciliation now lives in
        ``tools.path_identity``; re-pin the whole table at the seam so moving it
        cannot quietly drop a root.

        The permitted rows below are the non-vacuity half: without them a guard
        that refused EVERYTHING would satisfy the refusals above.
        """
        monkeypatch.setattr("tools.file_tools_write_guards._hermes_config_resolved", "/some/other/path")
        monkeypatch.setattr("tools.file_tools_write_guards._hermes_config_resolved_loaded", True)
        from tools.file_tools import _check_sensitive_path

        refused = (
            "/etc/hosts",
            "/etc/passwd",
            "/etc/../etc/shadow",
            "/boot/grub/grub.cfg",
            "/usr/lib/systemd/system/evil.service",
            "/private/etc/hosts",
            "/private/var/db/x",
            "/var/run/docker.sock",
            "/run/docker.sock",
        )
        for path in refused:
            assert _check_sensitive_path(path) is not None, path

        permitted = (
            "/etcetera/notes.txt",       # shares a prefix with /etc, is not /etc
            "/home/user/etc/hosts",      # /etc is not at the root here
            "/tmp/boot/kernel",          # ditto for /boot
            "/var/run/docker.sock.bak",  # extends an exact-match entry
        )
        for path in permitted:
            assert _check_sensitive_path(path) is None, path

    def test_config_guard_follows_a_symlink_when_resolution_fails(self, tmp_path, monkeypatch):
        """The config guard must not fail open on the fallback branch.

        ``_check_sensitive_path`` falls back to the RAW operand when
        ``_resolve_path_for_task`` raises, and the only other comparison was a
        ``normpath`` — which follows no symlinks. So on that branch a symlink
        pointing at config.yaml was writable, and writing config.yaml is how an
        agent turns approvals off. Identity comparison closes it.
        """
        config = tmp_path / "config.yaml"
        config.write_text("approvals:\n  mode: manual\n", encoding="utf-8")
        innocent = tmp_path / "innocent.yaml"
        try:
            innocent.symlink_to(config)
        except (OSError, NotImplementedError):
            pytest.skip("symlink creation unavailable for this user")

        monkeypatch.setattr(
            "tools.file_tools_write_guards._hermes_config_resolved", str(config.resolve())
        )
        monkeypatch.setattr("tools.file_tools_write_guards._hermes_config_resolved_loaded", True)

        def _resolution_unavailable(*_args, **_kwargs):
            raise OSError("resolution unavailable")

        monkeypatch.setattr(
            "tools.file_tools._resolve_path_for_task", _resolution_unavailable
        )
        from tools.file_tools import _check_sensitive_path

        error = _check_sensitive_path(str(innocent))
        assert error is not None and "Hermes config" in error

        # Non-vacuity: a real neighbouring file on the same fallback branch is
        # still writable, so the refusal above is the identity check firing and
        # not the branch refusing everything it is handed.
        sibling = tmp_path / "other.yaml"
        sibling.write_text("", encoding="utf-8")
        assert _check_sensitive_path(str(sibling)) is None
