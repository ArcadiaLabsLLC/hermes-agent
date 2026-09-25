"""``hermes harness providers``: which providers, keys and logins this operator can see.

Separate because the visibility envelope is read by the launcher's model picker;
every probe here is failure-isolated.
"""

from __future__ import annotations

from typing import Optional

from agent_runtime.cli_format import emit_json

__layer__ = "policy"
__all__ = [
    "_TOKEN_PREVIEW_CHARS",
    "_cmd_providers",
    "_credential_health",
    "_credential_token_preview",
    "_provider_visibility_api_keys",
    "_provider_visibility_auth_logins",
    "_provider_visibility_catalog",
    "_provider_visibility_environment",
    "_record_visibility_block",
    "build_provider_visibility",
]


def _credential_health(entry) -> dict:
    """Typed health for one pooled credential, derived from the SAME upstream
    classification the human `hermes auth list` uses — reused, never
    re-implemented, so there is exactly one authority on what "401 vs 429 vs
    dead" means. A healthy credential carries no annotation; an exhausted one
    is split into auth_failed / rate_limited / exhausted with the retry window;
    a dead credential (which the human list renders with NO marker — a latent
    "looks healthy" bug) is surfaced explicitly.
    """
    from agent.credential_pool import STATUS_DEAD, STATUS_EXHAUSTED, _exhausted_until
    from hermes_cli.auth_commands import (
        _classify_exhausted_status,
        _format_exhausted_status,
    )

    last_status = getattr(entry, "last_status", None)
    if last_status not in {STATUS_EXHAUSTED, STATUS_DEAD}:
        return {"state": "healthy"}

    message = _format_exhausted_status(entry).strip()
    if last_status == STATUS_DEAD:
        return {
            "state": "dead",
            "code": getattr(entry, "last_error_code", None),
            "reason": getattr(entry, "last_error_reason", None),
            "retry_at": None,
            "message": message or "credential dead (re-auth required)",
        }

    label, retryable = _classify_exhausted_status(entry)
    state = {"auth failed": "auth_failed", "rate-limited": "rate_limited"}.get(
        label, "exhausted"
    )
    return {
        "state": state,
        "code": getattr(entry, "last_error_code", None),
        "reason": getattr(entry, "last_error_reason", None),
        "retry_at": _exhausted_until(entry) if retryable else None,
        "message": message,
    }


#: How many trailing characters of a credential a preview may show. Matches the
#: dashboard's existing rule (`web_server.py::_truncate_token`), deliberately
#: SHORTER than its 6 because this payload is consumed by a GUI that only needs
#: to tell two keys apart, not to identify one out of context.
_TOKEN_PREVIEW_CHARS = 4


def _credential_token_preview(entry) -> Optional[str]:
    """``…abcd`` — the last few characters of a pooled credential, or None.

    This is the ONLY function in the provider-visibility payload that reads a
    credential value, and it is written so that no input can make it emit more
    than [_TOKEN_PREVIEW_CHARS] characters:

    * a value shorter than 2× the preview length yields None rather than a
      short secret rendered nearly whole — a 6-character key must not become
      its own preview;
    * a non-string (the Entra-ID bearer *callable*, for instance) yields None
      and is NEVER invoked;
    * every failure path yields None.

    A preview is not a fallback for an absent value: absence is None, and the
    client renders "no preview" rather than an empty-looking secret.
    """
    try:
        raw = getattr(entry, "access_token", None)
        if not isinstance(raw, str):
            return None
        value = raw.strip()
        if len(value) < _TOKEN_PREVIEW_CHARS * 2:
            return None
        return f"…{value[-_TOKEN_PREVIEW_CHARS:]}"
    except Exception:
        return None


