"""``runtime.realm.*`` — the ten realm verbs the launcher runs, on the method lane.

Each handler validates its params, calls :mod:`agent_runtime.realm_verbs` (the
one implementation the argv verbs also call) and returns the argv verb's
``--json`` envelope verbatim. Argv census rows 1-10: every one of them was a
COLD process per call, the 4-minute status poll included.

**Params shared by the family.** ``realm_id`` (required, except ``adopt``);
``dry_run`` (bool); ``credential`` (status / pull / publish / adopt): the
launcher-brokered credential OBJECT, schema v1 — the bytes the argv lane reads
from ``--credential-file``, inline, because a path names a file on the caller's
disk and not on the install the method is aimed at. It is parsed by
``RealmSyncCredential.parse``, never echoed, and an invalid one is the argv
lane's own ``sync_auth_failed``. ``yes`` (publish / resolve / revert): argv's
``--yes``; without it, and without ``dry_run``, the refusal is
``confirmation_required`` and nothing runs.

**Refusals.** ``data.reason`` is the argv envelope's ``error.code`` —
``RealmSyncError.code``, ``not_found``, ``invalid_request`` or
``confirmation_required`` — with the error's ``safe_details`` and
``retryable`` beside it. The JSON-RPC code is :data:`REASON_CODES`'s, and an
unlisted reason is ``ERR_HANDLER_FAILED``.

**Tier: ``console`` for all ten**, reads included: ``status`` reaches the
backend under a credential, and every ``show`` hands back the realm's publish
roster. None is on ``LOCAL_CONSOLE_METHODS`` — unlike ``runtime.realm.use``, no
verb here moves the machine owner's session pointer.
"""

from __future__ import annotations

import threading
from functools import partial
from typing import Any, Callable

from agent_runtime.call_authorization import TIER_CONSOLE
from agent_runtime.param_readers import read_flag, read_strings, read_text

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
from agent_runtime.serve_rpc.registry import method

__layer__ = "lanes"

__all__ = ["REASON_CODES", "REALM_METHODS"]

#: ``data.reason`` -> JSON-RPC code.
REASON_CODES: dict[str, int] = {
    "invalid_request": ERR_INVALID_PARAMS,
    "confirmation_required": ERR_INVALID_PARAMS,
    "not_found": ERR_NOT_FOUND,
    "version_not_found": ERR_NOT_FOUND,
    "sync_auth_failed": ERR_CONFLICT,
    "membership_denied": ERR_CONFLICT,
    "role_insufficient": ERR_CONFLICT,
    "sync_conflict": ERR_CONFLICT,
    "sync_behind": ERR_CONFLICT,
    "sync_secret_excluded": ERR_CONFLICT,
    "sync_remote_unreachable": ERR_HANDLER_FAILED,
}


class _Refused(Exception):
    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason


def _refusal(rid: Any, reason: str, message: str, details: dict | None = None, retryable: bool = False) -> dict:
    data = {"reason": reason, "retryable": bool(retryable), **(details or {})}
    return err(rid, REASON_CODES.get(reason, ERR_HANDLER_FAILED), message, data)


def _run_verb(rid: Any, call: Callable[[], dict]) -> dict:
    """Run one verb and render its typed refusal; anything untyped propagates."""
    from agent_runtime.errors import NotFound
    from agent_runtime.profile_artifact_sync import ProfileArtifactResolveError
    from agent_runtime.realm_sync import RealmSyncError
    from agent_runtime.realm_verbs import RealmSelectionInvalid
    from agent_runtime.skill_sync import SkillResolveError

    try:
        return ok(rid, call())
    except _Refused as exc:
        return _refusal(rid, exc.reason, str(exc))
    except RealmSyncError as exc:
        return _refusal(rid, exc.code, str(exc), exc.safe_details, exc.retryable)
    except (SkillResolveError, ProfileArtifactResolveError, RealmSelectionInvalid) as exc:
        return _refusal(rid, exc.code, str(exc))
    except NotFound:
        # Never the store's message: it is the realm JSON's ABSOLUTE PATH, which
        # the argv lane also keeps off every operator-visible surface.
        return _refusal(rid, "not_found", "Realm not found.")


# ── param readers: ``agent_runtime.param_readers``, refusing _Refused("invalid_request") ──


def _params(params: Any) -> dict:
    return params if isinstance(params, dict) else {}


def _invalid_request(key: str, sentence: str) -> _Refused:
    return _Refused("invalid_request", sentence)


#: A present value must be non-blank on this lane (``empty_ok=False``).
_param_text = partial(read_text, refuse=_invalid_request, empty_ok=False)
_param_flag = partial(read_flag, refuse=_invalid_request)
_param_strings = partial(read_strings, refuse=_invalid_request)


def _credential(params: dict):
    """The inline credential, parsed by the argv lane's own parser, or None."""
    from agent_runtime.realm_membership import RealmSyncCredential

    raw = params.get("credential")
    return None if raw is None else RealmSyncCredential.parse(raw)


def _confirmed(params: dict) -> bool:
    """argv's ``_require_yes`` predicate: ``yes or dry_run``."""
    if not (_param_flag(params, "yes") or _param_flag(params, "dry_run")):
        raise _Refused("confirmation_required", "This destructive operation requires yes.")
    return True


def _realm(params: dict) -> str:
    return _param_text(params, "realm_id", required=True)


# ── the ten verbs ────────────────────────────────────────────────────────────


def _status(p: dict) -> dict:
    """Params: ``realm_id``, ``credential``."""
    from agent_runtime.realm_verbs import realm_sync_status

    return realm_sync_status(_realm(p), credential=_credential(p))


