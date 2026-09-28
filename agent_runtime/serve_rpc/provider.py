"""``runtime.provider.*`` — provider catalog, sign-in, refresh, usage and sign-out.

Translation shims and nothing else: the work is ``agent_runtime.provider_account``
(list / usage / refresh / sign-out over upstream's own functions) and
``agent_runtime.provider_signin`` (sign-in sessions over the machine sign-in
child). The contract a client integrates from is
``docs/agent-runtime-harness/runtime-provider-methods.md``.

Credentials never ride a frame: results are catalog rows, session state,
booleans and usage windows; a refusal carries a closed ``data.reason`` and, for
an unexpected raise, the exception CLASS name — never ``str(exc)``, which is why
every handler here catches instead of letting the dispatcher's
``handler error: {exc}`` boundary format one.
"""

from __future__ import annotations

from typing import Any, Callable

from agent_runtime.call_authorization import TIER_CONSOLE, TIER_READ

from agent_runtime.serve_rpc.protocol import (
    DEFERRED,
    ERR_CONFLICT,
    ERR_HANDLER_FAILED,
    ERR_INVALID_PARAMS,
    ERR_NOT_FOUND,
    RpcContext,
    deferred_reply,
    err,
    ok,
)
from agent_runtime.serve_rpc.params import _text_param
from agent_runtime.serve_rpc.registry import method

__layer__ = "lanes"

__all__ = [
    "PROVIDER_CONTRACT",
    "_runtime_provider_list",
    "_runtime_provider_refresh",
    "_runtime_provider_signin_begin",
    "_runtime_provider_signin_cancel",
    "_runtime_provider_signin_complete",
    "_runtime_provider_signin_poll",
    "_runtime_provider_signout",
    "_runtime_provider_usage",
]

#: This family's own result-shape number (the ``MEDIA_CONTRACT`` precedent).
PROVIDER_CONTRACT = 1

#: The longest pasted authorization code accepted (Anthropic's is ~100 chars).
MAX_CODE_CHARS = 2048

_FAMILY_CODES = {"invalid_params": ERR_INVALID_PARAMS, "conflict": ERR_CONFLICT, "not_found": ERR_NOT_FOUND}


def _refused(rid: Any, method_name: str, reason: str, code: int, message: str = "", **data: Any) -> dict:
    return err(rid, code, message or f"{method_name} refused: {reason}", {"reason": reason, **data})


def _failed(rid: Any, method_name: str, exc: BaseException) -> dict:
    return err(rid, ERR_HANDLER_FAILED, f"{method_name} failed",
               {"reason": "handler_failed", "method": method_name, "error_class": type(exc).__name__})


def _stamp(result: dict) -> dict:
    return {"contract": PROVIDER_CONTRACT, **result}


def _answer(rid: Any, method_name: str, work: Callable[[], dict]) -> dict:
    """Run ``work`` and turn every outcome into ONE frame, credential-free."""
    from agent_runtime.provider_account import ProviderRefused
    from agent_runtime.provider_signin import SignInRefused

    try:
        return ok(rid, _stamp(work()))
    except SignInRefused as refusal:
        return _refused(rid, method_name, refusal.reason, _FAMILY_CODES[refusal.code], **refusal.data)
    except ProviderRefused as refusal:
        code = ERR_INVALID_PARAMS if refusal.reason == "provider_unknown" else ERR_HANDLER_FAILED
        return _refused(rid, method_name, refusal.reason, code, refusal.message, **refusal.data)
    except Exception as exc:  # noqa: BLE001 - class name only, never the message
        return _failed(rid, method_name, exc)


def _off_reader(rid: Any, method_name: str, context: RpcContext | None, work: Callable[[], dict]) -> dict:
    """Network-bound work goes to the worker lane when the transport has one."""
    spawn = None if context is None else context.spawn_reply
    build = lambda: _answer(rid, method_name, work)  # noqa: E731
    if spawn is not None and spawn(deferred_reply(rid, method_name, build)):
        return DEFERRED
    return build()


def _provider_or_refuse(rid: Any, method_name: str, params: dict) -> tuple[str | None, dict | None]:
    provider = _text_param(params, "provider")
    if provider is None:
        return None, _refused(rid, method_name, "provider_required", ERR_INVALID_PARAMS)
    return provider.lower(), None


def _login_id_or_refuse(rid: Any, method_name: str, params: dict) -> tuple[str | None, dict | None]:
    login_id = _text_param(params, "login_id")
    if login_id is None:
        return None, _refused(rid, method_name, "login_id_required", ERR_INVALID_PARAMS)
    return login_id, None


# ── catalog / usage ──────────────────────────────────────────────────────────


