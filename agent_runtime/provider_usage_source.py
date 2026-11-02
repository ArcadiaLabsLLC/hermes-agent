"""The usage lane under ``providers.<id>.credential_source``: what the chip can honestly show per pool.

Both usage doors — ``runtime.provider.usage`` (``provider_account.provider_usage``) and the argv
``hermes harness usage --json`` lane (``hermes_cli/harness_parts/usage/lanes.py``) — fetch
through :func:`sourced_usage`, so the two answer one shape:

* the Account effective (or no table): the provider's own fetch, unchanged;
* the API key effective (Anthropic): Anthropic exposes no credit balance to a user key (the
  rate-limit headers carry none; the Admin API needs an admin key), so the lane is
  ``available`` with no windows and :data:`API_KEY_USAGE_DETAIL` in ``details`` — never
  upstream's "only available for OAuth-backed Claude accounts" refusal, which read as
  "Limits unavailable". The Account's plan windows are still fetched, with the stored grant
  passed explicitly, as the lane's ``plan_windows``: a true fact about the signed-in Account, shown as
  "Plan limits — not spent while the API key is chosen".

Plan: Eternia ``docs/mission_control/planned/PROVIDER_API_KEY_AND_USAGE_SOURCE_2026-11-02.md``
(D4); row ``RT-USAGE-ANTHROPIC-SOURCE-LANE``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Callable, Optional

__layer__ = "stores"

__all__ = ["API_KEY_USAGE_DETAIL", "SourcedUsage", "sourced_usage"]

API_KEY_USAGE_DETAIL = (
    "Monthly API credits are spent by this key; the balance is not readable with an API key"
    " — see Console › Billing"
)


@dataclass(frozen=True)
class SourcedUsage:
    """One lane's fetch: the snapshot, the Account's plan snapshot while the key is spent, the block."""

    snapshot: Any
    plan: Any = None
    credential_source: Optional[dict] = None

    @property
    def spends_api_key(self) -> bool:
        return bool(self.credential_source) and self.credential_source.get("effective") == "api_key"


def _plan_snapshot() -> Any:
    from agent.account_usage import _fetch_anthropic_account_usage

    from .provider_credential_source import account_usage_token

    token = account_usage_token()
    if not token:
        return None
    try:
        return _fetch_anthropic_account_usage(api_key=token)
    except Exception:  # the plan half is extra; a failed read shows no plan windows
        return None


def sourced_usage(provider: str, fetch: Callable[[], Any]) -> SourcedUsage:
    """``fetch()`` unless the provider's effective source is its API key (see the module doc)."""
    from agent.account_usage import AccountUsageSnapshot

    from .provider_credential_source import credential_source_block

    try:
        block = credential_source_block(provider)
    except Exception:
        block = None
    if provider != "anthropic" or not block or block.get("effective") != "api_key":
        return SourcedUsage(fetch(), None, block)
    snapshot = AccountUsageSnapshot(provider=provider, source="api_key", fetched_at=datetime.now(UTC),
                                    title="API credits", details=(API_KEY_USAGE_DETAIL,))
    return SourcedUsage(snapshot, _plan_snapshot(), block)