def _record_visibility_block(payload: dict, name: str, builder) -> None:
    """Build one failure-isolated ``provider_visibility`` block, and NAME the
    failure when the builder raises.

    The isolation itself is load-bearing (a broken status probe must never break
    the credential payload the launcher's model switcher depends on), but until
    EG-6.1 the isolator was a bare ``except Exception: pass`` and an absent block
    meant TWO things: "this hermes is too old to emit it" or "this hermes tried
    and the builder threw". The `catalog` block made that worst: it exists
    precisely to separate "never configured" from "configured and dead", so a
    silent drop fell the client back into the indistinguishable rendering the
    block was added to end.

    So a raise records ``block_errors[name] = <ExceptionClass>`` — the class NAME
    only, never ``str(exc)``, the same disclosure rule
    [_usage_failure_reason] and [_credential_token_preview] follow: a status
    probe's message can carry a resolved key, a URL or a header.

    ``block_errors`` is written ONLY when something actually threw. A healthy
    build carries no such key at all, so the three wire states stay distinct:
    block present (built), block absent with no ``block_errors`` (old hermes /
    never emitted), block absent and named in ``block_errors`` (this hermes
    tried and failed).
    """
    try:
        value = builder()
    except Exception as exc:  # noqa: BLE001 — class name only, block isolated
        payload.setdefault("block_errors", {})[name] = type(exc).__name__
        return
    payload[name] = value


def _provider_visibility_catalog() -> list[dict]:
    """The `catalog` block: every CONNECTABLE provider, credential or not.

    Failure-isolated by its caller like every other v2 block. See
    `hermes_cli.provider_catalog.provider_login_catalog` for why this exists —
    in one line: without it a client cannot distinguish "never configured" from
    "configured and dead", because both render as an absence of usable models.
    """
    from hermes_cli.provider_catalog import provider_login_catalog

    return provider_login_catalog()


def build_provider_visibility() -> dict:
    """Typed, machine-readable snapshot of every credential pool — the contract
    the Launcher's provider/model surfaces consume instead of scraping the
    human `hermes auth list` table. Mirrors that command's provider iteration
    (skips empty pools, marks the selected credential) but emits structure, not
    prose, so a present-but-failing credential is never indistinguishable from
    an absent one.
    """
    from agent.credential_pool import list_custom_pool_providers, load_pool
    from hermes_cli.auth import PROVIDER_REGISTRY
    from hermes_cli.auth_commands import _display_source

    provider_ids = sorted(
        {*PROVIDER_REGISTRY.keys(), "openrouter", *list_custom_pool_providers()}
    )
    providers_out = []
    for provider in provider_ids:
        pool = load_pool(provider)
        entries = pool.entries()
        if not entries:
            continue
        current = pool.peek()
        credentials = []
        for idx, entry in enumerate(entries, start=1):
            credentials.append(
                {
                    "index": idx,
                    "label": entry.label,
                    "auth_type": entry.auth_type,
                    "source": _display_source(entry.source),
                    "selected": current is not None and entry.id == current.id,
                    "health": _credential_health(entry),
                    # Last-4 only, matching the dashboard's existing preview
                    # rule. Enough to tell two keys apart in a UI; never enough
                    # to use. See _credential_token_preview for why this is the
                    # only shape allowed anywhere near this payload.
                    "token_preview": _credential_token_preview(entry),
                }
            )
        providers_out.append({"id": provider, "credentials": credentials})
    payload: dict = {
        "schema": "hermes.provider_visibility/v2",
        "providers": providers_out,
    }
    # v2 additions (transport plan W4): the fields the launcher used to
    # scrape out of the human `hermes status` ◆-box — model/provider, API-key
    # presence (upstream's `status_auth._API_KEYS` is the box's own registry,
    # read directly so this cannot drift from it), and OAuth login state. Each block is
    # failure-isolated: a broken import or status probe drops the block, it
    # NEVER breaks the credential payload above (which the launcher's model
    # switcher depends on). Consumers treat an absent block as "fall back to
    # the scrape", exactly like a v1 hermes — and since EG-6.1 a block that
    # dropped because its builder RAISED is named in `block_errors` by exception
    # class, so absence no longer means two things. See
    # [_record_visibility_block].
    _record_visibility_block(payload, "environment", _provider_visibility_environment)
    _record_visibility_block(payload, "api_keys", _provider_visibility_api_keys)
    _record_visibility_block(payload, "auth_logins", _provider_visibility_auth_logins)
    from agent_runtime.local_llama_adapter.provider import catalog_visibility as local_llama_catalog_visibility
    _record_visibility_block(payload, "local_llama", local_llama_catalog_visibility)
    # The `catalog` block (plan PL-1). Additive and failure-isolated exactly
    # like the three blocks above, and — deliberately — WITHOUT a schema bump.
    #
    # Decided out loud at PL-1: the schema string stays
    # `hermes.provider_visibility/v2`. Every consumer feature-detects blocks
    # rather than reading the version (the Launcher decides "v2" by the
    # presence of `environment`, and never reads `schema` at all), so a bump
    # buys no consumer behaviour; meanwhile the string IS pinned by tests, one
    # of which was left stale and red by the v1→v2 bump. A version string
    # nothing branches on is a change-detector, so the additive-key path — the
    # one the plan names as preferred when a consumer pins the string — is
    # taken. `catalog` present ⇒ this hermes can name connectable providers.
    _record_visibility_block(payload, "catalog", _provider_visibility_catalog)
    return payload


