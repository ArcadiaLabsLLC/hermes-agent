"""Task-scoped approval policy for interactive surfaces (Mission Chat's operator root).

Ledger row ``tools/approval_context.py`` (owner-requested execution controls, 2026-10-14): a
surface binds its policy to the current task without changing config. Upstream's
``_is_gateway_approval_context`` and ``_get_approval_mode`` each read the binding through one
call (:func:`surface_gateway_session`, :func:`surface_mode`); hosted-room policy still wins
(``_get_approval_mode`` consults it first), and hardline/deny-rule checks and YOLO semantics stay
in the existing guards. The surface owns its gateway notify lifecycle. Sole caller:
``agent_runtime/session_controls.py``. Pinned by ``tests/agent_runtime/test_operator_session_controls.py``.

``tools.approval_context`` imports this module at load, so its names are imported lazily here.
"""
from __future__ import annotations

import contextvars
from contextlib import contextmanager

__layer__ = "policy"

__all__ = ["approval_policy_mode", "approval_policy_modes", "scoped_approval_policy",
           "surface_gateway_session", "surface_mode"]

_surface_policy: contextvars.ContextVar[tuple[str, bool] | None] = contextvars.ContextVar(
    "approval_surface_policy", default=None)


@contextmanager
def scoped_approval_policy(mode: str, *, gateway_session: bool = False, wait_without_expiry: bool = False,
                           also_deny: tuple[str, ...] = ()):
    """Bind an interactive surface's policy to this task, without changing config.

    ``wait_without_expiry``: a person-wait in this task never times out (``approvals.timeout`` reads as
    the platform-safe maximum, so upstream's gateway wait, its human-wait ceiling and every reader of the
    window agree). ``also_deny``: ``approvals.deny`` globs added to this task's own, never removing one —
    a floor only tightens. Both ride the fork's read projection (``hermes_cli.config_read_scope``), so no
    upstream reader changes. A dispatched helper's turn binds both from its lead (row
    ``RT-FU-A-DISPATCHED-HELPERS-APPROVAL-EXPIRES-UNSEEN-IN-60-SECONDS``; caller
    ``session_controls.session_approval_scope``).
    """
    from contextlib import nullcontext

    if mode not in approval_policy_modes():
        raise ValueError("invalid approval mode")
    extra_deny = tuple(str(glob) for glob in also_deny if isinstance(glob, str) and glob.strip())
    fold_scope = nullcontext()
    if wait_without_expiry or extra_deny:
        from hermes_cli.config_read_scope import readonly_section_scope

        fold_scope = readonly_section_scope("approvals", lambda approvals: _dispatched_approvals(
            approvals, wait_without_expiry=wait_without_expiry, also_deny=extra_deny))
    token = _surface_policy.set((mode, gateway_session))
    try:
        with fold_scope:
            yield
    finally:
        _surface_policy.reset(token)


def _dispatched_approvals(approvals: dict, *, wait_without_expiry: bool, also_deny: tuple[str, ...]) -> dict:
    """The ``approvals`` section a bound task reads: its own, plus the added deny globs and, for a
    person-wait with no expiry, the platform-safe maximum timeout."""
    if also_deny:
        own = approvals.get("deny")
        own = list(own) if isinstance(own, (list, tuple)) else []
        approvals["deny"] = own + [glob for glob in also_deny if glob not in own]
    if wait_without_expiry:
        from agent.deadline import MAX_SAFE_TIMEOUT_S

        approvals["timeout"] = int(MAX_SAFE_TIMEOUT_S)
    return approvals


def surface_mode() -> str | None:
    """The bound surface's mode, or None when no surface bound one."""
    policy = _surface_policy.get()
    return None if policy is None else policy[0]


def surface_gateway_session() -> bool:
    """Whether the bound surface attached the gateway approval queue."""
    policy = _surface_policy.get()
    return policy is not None and policy[1]


def approval_policy_mode() -> str:
    """The current task's effective approval policy, including hosted policy."""
    from tools.approval_context import _get_approval_mode

    return _get_approval_mode()


def approval_policy_modes() -> tuple[str, ...]:
    """The native engine's valid policy vocabulary for interactive surfaces."""
    from tools.approval_context import _VALID_MODES

    return _VALID_MODES
