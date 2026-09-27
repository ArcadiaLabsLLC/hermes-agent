"""Fork-owned: a process notification is redacted and ANSI-stripped before it re-enters
the conversation (``tools/process_notification_safety.py``, lane FOOTPRINT-DROP 2026-09-27).
"""

from __future__ import annotations

_SECRET = "sk-proj-abc123def456ghi789jkl012"


def _enable_redaction(monkeypatch):
    import agent.redact as redact

    monkeypatch.setattr(redact, "_REDACT_ENABLED", True)


def test_completion_notification_redacts_output_and_strips_ansi(monkeypatch):
    from tools.process_registry_notifications import format_process_notification

    _enable_redaction(monkeypatch)
    text = format_process_notification({
        "type": "completion", "session_id": "proc_x", "command": "python app.py",
        "exit_code": 0, "output": f"\x1b[31mleaked OPENAI_API_KEY {_SECRET} here\x1b[0m",
    })
    assert "abc123def456" not in text
    assert "\x1b[" not in text
    # Positive control: the same event with a harmless output keeps it verbatim.
    plain = format_process_notification({
        "type": "completion", "session_id": "proc_x", "command": "python app.py",
        "exit_code": 0, "output": "all good",
    })
    assert "all good" in plain


def test_short_command_is_redacted_before_it_is_clipped(monkeypatch):
    from tools.process_registry_notifications import _short_command

    _enable_redaction(monkeypatch)
    short = _short_command(f"curl -H 'Authorization: Bearer {_SECRET}' https://example.test/" + "x" * 80)
    assert "abc123def456" not in short
