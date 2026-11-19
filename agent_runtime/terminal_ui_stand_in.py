"""The phone's ``rich`` and ``prompt_toolkit``: the terminal-UI names upstream imports, none of them drawable.

A profile that ships no terminal (the bundled phone: Eternia draws every surface, and nothing on a
phone reads a TTY) still keeps upstream modules that import ``rich`` or ``prompt_toolkit`` — the
CLI renderers (``hermes_cli/cli_render.py``, ``cli_subagent_monitor.py``, ``cli_modern_layout.py``,
``banner.py``, ``journey.py``), the plugin commands' tables, ``tui_gateway/command_discovery.py``'s
completer. Their sites run only on a terminal, yet they pinned two distributions and, through
them, ``pygments`` and ``markdown-it-py``: about 1.7 MiB of the phone's compressed download
(RT-PHONE-ENGINE-BUNDLE-FITS-THE-DOWNLOAD-LIMIT). As :mod:`agent_runtime.psutil_stand_in` does for
``psutil``, this module retires them as a class, without a guard in upstream's files:
:func:`ensure_terminal_ui_stand_in` registers one module per name upstream imports, whose answers
are what a phone is —

* ``get_app_or_none()`` is ``None``: no prompt_toolkit application owns a terminal, so every
  guarded "is a TUI running?" read takes its no-TUI path;
* ``patch_stdout.StdoutProxy`` is a class nothing is an instance of;
* ``utils.get_cwidth`` is the real cell width (``wcwidth``, which the phone ships for
  ``agent/markdown_tables.py``);
* every other name — a renderer, a widget, a console — is a class or function that raises
  :class:`TerminalUiUnavailable` (an ``ImportError``, so a site guarded against the library being
  absent degrades as it would without it) when constructed or called.

Only the names upstream's unguarded sites import are answered: the packaging closure resolves each
site's dotted name against :func:`stand_in_modules` in a child interpreter
(``scripts/bundles/closure_probes.py``), so a new import site of a name this lacks is refused, not
silently answered. Phone-only, never a shadow: it installs only when the profile ships no provider
SDK (``agent.provider_sdks: false``, the phone's switch) AND no real ``rich`` is importable; the
phone entry (``EmbeddedServe.start``) calls it beside the ``psutil`` stand-in. Its modules carry no
``__spec__``, so ``importlib.util.find_spec("rich")`` still reads "not installed".
"""

from __future__ import annotations

import importlib.util
import sys
import types

__layer__ = "lanes"

__all__ = ["STAND_IN_MARKER", "TerminalUiUnavailable", "ensure_terminal_ui_stand_in", "is_stand_in",
           "stand_in_modules"]

#: Set on every module this installs, so a census can tell them from the real distributions.
STAND_IN_MARKER = "__hermes_terminal_ui_stand_in__"


class TerminalUiUnavailable(ImportError):
    """A terminal-UI name was used on a device that ships no terminal UI."""

    def __init__(self, name: str = "terminal UI"):
        super().__init__(f"{name} is not available on this device: it ships no terminal UI", name=name.split(".")[0])


def _unavailable_class(dotted: str) -> type:
    def __init__(self, *args, **kwargs):
        raise TerminalUiUnavailable(dotted)

    return type(dotted.rpartition(".")[2], (), {"__init__": __init__, "__module__": dotted.rpartition(".")[0]})


def _unavailable_function(dotted: str):
    def unavailable(*args, **kwargs):
        raise TerminalUiUnavailable(dotted)

    unavailable.__name__ = unavailable.__qualname__ = dotted.rpartition(".")[2]
    return unavailable


def _get_app_or_none():
    return None


class _StdoutProxy:
    """prompt_toolkit's ``StdoutProxy``: no stream on a phone is one."""

    def __init__(self, *args, **kwargs):
        raise TerminalUiUnavailable("prompt_toolkit.patch_stdout.StdoutProxy")


