"""List, usage, refresh and sign-out for ``runtime.provider.*`` — upstream's code, projected.

Every function here calls the one existing implementation and shapes its answer
for the wire; none decides anything an upstream function already decides:

* list      -> ``build_provider_visibility`` (the real catalog + pools + logins,
               the envelope ``hermes harness providers --json`` already emits)
* usage     -> ``agent.account_usage.fetch_account_usage``; Nous through the two
               public halves of upstream's own ``/usage`` path
* refresh   -> ``hermes auth refresh`` (``auth_refresh_command``), whose pool
               refresh dispatches to the per-provider refreshers
* sign-out  -> ``hermes auth logout`` (``auth_logout_command``)

No credential value crosses this module's return: usage drops the snapshot's
``raw`` body, refresh and sign-out answer with booleans, and a raised error is
reported by class name only (the ``provider_visibility`` disclosure rule).
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from typing import Any

__layer__ = "stores"

__all__ = [
    "ProviderRefused",
    "provider_list",
    "provider_refresh",
    "provider_signout",
    "provider_usage",
]


class ProviderRefused(Exception):
    """A refusal with a closed ``reason``; ``message`` is upstream's operator text."""

    def __init__(self, reason: str, message: str = "", **data: Any) -> None:
        super().__init__(reason)
        self.reason = reason
        self.message = message
        self.data = data


def provider_list() -> dict:
    from hermes_cli.harness_parts.provider_visibility import build_provider_visibility

    return build_provider_visibility()


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _usage_view(provider: str, snapshot: Any) -> dict:
    if snapshot is None:
        return {"provider": provider, "available": False, "unavailable_reason": "no_usage_source"}
    return {
        "provider": snapshot.provider,
        "available": bool(snapshot.available),
        "source": snapshot.source,
        "title": snapshot.title,
        "plan": snapshot.plan,
        "fetched_at": _iso(snapshot.fetched_at),
        "windows": [
            {"label": w.label, "used_percent": w.used_percent, "reset_at": _iso(w.reset_at), "detail": w.detail}
            for w in snapshot.windows
        ],
        "details": list(snapshot.details),
        "unavailable_reason": snapshot.unavailable_reason,
    }


def _nous_snapshot() -> Any:
    from agent.account_usage import build_nous_credits_snapshot
    from hermes_cli.nous_account import get_nous_portal_account_info

    account = get_nous_portal_account_info(force_fresh=True)
    if account is None or not getattr(account, "logged_in", False):
        return None
    return build_nous_credits_snapshot(account)


def provider_usage(provider: str) -> dict:
    """The account's limits and rate-limit windows, or ``available: false``."""
    from agent.account_usage import fetch_account_usage

    if provider == "nous":
        try:
            snapshot = _nous_snapshot()
        except Exception as exc:  # noqa: BLE001 - fail open like upstream's /usage, class name only
            return {"provider": provider, "available": False, "unavailable_reason": type(exc).__name__}
    else:
        snapshot = fetch_account_usage(provider)
    return _usage_view(provider, snapshot)


def _known(provider: str) -> None:
    from hermes_cli.auth import is_known_auth_provider

    if not is_known_auth_provider(provider):
        raise ProviderRefused("provider_unknown", provider=provider)


def provider_refresh(provider: str, credential: str | None = None) -> dict:
    """Force one pooled OAuth grant to rotate (``hermes auth refresh``)."""
    from hermes_cli.auth_commands import auth_refresh_command

    _known(provider)
    try:
        auth_refresh_command(SimpleNamespace(provider=provider, target=credential))
    except SystemExit as exit_:
        raise ProviderRefused("refresh_refused", str(exit_.code or ""), provider=provider) from None
    except Exception as exc:  # noqa: BLE001 - class name only, never the message
        raise ProviderRefused("refresh_failed", type(exc).__name__, provider=provider) from None
    return {"provider": provider, "credential": credential, "refreshed": True}


def _signed_in(provider: str) -> bool:
    from hermes_cli.auth import get_auth_status

    try:
        return bool((get_auth_status(provider) or {}).get("logged_in"))
    except Exception:  # noqa: BLE001 - an unreadable status reads as signed out
        return False


def provider_signout(provider: str) -> dict:
    """Clear this provider's sign-in (``hermes auth logout``)."""
    from hermes_cli.auth_commands import auth_logout_command

    _known(provider)
    was = _signed_in(provider)
    try:
        auth_logout_command(SimpleNamespace(provider=provider))
    except SystemExit as exit_:
        raise ProviderRefused("signout_refused", str(exit_.code or ""), provider=provider) from None
    except Exception as exc:  # noqa: BLE001 - class name only, never the message
        raise ProviderRefused("signout_failed", type(exc).__name__, provider=provider) from None
    return {"provider": provider, "was_signed_in": was, "signed_in": _signed_in(provider)}