def _provider_visibility_environment() -> dict:
    from hermes_cli.status import _configured_model_label, _effective_provider_label

    try:
        from hermes_cli.config import load_config

        config = load_config()
    except Exception:
        config = {}
    return {
        "model": _configured_model_label(config),
        "provider": _effective_provider_label(),
    }


def _provider_visibility_api_keys() -> list[dict]:
    """The status box's API-key rows, in its order: upstream's ``_API_KEYS``
    registry, then Anthropic, which the box renders last through the dedicated
    lookup (it also resolves OAuth tokens)."""
    from hermes_cli.auth import get_anthropic_key
    from hermes_cli.status import _first_env_value
    from hermes_cli.status_auth import _API_KEYS

    out = [{"name": name, "configured": bool(_first_env_value(env_ref))} for name, env_ref in _API_KEYS.items()]
    out.append({"name": "Anthropic", "configured": bool(get_anthropic_key())})
    return out


def _provider_visibility_auth_logins() -> list[dict]:
    from hermes_cli.auth import (
        get_codex_auth_status,
        get_minimax_oauth_auth_status,
        get_nous_auth_status,
        get_qwen_auth_status,
    )

    logins: list[dict] = []
    for name, probe in (
        ("Nous Portal", get_nous_auth_status),
        ("OpenAI Codex", get_codex_auth_status),
        ("Qwen", get_qwen_auth_status),
        ("MiniMax", get_minimax_oauth_auth_status),
    ):
        try:
            status = probe() or {}
        except Exception:
            status = {}
        entry: dict = {"name": name, "logged_in": bool(status.get("logged_in"))}
        refreshed = status.get("last_refresh")
        if refreshed:
            entry["refreshed_at"] = str(refreshed)
        logins.append(entry)
    return logins


def _cmd_providers(args) -> int:
    payload = build_provider_visibility()
    if getattr(args, "json", False):
        print(emit_json(payload))
        return 0
    if not payload["providers"]:
        print("No credential pools configured.")
        return 0
    for provider in payload["providers"]:
        print(f"{provider['id']} ({len(provider['credentials'])} credentials):")
        for credential in provider["credentials"]:
            health = credential["health"]
            tag = "" if health["state"] == "healthy" else f"  [{health['state']}]"
            marker = " ←" if credential["selected"] else ""
            print(
                f"  #{credential['index']}  {credential['label']:<20} "
                f"{credential['auth_type']:<7} {credential['source']}{tag}{marker}"
            )
    return 0
