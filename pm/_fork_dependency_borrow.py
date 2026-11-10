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

A QA launch pinned to ANOTHER checkout (a worktree) also names the lender's checkout, because
dependency state is keyed by checkout too (``installs/<install_key(checkout)>``) and the lender
only ever installed its own (RT-QA-CHECKOUT-BORROW-LENDER-KEY, plan
``docs/agent-runtime-harness/planned/qa-checkout-dependency-identity-2026-11-05.md``):

    HERMES_DEPENDENCY_CHECKOUT=<absolute lender checkout>       (only beside HERMES_DEPENDENCY_ROOT)

Then ``pm.environments.install_state_dir`` answers ``<lender root>/installs/<install_key(lender
checkout)>`` for every checkout, while the running checkout still owns ``sys.path`` (its code
runs). The borrow refuses, by name, the variable alone, a relative path, a lender checkout with no
committed environment there, and a running checkout whose dependency inputs differ in content from
the lender's (RT-QA-CHECKOUT-BORROW-INPUTS-MATCH): a receipt measured on the wrong packages is a
false green.

Stdlib only: ``pm.environments`` must work before any dependency is importable.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Callable

__all__ = [
    "CHECKOUT_ENV",
    "ENV",
    "BorrowedEnvironmentReadOnly",
    "borrowed_checkout",
    "borrowed_dependency_root",
    "differing_dependency_inputs",
    "lender_install_state_dir",
    "refuse_sync_while_borrowing",
]

ENV = "HERMES_DEPENDENCY_ROOT"
CHECKOUT_ENV = "HERMES_DEPENDENCY_CHECKOUT"


class BorrowedEnvironmentReadOnly(RuntimeError):
    """A borrow that cannot be honoured, or a sync asked of a process that only borrows.

    ``reason`` names the refusal (``dependency_checkout_without_root``,
    ``lender_checkout_not_installed``, ``dependency_inputs_differ``, ...) for a caller that
    reports it; the message leads with it and carries the paths.
    """

    def __init__(self, message: str, *, reason: str = "borrow_refused") -> None:
        super().__init__(f"{reason}: {message}")
        self.reason = reason


def borrowed_dependency_root() -> Path | None:
    """The data root named by :data:`ENV`, or ``None`` when unset. A relative path is refused."""
    value = os.environ.get(ENV, "").strip()
    if not value:
        return None
    root = Path(value)
    if not root.is_absolute():
        raise BorrowedEnvironmentReadOnly(
            f"{ENV} must name an absolute data root, got {value!r}", reason="relative_dependency_root")
    return root


def borrowed_checkout() -> Path | None:
    """The lender checkout named by :data:`CHECKOUT_ENV`, or ``None`` when unset.

    Refused: the variable without :data:`ENV` (a checkout names no root to read it under) and a
    relative path.
    """
    value = os.environ.get(CHECKOUT_ENV, "").strip()
    if not value:
        return None
    if not os.environ.get(ENV, "").strip():
        raise BorrowedEnvironmentReadOnly(
            f"{CHECKOUT_ENV} ({value!r}) is set without {ENV}: name the lender root beside it",
            reason="dependency_checkout_without_root")
    checkout = Path(value)
    if not checkout.is_absolute():
        raise BorrowedEnvironmentReadOnly(
            f"{CHECKOUT_ENV} must name an absolute lender checkout, got {value!r}",
            reason="relative_dependency_checkout")
    return checkout


def _input_digests(checkout: Path, names: tuple[str, ...]) -> dict[str, str | None]:
    digests: dict[str, str | None] = {}
    for name in names:
        try:
            digests[name] = hashlib.sha256((checkout / name).read_bytes()).hexdigest()
        except FileNotFoundError:
            digests[name] = None
    return digests


# (running, lender, stat signature) -> the differing names; uv.lock is hashed once per change,
# not once per ``install_state_dir`` call.
_INPUTS_MEMO: dict[tuple, tuple[str, ...]] = {}


def _stat_signature(checkout: Path, names: tuple[str, ...]) -> tuple:
    signature = []
    for name in names:
        try:
            stat = (checkout / name).stat()
            signature.append((stat.st_mtime_ns, stat.st_size, stat.st_ino))
        except FileNotFoundError:
            signature.append(None)
    return tuple(signature)


def differing_dependency_inputs(running: Path, lender: Path, names: tuple[str, ...]) -> tuple[str, ...]:
    """The dependency inputs whose CONTENT differs between two checkouts (mtimes never agree)."""
    key = (str(running), str(lender), names, _stat_signature(running, names), _stat_signature(lender, names))
    cached = _INPUTS_MEMO.get(key)
    if cached is None:
        mine, theirs = _input_digests(running, names), _input_digests(lender, names)
        cached = tuple(name for name in names if mine[name] != theirs[name])
        _INPUTS_MEMO.clear()
        _INPUTS_MEMO[key] = cached
    return cached


def _has_committed_environment(state: Path) -> bool:
    try:
        data = json.loads((state / "facts.json").read_text(encoding="utf-8-sig"))
        return isinstance(data["packages"]["venv"]["environment"], str)
    except (OSError, ValueError, KeyError, TypeError):
        return False


def lender_install_state_dir(project_root: Path, root: Path, checkout: Path,
                             install_key: Callable[[Path], str], inputs: tuple[str, ...]) -> Path:
    """``<root>/installs/<install_key(checkout)>`` for any running checkout, or a named refusal."""
    state = root / "installs" / install_key(checkout)
    if not _has_committed_environment(state):
        raise BorrowedEnvironmentReadOnly(
            f"{CHECKOUT_ENV} names {checkout}, but {state} holds no committed dependency environment "
            f"under the lender root {root}; install it from the lender's side",
            reason="lender_checkout_not_installed")
    running = Path(project_root).resolve()
    lender = checkout.resolve()
    if running != lender:
        differ = differing_dependency_inputs(running, lender, inputs)
        if differ:
            raise BorrowedEnvironmentReadOnly(
                f"{', '.join(differ)} differ between {running} and the lender "
                f"checkout {lender}; this checkout cannot run on the lender's environment",
                reason="dependency_inputs_differ")
    return state


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
