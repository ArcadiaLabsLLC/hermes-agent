"""The Lens RECIPE shelf: what a workspace SHARES of its monitors, apart from what this PC runs.

Plan ``docs/agent-runtime-harness/planned/lens-shared-recipes-2026-11-15.md`` §2 (slice 1, row
``RT-LENS-RECIPE-SHELF-SHARE-AND-ADD``). Ruling ``OR-2026-11-09-lens-shared-recipes-opt-in``: "it
should be only the recipe gets shared and you choose to enable it".

Two facts, two stores. The Lens store (``lens/store.py``) holds what this PC runs. The shelf holds
what a workspace shares: one document per shared monitor at
``store/lens_recipes/<workspace token>/<recipe id>.json`` (``paths.lens_recipe_path``),

    {"version": 1, "workspace_id": "ws_…", "monitor_id": "site-health", "withdrawn": false,
     "manifest": { …the sealed manifest… }}

and a withdrawn recipe is ``"withdrawn": true, "manifest": null`` (a document, not a deleted
file: in the whole-document class an absent file is never a removal).

**This module never imports ``lens.store``** — the shelf cannot create, seal or enable anything,
so nothing that will one day sync the shelf can reach a monitor
(``tests/agent_runtime/lens/test_lens_recipe_shelf.py`` pins the import). A recipe becomes a
DRAFT only through ``LensStore.create``, called by ``runtime.lens.recipe.add``
(``serve_rpc/lens_recipes.py``) with :func:`localize`'s output.

What is here:

* :data:`LENS_RECIPE_FAMILY` — the ONE description of the family (a
  ``realm_sync.document_family.DocumentFamily``): paths, bound, refusals, and
  :func:`read_recipe_document` as its ``extra_check``, so every door that stores or reads a recipe
  (share, list, add; later the publish scan, the pull and the revert) refuses the same documents.
  It carries no sync wiring: no ``SyncFamily`` member, no path-family row, no applier. Those are
  row ``RT-LENS-RECIPE-REALM-SYNC-FAMILY``'s, which swaps :data:`SYNC_KIND` for the enum member.
* :func:`recipe_document` / :func:`withdrawn_document` — the bytes a share and a withdrawal write.
* :func:`read_recipe` / :func:`read_shelf` — a workspace's shelf, each document checked and
  **filed where it says** (:func:`filed_token`; one that is not is ``recipe_misfiled``).
* :func:`localize` — what Add writes: every ``credential_ref`` moved into this recipe's own
  namespace and ``automation.actions`` removed.
* :func:`recipe_summary`, :func:`recipe_state` — the derived row fields Eternia draws.
* :func:`announce` — the ``lens.recipe.changed`` event (``decision_contract_registry``).

Pinned by ``tests/agent_runtime/lens/test_lens_recipe_shelf.py``.
"""

from __future__ import annotations

import json
from enum import Enum
from typing import Any, NamedTuple

from .. import paths
from ..realm_sync.document_family import (
    REFUSAL_MISSING_VERSION,
    REFUSAL_NOT_AN_OBJECT,
    REFUSAL_TOO_LARGE,
    REFUSAL_UNREADABLE_DOCUMENT,
    DocumentError,
    DocumentFamily,
    DocumentPullSummary,
    DocumentStore,
    document_hash,
    validate_document,
)
from .feed import FeedKind, address_parts, feed_address
from .host_budget import is_private_reader
from .manifest import read_manifest
from .wire_value import MAXIMUM_MANIFEST_BYTES, LensRefusal, RefusalKind, WireError, canonical_bytes, opaque_id

__layer__ = "stores"

#: The feed kinds a recipe may carry (plan decision 5). ``sql_readonly`` names an absolute path on
#: the publisher's disk and ``command_allowlisted`` carries the argv it runs: refused by name.
PORTABLE_FEED_KINDS = frozenset({FeedKind.HTTP_JSON.value, FeedKind.PROMETHEUS.value, FeedKind.PUSH.value})
RECIPE_KEYS = frozenset({"version", "workspace_id", "monitor_id", "withdrawn", "manifest"})
RECIPE_VERSION = 1
#: A manifest at its own bound plus the envelope.
MAX_RECIPE_DOCUMENT_BYTES = MAXIMUM_MANIFEST_BYTES + 1024
#: The publish artifact kind; ``SyncFamily.LENS_RECIPE`` takes this value when realm sync is wired.
SYNC_KIND = "lens_recipe"


