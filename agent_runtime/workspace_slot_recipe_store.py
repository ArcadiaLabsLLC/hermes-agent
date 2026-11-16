"""The setup recipe's doors: ``recipe.show`` and ``recipe.script`` read it; ``recipe.set`` is refused.

Plan ``docs/agent-runtime-harness/planned/slot-setup-recipe-2026-11-15.md`` §3. The recipe lives
IN THE REPOSITORY (``.eternia/setup/``, read by ``workspace_slot_repo_recipe.read_recipe`` from
this computer's checkout); hermes has no door that writes it, so ``recipe.set`` answers
``recipe_in_repository``.

* **show** is read-only: every live slot's readiness on THIS machine (the checkout alone, read
  from this machine's last report — ``ready``, ``checklist``, ``steps``, ``blocking``, ``notes``,
  kept for Eternia's Set up until it reads the new block) and the ``recipe`` block: this
  computer's platform, and either ``blank`` with its ``why`` or the recipe's items with their
  state here (probed when called), the install script (``{id, path, sha256, last_run}``) and
  ``left``, the count still to do here.
* **script** is read-only: one slot's install script, ``{slot, path, commit, sha256, text}`` —
  what Set up shows before Run.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from .workspace_slot_recipe import readiness
from .workspace_slot_repo_recipe import RecipeRead, read_recipe, read_script, this_platform
from .workspace_slots import (
    REASON_SLOT_NOT_DECLARED,
    SlotRefused,
    bound_path,
    known_machine_id,
    live_slots,
    load_document,
    resolve_slot,
    slot_revision,
)

__layer__ = "stores"

#: ``recipe.set``: the recipe changes by a commit to the repository, never through hermes.
REASON_RECIPE_IN_REPOSITORY = "recipe_in_repository"
#: ``recipe.script`` on a slot whose checkout has no recipe for this platform (the ``why`` rides the detail).
REASON_RECIPE_BLANK = "recipe_blank"
#: ``recipe.script`` on a recipe that names no install script for this platform.
REASON_NO_SCRIPT = "no_script"
#: The script item's id (its runs are recorded under it).
SCRIPT_ITEM_ID = "script"
_RUN_SUCCEEDED = "succeeded"
_STATE_TODO = "todo"
_RECIPE_SOURCE = ".eternia/setup/recipe.json"


def set_recipe(workspace_id: str | None, slot: str, *_args: Any, **_kwargs: Any) -> dict[str, Any]:
    """Refused: the recipe lives in the repository and changes by a commit (plan slot-setup-recipe §4)."""

    raise SlotRefused(REASON_RECIPE_IN_REPOSITORY, f"{slot}'s setup recipe is .eternia/setup/ in its repository")


def checkout_commit(path: Path) -> str | None:
    """The commit ``path``'s working tree is on, or None (not a repository, git absent)."""

    from .host_tools import git_command

    try:
        done = subprocess.run([git_command(), "-C", str(path), "rev-parse", "HEAD"], capture_output=True, text=True,
                              timeout=10, stdin=subprocess.DEVNULL, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout.strip() or None if done.returncode == 0 else None


def _my_rows(document: dict[str, Any]) -> dict[str, Any]:
    machine = known_machine_id()
    mine = ((document.get("machines") or {}).get(machine) or {}) if machine else {}
    return mine.get("slots") or {}


def recipe_block(workspace_id: str | None, name: str, slot: dict[str, Any], runs: dict[str, Any]) -> dict[str, Any]:
    """``name``'s repository recipe on this computer: blank with its ``why``, or its items, script and ``left``."""

    from .workspace_slot_env import slot_fill
    from .workspace_slots_probe import recipe_items

    path = bound_path(name, workspace_id=workspace_id)
    read = read_recipe(path, this_platform())
    if read.recipe is None or path is None:
        return {"platform": read.platform, "blank": read.blank, "why": read.why}
    items = recipe_items(name, slot, slot_fill(workspace_id, name), path, read.recipe)
    shown = read_script(path, read.recipe)
    script = None if shown is None else {"id": SCRIPT_ITEM_ID, "path": shown["path"], "sha256": shown["sha256"],
                                         "last_run": runs.get(SCRIPT_ITEM_ID)}
    left = sum(item["state"] == _STATE_TODO for item in items)
    if script is not None and (script["last_run"] or {}).get("status") != _RUN_SUCCEEDED:
        left += 1
    return {"platform": read.platform, "source": {"path": _RECIPE_SOURCE, "commit": checkout_commit(path)},
            "items": items, "script": script, "left": left}


def _slot_checklist(workspace_id: str | None, name: str, slot: dict[str, Any], rows: dict[str, Any]) -> dict[str, Any]:
    """One slot's readiness and recipe block; ``runs`` is the newest Clone / script run on THIS machine."""

    from .workspace_slot_runs import latest_runs

    runs = latest_runs(workspace_id, name)
    legacy = slot.get("recipe") if isinstance(slot.get("recipe"), dict) else {}
    # ``edited_at`` / ``edited_by`` are an older writer's, kept for Eternia's Set up until it moves (§6 slice 3).
    return {"revision": slot_revision(slot), "edited_at": legacy.get("edited_at"), "edited_by": legacy.get("edited_by"),
            **readiness(name, slot, rows.get(name)),
            "recipe": recipe_block(workspace_id, name, slot, runs), "runs": runs}


def show_recipe(workspace_id: str) -> dict[str, Any]:
    """Every live slot of the workspace, with its readiness and its repository recipe on THIS machine."""

    document = load_document(workspace_id)
    machine = known_machine_id()
    mine = ((document.get("machines") or {}).get(machine) or {}) if machine else {}
    rows = _my_rows(document)
    slots = {name: _slot_checklist(workspace_id, name, slot, rows) for name, slot in sorted(live_slots(document).items())}
    return {"workspace_id": workspace_id, "machine": machine, "reported_at": mine.get("reported_at") or None,
            "platform": this_platform(), "slots": slots}


def bound_recipe(workspace_id: str | None, slot: str) -> tuple[Path, RecipeRead]:
    """``slot``'s checkout here and its recipe, or :class:`SlotRefused` (undeclared, or blank with its why)."""

    if resolve_slot(workspace_id, slot) is None:
        raise SlotRefused(REASON_SLOT_NOT_DECLARED, f"{workspace_id} declares no slot {slot!r}")
    path = bound_path(slot, workspace_id=workspace_id)
    read = read_recipe(path, this_platform())
    if read.recipe is None or path is None:
        raise SlotRefused(REASON_RECIPE_BLANK, f"{read.blank}: {read.why}")
    return path, read


def show_script(workspace_id: str | None, slot: str) -> dict[str, Any]:
    """``slot``'s install script for this platform: ``{slot, path, commit, sha256, text}`` (read-only)."""

    path, read = bound_recipe(workspace_id, slot)
    shown = read_script(path, read.recipe)
    if shown is None:
        raise SlotRefused(REASON_NO_SCRIPT, f"{slot}'s {read.platform} recipe names no install script")
    return {"slot": slot, "platform": read.platform, "commit": checkout_commit(path), **shown}


__all__ = ["bound_recipe", "recipe_block", "set_recipe", "show_recipe", "show_script"]