def _pull(p: dict) -> dict:
    """Params: ``realm_id``, ``credential``, ``dry_run``."""
    from agent_runtime.realm_verbs import realm_sync_pull

    return realm_sync_pull(_realm(p), credential=_credential(p), dry_run=_param_flag(p, "dry_run"))


def _sync_publish(p: dict) -> dict:
    """Params: ``realm_id``, ``credential``, ``dry_run``, ``yes``."""
    from agent_runtime.realm_verbs import realm_sync_publish

    realm_id = _realm(p)
    _confirmed(p)
    return realm_sync_publish(realm_id, credential=_credential(p), dry_run=_param_flag(p, "dry_run"))


def _revert(p: dict) -> dict:
    """Params: ``realm_id``, ``items`` (FAMILY:CONTAINER:KEY strings), ``all``, ``to`` (a published sha), ``dry_run``, ``yes``."""
    from agent_runtime.realm_verbs import realm_sync_revert

    realm_id, items, to = _realm(p), _param_strings(p, "items"), _param_text(p, "to")
    _confirmed(p)
    return realm_sync_revert(realm_id, items=items, revert_all=_param_flag(p, "all"), to=to, dry_run=_param_flag(p, "dry_run"))


def _sync_resolve(p: dict) -> dict:
    """Params: ``realm_id``, ``key``, ``take`` (local|remote), ``dry_run``, ``yes``."""
    from agent_runtime.realm_verbs import realm_sync_resolve

    realm_id, key, take = _realm(p), _param_text(p, "key", required=True), _param_text(p, "take", required=True)
    if take not in {"local", "remote"}:
        raise _Refused("invalid_request", "take must be 'local' or 'remote'")
    _confirmed(p)
    return realm_sync_resolve(realm_id, key=key, take=take, dry_run=_param_flag(p, "dry_run"))


def _skills_show(p: dict) -> dict:
    """Params: ``realm_id``."""
    from agent_runtime.realm_verbs import realm_skills_show

    return realm_skills_show(_realm(p))


def _skills_set(p: dict) -> dict:
    """Params: ``realm_id``; exactly one of ``all`` / ``skills`` (list) / ``none``; ``dry_run``."""
    from agent_runtime.realm_verbs import realm_skills_set

    return realm_skills_set(_realm(p), publish_all=_param_flag(p, "all"), skills=_param_strings(p, "skills"),
                            publish_none=_param_flag(p, "none"), dry_run=_param_flag(p, "dry_run"))


def _agents_show(p: dict) -> dict:
    """Params: ``realm_id``."""
    from agent_runtime.realm_verbs import realm_agents_show

    return realm_agents_show(_realm(p))


def _agents_set(p: dict) -> dict:
    """Params: ``realm_id``; exactly one of ``workspace`` / ``agents`` (list) / ``none``; ``dry_run``."""
    from agent_runtime.realm_verbs import realm_agents_set

    return realm_agents_set(_realm(p), publish_workspace=_param_flag(p, "workspace"), agents=_param_strings(p, "agents"),
                            publish_none=_param_flag(p, "none"), dry_run=_param_flag(p, "dry_run"))


def _adopt(p: dict) -> dict:
    """Params: ``credential`` (required by the verb), ``server_id``, ``dry_run``, ``sort``."""
    from agent_runtime.realm_verbs import realm_adopt

    return realm_adopt(_credential(p), server_id=_param_text(p, "server_id"), dry_run=_param_flag(p, "dry_run"),
                       sort=_param_text(p, "sort"))


#: method name -> verb body. One table, so a test can iterate it and a verb is
#: registered by adding a row. The params each honours are on its body above.
REALM_METHODS: dict[str, Callable[[dict], dict]] = {
    "runtime.realm.sync.status": _status,
    "runtime.realm.sync.pull": _pull,
    "runtime.realm.sync.publish": _sync_publish,
    "runtime.realm.sync.revert": _revert,
    "runtime.realm.sync.resolve": _sync_resolve,
    "runtime.realm.skills.show": _skills_show,
    "runtime.realm.skills.set": _skills_set,
    "runtime.realm.agents.show": _agents_show,
    "runtime.realm.agents.set": _agents_set,
    "runtime.realm.adopt": _adopt,
}


#: Realm verbs run OFF the reader loop (``RpcContext.spawn_reply``) and one at a
#: time among themselves. ``status`` fetches the realm remote and walks every
#: store for drift: live 2026-10-06 01:25:01-04:18 local, one inline status held
#: the dispatcher 2.5 s and the operator's first chat send queued behind it
#: (``send_to_admit_ms=2564``, the chat-turn lock written 50 ms after the status
#: sidecar). The lock keeps what the inline lane gave for free: two realm verbs
#: never share the sync repo at once.
_REALM_VERB_LOCK = threading.Lock()


def _register(name: str, body: Callable[[dict], dict]) -> None:
    @method(name, tier=TIER_CONSOLE)
    def _handler(rid: Any, params: dict, context: RpcContext | None = None) -> dict:
        def _answer() -> dict:
            with _REALM_VERB_LOCK:
                return _run_verb(rid, lambda: body(_params(params)))

        build = deferred_reply(rid, name, _answer)
        if context is not None and context.spawn_reply is not None and context.spawn_reply(build):
            return DEFERRED
        return build()

    _handler.__name__ = "_runtime_" + name.removeprefix("runtime.").replace(".", "_")
    _handler.__doc__ = f"``{name}`` — the argv verb's envelope; see :mod:`agent_runtime.realm_verbs`."


for _name, _body in REALM_METHODS.items():
    _register(_name, _body)
