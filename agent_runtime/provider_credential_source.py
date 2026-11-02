"""Which STORED credential a provider's turns spend: ``providers.<id>.credential_source``.

A home can hold an Anthropic API key and a Claude account sign-in at once. Upstream's
ladder (``agent/anthropic_credentials.py::resolve_anthropic_token``) then spends the key on
every turn, and ``load_pool("anthropic")`` prunes the account rows so a 401/429 rotation
cannot flip the session onto OAuth. An explicit choice here replaces both behaviours:

* the resolver spends the CHOSEN family (:func:`resolve_chosen_anthropic_token`), and falls
  to the other only when the chosen one has nothing stored — never because the chosen
  token is benched for a model, which is the rotation guarantee the pruning protected;
* the pool keeps every row and BENCHES the unchosen family (:func:`benched_entry_ids`)
  while the chosen family has a row, instead of deleting it.

Unset keeps upstream's ladder byte for byte (a CLI user who hand-wrote a key sees no
change). The choice is per home: it lives in the bound provider home's ``config.yaml``
(``HERMES_AUTH_HOME`` when a binding shares the HEAD home's store, else this home), next to
the ``.env`` and ``auth.json`` that hold the credentials it chooses between.

Plan: Eternia ``docs/mission_control/planned/PROVIDER_API_KEY_AND_USAGE_SOURCE_2026-11-02.md``
(D2); row ``RT-ANTHROPIC-CREDENTIAL-SOURCE-CHOICE``. No credential value leaves this module:
the block answers ids, labels and booleans.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, Optional

__layer__ = "stores"

__all__ = [
    "ACCOUNT",
    "API_KEY",
    "account_usage_token",
    "benched_entry_ids",
    "chosen_credential_source",
    "credential_source_block",
    "credential_source_ids",
    "entry_family",
    "present_credential_sources",
    "resolve_chosen_anthropic_token",
]

ACCOUNT = "account"
API_KEY = "api_key"

#: Anthropic pool sources whose family is not read from ``auth_type``: an env token in
#: ``ANTHROPIC_TOKEN`` that is not ``sk-ant-oat`` shaped still IS an account token.
_ANTHROPIC_SOURCE_FAMILY = {
    "env:ANTHROPIC_TOKEN": ACCOUNT,
    "env:CLAUDE_CODE_OAUTH_TOKEN": ACCOUNT,
    "hermes_pkce": ACCOUNT,
    "claude_code": ACCOUNT,
    "env:ANTHROPIC_API_KEY": API_KEY,
}

def credential_source_ids(provider: str) -> tuple[tuple[str, str], ...]:
    """``((id, label), …)`` the provider declares; empty = no choice to make."""
    from hermes_cli.provider_login_catalog import PROVIDER_CREDENTIAL_SOURCES

    return PROVIDER_CREDENTIAL_SOURCES.get((provider or "").strip().lower(), ())


def _bound_config_path() -> Optional[Path]:
    from .provider_credentials import bound_provider_home

    home = bound_provider_home()
    return home / "config.yaml" if home is not None else None


def _read_bound_config(path: Path) -> dict:
    """A bound home's ``config.yaml``, parsed once per file signature; ``{}`` when absent or broken."""
    from utils import load_yaml_file_readonly

    try:
        data = load_yaml_file_readonly(path)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _providers_config() -> dict:
    path = _bound_config_path()
    if path is not None:
        config = _read_bound_config(path)
    else:
        from hermes_cli.config import load_config_readonly

        config = load_config_readonly() or {}
    providers = config.get("providers") if isinstance(config, dict) else None
    return providers if isinstance(providers, dict) else {}


def chosen_credential_source(provider: str) -> Optional[str]:
    """The declared id at ``providers.<provider>.credential_source``, else None. Never raises.

    A value the provider does not declare reads as unset, so a hand-edited typo keeps the
    ladder instead of benching a family by accident."""
    try:
        declared = {source_id for source_id, _label in credential_source_ids(provider)}
        if not declared:
            return None
        block = _providers_config().get((provider or "").strip().lower())
        value = block.get("credential_source") if isinstance(block, dict) else None
    except Exception:
        return None
    value = str(value or "").strip().lower()
    return value if value in declared else None


def entry_family(entry: Any) -> str:
    """``account`` or ``api_key`` for one pooled Anthropic row."""
    source = str(getattr(entry, "source", "") or "")
    if source in _ANTHROPIC_SOURCE_FAMILY:
        return _ANTHROPIC_SOURCE_FAMILY[source]
    from agent.credential_pool import AUTH_TYPE_OAUTH

    return ACCOUNT if getattr(entry, "auth_type", None) == AUTH_TYPE_OAUTH else API_KEY


def _has_secret(entry: Any) -> bool:
    for name in ("access_token", "runtime_api_key"):
        try:
            value = getattr(entry, name, None)
        except Exception:
            value = None
        if isinstance(value, str) and value.strip():
            return True
    return False


def benched_entry_ids(provider: str, entries: Iterable[Any]) -> frozenset[str]:
    """Ids of the unchosen family's rows, while the chosen family holds at least one row.

    Called once per ``CredentialPool._available_entries``: a benched row is skipped exactly
    like one in cooldown, so neither ``select`` nor a 401/429 rotation can lease it. With
    nothing stored for the chosen family the bench lifts, matching
    :func:`resolve_chosen_anthropic_token`'s fall-through."""
    if provider != "anthropic":
        return frozenset()
    chosen = chosen_credential_source(provider)
    if chosen is None:
        return frozenset()
    rows = [entry for entry in entries if _has_secret(entry)]
    if not any(entry_family(entry) == chosen for entry in rows):
        return frozenset()
    return frozenset(str(entry.id) for entry in rows if entry_family(entry) != chosen)


