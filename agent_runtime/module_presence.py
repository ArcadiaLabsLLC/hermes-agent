"""Whether a module ships in this installation — the presence probe a profile's omissions answer.

A pure probe (``sys.modules`` + ``importlib.util.find_spec``), so any layer may ask it: a store or
a policy deciding whether a feature exists needs no lane. ``agent_runtime/loop_tool_lifecycles.py``
registers the placeholders this probe sees through, and re-exports both names
(RT-SHIPPED-PROBE-IN-LANES).
"""

from __future__ import annotations

import importlib.util
import sys

__layer__ = "policy"
__all__ = ["is_lifecycle_placeholder", "shipped"]


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
