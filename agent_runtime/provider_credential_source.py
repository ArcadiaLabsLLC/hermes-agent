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

**Eternia's Anthropic Account never borrows Claude Code's login** (owner, 2026-11-14,
``RT-ANTHROPIC-ACCOUNT-NEVER-BORROWS-CLAUDE-CODE-LOGIN``: "the boundry its being put in is its
own connector login button"). In a process Eternia spawned (``HERMES_LAUNCHER_SPAWNED=1``,
:func:`borrowed_login_fenced`) the account half is the Hermes PKCE grant the connection's Sign
in button drives (plus an env token or a manual row the user put there, each shown on its own):
the pool's ``claude_code`` row is benched, the resolver decides every turn itself so upstream's
ladder never reaches ``~/.claude/.credentials.json`` / the Keychain, and the status facts
(:func:`present_credential_sources`, :func:`visible_entries`, :func:`account_signed_in`) never
count it. Upstream's readers still SEE the file; nothing here spends or reports it. Outside
Eternia (a CLI user) the ladder is upstream's, byte for byte.

**The fence is one table, per provider** (:data:`BORROWED_LOGINS`, review w1118a.66 D3,
``RT-FU-A-QA-COPYS-QWEN-AND-COPILOT-SIGN-INS-COME-FROM-THIS-COMPUTERS-OWN-CLI-LOGINS``): a QA
copy runs with the machine user's HOME, so every other program's login under it is the
owner's. Qwen's is the Qwen CLI's ``~/.qwen/oauth_creds.json``: fenced, its one reader
(``hermes_cli/auth_qwen.py::_read_qwen_cli_tokens``) refuses it through
:func:`refuse_borrowed_login`, so the pool never seeds it, the runtime ladder never spends or
refreshes (rotates) it, and its status reads signed out; a Qwen row the profile's own pool
holds is what a turn spends. Copilot ACP runs the Copilot CLI on that CLI's own login: fenced,
it reads not connected (:func:`account_signed_in`) unless the pool holds a row of its own.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, Optional

__layer__ = "stores"

