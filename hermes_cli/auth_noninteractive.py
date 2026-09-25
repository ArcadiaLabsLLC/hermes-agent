"""Non-interactive credential verbs — the machine-drivable half of ``hermes auth``.

``hermes auth add`` is a TTY flow: it prompts through
:func:`hermes_cli.secret_prompt.masked_secret_prompt`, which falls back to
``getpass.getpass`` on a non-tty stdin (``secret_prompt.py:56-81``). ``getpass``
on a piped Windows stdin emits a ``GetPassWarning`` to stderr and echoes its
prompt — behaviour a GUI cannot parse and must not have to. So this module owns
one deterministic entry point instead: read the secret as the FIRST LINE of
stdin, ourselves, with no prompt and no warning.

Three properties are the whole point of this module, and every one of them is
a test in ``tests/cli/test_auth_noninteractive.py``:

1. **The secret never appears in argv.** There is deliberately no
   ``--api-key <value>`` flag on ``set-key`` (``auth add`` has one; this verb
   must not, because THIS is the verb a GUI drives, and argv is visible in
   process listings, transport receipts, and shell history). The value arrives
   on stdin and lives in one local for the length of one call.

2. **The secret is never echoed.** The ack is JSON carrying key NAMES, the
   resolved home, and nothing else. This module inherits the
   ``credential_lifecycle`` secrecy contract verbatim: no function here logs,
   prints, or returns a credential value.

3. **The write NAMES the home it landed in.** A credential written to the
   wrong Hermes home is indistinguishable, from every read surface, from a
   credential that was never written — which is the exact confusion this whole
   effort exists to end. So the ack always carries ``home`` (and ``profile``
   when one was requested), whether or not ``--profile`` was passed. A caller
   that shows the operator "saved to <home>" cannot silently fix the wrong
   world.

Writes route through :func:`hermes_cli.credential_lifecycle.save_provider_env_credential`
— the declared single choke point across ``.env`` / ``auth.json`` /
``config.yaml`` — so a GUI-driven save cannot recreate the mirror-drift bug
family (#51071 / #59761 / #62269) that the choke point exists to prevent.
"""

from __future__ import annotations

import json
import sys
import uuid
from typing import Any, Optional


class NonInteractiveAuthError(Exception):
    """A failure that should be reported as a JSON error, not a traceback."""

    def __init__(self, reason: str, code: str = "error"):
        super().__init__(reason)
        self.reason = reason
        self.code = code


def _read_secret_from_stdin() -> str:
    """The first line of stdin, stripped of its newline. Deterministic.

    Uses ``readline`` rather than ``read``: a caller that keeps the pipe open
    (to send a cancel, or because it reuses the handle) must not make this
    block forever waiting for EOF. Trailing ``\\r`` is stripped so a Windows
    caller writing ``\\r\\n`` does not store a credential with a carriage
    return welded to it — a failure that would present as an unexplained 401.
    """
    line = sys.stdin.readline()
    if not line:
        raise NonInteractiveAuthError(
            "No secret on stdin. Write the value followed by a newline.",
            code="empty_stdin",
        )
    return line.rstrip("\n").rstrip("\r").strip()


def resolve_target_home(profile: Optional[str]) -> tuple[str, Optional[str]]:
    """Return ``(home_path, applied_profile)`` for this write.

    ``profile`` of None/""/"current" means "whatever home this process already
    resolves" — the caller still gets it back by name. A named profile is
    resolved through :mod:`hermes_cli.profiles` so the answer is the same one
    every other hermes surface would give.

    NOTE on ``HERMES_AUTH_HOME``: inside a profile context the runtime pins
    that env var to the HEAD home (``agent_runtime/profile_context.py``) so a
    persona shares the head credential store. Since the 2026-09-17 theme-7
    ruling that pin selects the ACTIVE store — ``hermes_cli.auth._auth_file_path``
    consumes it for reads AND writes — so under a binding the credential this
    function reports a home for actually lands in the HEAD's ``auth.json``, not
    in the home returned here. The returned home is the profile identity the
    caller asked about; naming it is the point precisely because the two can
    differ.
    """
    from hermes_constants import get_hermes_home

    requested = (profile or "").strip()
    if not requested or requested.lower() == "current":
        return str(get_hermes_home()), None

    from hermes_cli.profiles import get_profile_dir, normalize_profile_name

    name = normalize_profile_name(requested)
    return str(get_profile_dir(name)), name


def _provider_key_var(provider: str) -> Optional[str]:
    """The registered API-key env var for ``provider``, or None.

    Providers with a registered var go through the lifecycle choke point (which
    reconciles .env + pool + config mirrors). Providers without one — custom
    pools, mostly — have no env var to write, so they take the manual-pool path
    below.

    Reads the UNIFIED catalog rather than ``PROVIDER_REGISTRY`` directly: the
    registry is only one of the two places a key var can be declared (a
    ``ProviderProfile``'s ``env_vars`` is the other, and it is where e.g.
    ``openrouter`` declares ``OPENROUTER_API_KEY``). Consulting the registry
    alone silently sent registry-less providers down the custom-pool path,
    where they were rejected outright.
    """
    try:
        from hermes_cli.provider_catalog import provider_catalog_by_slug

        descriptor = provider_catalog_by_slug().get(provider)
        env_vars = tuple(getattr(descriptor, "api_key_env_vars", ()) or ())
        return env_vars[0] if env_vars else None
    except Exception:
        return None


