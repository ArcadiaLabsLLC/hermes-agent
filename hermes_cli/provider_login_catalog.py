"""Login-flow metadata over ``hermes_cli.provider_catalog`` — fork-owned.

Lane FOOTPRINT-DROP (2026-09-27) moved this block out of upstream's
``hermes_cli/provider_catalog.py``, which is upstream's bytes again. The OAuth login-flow
rows (``OAUTH_FLOW_OVERRIDES``, ``disconnect_command_for``) are the G15 PR candidate
that would hoist them into upstream's catalog; ``provider_login_catalog`` /
``MODELS_DEV_LANE_IDS`` / ``models_dev_id_for`` are the launcher roster and stay here.
The catalog itself is read through the module at call time, so a patched
``provider_catalog.provider_catalog`` is the one this module sees.
"""

from __future__ import annotations

from hermes_cli import provider_catalog as _catalog


def provider_disabled(slug: str) -> bool:
    """``providers.<slug>.enabled: false`` in this home's config — the existing switch that hides a
    provider from the picker and refuses it in the runtime resolver. The login catalog, the
    credential visibility snapshot and the machine sign-in honour it too, so a distribution
    profile can take a provider out whole (bundled desktop: ``qwen-oauth``). Never raises."""
    try:
        from hermes_cli.config import load_config_readonly
        from hermes_cli.config_providers import is_provider_enabled

        providers = (load_config_readonly() or {}).get("providers")
        block = providers.get(slug) if isinstance(providers, dict) else None
    except Exception:
        return False
    return isinstance(block, dict) and not is_provider_enabled(block)


# ---------------------------------------------------------------------------
# Login-flow metadata (hoisted 2026-08-16, plan PL-1)
# ---------------------------------------------------------------------------
#
# These rows used to live ONLY inside ``hermes_cli/web_server.py`` as
# ``_OAUTH_PROVIDER_CATALOG`` — welded to the FastAPI dashboard process, and so
# unreachable from any surface that does not run it (the Launcher runs a local
# ``hermes`` CLI, never the dashboard). The module docstring above already names
# that tuple as one of the hand-maintained lists this module exists to unify, so
# the DATA moves here and web_server keeps only the binding of its per-provider
# ``status_fn`` callables (which are dashboard presentation, not identity).
#
# ``flow`` describes the login SHAPE so any client can pick the right UI:
#   ``pkce``        — open a URL, paste the callback code back
#   ``device_code`` — show a user code + verification URI, poll for the token
#   ``external``    — delegated to a third-party CLI; Hermes only reads it
#
# Two rows are deliberately NOT catalog providers but must still be offered as
# sign-ins: the Anthropic PKCE card and the synthetic ``claude-code``
# subscription row.
OAUTH_FLOW_OVERRIDES: tuple[dict, ...] = ({'id': 'nous',
  'name': 'Nous Portal',
  'flow': 'device_code',
  'cli_command': 'hermes auth add nous',
  'docs_url': 'https://portal.nousresearch.com'},
 {'id': 'openai-codex',
  'name': 'ChatGPT or Codex Subscription',
  'flow': 'device_code',
  'cli_command': 'hermes auth add openai-codex',
  'docs_url': 'https://platform.openai.com/docs'},
 {'id': 'qwen-oauth',
  'name': 'Qwen (via Qwen CLI)',
  'flow': 'external',
  'cli_command': 'hermes auth add qwen-oauth',
  'docs_url': 'https://github.com/QwenLM/qwen-code'},
 {'id': 'minimax-oauth',
  'name': 'MiniMax (OAuth)',
  'flow': 'device_code',
  'cli_command': 'hermes auth add minimax-oauth',
  'docs_url': 'https://www.minimax.io'},
 {'id': 'xai-oauth',
  'name': 'xAI Grok OAuth (SuperGrok / Premium+)',
  'flow': 'device_code',
  'cli_command': 'hermes auth add xai-oauth',
  'docs_url': 'https://hermes-agent.nousresearch.com/docs/guides/xai-grok-oauth'},
 {'id': 'copilot-acp',
  'name': 'GitHub Copilot (ACP)',
  'flow': 'external',
  'cli_command': 'copilot login',
  'docs_url': 'https://docs.github.com/en/copilot'},
 {'id': 'anthropic',
  'name': 'Anthropic Account',
  'flow': 'external',
  'cli_command': 'hermes auth add anthropic',
  'docs_url': 'https://docs.claude.com/en/api/getting-started'},
 {'id': 'claude-code',
  'name': 'Anthropic OAuth: Required Extra Usage Credits to Use Subscription',
  'flow': 'external',
  'cli_command': 'claude setup-token',
  'docs_url': 'https://docs.claude.com/en/docs/claude-code'})


