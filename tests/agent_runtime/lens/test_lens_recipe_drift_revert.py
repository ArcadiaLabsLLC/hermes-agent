"""A shared Lens watch you changed but have not published shows as pending, and you can put the
workspace's copy back (row ``RT-LENS-RECIPE-DRIFT-ARM``; plan
``docs/agent-runtime-harness/planned/lens-shared-recipes-2026-11-15.md`` §3, §7 "Drift and revert
agree").

The publisher's PC from ``test_lens_recipe_realm_sync``: share, publish, then the shelf document
changes here. The change is ONE ``store_drift`` row, and reverting that row restores the published
bytes through the shelf's door without touching the monitor. Killed by omitting the
``SyncFamily.LENS_RECIPE`` row from ``realm_revert._FAMILY_ARMS`` — the row is no longer
revert-addressable (``--item`` refuses the family).
"""

from __future__ import annotations

from agent_runtime import paths
from agent_runtime.lens.recipe_shelf import LENS_RECIPE_FAMILY, recipe_document
from agent_runtime.lens.store import LensStore
from agent_runtime.realm_revert import revert_realm_sync
from agent_runtime.realm_sync import realm_sync_status
from agent_runtime.realm_sync.document_family import DocumentStore
from tests.agent_runtime.lens.test_lens_recipe_realm_sync import _manifest, team  # noqa: F401  (fixture)


def _recipe_rows(realm_id: str) -> list[dict]:
    return [row for row in realm_sync_status(realm_id)["store_drift"]["items"] if row["family"] == "lens_recipe"]


def test_a_changed_shared_recipe_is_one_row_and_a_revert_restores_the_published_copy(team):
    team.share()
    team.publish()
    shelf = DocumentStore(LENS_RECIPE_FAMILY)
    published = shelf.read(team.token)
    assert _recipe_rows(team.realm.id) == []
    monitor = LensStore().get("site-health")

    shelf.write(team.token, recipe_document(team.workspace, _manifest(interval_ms=9000)))
    container = paths.safe_path_token(team.workspace)
    assert _recipe_rows(team.realm.id) == [
        {"family": "lens_recipe", "container": container, "item_key": team.token, "kind": "changed"}]

    result = revert_realm_sync(team.realm.id, item_specs=[f"lens_recipe:{container}:{team.token}"])

    assert [(row["family"], row["outcome"]) for row in result["items"]] == [("lens_recipe", "reverted_to_upstream")]
    assert shelf.read(team.token) == published
    assert _recipe_rows(team.realm.id) == []
    assert LensStore().get("site-health") == monitor  # the shelf only; no monitor is rewritten


def test_a_share_the_realm_never_carried_is_not_archived_by_a_revert(team):
    team.publish()  # the realm's subtree exists and carries no recipe
    team.share()
    container = paths.safe_path_token(team.workspace)
    assert [row["kind"] for row in _recipe_rows(team.realm.id)] == ["added"]
    mine = DocumentStore(LENS_RECIPE_FAMILY).read(team.token)

    result = revert_realm_sync(team.realm.id, item_specs=[f"lens_recipe:{container}:{team.token}"])

    assert [row["outcome"] for row in result["items"]] == ["refused_no_upstream"]
    assert DocumentStore(LENS_RECIPE_FAMILY).read(team.token) == mine