@method("runtime.provider.list", tier=TIER_READ)
def _runtime_provider_list(rid: Any, params: dict, context: RpcContext | None = None) -> dict:
    """The real provider catalog with pools, logins and sign-in methods. Params: none."""
    from agent_runtime import provider_account

    return _off_reader(rid, "runtime.provider.list", context, provider_account.provider_list)


@method("runtime.provider.usage", tier=TIER_READ)
def _runtime_provider_usage(rid: Any, params: dict, context: RpcContext | None = None) -> dict:
    """Account limits / rate-limit windows. Params: ``provider``."""
    from agent_runtime import provider_account

    provider, refusal = _provider_or_refuse(rid, "runtime.provider.usage", params)
    if refusal is not None:
        return refusal
    return _off_reader(rid, "runtime.provider.usage", context, lambda: provider_account.provider_usage(provider))


# ── sign-in session ──────────────────────────────────────────────────────────


@method("runtime.provider.signin.begin", tier=TIER_CONSOLE)
def _runtime_provider_signin_begin(rid: Any, params: dict, context: RpcContext | None = None) -> dict:
    """Start one sign-in. Params: ``provider``; ``flow``, ``profile`` optional."""
    from agent_runtime import provider_signin

    provider, refusal = _provider_or_refuse(rid, "runtime.provider.signin.begin", params)
    if refusal is not None:
        return refusal
    flow, profile = _text_param(params, "flow"), _text_param(params, "profile")
    return _answer(rid, "runtime.provider.signin.begin",
                   lambda: provider_signin.registry().begin(provider, flow, profile))


@method("runtime.provider.signin.poll", tier=TIER_CONSOLE)
def _runtime_provider_signin_poll(rid: Any, params: dict, context: RpcContext | None = None) -> dict:
    """The session's state. Params: ``login_id``."""
    from agent_runtime import provider_signin

    login_id, refusal = _login_id_or_refuse(rid, "runtime.provider.signin.poll", params)
    if refusal is not None:
        return refusal
    return _answer(rid, "runtime.provider.signin.poll", lambda: provider_signin.registry().poll(login_id))


@method("runtime.provider.signin.complete", tier=TIER_CONSOLE)
def _runtime_provider_signin_complete(rid: Any, params: dict, context: RpcContext | None = None) -> dict:
    """Hand a ``paste_code`` session its pasted code. Params: ``login_id``, ``code``."""
    from agent_runtime import provider_signin

    login_id, refusal = _login_id_or_refuse(rid, "runtime.provider.signin.complete", params)
    if refusal is not None:
        return refusal
    code = _text_param(params, "code")
    if code is None or len(code) > MAX_CODE_CHARS or any(ch in code for ch in "\r\n\0"):
        return _refused(rid, "runtime.provider.signin.complete", "code_invalid", ERR_INVALID_PARAMS)
    return _answer(rid, "runtime.provider.signin.complete",
                   lambda: provider_signin.registry().complete(login_id, code))


@method("runtime.provider.signin.cancel", tier=TIER_CONSOLE)
def _runtime_provider_signin_cancel(rid: Any, params: dict, context: RpcContext | None = None) -> dict:
    """Stop an unfinished sign-in. Params: ``login_id``."""
    from agent_runtime import provider_signin

    login_id, refusal = _login_id_or_refuse(rid, "runtime.provider.signin.cancel", params)
    if refusal is not None:
        return refusal
    return _answer(rid, "runtime.provider.signin.cancel", lambda: provider_signin.registry().cancel(login_id))


# ── refresh / sign-out ───────────────────────────────────────────────────────


@method("runtime.provider.refresh", tier=TIER_CONSOLE)
def _runtime_provider_refresh(rid: Any, params: dict, context: RpcContext | None = None) -> dict:
    """Rotate one pooled OAuth grant. Params: ``provider``; ``credential`` optional."""
    from agent_runtime import provider_account

    provider, refusal = _provider_or_refuse(rid, "runtime.provider.refresh", params)
    if refusal is not None:
        return refusal
    credential = _text_param(params, "credential")
    return _off_reader(rid, "runtime.provider.refresh", context,
                       lambda: provider_account.provider_refresh(provider, credential))


@method("runtime.provider.signout", tier=TIER_CONSOLE)
def _runtime_provider_signout(rid: Any, params: dict, context: RpcContext | None = None) -> dict:
    """Clear this provider's sign-in. Params: ``provider``."""
    from agent_runtime import provider_account

    provider, refusal = _provider_or_refuse(rid, "runtime.provider.signout", params)
    if refusal is not None:
        return refusal
    return _off_reader(rid, "runtime.provider.signout", context,
                       lambda: provider_account.provider_signout(provider))