# ── the resolver ─────────────────────────────────────────────────────────────


def _env(*names: str) -> str:
    from ._upstream_doors import anthropic_env

    return anthropic_env(*names)


def _account_token() -> Optional[str]:
    """The ladder's account half, in the ladder's order: env OAuth token, pool grant, borrowed login."""
    import functools

    from agent import anthropic_credentials as creds

    from . import _upstream_doors as doors

    read = functools.cache(creds.read_claude_code_credentials)
    token = doors.anthropic_env("ANTHROPIC_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN")
    if token:
        return doors.anthropic_prefer_refreshable_token(token, read()) or token
    return doors.anthropic_pool_account_token() or doors.anthropic_resolve_claude_code_token(read())


def resolve_chosen_anthropic_token(model: Optional[str] = None) -> Optional[str]:
    """The token an explicit choice spends; None when unset (the caller's ladder runs).

    ``""`` means "chosen, and nothing usable": the chosen token benched for *model* does NOT
    fall to the other family. Only a family with nothing stored falls through."""
    chosen = chosen_credential_source("anthropic")
    if chosen is None:
        return None
    from . import _upstream_doors as doors

    api_key = doors.anthropic_env("ANTHROPIC_API_KEY")
    if chosen == API_KEY and api_key:
        return doors.anthropic_token_unless_benched(api_key, model) or ""
    account = _account_token()
    if account:
        return doors.anthropic_token_unless_benched(account, model) or ""
    return doors.anthropic_token_unless_benched(api_key, model) or ""


# ── the fact a client reads ──────────────────────────────────────────────────


def _account_stored() -> bool:
    from agent import anthropic_credentials as creds
    from agent.credential_sources import adopt_external_logins_enabled

    if _env("ANTHROPIC_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN"):
        return True
    if (creds.read_hermes_oauth_credentials() or {}).get("accessToken"):
        return True
    return bool(adopt_external_logins_enabled() and (creds.read_claude_code_credentials() or {}).get("accessToken"))


def _manual_families() -> set[str]:
    from agent.credential_pool import PooledCredential, read_credential_pool

    from ._upstream_doors import pool_source_is_manual

    families: set[str] = set()
    for payload in read_credential_pool("anthropic"):
        if not isinstance(payload, dict) or not pool_source_is_manual(str(payload.get("source") or "")):
            continue
        entry = PooledCredential.from_dict("anthropic", payload)
        if _has_secret(entry):
            families.add(entry_family(entry))
    return families


def present_credential_sources(provider: str) -> dict[str, bool]:
    """``{source_id: stored?}`` for every source the provider declares. Reads, never refreshes."""
    if provider != "anthropic":
        return {source_id: False for source_id, _label in credential_source_ids(provider)}
    try:
        manual = _manual_families()
    except Exception:
        manual = set()
    return {
        ACCOUNT: _account_stored() or ACCOUNT in manual,
        API_KEY: bool(_env("ANTHROPIC_API_KEY")) or API_KEY in manual,
    }


def _effective_source(provider: str, chosen: Optional[str], present: dict[str, bool]) -> Optional[str]:
    if chosen is not None:
        if present.get(chosen):
            return chosen
        return next((source_id for source_id, stored in present.items() if stored), None)
    # Unset: upstream's ladder — env account token, env key, stored grant, then a pooled key.
    if _env("ANTHROPIC_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN"):
        return ACCOUNT
    if _env("ANTHROPIC_API_KEY"):
        return API_KEY
    if present.get(ACCOUNT):
        return ACCOUNT
    return API_KEY if present.get(API_KEY) else None


def credential_source_block(provider: str) -> Optional[dict]:
    """``{chosen, effective, sources: [{id, label, present}]}``; None for a provider without a table.

    ``effective`` is what a turn spends now, so a client never infers it from pool rows."""
    table = credential_source_ids(provider)
    if not table:
        return None
    chosen = chosen_credential_source(provider)
    try:
        present = present_credential_sources(provider)
    except Exception:
        present = {source_id: False for source_id, _label in table}
    return {
        "chosen": chosen,
        "effective": _effective_source(provider, chosen, present),
        "sources": [{"id": source_id, "label": label, "present": bool(present.get(source_id))}
                    for source_id, label in table],
    }


def account_usage_token() -> Optional[str]:
    """The Claude account's stored token for a USAGE read, with no refresh and no pool lease.

    While the API key is effective the pool benches (or, unset, prunes) the account rows, so
    the grant is read where it is stored: env account token, the Hermes PKCE file, then the
    borrowed Claude Code login when adoption is on. An expired token simply reads no windows."""
    from agent import anthropic_credentials as creds
    from agent.credential_sources import adopt_external_logins_enabled

    token = _env("ANTHROPIC_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN")
    if token:
        return token
    stored = (creds.read_hermes_oauth_credentials() or {}).get("accessToken")
    if not stored and adopt_external_logins_enabled():
        stored = (creds.read_claude_code_credentials() or {}).get("accessToken")
    return str(stored or "").strip() or None