# Lanes whose models live under a DIFFERENT models.dev catalog id. Seeded from
# the map the Launcher hardcoded (hand-verified 2026-07-08) so the mapping now
# drifts with the fork that owns the lanes instead of with the client.
MODELS_DEV_LANE_IDS: dict[str, str] = {
    "openai-codex": "openai",
    "opencode-zen": "opencode",
    "xai-oauth": "xai",
    "minimax-oauth": "minimax",
    "qwen-oauth": "alibaba",
}


def models_dev_id_for(slug: str) -> str:
    """The models.dev catalog id serving ``slug``'s model list.

    Defaults to the slug itself — most lanes ARE their catalog id; only the
    hermes-specific OAuth lanes above need redirecting.
    """
    return MODELS_DEV_LANE_IDS.get(slug, slug)


def disconnect_command_for(slug: str, flow: str, platform: str | None = None) -> str | None:
    """The documented command that clears an EXTERNAL provider's credentials.

    External providers store credentials outside Hermes, so Hermes never
    deletes them behind a silent API call — it hands the operator the exact
    command instead. Returns None for providers we cannot safely clear (the UI
    shows a manual hint) and for every non-external flow.

    Claude Code has no scriptable logout (only the interactive ``/logout``), so
    the command removes the same two sources ``read_claude_code_credentials()``
    consults, host-native per ``platform`` (default: this process).
    """
    if flow != "external":
        return None
    if slug == "claude-code":
        import sys as _sys

        host = platform or _sys.platform
        if host == "win32":
            literal = '"$HOME/.claude/.credentials.json"'
            return (
                f"if (Test-Path -LiteralPath {literal}) {{ "
                f"Remove-Item -LiteralPath {literal} -Force -ErrorAction Stop }}"
            )
        rm_file = "rm -f ~/.claude/.credentials.json"
        if host == "darwin":
            return (
                'security delete-generic-password -s "Claude Code-credentials" '
                f"2>/dev/null; {rm_file}"
            )
        return rm_file
    return None


def provider_login_catalog() -> list[dict]:
    """Every CONNECTABLE provider, whether or not a credential exists for it.

    This is the block that makes "never configured" representable. A client
    that builds its provider roster from credentials-present + logins-present
    (which is what every hermes client did before this existed) can render
    "this key is dead" but literally cannot render "you could connect this" —
    the two states collapse into the same absence-of-models.

    MEMBERSHIP is the union of the whole ``provider_catalog()`` universe (the
    set ``hermes model`` offers) and [OAUTH_FLOW_OVERRIDES] — the latter adds
    the two synthetic sign-in rows that are not catalog providers. Order:
    catalog order first, then any override-only rows.

    Each row: ``{id, name, flows, key_var, models_dev_id, docs_url,
    disconnect_command}``. NEVER a credential value — this block describes what
    CAN be connected, never what is stored.
    """
    from hermes_cli.model_picker_policy import model_picker_policy_for

    overrides = {row["id"]: row for row in OAUTH_FLOW_OVERRIDES}
    rows: list[dict] = []
    seen: set[str] = set()

    def _emit(
        slug: str, name: str, default_flow: str, key_var: str | None, docs_url: str
    ) -> None:
        if slug in seen:
            return
        seen.add(slug)
        if provider_disabled(slug):
            return
        override = overrides.get(slug)
        flow = (override or {}).get("flow") or default_flow
        # `flows` is a LIST because a lane can legitimately offer more than one
        # entrance — anthropic takes a pasted API key OR the PKCE sign-in — and
        # a client that only knows one of them offers a dead affordance.
        flows = [flow]
        if key_var and flow != "api_key":
            flows.append("api_key")
        rows.append(
            {
                "id": slug,
                "name": (override or {}).get("name") or name or slug,
                "flows": flows,
                "key_var": key_var,
                "models_dev_id": models_dev_id_for(slug),
                "docs_url": (override or {}).get("docs_url") or docs_url or None,
                "disconnect_command": disconnect_command_for(slug, flow),
                "model_picker": model_picker_policy_for(slug),
            }
        )

    for descriptor in _catalog.provider_catalog():
        key_var = (
            descriptor.api_key_env_vars[0] if descriptor.api_key_env_vars else None
        )
        _emit(
            descriptor.slug,
            descriptor.label,
            _default_flow_for(descriptor.auth_type),
            key_var,
            descriptor.signup_url,
        )
    for row in OAUTH_FLOW_OVERRIDES:
        _emit(row["id"], row["name"], row["flow"], None, row["docs_url"])
    return rows


def _default_flow_for(auth_type: str) -> str:
    """Login shape implied by a provider's ``auth_type`` when no override row
    names one explicitly."""
    if auth_type == "oauth_device_code":
        return "device_code"
    if auth_type in {"oauth_external", "external_process", "copilot"}:
        return "external"
    if auth_type.startswith("oauth"):
        return "pkce"
    return "api_key"