class RecipeRefusal(str, Enum):
    """Why a recipe document, or a verb over one, is refused. The value is the wire reason."""

    #: A feed kind outside :data:`PORTABLE_FEED_KINDS` (``detail`` names the feed).
    NOT_PORTABLE = "recipe_not_portable"
    #: Not the closed document shape, or its manifest does not read (``detail`` names the field).
    INVALID = "recipe_invalid"
    #: The document's ``workspace_id`` / ``monitor_id`` are not its folder and file name, or its
    #: manifest is another monitor's.
    MISFILED = "recipe_misfiled"
    NOT_FOUND = "recipe_not_found"
    WITHDRAWN = "recipe_withdrawn"
    #: A monitor with no workspace has no shelf to be shared on; no workspace is active to list or add in.
    NEEDS_WORKSPACE = "recipe_needs_workspace"
    #: Another monitor of this workspace already shares under this recipe id (ids that differ
    #: only in characters a file name cannot carry).
    ID_TAKEN = "recipe_id_taken"
    #: The whole-document class's own refusals (``realm_sync.document_family``), spelled by its constants.
    UNREADABLE_DOCUMENT = REFUSAL_UNREADABLE_DOCUMENT
    NOT_AN_OBJECT = REFUSAL_NOT_AN_OBJECT
    MISSING_VERSION = REFUSAL_MISSING_VERSION
    TOO_LARGE = REFUSAL_TOO_LARGE
    #: A shelf file listed and then gone before it was read (the family's ``unreadable_reason``).
    UNREADABLE = "lens_recipe_unreadable"


_MESSAGES = {
    RecipeRefusal.NOT_PORTABLE.value: "A recipe may only carry http_json, prometheus and push sources.",
    RecipeRefusal.INVALID.value: "The recipe document is not a valid shared recipe.",
    RecipeRefusal.MISFILED.value: "The recipe document is not filed under its own workspace and monitor.",
    RecipeRefusal.NOT_FOUND.value: "This workspace shares no recipe of that id.",
    RecipeRefusal.WITHDRAWN.value: "The recipe is no longer shared.",
    RecipeRefusal.NEEDS_WORKSPACE.value: "A recipe is shared with a workspace, and none is named or active.",
    RecipeRefusal.ID_TAKEN.value: "Another monitor of this workspace already shares under that recipe id.",
}


class RecipeDocumentError(LensRefusal, DocumentError):
    """A refused recipe: a :class:`LensRefusal` whose ``reason`` is a :class:`RecipeRefusal`, and the
    recipe family's ``DocumentError`` (``code`` is ``reason.value``, the string the whole-document
    class spends, which is why :class:`RecipeRefusal` also carries that class's own codes).
    ``detail`` names a field or feed, never a value."""

    messages = _MESSAGES
    reasons = RecipeRefusal
    refused_as = RefusalKind.CONFLICT
    not_found_reasons = frozenset({RecipeRefusal.NOT_FOUND})

    def __init__(self, code: RecipeRefusal | str, message: str | None = None, *, detail: str = "") -> None:
        LensRefusal.__init__(self, code, detail)
        DocumentError.__init__(self, self.reason.value, message)

    @property
    def summary(self) -> str:  # the reason's own sentence (``_MESSAGES``), not one per family
        return str(self)


class LensRecipePullSummary(DocumentPullSummary):
    """The recipe pull's accounting (``result["lens_recipe_sync"]`` once realm sync carries the
    family); tokens are ``<workspace>/<recipe>``."""

    __slots__ = ()


def read_recipe_document(parsed: dict[str, Any]) -> None:
    """The family's ``extra_check``: the closed shape, a manifest that reads and is this monitor's,
    and only portable sources. Raises :class:`RecipeDocumentError`."""

    if set(parsed) != RECIPE_KEYS or parsed["version"] != RECIPE_VERSION or not isinstance(parsed["withdrawn"], bool):
        raise RecipeDocumentError(RecipeRefusal.INVALID, detail="keys")
    try:
        opaque_id(parsed["workspace_id"])
        monitor_id = opaque_id(parsed["monitor_id"])
        manifest = None if parsed["withdrawn"] else read_manifest(parsed["manifest"])
    except WireError as exc:
        raise RecipeDocumentError(RecipeRefusal.INVALID, detail=exc.detail or exc.reason.value) from exc
    if manifest is None:
        if parsed["manifest"] is not None:
            raise RecipeDocumentError(RecipeRefusal.INVALID, detail="manifest")
        return
    if manifest["monitor_id"] != monitor_id:
        raise RecipeDocumentError(RecipeRefusal.MISFILED, detail="monitor_id")
    for feed in manifest["feeds"]:
        if feed["kind"] not in PORTABLE_FEED_KINDS:
            raise RecipeDocumentError(RecipeRefusal.NOT_PORTABLE, detail=feed["id"])


def recipe_token(workspace_id: str, recipe_id: str) -> str:
    """The family token of one recipe: ``<workspace token>/<recipe id>``. ``recipe_id`` is a
    monitor id or its own token (the tokenizer is idempotent)."""

    return f"{paths.safe_path_token(workspace_id)}/{paths.safe_path_token(recipe_id)}"


