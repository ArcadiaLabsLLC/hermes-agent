"""The phone's forced tree: switched-off code the wheel ships where no directory scan looks.

Owner ruling 2026-09-30 (option (1), phone-gate-to-zero plan lane G6). The packager's
forced set (``scripts/bundle_profile_package.first_party_plan``) is switched-off code that
kept code imports unguarded, so it must ship — but upstream finds tools and plugins by
DIRECTORY SCAN (``tools/registry.py::discover_builtin_tools`` globs ``tools/*.py`` and
``tools/*/tool.py``; the plugin loader walks ``plugins/``), and a scan that sees a shipped
file imports it. So a profile that sets ``packaging.forced_sibling_tree`` ships those
modules under a sibling root beside ``app/``::

    <bundle>/app/tools/...            kept code, what the scans see
    <bundle>/phone_forced/tools/...   the forced set, resolvable by import, never scanned

and the embedded entry (``EmbeddedServe.start``) appends ``phone_forced/tools`` and
``phone_forced/plugins`` to ``tools.__path__`` / ``plugins.__path__``. An import of a forced
module resolves; no scan walks ``__path__``, so none reaches it. Upstream is untouched.

A forced module goes to the sibling tree when it lies under a scanned package with no KEPT
package between (:func:`sibling_modules`): then appending to the scanned package's
``__path__`` is enough to resolve it (a regular sub-package found there carries its own
``__path__``; a namespace directory recomputes its path from its parent's). A forced module
inside a kept sub-package (``plugins.memory.mem0._setup``) stays in ``app/``: that package's
``__path__`` is ``app/``-only, and no scan imports a non-entry file of a kept package.
"""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Iterable

__layer__ = "policy"

__all__ = ["FORCED_TREE_DIR", "SCANNED_PACKAGES", "forced_tree_root", "mount_forced_tree", "sibling_modules"]

#: The sibling root's directory name, beside the bundle's ``app/``.
FORCED_TREE_DIR = "phone_forced"
#: The packages upstream discovers by directory scan.
SCANNED_PACKAGES = ("tools", "plugins")


def sibling_modules(forced: Iterable[str], kept: Iterable[str]) -> set[str]:
    """The forced modules that ship in the sibling tree: under a scanned package, no kept package between."""
    kept = set(kept)
    out: set[str] = set()
    for module in forced:
        parts = module.split(".")
        if len(parts) < 2 or parts[0] not in SCANNED_PACKAGES:
            continue
        if any(".".join(parts[:i]) in kept for i in range(2, len(parts))):
            continue
        out.add(module)
    return out


def forced_tree_root(app_root: Path) -> Path:
    """``<bundle>/phone_forced`` for a bundle whose first-party tree is ``app_root``."""
    return Path(app_root).parent / FORCED_TREE_DIR


def mount_forced_tree(app_root: Path | None = None) -> list[str]:
    """Append the sibling tree's scanned-package directories to those packages' ``__path__``.

    ``app_root`` defaults to the directory holding the imported ``tools`` package. Nothing is
    mounted when the sibling tree does not exist (a checkout, a desktop bundle). Idempotent.
    Returns the directories appended by this call.
    """
    if app_root is None:
        app_root = Path(importlib.import_module("tools").__file__).resolve().parent.parent
    root = forced_tree_root(app_root)
    mounted: list[str] = []
    if not root.is_dir():
        return mounted
    for name in SCANNED_PACKAGES:
        directory = root / name
        if not directory.is_dir():
            continue
        package = importlib.import_module(name)
        if str(directory) not in list(package.__path__):
            package.__path__.append(str(directory))
            mounted.append(str(directory))
    return mounted
