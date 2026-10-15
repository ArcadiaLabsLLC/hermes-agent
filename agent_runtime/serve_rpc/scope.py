"""``runtime.workspace.use`` / ``runtime.realm.use`` — scope activation verbs.
"""

from __future__ import annotations

from typing import Any

from agent_runtime.call_authorization import TIER_CONSOLE

from agent_runtime.serve_rpc.protocol import RpcContext, err, ok
from agent_runtime.serve_rpc.registry import method

__layer__ = "lanes"

__all__ = [
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
