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
to upstream.

:func:`ensure_lifecycle_placeholders` registers, for each lifecycle module that is NOT
installed, a placeholder module carrying exactly the names the loop imports, with the
answers that are true when the tool cannot exist: nothing to clean up, no active
environment, nothing persistent, no cap on a ``delegate_task`` call (with no delegation
tool registered, each such call is answered "tool does not exist" rather than dropped). Any other name raises :class:`LifecycleNotShipped`.

The loop's task cleanup (``agent.client_lifecycle._close_task_resources``) also reaches the
file tools and the computer-use tool, and the per-turn cleanup
(``agent.chat_completion_helpers.cleanup_task_resources``) asks the browser tool whether it
runs headed: absent, there is no read stamp to forget, no computer-use session to release
and no headed browser — the same answers. (Its process-registry step asks
:func:`shipped` instead: the registry's surface is too wide for a stand-in.)

Beyond the loop, four upstream modules import a switched-off module's names at module level or
ask it one question, and a stand-in answers them the same way, so those upstream files keep
upstream's bytes (lane h11-fp, 2026-09-29): ``agent.copilot_acp_client`` and
``agent.transports.codex_app_server`` bind ``tools.environments.local.hermes_subprocess_env``
(a loud stand-in: they start a child process only where it is shipped); ``tools.tts_tool`` and
``tools.tts_tool_lifecycle`` bind the local TTS engines (no engine, no model cache to warm or
release); ``agent.image_routing`` asks ``hermes_cli.local_runtime.capabilities`` whether the
provider is the managed local runtime (no local runtime: never). Each is placed only when its
switched-off PACKAGE is absent, probed without importing it (``_PRESENCE``), so a desktop boot
never pays for importing a package to learn it is there.
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
__all__ = ["BROWSER_CLOUD", "BROWSER_LIFECYCLE", "COMPUTER_USE_TOOL", "DELEGATE_TOOL", "FILE_TOOLS", "TERMINAL_LIFECYCLE", "LifecycleNotShipped",
           "ensure_lifecycle_placeholders", "is_lifecycle_placeholder", "not_shipped", "shipped"]

TERMINAL_LIFECYCLE = "tools.terminal_tool_lifecycle"
BROWSER_LIFECYCLE = "tools.browser_tool_lifecycle"
DELEGATE_TOOL = "tools.delegate_tool"
FILE_TOOLS = "tools.file_tools"
COMPUTER_USE_TOOL = "tools.computer_use.tool"
BROWSER_CLOUD = "tools.browser_tool_cloud"
LOCAL_ENVIRONMENT = "tools.environments.local"
LOCAL_TTS = "tools.tts_tool_local"
LOCAL_RUNTIME_CAPABILITIES = "hermes_cli.local_runtime.capabilities"


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


def _not_headed() -> bool:
    return False


def _no_delegation_cap() -> int:
    return sys.maxsize


def _not_managed(provider: Any = None, base_url: Any = None, *_args: Any, **_kwargs: Any) -> bool:
    return False


def not_shipped(module: str, name: str):
    """A stand-in for ``module.name`` where *module* is not shipped: calling it raises.

    For an upstream module-level ``from module import name`` whose ImportError guard needs a
    binding: the importer loads (the phone wheel omits *module*), and the one path that would
    have used the name — spawning a child process, say — fails loudly instead of silently.
    """

    def unavailable(*_args: Any, **_kwargs: Any) -> Any:
        raise LifecycleNotShipped(f"{module}.{name} is not in this installation")

    unavailable.__name__ = unavailable.__qualname__ = name
    return unavailable


def _loud(module: str, *names: str) -> dict[str, Any]:
    return {name: not_shipped(module, name) for name in names}


#: module -> the names upstream imports from it, as the absent tool answers them.
_LOOP_NAMES: dict[str, dict[str, Any]] = {
    TERMINAL_LIFECYCLE: {"cleanup_vm": _no_cleanup, "get_active_env": _no_env, "is_persistent_env": _not_persistent},
    BROWSER_LIFECYCLE: {"cleanup_browser": _no_cleanup},
    DELEGATE_TOOL: {"_get_max_concurrent_children": _no_delegation_cap},
    FILE_TOOLS: {"clear_file_ops_cache": _no_cleanup},
    COMPUTER_USE_TOOL: {"release_computer_use_session": _no_cleanup},
    BROWSER_CLOUD: {"_is_headed_mode": _not_headed},
    LOCAL_ENVIRONMENT: _loud(LOCAL_ENVIRONMENT, "hermes_subprocess_env"),
    LOCAL_TTS: {"_LOCAL_TTS_MODEL_CACHES": types.MappingProxyType({}),
                **_loud(LOCAL_TTS, "_generate_kittentts", "_generate_neutts", "_generate_piper_tts",
                        "_load_kittentts_model_for_config", "_load_piper_voice_for_config")},
    LOCAL_RUNTIME_CAPABILITIES: {"is_managed_provider": _not_managed,
                                 **_loud(LOCAL_RUNTIME_CAPABILITIES, "managed_model_supports_vision")},
}

#: module -> the module whose presence decides it, when that is its switched-off PACKAGE: probing the
#: package's spec does not run its ``__init__`` (``hermes_cli.local_runtime``'s imports the whole runtime).
_PRESENCE: dict[str, str] = {
    LOCAL_ENVIRONMENT: "tools.environments",
    LOCAL_RUNTIME_CAPABILITIES: "hermes_cli.local_runtime",
}


def is_lifecycle_placeholder(module: object) -> bool:
    return bool(getattr(type(module), "__hermes_placeholder__", False))


def shipped(module: str) -> bool:
    """True when *module* is in this installation — importable, and not one of these placeholders.

    The presence test for a feature a profile leaves out of its wheel (``packaging.switched_off_modules``):
    the phone wheel omits the module, so the caller skips the step that would import it. Desktop and
    full Hermes ship every module, so there the answer is always True and the step runs as before.
    """
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
        if module in sys.modules or shipped(_PRESENCE.get(module, module)):
            continue
        stand_in = _LifecyclePlaceholder(module, f"Placeholder: {module} is not shipped in this installation.")
        for name, answer in names.items():
            setattr(stand_in, name, answer)
        sys.modules[module] = stand_in
        placed.append(module)
    return tuple(placed)
