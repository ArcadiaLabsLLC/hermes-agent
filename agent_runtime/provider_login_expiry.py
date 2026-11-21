"""A provider refusal that names its provider, and an expired sign-in as its reason.

RT-EXPIRED-LOGIN-REFUSAL-UNNAMED: an explicit provider with no usable credential was refused
``ProviderNotConfiguredError`` with no provider, so the console said "no model provider is
configured" even when the provider's OAuth login had simply expired. Upstream
``agent/agent_init.py::_routed_client_kwargs`` raises through :func:`named_missing_provider_error`
(one fork seam, additive); everything else lives here, so ``agent/auxiliary_unavailable.py`` keeps
its upstream bytes (FH-UPSTREAM-FOOTPRINT-UNLEDGERED-AUX-UNAVAILABLE).
"""

from __future__ import annotations

from typing import Any, Optional

from agent.auxiliary_unavailable import ProviderNotConfiguredError, missing_provider_credentials_message

from .api_key_check import API_KEY_CONTROL_CHARACTER

__layer__ = "models"

__all__ = [
    "LOGIN_EXPIRED_REASON",
    "NamedProviderNotConfiguredError",
    "expired_login_message",
    "named_missing_provider_error",
    "pool_key_refused",
    "pool_login_expired",
    "refused_key_message",
]

#: The credentials reason of a refusal whose provider's sign-in itself is gone: every usable entry
#: is spent and an OAuth login in the pool went DEAD when its refresh grant was rejected terminally
#: (``invalid_grant`` and kin). Rides the refusal block's ``failure_reason``, so a client can say
#: "sign in again", not "configure one".
LOGIN_EXPIRED_REASON = "login_expired"


class NamedProviderNotConfiguredError(ProviderNotConfiguredError):
    """:class:`ProviderNotConfiguredError` for an explicitly configured provider, which it names.

    ``provider`` is the explicitly configured provider with no usable credential, and
    ``credentials_reason`` is :data:`LOGIN_EXPIRED_REASON` when its sign-in expired: the turn's
    refusal block carries both (``agent_runtime.mission_chat_outcome.classify_turn_failure``).
    Every ``except ProviderNotConfiguredError`` still catches it.
    """

    def __init__(self, message: str, *, provider: str, credentials_reason: Optional[str] = None):
        super().__init__(message)
        self.provider = provider
        self.credentials_reason = credentials_reason


def pool_login_expired(pool: Optional[Any]) -> bool:
    """True when ``pool`` has no usable entry and holds an OAuth login that went DEAD.

    DEAD is the pool's word for a credential rejected permanently server-side; on an OAuth row it
    is the refresh grant (``_mark_dead_refresh_grant``) or a terminal 401 reason, both "the login
    expired". An API-key row going DEAD is a rejected key, not an expired sign-in, so it does not
    count. Never raises: a pool that cannot be read is not proof of anything.
    """
    if pool is None:
        return False
    from agent.credential_pool import AUTH_TYPE_OAUTH, STATUS_DEAD

    try:
        if pool.has_available():
            return False
        return any(e.auth_type == AUTH_TYPE_OAUTH and e.last_status == STATUS_DEAD for e in pool.entries())
    except Exception:
        return False


def expired_login_message(provider_id: str) -> str:
    """The "Provider 'X' sign-in has expired" error for a pool whose login went DEAD."""
    return (f"Provider '{provider_id}' sign-in has expired: its refresh token was rejected. "
            f"Run `hermes auth add {provider_id}` to sign in again, or switch to a different "
            "provider with `hermes model`.")


def named_missing_provider_error(provider_id: str, exhausted_pool: Optional[Any]) -> NamedProviderNotConfiguredError:
    """The refusal for explicit ``provider_id`` with no usable credential, naming it.

    ``exhausted_pool`` is the provider's credential pool when init found it exhausted (else
    ``None``); a DEAD OAuth login in it makes the refusal an expired sign-in.
    """
    if pool_login_expired(exhausted_pool):
        return NamedProviderNotConfiguredError(
            expired_login_message(provider_id), provider=provider_id, credentials_reason=LOGIN_EXPIRED_REASON)
    if pool_key_refused(exhausted_pool):
        return NamedProviderNotConfiguredError(
            refused_key_message(provider_id), provider=provider_id, credentials_reason=API_KEY_CONTROL_CHARACTER)
    return NamedProviderNotConfiguredError(missing_provider_credentials_message(provider_id), provider=provider_id)


def pool_key_refused(pool: Optional[Any]) -> bool:
    """True when ``pool`` has no usable entry and holds a key the one key check refused at lease.

    RT-FU-AN-API-KEY-WITH-A-HIDDEN-CONTROL-CHARACTER-IS-REFUSED-WHEN-IT-IS-SAVED: such a row reads
    DEAD with :data:`agent_runtime.api_key_check.API_KEY_CONTROL_CHARACTER` (the pool's fork seam),
    so the turn names it instead of 21 transport retries. Never raises."""
    if pool is None:
        return False
    from agent.credential_pool import STATUS_DEAD

    try:
        if pool.has_available():
            return False
        # MUTATION: answer False here and test_a_turn_on_a_refused_key_names_the_hidden_character reddens.
        return any(e.last_status == STATUS_DEAD and e.last_error_reason == API_KEY_CONTROL_CHARACTER
                   for e in pool.entries())
    except Exception:
        return False


def refused_key_message(provider_id: str) -> str:
    """The error for a provider whose saved API key holds a hidden character (never the key)."""
    return (f"Provider '{provider_id}' API key contains a hidden character (often picked up when it was "
            "copied), so it was never sent; save the key again.")