def filed_token(parsed: dict[str, Any]) -> str:
    """The token a checked document belongs under — what its own ``workspace_id`` and
    ``monitor_id`` say. A document found under any other token is ``recipe_misfiled``."""

    return recipe_token(parsed["workspace_id"], parsed["monitor_id"])


#: The recipe family: one document per ``(workspace, shared monitor)``.
LENS_RECIPE_FAMILY = DocumentFamily(
    noun="lens_recipe",
    published_prefix=f"store/{paths.LENS_RECIPES_DIRNAME}/",
    max_bytes=MAX_RECIPE_DOCUMENT_BYTES,
    error=RecipeDocumentError,
    messages=_MESSAGES,
    refusal_unreadable_local="unreadable_local_lens_recipe",
    refusal_unreadable_remote="unreadable_remote_lens_recipe",
    token_field="recipe_token",
    document_path=lambda token: paths.lens_recipe_path(*token.split("/", 1)),
    store_root=lambda: paths.lens_recipes_root(),
    baseline_path=lambda realm_id: paths.lens_recipe_baseline_path(realm_id),
    conflict_path=lambda realm_id, token: paths.lens_recipe_conflict_path(realm_id, *token.split("/", 1)),
    conflict_dir=lambda realm_id: paths.lens_recipe_conflicts_root(realm_id),
    summary_type=LensRecipePullSummary,
    sync_kind=SYNC_KIND,
    unreadable_reason=RecipeRefusal.UNREADABLE.value,
    extra_check=read_recipe_document,
    glob="*/*.json",
)


# --- the documents a share and a withdrawal write ----------------------------------


def _document(workspace_id: str, monitor_id: str, manifest: dict[str, Any] | None) -> bytes:
    return canonical_bytes({"version": RECIPE_VERSION, "workspace_id": workspace_id, "monitor_id": monitor_id,
                            "withdrawn": manifest is None, "manifest": manifest})


def recipe_document(workspace_id: str, manifest: dict[str, Any]) -> bytes:
    """The shelf bytes for a SEALED ``manifest`` — the manifest and its address, nothing else: no
    state, revision, credential value, Episode, receipt or route is read to build it."""

    return _document(workspace_id, manifest["monitor_id"], manifest)


def withdrawn_document(workspace_id: str, monitor_id: str) -> bytes:
    return _document(workspace_id, monitor_id, None)


class ShelfRecipe(NamedTuple):
    """One checked shelf document. ``manifest`` is canonical, or None when withdrawn; ``hash`` is
    the family's semantic document hash (what ``monitors.recipe_hash`` records)."""

    recipe_id: str
    workspace_id: str
    monitor_id: str
    manifest: dict[str, Any] | None
    hash: str

    @property
    def withdrawn(self) -> bool:
        return self.manifest is None


def _shelf_recipe(token: str, raw: bytes) -> ShelfRecipe:
    parsed = validate_document(LENS_RECIPE_FAMILY, raw)
    if filed_token(parsed) != token:
        raise RecipeDocumentError(RecipeRefusal.MISFILED, detail="path")
    manifest = None if parsed["withdrawn"] else read_manifest(parsed["manifest"])
    return ShelfRecipe(recipe_id=token.split("/", 1)[1], workspace_id=parsed["workspace_id"],
                       monitor_id=parsed["monitor_id"], manifest=manifest,
                       hash=document_hash(LENS_RECIPE_FAMILY, raw))


def read_recipe(workspace_id: str, recipe_id: str) -> ShelfRecipe:
    """One recipe of ``workspace_id``'s shelf; ``recipe_not_found`` when the shelf holds none."""

    token = recipe_token(workspace_id, recipe_id)
    raw = DocumentStore(LENS_RECIPE_FAMILY).read(token)
    if raw is None:
        raise RecipeDocumentError(RecipeRefusal.NOT_FOUND)
    return _shelf_recipe(token, raw)


def read_shelf(workspace_id: str) -> tuple[list[ShelfRecipe], list[dict[str, str]]]:
    """``(recipes, refused)`` for one workspace, by recipe id. A document that will not read, or
    is not filed where it says, is named in ``refused`` (``{recipe_id, reason}``), never listed."""

    store = DocumentStore(LENS_RECIPE_FAMILY)
    prefix = f"{paths.safe_path_token(workspace_id)}/"
    recipes: list[ShelfRecipe] = []
    refused: list[dict[str, str]] = []
    for token in store.list_tokens():
        if not token.startswith(prefix):
            continue
        raw = store.read(token)
        try:
            if raw is None:
                raise RecipeDocumentError(RecipeRefusal.UNREADABLE)
            recipes.append(_shelf_recipe(token, raw))
        except RecipeDocumentError as exc:
            refused.append({"recipe_id": token[len(prefix):], "reason": exc.reason.value})
    return recipes, refused


