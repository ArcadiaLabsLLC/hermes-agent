"""Fork-owned tests moved out of ``tests/hermes_cli/test_slack_cli.py`` (seam Stage 5).

Same names, same bodies; the upstream file keeps only upstream's tests.
"""

import json
from hermes_cli.slack_cli import slack_manifest_command

from tests.hermes_cli.test_slack_cli import (  # noqa: F401 — upstream names the moved tests use
    _parse_slack_args,
)


class TestSlackManifestArgparse:
    def test_manifest_names_the_commands_slacks_cap_left_out(self, monkeypatch, capsys):
        """The person pasting the manifest is told what is missing from it.

        Slack allows an app only 50 slash commands. When the registry does not
        fit, the generated manifest is silently incomplete relative to every
        other surface — so the clamp is reported on stderr, next to the paste
        instructions, leaving stdout pure JSON for redirection.
        """
        from hermes_cli import commands_platforms as commands_module

        monkeypatch.setattr(
            commands_module, "slack_clamped_slashes", lambda: ["platform", "diff"]
        )
        args = _parse_slack_args(["slack", "manifest"])

        assert slack_manifest_command(args) == 0

        captured = capsys.readouterr()
        json.loads(captured.out)  # stdout stays machine-readable
        assert "/platform" in captured.err
        assert "/diff" in captured.err
        assert "50" in captured.err

    def test_manifest_is_quiet_when_every_command_fits(self, monkeypatch, capsys):
        """Control: the note is caused by the clamp, not printed always."""
        from hermes_cli import commands_platforms as commands_module

        monkeypatch.setattr(commands_module, "slack_clamped_slashes", list)
        args = _parse_slack_args(["slack", "manifest"])

        assert slack_manifest_command(args) == 0

        captured = capsys.readouterr()
        json.loads(captured.out)
        assert "did not fit" not in captured.err
