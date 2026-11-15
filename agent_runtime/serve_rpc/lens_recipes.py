"""``runtime.lens.recipe.*`` — a workspace's shared Lens recipes (tier ``console``).

Plan ``docs/agent-runtime-harness/planned/lens-shared-recipes-2026-11-15.md`` §4 and §5 (slice 1,
row ``RT-LENS-RECIPE-SHELF-SHARE-AND-ADD``). The shelf is ``lens/recipe_shelf.py``; what this PC
runs stays ``lens/store.py``. A recipe becomes a monitor here only through ``add``, and then as a
DRAFT written by the one create door: nothing runs until its person signs in the sources, seals
and enables it (``runtime.lens.credential.set`` / ``.seal`` / ``.enable``).

==========  ======================================================================================
verb        params -> result
==========  ======================================================================================
list        {workspace_id?} -> {workspace_id, recipes: [row], held: [recipe_id], refused:
            [{recipe_id, reason}]} (absent ``workspace_id``: the active workspace). ``refused``
            names each shelf document that will not read or is not filed where it says; ``held``
            is the recipes a realm pull parked — always empty until realm sync carries the family
share       {monitor_id} -> row. Writes the monitor's SEALED manifest (never a draft) to its
            workspace's shelf. ``monitor_not_found``, ``not_sealed``, ``recipe_needs_workspace``
            (the monitor has no workspace), ``recipe_not_portable`` (``detail`` names the feed: a
            command or SQL source is never shared), ``recipe_id_taken``
withdraw    {workspace_id?, recipe_id} -> row (state ``withdrawn``). ``recipe_not_found``. A
            monitor someone already added keeps running: their PC, their choice
add         {workspace_id?, recipe_id} -> the monitor, as ``runtime.lens.get`` answers it. A new
            DRAFT in that workspace, or a sealed monitor's next-revision draft when the workspace
            already holds that monitor (an update; the sealed revision keeps running unchanged, and
            ``runtime.lens.draft.drop`` of that draft puts the recipe back to ``update_available``; an
            update that moved a source reads ``draft_credentials`` unset there, and is signed in
            before Seal with ``credential.set``'s ``monitor_id`` + ``revision: draft``).
            Its credential refs are renamed ``shared:<monitor_id>:<ref>`` and read ``set: false``;
            ``automation.actions`` is dropped. ``recipe_not_found``, ``recipe_withdrawn``,
            ``monitor_exists`` (the id is another workspace's monitor), ``capacity_refused``,
            ``monitor_retired``, ``invalid_string`` (a renamed ref past the id bound)
==========  ======================================================================================

A row is ``{recipe_id, workspace_id, monitor_id, state, manifest, summary}``:

* ``state`` — ``recipe_shelf.RECIPE_STATES`` over the shelf document and this PC's monitor of that
  id in that workspace: ``not_added`` · ``added`` (its ``recipe_hash`` is the document's) ·
  ``update_available`` (it is not) · ``withdrawn``;
* ``manifest`` — the shared manifest as published (null when withdrawn);
* ``summary`` — ``{level, sources: [{feed_id, kind, host}], scheduled, needs_credentials: [ref],
  private_network, suggested_actions: [tool]}`` (null when withdrawn).

``share``, ``withdraw`` and ``add`` append ``lens.recipe.changed {workspace_id, recipe_id,
change: shared|withdrawn|added}``. Refusals carry ``data.reason`` and ``data.detail`` (``""`` where
none is named; ``_lens_call``).

Pinned by ``tests/agent_runtime/lens/test_lens_recipe_shelf.py``.
"""

from __future__ import annotations

from typing import Any

from agent_runtime.call_authorization import TIER_CONSOLE
from agent_runtime.serve_rpc.lens import _lens_call, _monitor_answer, _monitor_id, _store
from agent_runtime.serve_rpc.protocol import RpcContext
from agent_runtime.serve_rpc.registry import method

__layer__ = "lanes"


def _recipe_workspace(params: dict) -> str:
    """The verb's workspace: the one named, else the active one; ``recipe_needs_workspace`` with neither."""

    from agent_runtime.lens.recipe_shelf import RecipeDocumentError, RecipeRefusal
    from agent_runtime.lens.store_scope import active_workspace_id, workspace_param

    workspace_id = workspace_param(params) or active_workspace_id()
    if workspace_id is None:
        raise RecipeDocumentError(RecipeRefusal.NEEDS_WORKSPACE)
    return workspace_id


