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
def scoped_approval_policy(mode: str, *, gateway_session: bool = False):
    """Bind an interactive surface's policy to this task, without changing config."""
    if mode not in approval_policy_modes():
        raise ValueError("invalid approval mode")
    token = _surface_policy.set((mode, gateway_session))
    try:
        yield
    finally:
        _surface_policy.reset(token)


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
