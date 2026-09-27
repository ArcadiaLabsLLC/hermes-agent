"""Fork-owned hardening for ``tools/process_registry_notifications.py`` (class G6).

A process notification re-enters the conversation, so every free-text field is
ANSI-stripped, bounded and redacted first, and the short command line is redacted
before it is clipped. Moved out of the upstream module by lane FOOTPRINT-DROP
(2026-09-27), which keeps one import and two call lines; retires with the G6
security-hardening upstream PR.
"""

from __future__ import annotations

from typing import Any

#: Per-field bounds for the free-text fields of a completion-queue event.
_FIELD_LIMITS = (("command", 500), ("message", 1000), ("pattern", 200),
                 ("output", 2000), ("handoff_note", 1000))


def redacted_command_line(command) -> str:
    """``command`` as one whitespace-normalised line, ANSI-stripped and redacted.

    Redact before shortening: clipping a credential can hide its recognizable prefix.
    """
    from agent.redact import redact_sensitive_text
    from tools.ansi_strip import strip_ansi

    return " ".join(redact_sensitive_text(strip_ansi(str(command or ""))).split())


def sanitize_notification_event(evt: dict) -> dict:
    """A copy of ``evt`` whose free-text fields are ANSI-stripped, bounded and redacted."""
    try:
        from agent.redact import redact_sensitive_text
    except Exception:
        redact_sensitive_text = lambda text: ""  # fail closed for UI notifications
    try:
        from tools.ansi_strip import strip_ansi
    except Exception:
        strip_ansi = lambda text: str(text or "")

    def _safe(value: Any, *, limit: int = 2000) -> str:
        text = strip_ansi(str(value or ""))
        if len(text) > limit:
            tail = text[-limit:]
            nl = tail.find("\n")
            tail = tail[nl + 1:] if nl != -1 else tail
            text = f"[… output truncated — showing last {len(tail)} chars]\n{tail}"
        return redact_sensitive_text(text)

    evt = dict(evt)
    for key, limit in _FIELD_LIMITS:
        if key in evt:
            evt[key] = _safe(evt[key], limit=limit)
    return evt
