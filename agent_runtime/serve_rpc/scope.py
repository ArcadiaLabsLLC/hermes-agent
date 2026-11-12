"""``runtime.workspace.use`` / ``runtime.realm.use`` — scope activation verbs — and
``runtime.realm.set_default``, the account's default-realm pointer, and ``runtime.realm.archive`` /
``runtime.realm.unarchive``.
"""

from __future__ import annotations

from typing import Any

from agent_runtime.call_authorization import TIER_CONSOLE

from agent_runtime.serve_rpc.protocol import ERR_CONFLICT, ERR_INVALID_PARAMS, ERR_NOT_FOUND, RpcContext, err, ok
from agent_runtime.serve_rpc.registry import method

__layer__ = "lanes"

__all__ = [
    "_runtime_realm_archive",
    "_runtime_realm_set_default",
    "_runtime_realm_unarchive",
    "_runtime_realm_use",
    "_runtime_workspace_use",
]


# ── runtime.workspace.use / runtime.realm.use ────────────────────────────────
#
# Plan WS4 (``archive/instant-workspace-switching.md``), ruling R-W1. TWO things
# at once, and the second is the reason the stage exists rather than a latency
# footnote:
#
#  1. the local switch's ACCEPT stops being a process spawn and becomes a socket
#     round trip on a lane the launcher already holds open;
#  2. the pointer gets a SERVER-SIDE enforcement point. `local_console` is the
#     tier, and the device arm of ``call_authorization.authorize_call`` is an
#     EQUALITY against the word a device's own pairing record holds — so a
#     device paired at ``read`` is refused, a device paired at ``console`` is
#     refused too (its word is ``console`` and this verb wants the machine
#     owner's kind, not a tier a remote credential can hold), and a paired
#     INSTALL is refused because ``PEER_METHOD_ALLOWLIST`` admits nothing it was
#     not edited to admit. That is RS4's R-B, built here instead of asked for
#     politely at the client.
#
# **WHERE the enforcement is, and why not here.** These handlers contain no
# authorization code at all: the restriction is one membership set at the
# chokepoint (``call_authorization.LOCAL_CONSOLE_METHODS``), evaluated by
# ``authorize_call`` before dispatch, which is where Ruling A put the decision
# and where every other caller-kind rule already lives. A handler-local check
# would be a second policy in the dispatcher's own file, and the module's
# opening argument — ``serve_rpc`` renders refusals, it does not author them —
# would stop being true the day someone edited one of the two and not the other.
#
# **The correction the set carries** (WS4 field notes, 2026-09-01): the plan said
# the device arm's tier EQUALITY alone refuses a device caller. It refuses a
# ``read`` device and not a ``console`` one — R11 explicitly contemplates paired
# console devices — so R-B needed a kind test beside the strength test. That
# argument is written out at :data:`call_authorization.LOCAL_CONSOLE_METHODS`.
#
# NOT on ``PEER_METHOD_ALLOWLIST``, and deliberately with no edit: that set
# admits nothing it does not name, and ``test_peer_authorization`` iterates the
# whole registry against it, so these two names arrive already covered by a test
# nobody had to touch. Canon 06's sentence — a remote OPERATOR acts on an
# install, another install's agents do not — reads the same for a scope pointer
# as it does for an agent retire.
#
# The argv verbs STAY (CLI parity, scripts, and an older launcher), and both
# doors call ``agent_runtime.scope_activation`` so there is one decision and one
# row. The launcher's argv lowering for these two is marked for delete in the
# plan's retirement ledger, gated on manifest membership being universal.


@method("runtime.workspace.use", tier=TIER_CONSOLE)
def _runtime_workspace_use(
    rid: Any, params: dict, context: RpcContext | None = None
) -> dict:
    """Park this install's active-workspace pointer.

    Params: ``workspace_id`` (required); ``issued_at`` (optional, the supersede
    basis the argv verb takes as ``--issued-at``); ``correlation_id`` (optional,
    echoed).

    Result: the argv verb's row, verbatim — ``{id, name, realm_id, agents, …,
    applied}`` when the write took, and the DECLINED row
    (``applied: false`` plus ``reason`` / ``superseded`` /
    ``requested_workspace_id``) when a strictly newer intent already owns the
    pointer or this exact intent already applied.

    **A declined activation is a RESULT, not an error**, exactly as it is on the
    argv lane where both arms exit 0. Rendering ``superseded`` as a JSON-RPC
    error would make the launcher's accept path treat a correctly-ordered switch
    as a failure and raise the R-A parked-elsewhere surface for something that
    worked.

    Answered INLINE on the reader loop, and it belongs there: the whole write is
    one small JSON file plus one event append — the same budget
    ``runtime.office.upsert`` already spends on this lane, and orders of
    magnitude under the chat turn that made the worker pool necessary.
    """

    from agent_runtime.scope_activation import (
        WORKSPACE_USE_METHOD,
        perform_scope_activation,
    )

    outcome = perform_scope_activation(params, verb=WORKSPACE_USE_METHOD)
    if outcome.refusal is not None:
        denial = outcome.refusal
        return err(rid, denial.code, denial.message, denial.data)
    return ok(rid, outcome.result)