def _get_cwidth(string: str) -> int:
    from wcwidth import wcwidth

    return sum(max(wcwidth(char), 0) for char in string)


#: module -> {name: "class" | "function" | a value}: every name upstream imports from it.
_NAMES: dict[str, dict[str, object]] = {
    "rich": {},
    "rich.console": {"Console": "class", "Group": "class"},
    "rich.live": {"Live": "class"},
    "rich.markdown": {"Markdown": "class"},
    "rich.markup": {"escape": "function"},
    "rich.panel": {"Panel": "class"},
    "rich.table": {"Table": "class"},
    "rich.text": {"Text": "class"},
    "prompt_toolkit": {"PromptSession": "class", "prompt": "function", "print_formatted_text": "function"},
    "prompt_toolkit.application": {"Application": "class", "get_app": "function",
                                   "get_app_or_none": _get_app_or_none, "in_terminal": "function",
                                   "run_in_terminal": "function"},
    "prompt_toolkit.application.current": {"get_app_or_none": _get_app_or_none, "get_app": "function"},
    "prompt_toolkit.data_structures": {"Point": "class"},
    "prompt_toolkit.document": {"Document": "class"},
    "prompt_toolkit.filters": {"Condition": "class"},
    "prompt_toolkit.formatted_text": {"ANSI": "class", "fragment_list_width": "function",
                                      "to_formatted_text": "function", "to_plain_text": "function"},
    "prompt_toolkit.key_binding": {"KeyBindings": "class"},
    "prompt_toolkit.layout": {"ConditionalContainer": "class", "FormattedTextControl": "class", "HSplit": "class",
                              "Layout": "class", "Window": "class"},
    "prompt_toolkit.layout.controls": {"FormattedTextControl": "class"},
    "prompt_toolkit.patch_stdout": {"patch_stdout": "function", "StdoutProxy": _StdoutProxy},
    "prompt_toolkit.renderer": {"print_formatted_text": "function"},
    "prompt_toolkit.styles": {"Style": "class"},
    "prompt_toolkit.utils": {"get_cwidth": _get_cwidth},
    "prompt_toolkit.widgets": {"TextArea": "class"},
}


def stand_in_modules() -> dict[str, types.ModuleType]:
    """The ``sys.modules`` entries this registers (the packaging closure asks it too)."""
    modules: dict[str, types.ModuleType] = {}
    for module_name, names in _NAMES.items():
        top = module_name.split(".")[0]
        module = types.ModuleType(module_name, f"Hermes phone stand-in for {top}: no terminal UI on this device.")
        module.__spec__ = None
        setattr(module, STAND_IN_MARKER, True)
        for name, kind in names.items():
            dotted = f"{module_name}.{name}"
            value = _unavailable_class(dotted) if kind == "class" else \
                _unavailable_function(dotted) if kind == "function" else kind
            setattr(module, name, value)
        modules[module_name] = module
    for module_name, module in modules.items():  # a package's submodules are its attributes, as after an import
        parent, _, child = module_name.rpartition(".")
        if parent:
            setattr(modules[parent], child, module)
    return modules


def is_stand_in(module) -> bool:
    return bool(getattr(module, STAND_IN_MARKER, False))


def _real_terminal_ui_importable() -> bool:
    if "rich" in sys.modules or "prompt_toolkit" in sys.modules:
        return True
    try:
        return importlib.util.find_spec("rich") is not None or importlib.util.find_spec("prompt_toolkit") is not None
    except (ImportError, ValueError):
        return False


def ensure_terminal_ui_stand_in() -> bool:
    """Register the stand-in when this profile ships no terminal UI; True when it is in place."""
    if is_stand_in(sys.modules.get("rich")):
        return True
    from agent.transports.httpx_client import provider_sdks_enabled

    if provider_sdks_enabled() or _real_terminal_ui_importable():
        return False
    sys.modules.update(stand_in_modules())
    return True