def set_key(
    provider: str,
    secret: str,
    *,
    label: Optional[str] = None,
    profile: Optional[str] = None,
) -> dict:
    """Store ``secret`` as ``provider``'s API key. Returns the ack dict.

    Never returns, logs, or raises with the secret in it.
    """
    from hermes_cli.auth_commands import _normalize_provider
    from agent.credential_pool import CUSTOM_POOL_PREFIX

    normalized = _normalize_provider(provider)
    if not secret:
        raise NonInteractiveAuthError("No API key provided.", code="empty_secret")

    home, applied_profile = resolve_target_home(profile)

    token = None
    if applied_profile is not None:
        from hermes_constants import (
            reset_hermes_home_override,
            set_hermes_home_override,
        )

        token = set_hermes_home_override(home)
    try:
        key_var = _provider_key_var(normalized)
        if key_var:
            from hermes_cli.credential_lifecycle import save_provider_env_credential

            result = save_provider_env_credential(key_var, secret)
            ack = {
                "ok": bool(result.get("ok", True)),
                "provider": normalized,
                "label": key_var,
                "key_var": key_var,
                "config_updates": list(result.get("config_updates") or []),
            }
        else:
            # No registered env var (custom pools). The lifecycle choke point
            # has nothing to reconcile, so store a manual pool entry — the same
            # record `auth add --type api-key` writes.
            from agent.credential_pool import (
                AUTH_TYPE_API_KEY,
                PooledCredential,
                SOURCE_MANUAL,
                load_pool,
            )
            from hermes_cli.auth_commands import (
                _api_key_default_label,
                _provider_base_url,
            )

            if not normalized.startswith(CUSTOM_POOL_PREFIX):
                raise NonInteractiveAuthError(
                    f"{normalized} has no registered API-key variable; "
                    "use `hermes auth add` for its login flow.",
                    code="no_key_var",
                )
            pool = load_pool(normalized)
            resolved_label = (label or "").strip() or _api_key_default_label(
                len(pool.entries()) + 1
            )
            pool.add_entry(
                PooledCredential(
                    provider=normalized,
                    id=uuid.uuid4().hex[:6],
                    label=resolved_label,
                    auth_type=AUTH_TYPE_API_KEY,
                    priority=0,
                    source=SOURCE_MANUAL,
                    access_token=secret,
                    base_url=_provider_base_url(normalized),
                )
            )
            ack = {
                "ok": True,
                "provider": normalized,
                "label": resolved_label,
                "key_var": None,
                "config_updates": [],
            }
    finally:
        if token is not None:
            reset_hermes_home_override(token)

    # Always name the world this landed in — see the module docstring.
    ack["home"] = home
    ack["profile"] = applied_profile
    return ack


def auth_set_key_command(args) -> int:
    """``hermes auth set-key <provider> --stdin [--label L] [--profile P]``."""
    if not getattr(args, "stdin", False):
        # The ONLY way in. Refusing to fall back to a prompt keeps the verb
        # non-interactive by construction: there is no path where this command
        # blocks a GUI on a terminal that will never be typed into.
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": "set-key reads the secret from stdin; pass --stdin.",
                    "code": "stdin_required",
                }
            )
        )
        return 2

    try:
        secret = _read_secret_from_stdin()
        ack = set_key(
            str(getattr(args, "provider", "") or ""),
            secret,
            label=getattr(args, "label", None),
            profile=getattr(args, "profile", None),
        )
    except NonInteractiveAuthError as exc:
        print(json.dumps({"ok": False, "error": exc.reason, "code": exc.code}))
        return 1
    except Exception as exc:  # noqa: BLE001
        # CLASS NAME ONLY. An exception raised anywhere on this path has had a
        # credential value in scope; its message is not safe to print.
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": f"set-key failed ({type(exc).__name__})",
                    "code": "internal_error",
                }
            )
        )
        return 1
    finally:
        # Drop the reference promptly. This is hygiene, not a guarantee —
        # CPython gives no way to wipe a str's backing buffer — and the real
        # protection is that the value was never written anywhere but the
        # store.
        secret = None  # noqa: F841

    print(json.dumps(ack))
    return 0


def _login_flow_for(provider: str) -> tuple[Optional[str], Optional[str]]:
    """``(flow, cli_command)`` for ``provider`` from the login catalog."""
    try:
        from hermes_cli.provider_catalog import (
            OAUTH_FLOW_OVERRIDES,
            provider_login_catalog,
        )

        commands = {row["id"]: row.get("cli_command") for row in OAUTH_FLOW_OVERRIDES}
        for row in provider_login_catalog():
            if row["id"] == provider:
                flows = row.get("flows") or []
                return (
                    flows[0] if flows else None,
                    commands.get(provider) or f"hermes auth add {provider}",
                )
    except Exception:
        pass
    return None, f"hermes auth add {provider}"


def auth_login_command(args) -> int:
    """NDJSON browser sign-in; unsupported providers fail without prompting."""
    from hermes_cli.provider_browser_login import browser_login_command, supports_browser_login
    from hermes_constants import reset_hermes_home_override, set_hermes_home_override

    provider = str(getattr(args, "provider", "") or "").strip().lower()
    flow, cli_command = _login_flow_for(provider)
    home, applied_profile = resolve_target_home(getattr(args, "profile", None))

    if supports_browser_login(provider):
        token = set_hermes_home_override(home) if applied_profile is not None else None
        try:
            return browser_login_command(provider, home=home, flow=getattr(args, "flow", None))
        finally:
            if token is not None:
                reset_hermes_home_override(token)

    def emit(event: dict) -> None:
        print(json.dumps(event), flush=True)

    if flow is None:
        emit(
            {
                "event": "error",
                "ok": False,
                "reason": f"Unknown provider: {provider}",
                "code": "unknown_provider",
            }
        )
        return 1
    emit({
        "event": "error", "ok": False, "code": "unsupported_flow",
        "reason": "This provider does not support browser sign-in from this app.",
        "flow": flow, "cli_command": cli_command, "home": home,
    })
    return 1
