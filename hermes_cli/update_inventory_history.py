"""The update plan's cached fork-history block — fork-owned (PR #125265's inventory half).

``hermes update --plan`` shows, for a git checkout whose origin is a fork, how the cached
``origin/main`` relates to HEAD and which branch ``update_history.guard_fork_history`` will
take. Upstream's ``hermes_cli/update_inventory.py`` keeps one ``history`` field and two calls
into this module (FH-FOOTPRINT-UPDATE-INVENTORY-HISTORY); the body lives here. Local refs only:
the plan never fetches.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

#: A relationship the update applies without the fork-history guard stepping in.
_PLAIN = frozenset({"equal", "fast_forward", "local_ahead"})


def _origin_is_fork(git_cmd: list[str], root: Path) -> bool:
    from hermes_cli.update_cmd_git import OFFICIAL_REPO_URLS
    from hermes_cli.update_history import _git

    origin = _git(git_cmd, root, "remote", "get-url", "origin").stdout.strip()
    official = {url.rstrip("/").removesuffix(".git") for url in OFFICIAL_REPO_URLS}
    return bool(origin) and origin.rstrip("/").removesuffix(".git") not in official


def inventory_history(git_cmd: list[str] | None = None, root: Path | None = None) -> dict[str, Any]:
    """The cached fork-history assessment of *root* (the running checkout), or ``{}`` for an
    official checkout or on any failure (an inventory probe never raises)."""
    try:
        from hermes_cli.update_history import assess_history, has_fork_ancestry

        git_cmd = git_cmd or ["git"]
        if root is None:
            from hermes_cli.main import PROJECT_ROOT as root
        if not _origin_is_fork(git_cmd, root):
            return {}
        return {**assess_history(git_cmd, root, "origin/main").to_dict(),
                "guarded": has_fork_ancestry(git_cmd, root)}
    except Exception as exc:  # health: allow BLE001 -- an inventory probe yields fewer rows, never an exception
        logger.debug("Fork history assessment failed: %s", exc)
        return {}


def print_inventory_history(history: dict[str, Any]) -> None:
    """The plan's fork-history lines; nothing when there is no assessment."""
    if not history:
        return
    print(f"  Fork history (cached {history['target']}): {history['relationship']}")
    if history["relationship"] in _PLAIN:
        return
    # The plan must describe the branch guard_fork_history will actually take.
    if not history["guarded"]:
        print("  No fork ancestry here: the update takes the standard rescue-ref and reset path.")
        return
    if history["same_tree"]:
        print("  Matching trees with different ancestry: possible fold; review required, never automatic reset.")
    print("  Update will preserve recovery refs and stop before stashing or switching this checkout.")
