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
    from .provider_account_view import account_view

    if snapshot is None:
        return {"account": account_view(provider, snapshot), "provider": provider, "available": False, "unavailable_reason": "no_usage_source"}
    return {
        "provider": snapshot.provider,
        "account": account_view(provider, snapshot),
        "available": bool(snapshot.available),
        "source": snapshot.source,
        "title": snapshot.title,
        "plan": snapshot.plan,
        "fetched_at": _iso(snapshot.fetched_at),
        "windows": [
            {"label": w.label, "used_percent": w.used_percent, "reset_at": _iso(w.reset_at), "detail": w.detail,
             "scope": w.scope}
            for w in snapshot.windows
        ],
        "details": list(snapshot.details),
        "unavailable_reason": snapshot.unavailable_reason,
    }


def _nous_snapshot() -> Any:
    from .provider_account_metadata import nous_usage_snapshot

    return nous_usage_snapshot()


def provider_usage(provider: str) -> dict:
    """The account's limits and rate-limit windows, or ``available: false``."""
    from agent.account_usage import fetch_account_usage

    if provider == "nous":
        try:
            snapshot = _nous_snapshot()
        except Exception as exc:  # fail open like upstream's /usage, class name only
            return _usage_view(provider, None) | {"unavailable_reason": type(exc).__name__}
    else:
        snapshot = fetch_account_usage(provider)
    from .provider_account_metadata import usage_snapshot

    return _usage_view(provider, usage_snapshot(provider, snapshot))


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
    except Exception as exc:  # class name only, never the message
        raise ProviderRefused("refresh_failed", type(exc).__name__, provider=provider) from None
    return {"provider": provider, "credential": credential, "refreshed": True}


def _signed_in(provider: str) -> bool:
    from hermes_cli.auth import get_auth_status

    try:
        return bool((get_auth_status(provider) or {}).get("logged_in"))
    except Exception:  # an unreadable status reads as signed out
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
    except Exception as exc:  # class name only, never the message
        raise ProviderRefused("signout_failed", type(exc).__name__, provider=provider) from None
    return {"provider": provider, "was_signed_in": was, "signed_in": _signed_in(provider)}


#: ``runtime.provider.configure``'s writes, in order, on the bound provider home's ``config.yaml``.
#: ``model.auth_mode`` and ``model.base_url`` are read only while ``model.provider`` names that
#: provider (``hermes_cli/runtime_provider_backends.py``), so the write selects it too: a mode
#: written beside another provider would be a setting nothing reads.
CONFIGURE_KEYS = ("model.provider", "model.auth_mode", "model.base_url")


def _configure_home():
    from hermes_constants import get_hermes_home

    from .provider_credentials import bound_provider_home

    return bound_provider_home() or get_hermes_home().resolve()


def provider_configure(provider: str, auth_mode: str, base_url: str | None = None) -> dict:
    """Write ``model.auth_mode`` (and ``model.base_url``) for a multi-mode provider (RULED 2026-10-22).

    Only a provider ``PROVIDER_AUTH_MODES`` declares, and only one of its declared modes. No secret is
    taken: a mode that ``needs_key`` is configured here and keyed through ``auth set-key``. One key at a
    time through the round-trip YAML writer, so comments and every other key survive.
    """
    from hermes_cli.provider_login_catalog import PROVIDER_AUTH_MODES
    from utils import atomic_roundtrip_yaml_update

    modes = {mode: needs_key for mode, _label, needs_key in PROVIDER_AUTH_MODES.get(provider, ())}
    if not modes:
        raise ProviderRefused("auth_mode_unsupported", provider=provider)
    if auth_mode not in modes:
        raise ProviderRefused("auth_mode_unknown", provider=provider, auth_modes=sorted(modes))
    url = (base_url or "").strip().rstrip("/") or None
    if url is not None and not url.lower().startswith(("https://", "http://")):
        raise ProviderRefused("base_url_invalid", provider=provider)
    home = _configure_home()
    path = home / "config.yaml"
    values = {"model.provider": provider, "model.auth_mode": auth_mode}
    if url is not None:
        values["model.base_url"] = url
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_text("", encoding="utf-8")
        for key in CONFIGURE_KEYS:
            if key in values:
                atomic_roundtrip_yaml_update(path, key, values[key])
    except Exception as exc:  # class name only
        raise ProviderRefused("configure_failed", type(exc).__name__, provider=provider) from None
    return {"provider": provider, "auth_mode": auth_mode, "base_url": url, "needs_key": modes[auth_mode],
            "written": [key for key in CONFIGURE_KEYS if key in values]}