@method("runtime.realm.use", tier=TIER_CONSOLE)
def _runtime_realm_use(
    rid: Any, params: dict, context: RpcContext | None = None
) -> dict:
    """Park this install's active-realm pointer, reconciling the workspace.

    Params: ``realm_id`` (required); ``issued_at``, ``correlation_id``
    (optional).

    Result: ``harness realm use``'s row, verbatim — everything on
    :func:`_runtime_workspace_use` applies, with one addition it inherits from
    the shared implementation rather than re-states: an applied realm switch
    also moves the ACTIVE WORKSPACE when the current one belongs to the realm
    just left (``scope_activation.reconcile_active_workspace_to_realm``). So one
    call can emit two events, and a client that folds them must expect both.
    """

    from agent_runtime.scope_activation import REALM_USE_METHOD, perform_scope_activation

    outcome = perform_scope_activation(params, verb=REALM_USE_METHOD)
    if outcome.refusal is not None:
        denial = outcome.refusal
        return err(rid, denial.code, denial.message, denial.data)
    return ok(rid, outcome.result)


_SET_DEFAULT_CODES = {"invalid_request": ERR_INVALID_PARAMS, "realm_not_found": ERR_NOT_FOUND}


@method("runtime.realm.set_default", tier=TIER_CONSOLE)
def _runtime_realm_set_default(
    rid: Any, params: dict, context: RpcContext | None = None
) -> dict:
    """Choose the account's default realm (RT-ACCOUNT-DEFAULT-REALM): where a workspace created with
    no realm lands, and the snapshot's top-level ``default_realm_id``.

    Params: exactly ``realm_id``. Result: ``harness realm default``'s row — the realm row plus
    ``default_realm_id`` (the resolved default after the write) and ``changed`` (false when the
    pointer already named it). Refusals ride ``error.data.reason``: ``invalid_request`` (-32602),
    ``realm_not_found`` (4001), ``realm_archived`` (4090). One implementation with the argv verb,
    ``agent_runtime.default_realm.set_default_realm``. It moves no active pointer.
    """

    from agent_runtime.default_realm import DefaultRealmRefused, default_realm_row
    from agent_runtime.serde import to_jsonable

    if not isinstance(params, dict) or set(params) != {"realm_id"}:
        return err(rid, ERR_INVALID_PARAMS, "realm_id is required.", {"reason": "invalid_request"})
    try:
        row = default_realm_row(params["realm_id"])
    except DefaultRealmRefused as exc:
        code = _SET_DEFAULT_CODES.get(exc.reason.value, ERR_CONFLICT)
        return err(rid, code, "The default realm was not changed.", {"reason": exc.reason.value})
    return ok(rid, dict(to_jsonable(row)))


_REALM_MANAGE_CODES = {"invalid_request": ERR_INVALID_PARAMS, "realm_not_found": ERR_NOT_FOUND}


def _realm_manage(rid: Any, params: dict, verb: str) -> dict:
    """One ``agent_runtime.realm_manage`` verb: exactly ``realm_id``; the full realm row plus ``changed``,
    or the typed refusal on ``error.data`` (``reason`` and the refusal's details)."""
    from agent_runtime import realm_manage
    from agent_runtime.serde import to_jsonable

    if not isinstance(params, dict) or set(params) != {"realm_id"}:
        return err(rid, ERR_INVALID_PARAMS, "realm_id is required.", {"reason": "invalid_request"})
    try:
        row, changed = getattr(realm_manage, verb)(params["realm_id"])
    except realm_manage.RealmManageRefused as exc:
        code = _REALM_MANAGE_CODES.get(exc.reason.value, ERR_CONFLICT)
        return err(rid, code, "The realm was not changed.", {"reason": exc.reason.value, **exc.details})
    return ok(rid, dict(to_jsonable({**row, "changed": changed})))


@method("runtime.realm.archive", tier=TIER_CONSOLE)
def _runtime_realm_archive(
    rid: Any, params: dict, context: RpcContext | None = None
) -> dict:
    """Put an empty realm away (RT-REALM-ARCHIVE-RESTORE; argv twin ``harness realm archive``).

    Params: exactly ``realm_id``. Result: the full realm row (``archived: true``) plus ``changed``
    (false when it was already archived). Refusals ride ``error.data.reason``: ``invalid_request``
    (-32602), ``realm_not_found`` (4001), and at 4090 ``realm_server_bound`` (+ ``server_id`` — the
    realm comes from a server; leave the server to remove it), ``realm_is_active``,
    ``realm_is_default``, ``realm_not_empty`` (+ ``workspace_ids``, the workspaces not archived). The
    rules are ``agent_runtime.realm_manage.archive_realm``'s. It moves no pointer.
    """

    return _realm_manage(rid, params, "archive_realm")


@method("runtime.realm.unarchive", tier=TIER_CONSOLE)
def _runtime_realm_unarchive(
    rid: Any, params: dict, context: RpcContext | None = None
) -> dict:
    """Bring an archived realm back (RT-REALM-ARCHIVE-RESTORE; argv twin ``harness realm unarchive``).

    Params: exactly ``realm_id``. Result: the full realm row (``archived: false``) plus ``changed``
    (false when it was not archived). Refusals: ``invalid_request`` (-32602), ``realm_not_found``
    (4001). Its archived workspaces stay archived until each is restored.
    """

    return _realm_manage(rid, params, "unarchive_realm")