def _recipe(params: dict, required: set[str]):
    """``(workspace_id, the shelf recipe)`` of a ``{workspace_id?, recipe_id}`` request."""

    from agent_runtime.lens.recipe_shelf import read_recipe
    from agent_runtime.lens.wire_value import checked_object, opaque_id

    m = checked_object(params or {}, required, {"workspace_id"})
    workspace_id = _recipe_workspace(m)
    return workspace_id, read_recipe(workspace_id, opaque_id(m["recipe_id"]))


def _row(recipe, monitors: dict[str, dict]) -> dict:
    """``monitors``: this PC's monitors by id. Only one in the recipe's own workspace counts."""

    from agent_runtime.lens.recipe_shelf import recipe_state, recipe_summary

    monitor = monitors.get(recipe.monitor_id)
    if monitor is not None and monitor["workspace_id"] != recipe.workspace_id:
        monitor = None
    return {"recipe_id": recipe.recipe_id, "workspace_id": recipe.workspace_id, "monitor_id": recipe.monitor_id,
            "state": recipe_state(recipe, monitor).value, "manifest": recipe.manifest,
            "summary": None if recipe.withdrawn else recipe_summary(recipe.manifest)}


def _monitors() -> dict[str, dict]:
    return {row["monitor_id"]: row for row in _store().monitors()}


@method("runtime.lens.recipe.list", tier=TIER_CONSOLE)
def _runtime_lens_recipe_list(rid: Any, params: dict, context: RpcContext | None = None) -> dict:
    def body() -> dict:
        from agent_runtime.lens.recipe_shelf import read_shelf
        from agent_runtime.lens.wire_value import checked_object

        workspace_id = _recipe_workspace(checked_object(params or {}, set(), {"workspace_id"}))
        recipes, refused = read_shelf(workspace_id)
        monitors = _monitors()
        return {"workspace_id": workspace_id, "recipes": [_row(recipe, monitors) for recipe in recipes],
                "held": [], "refused": refused}

    return _lens_call(rid, body)


@method("runtime.lens.recipe.share", tier=TIER_CONSOLE)
def _runtime_lens_recipe_share(rid: Any, params: dict, context: RpcContext | None = None) -> dict:
    def body() -> dict:
        from agent_runtime.lens.recipe_shelf import (
            RecipeChange, RecipeDocumentError, RecipeRefusal, announce, recipe_document, write_recipe,
        )
        from agent_runtime.lens.store import LensStoreError, StoreRefusal
        from agent_runtime.lens.wire_value import checked_object

        store = _store()
        monitor = store.get(_monitor_id(checked_object(params or {}, {"monitor_id"})))
        if monitor["sealed"] is None:
            raise LensStoreError(StoreRefusal.NOT_SEALED)
        if monitor["workspace_id"] is None:
            raise RecipeDocumentError(RecipeRefusal.NEEDS_WORKSPACE)
        recipe = write_recipe(recipe_document(monitor["workspace_id"], monitor["sealed"]["manifest"]))
        store.mark_shared(recipe.monitor_id, recipe.hash)
        announce(recipe, RecipeChange.SHARED)
        return _row(recipe, _monitors())

    return _lens_call(rid, body)


@method("runtime.lens.recipe.withdraw", tier=TIER_CONSOLE)
def _runtime_lens_recipe_withdraw(rid: Any, params: dict, context: RpcContext | None = None) -> dict:
    def body() -> dict:
        from agent_runtime.lens.recipe_shelf import RecipeChange, announce, withdrawn_document, write_recipe

        workspace_id, held = _recipe(params, {"recipe_id"})
        recipe = write_recipe(withdrawn_document(workspace_id, held.monitor_id))
        announce(recipe, RecipeChange.WITHDRAWN)
        return _row(recipe, _monitors())

    return _lens_call(rid, body)


@method("runtime.lens.recipe.add", tier=TIER_CONSOLE)
def _runtime_lens_recipe_add(rid: Any, params: dict, context: RpcContext | None = None) -> dict:
    """The recipe becomes a DRAFT through ``LensStore.create`` — the one door, and the only write
    this verb makes: it seals nothing and enables nothing."""

    def body() -> dict:
        from agent_runtime.lens.recipe_shelf import (
            RecipeChange, RecipeDocumentError, RecipeRefusal, announce, localize,
        )

        workspace_id, recipe = _recipe(params, {"recipe_id"})
        if recipe.withdrawn:
            raise RecipeDocumentError(RecipeRefusal.WITHDRAWN)
        _store().create(localize(recipe.manifest), workspace_id=workspace_id, recipe_hash=recipe.hash)
        announce(recipe, RecipeChange.ADDED)
        return _monitor_answer(recipe.monitor_id)

    return _lens_call(rid, body)