__all__ = [
    "ACCOUNT",
    "API_KEY",
    "CHOSEN_CREDENTIAL_UNUSABLE",
    "BORROWED_LOGINS",
    "BORROWED_SOURCES",
    "account_signed_in",
    "account_usage_token",
    "borrowed_login_fenced",
    "benched_entry_ids",
    "chosen_credential_source",
    "chosen_credential_unusable",
    "chosen_unusable_message",
    "credential_source_block",
    "credential_source_ids",
    "entry_family",
    "present_credential_sources",
    "refuse_an_unusable_chosen_credential",
    "refuse_borrowed_login",
    "resolve_chosen_anthropic_token",
    "visible_entries",
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

#: The ONE fence table: per provider, the pool sources that are another program's own login on
#: this computer, mirrored in. A provider listed here never borrows in a process Eternia spawned
#: (:func:`borrowed_login_fenced`); an empty set means that program's login is never a pool row
#: (the Copilot CLI runs on its own) and the provider reads connected only through its pool.
BORROWED_LOGINS: dict[str, frozenset[str]] = {
    "anthropic": frozenset({"claude_code"}),  # Claude Code's ~/.claude/.credentials.json / Keychain
    "qwen-oauth": frozenset({"qwen-cli"}),  # the Qwen CLI's ~/.qwen/oauth_creds.json
    "copilot-acp": frozenset(),  # the Copilot CLI's own login (``copilot --acp``)
}

#: Every borrowed pool source, whatever its provider.
BORROWED_SOURCES = frozenset().union(*BORROWED_LOGINS.values())


def borrowed_login_fenced(provider: str = "anthropic") -> bool:
    """True in a process Eternia spawned: the provider's account never borrows another CLI's login."""
    # MUTATION: drop "qwen-oauth" from BORROWED_LOGINS and test_qwen_cli_login_borrow_fence reddens.
    if provider not in BORROWED_LOGINS:
        return False
    import os

    from hermes_cli._namespace_bootstrap import launcher_spawned

    # MUTATION: return False here and test_anthropic_account_never_borrows_claude_code_login reddens.
    return launcher_spawned(os.environ)


def refuse_borrowed_login(provider: str) -> Optional[str]:
    """Why a fenced provider's borrowed-login reader must not read, else None (read as upstream does).

    The one door an upstream reader of another program's login file asks, beside the file's path."""
    if not borrowed_login_fenced(provider):
        return None
    return (f"Eternia never signs in to {provider} with this computer's own command-line login; "
            "sign in through this profile's own credential pool.")


def _borrowed(entry: Any, provider: str = "anthropic") -> bool:
    return str(getattr(entry, "source", "") or "") in BORROWED_LOGINS.get(provider, frozenset())


def visible_entries(provider: str, entries: Iterable[Any]) -> list[Any]:
    """*entries* minus the borrowed rows a fenced provider never reports (the Connections facts)."""
    entries = list(entries)
    if not borrowed_login_fenced(provider):
        return entries
    return [entry for entry in entries if not _borrowed(entry, provider)]


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
    entries = list(entries)
    fenced = frozenset(str(entry.id) for entry in entries
                       if _borrowed(entry, provider)) if borrowed_login_fenced(provider) else frozenset()
    if provider != "anthropic":
        return fenced
    chosen = chosen_credential_source(provider)
    if chosen is None:
        return fenced
    rows = [entry for entry in entries if _has_secret(entry) and str(entry.id) not in fenced]
    if not any(entry_family(entry) == chosen for entry in rows):
        return fenced
    return fenced | frozenset(str(entry.id) for entry in rows if entry_family(entry) != chosen)


# ── the chosen kind cannot serve (review w1118a.69 D1) ───────────────────────

#: The typed reason a model pick and a turn refuse with while every stored row of the CHOSEN kind
#: is exhausted or refused and a saved credential of the other kind exists
#: (RT-FU-A-SAVED-API-KEY-IS-NEVER-USED-WHILE-THE-CHOSEN-SIGN-IN-IS-EXHAUSTED, D1 (a)); the constant
#: lives in the models layer. The bench stays: ``credential_source`` is a spending choice, so nothing
#: is spent from the other kind until the person switches (``runtime.provider.source.set``).
from .provider_login_expiry import CHOSEN_CREDENTIAL_UNUSABLE  # noqa: E402  (models layer, points down)


def chosen_credential_unusable(provider: str, pool: Any = None, *, model: Optional[str] = None) -> bool:
    """True when the chosen kind holds rows but none can serve *model*, and the other kind holds one.

    False (the usual refusal stands) when no choice is set, when the chosen kind has nothing stored
    (the bench lifts, :func:`benched_entry_ids`), when nothing of the other kind is saved, or when a
    chosen row is usable. *pool* is an already-loaded pool, else the provider's is loaded in the
    caller's profile. Never raises: a pool that cannot be read is not proof of anything."""
    if provider != "anthropic" or chosen_credential_source(provider) is None:
        return False
    chosen = chosen_credential_source(provider)
    try:
        if pool is None:
            from agent.credential_pool import load_pool

            pool = load_pool(provider)
        fenced = borrowed_login_fenced(provider)
        rows = [entry for entry in pool.entries()
                if _has_secret(entry) and not (fenced and _borrowed(entry, provider))]
        if not any(entry_family(entry) == chosen for entry in rows):
            return False
        # MUTATION: drop this guard and test_no_saved_other_kind_keeps_the_usual_refusal reddens.
        if not any(entry_family(entry) != chosen for entry in rows):
            return False
        # The unchosen rows are benched while a chosen row is stored, so this is the chosen kind's answer.
        # MUTATION: return True here and test_a_usable_chosen_row_is_not_refused reddens.
        return not pool.has_available(model=model)
    except Exception:
        return False


def chosen_unusable_message(provider: str) -> str:
    """The refusal's words: which kind was chosen, and that the other kind is not spent. No secret."""
    labels = dict(credential_source_ids(provider))
    chosen = chosen_credential_source(provider) or ""
    other = next((label for source_id, label in labels.items() if source_id != chosen), "the other credential")
    return (f"Provider '{provider}': the credential chosen for its turns ({labels.get(chosen, chosen)}) cannot "
            f"be used right now, so the request was not sent. A saved {other} is not spent unless you "
            "switch to it; switch which credential this provider uses, or wait for the chosen one to recover.")


def refuse_an_unusable_chosen_credential(request: Any) -> None:
    """Refuse a run, before any token, while its provider's CHOSEN credential cannot serve and one of
    the other kind is saved: named, typed :data:`CHOSEN_CREDENTIAL_UNUSABLE`, and the other kind is
    never spent. The runner calls it inside the persona's profile (``operator_turn_policy.OperatorTurn``), so
    that profile's pool and choice are what is read; a prewarm is never refused."""
    if getattr(request, "prewarm_only", False) or not getattr(request, "provider", None):
        return
    provider = str(request.provider)
    # MUTATION: return before this check and test_a_turn_on_an_exhausted_chosen_sign_in_is_refused_typed reddens.
    if chosen_credential_unusable(provider, model=getattr(request, "model", None)):
        from .provider_login_expiry import NamedProviderNotConfiguredError

        raise NamedProviderNotConfiguredError(chosen_unusable_message(provider), provider=provider,
                                              credentials_reason=CHOSEN_CREDENTIAL_UNUSABLE)


# ── the resolver ─────────────────────────────────────────────────────────────


def _env(*names: str) -> str:
    from ._upstream_doors import anthropic_env

    return anthropic_env(*names)


def _account_token() -> Optional[str]:
    """The ladder's account half, in the ladder's order: env OAuth token, pool grant, borrowed login."""
    import functools

    from agent import anthropic_credentials as creds

    from . import _upstream_doors as doors

    token = doors.anthropic_env("ANTHROPIC_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN")
    if borrowed_login_fenced():  # never the borrowed login, not even to swap a static env token for it
        return token or doors.anthropic_pool_account_token()
    read = functools.cache(creds.read_claude_code_credentials)
    if token:
        return doors.anthropic_prefer_refreshable_token(token, read()) or token
    return doors.anthropic_pool_account_token() or doors.anthropic_resolve_claude_code_token(read())


def resolve_chosen_anthropic_token(model: Optional[str] = None) -> Optional[str]:
    """The token an explicit choice spends; None when unset (the caller's ladder runs).

    ``""`` means "chosen, and nothing usable": the chosen token benched for *model* does NOT
    fall to the other family. Only a family with nothing stored falls through.

    Fenced (:func:`borrowed_login_fenced`) it never answers None: unset runs the ladder's order
    here, without the borrowed login, so upstream's ladder never reaches it."""
    chosen = chosen_credential_source("anthropic")
    from . import _upstream_doors as doors

    if chosen is None:
        if not borrowed_login_fenced():
            return None
        token = (doors.anthropic_env("ANTHROPIC_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN")
                 or doors.anthropic_env("ANTHROPIC_API_KEY") or doors.anthropic_pool_account_token())
        return doors.anthropic_token_unless_benched(token, model) or ""

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
    if borrowed_login_fenced():
        return False
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
    if not stored and not borrowed_login_fenced() and adopt_external_logins_enabled():
        stored = (creds.read_claude_code_credentials() or {}).get("accessToken")
    return str(stored or "").strip() or None


def _pool_signed_in(provider: str) -> bool:
    """A row of the provider's own pool, with a secret, that is not a borrowed login."""
    from agent.credential_pool import load_pool

    return any(_has_secret(entry) and not _borrowed(entry, provider) for entry in load_pool(provider).entries())


def account_signed_in(provider: str) -> Optional[bool]:
    """A fenced provider's sign-in fact (a stored credential of its own), else None (ask upstream).

    Upstream's ``get_auth_status`` counts every pool row, the borrowed one included; for Qwen and
    Copilot ACP it reads the CLI's own login, which a fenced process never counts."""
    if not borrowed_login_fenced(provider):
        return None
    if provider == "anthropic":
        return any(present_credential_sources(provider).values())
    # MUTATION: answer None here and test_copilot_acp_reads_not_connected_on_its_cli_login reddens.
    return _pool_signed_in(provider)
