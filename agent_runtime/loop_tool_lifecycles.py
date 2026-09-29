"""Stand-ins for the agent loop's desktop tool lifecycles when the installation does not ship them.

Upstream's loop imports four names from the terminal and browser tool lifecycles at
module import (``run_agent``: ``cleanup_vm``, ``get_active_env``, ``cleanup_browser``;
``agent.chat_completion_helpers``: ``is_persistent_env``; ``agent.tool_executor``:
``get_active_env``), and every tool round asks ``tools.delegate_tool`` for the
delegation cap (``AIAgent._cap_delegate_task_calls``). Those modules drag in the
execution backends (Docker, SSH, Modal, Singularity), the browser supervisor and the
terminal tool, so a profile that does not ship the terminal and browser tools (the
phone wheel — and delegation, which imports the terminal tool) could not load the
loop, or could not finish a tool round. This is
the fork seam that lets the SAME loop load there — never a second loop, and no edit
to upstream: the precedent is the ``av`` placeholder (``agent_runtime.speech_decode``).

:func:`ensure_lifecycle_placeholders` registers, for each lifecycle module that is NOT
installed, a placeholder module carrying exactly the names the loop imports, with the
answers that are true when the tool cannot exist: nothing to clean up, no active
environment, nothing persistent, no cap on a ``delegate_task`` call (with no delegation
tool registered, each such call is answered "tool does not exist" rather than dropped). Any other name raises :class:`LifecycleNotShipped`.
With the real modules installed (desktop, full Hermes) it does nothing. It must run
before the loop is imported: the in-process conversation worker calls it, and so must
the phone runtime's entry point.
"""

from __future__ import annotations

import importlib.util
import sys
import types
from typing import Any

__layer__ = "lanes"
__all__ = ["BROWSER_LIFECYCLE", "DELEGATE_TOOL", "TERMINAL_LIFECYCLE", "LifecycleNotShipped",
           "ensure_lifecycle_placeholders", "is_lifecycle_placeholder"]

TERMINAL_LIFECYCLE = "tools.terminal_tool_lifecycle"
BROWSER_LIFECYCLE = "tools.browser_tool_lifecycle"
DELEGATE_TOOL = "tools.delegate_tool"


class LifecycleNotShipped(RuntimeError):
    """Something beyond the loop's cleanup reached a tool lifecycle this installation lacks."""


class _LifecyclePlaceholder(types.ModuleType):
    __hermes_placeholder__ = True

    def __getattr__(self, name: str):
        if name.startswith("__") and name.endswith("__"):
            raise AttributeError(name)
        raise LifecycleNotShipped(f"{self.__name__}.{name} is not in this installation")


def _no_cleanup(task_id: Any = None, **_kwargs: Any) -> None:
    return None


def _no_env(task_id: Any) -> None:
    return None


def _not_persistent(task_id: Any) -> bool:
    return False


def _no_delegation_cap() -> int:
    return sys.maxsize


#: module -> the names upstream's loop imports from it, as the absent tool answers them.
_LOOP_NAMES: dict[str, dict[str, Any]] = {
    TERMINAL_LIFECYCLE: {"cleanup_vm": _no_cleanup, "get_active_env": _no_env, "is_persistent_env": _not_persistent},
    BROWSER_LIFECYCLE: {"cleanup_browser": _no_cleanup},
    DELEGATE_TOOL: {"_get_max_concurrent_children": _no_delegation_cap},
}


def is_lifecycle_placeholder(module: object) -> bool:
    return bool(getattr(type(module), "__hermes_placeholder__", False))


def _installed(module: str) -> bool:
    loaded = sys.modules.get(module)
    if loaded is not None:
        return not is_lifecycle_placeholder(loaded)
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):
        return False


def ensure_lifecycle_placeholders() -> tuple[str, ...]:
    """Register a placeholder for each loop lifecycle module not installed; returns those placed."""
    placed = []
    for module, names in _LOOP_NAMES.items():
        if module in sys.modules or _installed(module):
            continue
        stand_in = _LifecyclePlaceholder(module, f"Placeholder: {module} is not shipped in this installation.")
        for name, answer in names.items():
            setattr(stand_in, name, answer)
        sys.modules[module] = stand_in
        placed.append(module)
    return tuple(placed)
