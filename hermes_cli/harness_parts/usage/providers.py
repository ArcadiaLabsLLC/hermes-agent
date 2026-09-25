"""The usage-lane table: one strategy per provider, and the lane vocabulary it defines.

Program rule 12: a provider id reaches its behaviour through ``USAGE_LANES``, never
through an ``if provider_id == ...`` ladder. Detection (``detect._usage_lane_detected``)
and fetching (``lanes._fetch_usage_lane``) both read this ONE table, so a provider
cannot have a detector without a fetcher; the emission order is the table's key
order (``detect._USAGE_LANE_PROVIDERS``).

Every strategy imports its upstream reader lazily, at call time: a test that stubs
``agent.account_usage`` (or the credential readers) reaches the strategy, and a
lane nobody asks for costs no import.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Final, Optional

from hermes_cli.harness_parts._upstream_doors import (
    fetch_anthropic_account_usage,
    fetch_codex_account_usage,
    fetch_openrouter_account_usage,
)

__layer__ = "policy"
__all__ = [
    "USAGE_LANES",
    "UsageLane",
    "_codex_usage_login_detected",
    "_openrouter_usage_login_detected",
]


@dataclass(frozen=True)
class UsageLane:
    """One provider's usage lane: is the operator signed in to it, and fetch its snapshot.

    ``detect`` answers True / False, or RAISES when it cannot tell (EG-6.1 — the
    caller names the class). ``fetch`` returns a snapshot or None, or raises.
    """

    detect: Callable[[], bool]
    fetch: Callable[[], Any]


def _codex_usage_login_detected() -> bool:
    """Codex lane detected when the OAuth status is logged-in OR the credential
    pool holds any openai-codex entry.

    Two independent sources OR'd together, so a raise from the FIRST is not yet
    an answer — the pool may still say yes, and that yes is the truth. But a
    raise that ends with no affirmative source is NOT "not signed in": it is
    "we could not tell", and per EG-6.1 that must reach the caller as a class,
    not as a ``False`` indistinguishable from an empty pool. So the primary
    error is held and re-raised only if nothing affirms; a raise from the pool
    read itself propagates directly (one lane carries one named class).
    """
    primary_error: Optional[BaseException] = None
    try:
        from hermes_cli.auth import get_codex_auth_status

        if bool((get_codex_auth_status() or {}).get("logged_in")):
            return True
    except Exception as exc:  # noqa: BLE001 — held, re-raised only if unanswered
        primary_error = exc
    from agent.credential_pool import load_pool

    if load_pool("openai-codex").entries():
        return True
    if primary_error is not None:
        raise primary_error
    return False


def _openrouter_usage_login_detected() -> bool:
    """OpenRouter lane detected when the pool holds an entry OR the runtime
    resolver finds a usable key.

    Same held-primary-error discipline as [_codex_usage_login_detected]: a
    failure that leaves the question unanswered is raised, never flattened into
    the ``False`` that would silently delete the lane.
    """
    primary_error: Optional[BaseException] = None
    try:
        from agent.credential_pool import load_pool

        if load_pool("openrouter").entries():
            return True
    except Exception as exc:  # noqa: BLE001 — held, re-raised only if unanswered
        primary_error = exc
    from hermes_cli.runtime_provider import resolve_runtime_provider

    runtime = resolve_runtime_provider(requested="openrouter")
    if str(runtime.get("api_key", "") or "").strip():
        return True
    if primary_error is not None:
        raise primary_error
    return False


def _anthropic_usage_login_detected() -> bool:
    from agent.anthropic_credentials import resolve_anthropic_token

    return bool((resolve_anthropic_token() or "").strip())


def _nous_usage_login_detected() -> bool:
    from hermes_cli.auth import get_provider_auth_state

    tok = (get_provider_auth_state("nous") or {}).get("access_token")
    return bool(isinstance(tok, str) and tok.strip())


def _fetch_nous_usage():
    from agent.account_usage import build_nous_credits_snapshot
    from hermes_cli.nous_account import get_nous_portal_account_info

    account = get_nous_portal_account_info(force_fresh=True)
    return build_nous_credits_snapshot(account)


def _fetch_codex_usage():
    return fetch_codex_account_usage()


def _fetch_anthropic_usage():
    return fetch_anthropic_account_usage()


def _fetch_openrouter_usage():
    return fetch_openrouter_account_usage(None, None)


#: Every usage lane, in stable emission order. Adding a provider is one row here.
USAGE_LANES: Final[Mapping[str, UsageLane]] = MappingProxyType(
    {
        "openai-codex": UsageLane(detect=_codex_usage_login_detected, fetch=_fetch_codex_usage),
        "anthropic": UsageLane(detect=_anthropic_usage_login_detected, fetch=_fetch_anthropic_usage),
        "openrouter": UsageLane(detect=_openrouter_usage_login_detected, fetch=_fetch_openrouter_usage),
        "nous": UsageLane(detect=_nous_usage_login_detected, fetch=_fetch_nous_usage),
    }
)
