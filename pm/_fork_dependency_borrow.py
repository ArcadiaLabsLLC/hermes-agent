"""Fork-owned: a data root may BORROW another root's dependency environment, read-only.

Owner ruling 2026-10-15 (wave w1015c-dev, runtime row "pm cannot lend the owner's Developer
Edition environment to a QA HERMES_HOME"): QA's Developer Edition side runs under a QA-owned
``HERMES_HOME`` but on the owner's installed environment — never a second environment of its own,
which drifted (no provider-SDK extras while the owner's had them). The caller names the lender:

    HERMES_DEPENDENCY_ROOT=<data root whose installs/ to use>   (e.g. <hermes root>, the parent of profiles/)

Unset, every function here is upstream's own (the per-home rule of #123238 is untouched). Set:

* ``pm.environments.dependency_home_root`` answers the named root, so ``install_state_dir``,
  ``selected_venv``, ``venv_is_current`` and the facts read the LENDER's committed environment;
* ``pm.environments.owning_home_root`` answers the named root too, so the launch stays a
  borrower's (no launcher republish, no completion tail, no owner markers);
* ``pm.install.sync_venv`` refuses: a borrower never writes the lender's environment. A stale
  lender is fixed from the owner's side (``hermes update`` / ``hermes pm install`` there).

Stdlib only: ``pm.environments`` must work before any dependency is importable.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable

__all__ = [
    "ENV",
    "BorrowedEnvironmentReadOnly",
    "borrowed_dependency_root",
    "refuse_sync_while_borrowing",
]

ENV = "HERMES_DEPENDENCY_ROOT"


class BorrowedEnvironmentReadOnly(RuntimeError):
    """A sync was asked of a process that only borrows another root's environment."""


def borrowed_dependency_root() -> Path | None:
    """The data root named by :data:`ENV`, or ``None`` when unset. A relative path is refused."""
    value = os.environ.get(ENV, "").strip()
    if not value:
        return None
    root = Path(value)
    if not root.is_absolute():
        raise BorrowedEnvironmentReadOnly(f"{ENV} must name an absolute data root, got {value!r}")
    return root


def refuse_sync_while_borrowing(original: Callable[..., Any]) -> Callable[..., Any]:
    if getattr(original, "__fork_borrow__", False):
        return original

    def sync_venv(*args: Any, **kwargs: Any) -> Any:
        lender = borrowed_dependency_root()
        if lender is not None:
            from pm.package import InstallError

            raise InstallError(
                "venv",
                f"this process borrows {lender}'s dependency environment read-only ({ENV}); "
                "it is never synced from here",
                f"update the Developer Edition from its owner ({lender}), then relaunch",
            )
        return original(*args, **kwargs)

    sync_venv.__fork_borrow__ = True  # type: ignore[attr-defined]
    sync_venv.__wrapped__ = original  # type: ignore[attr-defined]
    sync_venv.__doc__ = original.__doc__
    return sync_venv