def write_recipe(raw: bytes) -> ShelfRecipe:
    """Store one recipe document through the family's door, under the token it names itself.
    Refused ``recipe_id_taken`` when that file holds another monitor's recipe."""

    token = filed_token(json.loads(raw))
    store = DocumentStore(LENS_RECIPE_FAMILY)
    entry = _shelf_recipe(token, raw)
    held = store.read(token)
    if held is not None:
        try:
            other = _shelf_recipe(token, held).monitor_id
        except RecipeDocumentError:
            other = entry.monitor_id  # an unreadable file is replaced, not protected
        if other != entry.monitor_id:
            raise RecipeDocumentError(RecipeRefusal.ID_TAKEN)
    store.write(token, raw)
    return entry


# --- what Add writes -----------------------------------------------------------------


def shared_ref_prefix(monitor_id: str) -> str:
    """The credential namespace of one recipe on the PC that adds it."""

    return f"shared:{monitor_id}:"


def localize(manifest: dict[str, Any]) -> dict[str, Any]:
    """``manifest`` as this PC may hold it as a DRAFT (plan decisions 3 and 4).

    * Every ``credential_ref`` is moved into the recipe's own namespace,
      ``shared:<monitor_id>:<ref>``: a name this PC's own monitors do not use, so an added recipe
      reads through no sign-in its person made for something else. A ref already in that
      namespace stays as it is, so an update of the recipe keeps the sign-in made for it (and the
      credential's saved address, ``lens.credentials``, still decides where it may go). A name
      past the id bound is refused (``invalid_string``), never cut.
    * ``automation.actions`` is removed: what a monitor may change alone on this PC is this PC's
      person's decision; without the list every change is a proposal."""

    doc = read_manifest(manifest)
    prefix = shared_ref_prefix(doc["monitor_id"])
    for feed in doc["feeds"]:
        ref = feed.get("credential_ref")
        if ref is not None and not ref.startswith(prefix):
            feed["credential_ref"] = opaque_id(prefix + ref)
    doc["automation"].pop("actions", None)
    return doc


# --- the derived row fields --------------------------------------------------------


def recipe_summary(manifest: dict[str, Any]) -> dict[str, Any]:
    """What a recipe asks of the PC that adds it, so Eternia does not parse a manifest."""

    def host(feed: dict[str, Any]) -> str | None:
        address = feed_address(feed)
        return None if address is None else address_parts(address)[1]

    return {
        "level": manifest["automation"]["level"],
        "sources": [{"feed_id": feed["id"], "kind": feed["kind"], "host": host(feed)} for feed in manifest["feeds"]],
        "scheduled": "schedule" in manifest,
        "needs_credentials": sorted({feed["credential_ref"] for feed in manifest["feeds"] if "credential_ref" in feed}),
        "private_network": any(is_private_reader(feed) for feed in manifest["feeds"]),
        "suggested_actions": list(manifest["automation"].get("actions", [])),
    }


class RecipeState(str, Enum):
    NOT_ADDED = "not_added"
    ADDED = "added"
    UPDATE_AVAILABLE = "update_available"
    WITHDRAWN = "withdrawn"


#: ``(the recipe is withdrawn, this PC's monitor of that id in the workspace)`` -> state, the
#: monitor being None (there is none), True (its ``recipe_hash`` is the shelf document's) or
#: False (it is not: another version, or a monitor that never met the shelf).
RECIPE_STATES: dict[tuple[bool, bool | None], RecipeState] = {
    (False, None): RecipeState.NOT_ADDED,
    (False, True): RecipeState.ADDED,
    (False, False): RecipeState.UPDATE_AVAILABLE,
    (True, None): RecipeState.WITHDRAWN,
    (True, True): RecipeState.WITHDRAWN,
    (True, False): RecipeState.WITHDRAWN,
}


def recipe_state(recipe: ShelfRecipe, monitor: dict[str, Any] | None) -> RecipeState:
    """``monitor``: this PC's monitor of the recipe's id IN the recipe's workspace, or None."""

    return RECIPE_STATES[recipe.withdrawn, None if monitor is None else monitor.get("recipe_hash") == recipe.hash]


class RecipeChange(str, Enum):
    SHARED = "shared"
    WITHDRAWN = "withdrawn"
    ADDED = "added"


def announce(recipe: ShelfRecipe, change: RecipeChange) -> None:
    """Append ``lens.recipe.changed`` for one shelf write or one Add; never raises."""

    from ..events import EventLog
    from ..store_events import emit_store_event

    emit_store_event(EventLog(), "lens.recipe.changed",
                     {"workspace_id": recipe.workspace_id, "recipe_id": recipe.recipe_id, "change": change.value},
                     domain="lens")
