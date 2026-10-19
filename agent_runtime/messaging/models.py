"""The messaging vocabularies: the platforms the fork carries and every refusal, as enums."""

from __future__ import annotations

from enum import StrEnum

__layer__ = "models"
__all__ = ["MessagingRefused", "Platform", "Reason", "platform_of"]


class Platform(StrEnum):
    """v1 carries Telegram alone (plan §2.1); each later platform is one member and one transport."""

    TELEGRAM = "telegram"


class Reason(StrEnum):
    INVALID = "invalid_request"
    UNKNOWN_PLATFORM = "unknown_platform"
    UNKNOWN_INSTANCE = "unknown_instance"
    TOKEN_INVALID = "token_invalid"
    UNAVAILABLE = "messaging_unavailable"
    #: The bridge's drops (M3/M4): a platform user with no operator row; a ``/persona`` naming no instance.
    UNKNOWN_OPERATOR = "unknown_operator"
    UNKNOWN_PERSONA = "unknown_persona"


class MessagingRefused(Exception):
    """A typed refusal. ``detail`` names the offending FIELD, never its value (a token is a value)."""

    def __init__(self, reason: Reason, detail: str = "") -> None:
        super().__init__(f"{reason.value}: {detail}" if detail else reason.value)
        self.reason = reason
        self.detail = detail


def platform_of(value: object) -> Platform:
    try:
        return Platform(str(value or "").strip().lower())
    except ValueError:
        raise MessagingRefused(Reason.UNKNOWN_PLATFORM, "platform") from None
