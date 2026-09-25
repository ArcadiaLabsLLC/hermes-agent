"""Patch a ``dispatch_delivery`` seam in EVERY module that binds it.

``agent_runtime/dispatch_delivery.py`` became a package (god-file program lane
B3). The drain's decision seams — ``_sender_is_idle``, ``_sender_persona`` —
are defined in ``forge`` and bound by import in ``drain`` and ``completions``;
the package re-exports them for ``tools/agent_chat_tool``, which reads the
package attribute at call time. A ``monkeypatch.setattr(dispatch_delivery,
...)`` therefore reaches only that last reader and is a silent no-op for the
drain itself — the class the lane-B2 report named.

The bindings are ENUMERATED from the modules (``hasattr``), never typed here,
so a seam that moves or gains a binder is followed without an edit, and a
name nothing binds is a loud failure rather than a vacuous patch.
"""

from __future__ import annotations

from typing import Any

__all__ = ["patch_delivery_seam"]


def patch_delivery_seam(monkeypatch: Any, name: str, value: Any) -> list[str]:
    """``monkeypatch.setattr`` *name* on the package and each submodule binding it.

    Returns the dotted modules patched, so a test may assert the reach.
    """

    import pkgutil
    from importlib import import_module

    package = import_module("agent_runtime.dispatch_delivery")
    modules = [package] + [
        import_module(f"{package.__name__}.{info.name}")
        for info in pkgutil.iter_modules(package.__path__)
    ]
    bound = [module for module in modules if name in vars(module)]
    assert bound, f"no dispatch_delivery module binds {name!r}"
    for module in bound:
        monkeypatch.setattr(module, name, value)
    return [module.__name__ for module in bound]
