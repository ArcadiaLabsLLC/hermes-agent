"""The MAP CATALOGUE as a realm-syncable family — the level family's sibling.

**The report this implements** (owner, 2026-09-22): one workspace read
``flat grass test level v4 · yours`` on the Windows box and ``unnamed · yours``
on the Mac after a realm pull. Both machines resolved ``WorkspaceLevelSlotOwned``,
so the level DOCUMENT and its ownership survived the pull intact — only the NAME
was lost. The caption's name is ``displayName``, which the launcher's
``workspace_level_slot.dart`` resolves from the ``SavedMapId`` in the level's
sidecar against the LOCAL catalogue and leaves null when the sidecar names a map
the catalogue no longer holds. On the Mac it never held it, because that
catalogue (``LocalLevelCatalog``) is SharedPreferences-backed and machine-local.

So this is the exact swap ``level_sync`` made one family over, for the same
reason and in the same shape: one more machine-local store behind a document the
realm now carries.

**Why a catalogue family rather than storing the name in the sidecar.** The
launcher's own note argues it by name — *"Resolved, not stored … a second copy
of the label would be free to disagree"*. The sidecar keeps storing only the
``SavedMapId``; what changes is that the catalogue it resolves against is no
longer one machine's preferences file.

**What a map IS here.** A ``MapDescriptor {id, name, origin, savedAt}`` and its
``SceneDocument``, stored as ONE document per map, verbatim. hermes reads three
facts from the bytes — it is UTF-8 JSON, the object carries a numeric
``version``, and it carries a non-empty string ``name`` — and stores what it was
handed byte for byte. The ``name`` is the one fact this family reads that the
level family does not, and it is read because the name is the ENTIRE defect this
family exists to close: a catalogue entry with no name resolves to ``unnamed``
on arrival exactly like no entry at all, so accepting one would publish the bug.

**Addressed by MAP ID, not by workspace.** That is the one structural difference
from ``level_sync`` and it reaches two places. The store keys on the map id (the
launcher's ``SavedMapId``, which is what the level's sidecar stores), and the
publish scan has NO realm filter: a level is addressed BY a workspace and a
workspace belongs to a realm, but a map id belongs to nothing smaller than the
install, so there is no id set to filter against. A realm carries the whole
catalogue. The cost is named rather than hidden — a member pulls maps it has no
workspace standing on — and it is the cheaper half of the trade, because the
alternative is a catalogue that is missing exactly the entry the incoming level
names, which is the reported defect.

Everything else is the level family verbatim: one document, whole-document
three-way merge through :func:`sync_merge.classify_three_way_pull`, a
never-synced baseline sidecar, a loud HOLD with a parked copy, and a content hash
taken over the canonical re-serialisation so two publishers whose serializers
differ only in whitespace converge instead of conflicting while the STORED bytes
stay the ones their author wrote.
"""

from __future__ import annotations

from typing import Any

from . import paths
from .realm_sync.families import SyncFamily
from .realm_sync.document_family import (
    REFUSAL_MISSING_VERSION,
    REFUSAL_NOT_AN_OBJECT,
    REFUSAL_TOO_LARGE,
    REFUSAL_UNREADABLE_DOCUMENT,
    DocumentError,
    DocumentFamily,
    DocumentPullSummary,
    DocumentStore,
    apply_document_pull,
    document_hash,
    expectation_matches,
    read_document_baseline,
    read_remote_documents,
    stored_sha256,
    update_document_baseline_after_publish,
    validate_document,
    write_document_baseline,
)

__layer__ = "stores"

__all__ = [
    "MAP_FAMILY",
    "MAP_PUBLISHED_PREFIX",
    "MAX_MAP_DOCUMENT_BYTES",
    "REFUSAL_MISSING_VERSION",
    "REFUSAL_NAME_INVALID",
    "REFUSAL_NAME_TAKEN",
    "REFUSAL_NOT_AN_OBJECT",
    "REFUSAL_TOO_LARGE",
    "REFUSAL_UNREADABLE_DOCUMENT",
    "REFUSAL_UNREADABLE_LOCAL",
    "REFUSAL_UNREADABLE_REMOTE",
    "MapDocumentError",
    "MapPullSummary",
    "MapStore",
    "apply_map_pull",
    "map_baseline_key",
    "map_document_hash",
    "map_document_row",
    "map_expectation_matches",
    "map_name_holder",
    "published_relative_path",
    "read_map_baseline",
    "read_remote_maps",
    "stored_map_sha256",
    "update_map_baseline_after_publish",
    "validate_map_document",
    "write_map_baseline",
]

#: Published subtree prefix for this family. Unknown to every older hermes:
#: ``_destination_for_sync_path`` answers ``None`` for it through the final
#: fallthrough, so an older member SKIPS the artifact rather than writing it
#: somewhere wrong. Degrading to "no catalogue replication" leaves that member
#: exactly where it is today — which is the defect, not a regression.
MAP_PUBLISHED_PREFIX = "store/maps/"

#: The same store bound the level family mirrors, for the same reason: a map
#: document IS a scene document plus a descriptor, and the launcher's store
#: refuses anything larger on the receiving end.
MAX_MAP_DOCUMENT_BYTES = 1024 * 1024

#: No non-empty string ``name``. THIS family's extra arm, and the reason it
#: exists is the report: a catalogue entry whose name is absent resolves to
#: ``unnamed`` on arrival exactly as a missing entry does, so storing one would
#: publish the defect rather than fix it.
#:
#: The SPELLING is lane LM's, pinned across the two repos: the launcher maps
#: ``name_invalid`` to a typed failure, and a missing name and a blank one are
#: one fact to it because the caption they produce is the same.
REFUSAL_NAME_INVALID = "name_invalid"

#: Another map already holds this name. NOT a document-shape refusal — the bytes
#: are fine and the document alone cannot answer it — so it is deliberately not
#: raised by :func:`validate_map_document`. See :func:`map_name_holder` for where
#: it IS asked and, more importantly, where it is not.
REFUSAL_NAME_TAKEN = "name_taken"
#: The LOCAL stored map exists and will not read. Refused rather than reported
#: absent: absent drives the ADOPT arm, and adopting over a file this machine
#: could not read would overwrite a catalogue entry nobody has seen.
REFUSAL_UNREADABLE_LOCAL = "unreadable_local_map"
#: A published map file that will not read on arrival.
REFUSAL_UNREADABLE_REMOTE = "unreadable_remote_map"

_REFUSAL_MESSAGES = {
    REFUSAL_UNREADABLE_DOCUMENT: "map document is not readable UTF-8 JSON",
    REFUSAL_NOT_AN_OBJECT: "map document is not a JSON object",
    REFUSAL_MISSING_VERSION: "map document carries no numeric version",
    REFUSAL_NAME_INVALID: "map document carries no non-empty name",
    REFUSAL_NAME_TAKEN: "another map already holds this name",
    REFUSAL_TOO_LARGE: "map document is larger than the store accepts",
    REFUSAL_UNREADABLE_LOCAL: "stored map is not a readable document",
    REFUSAL_UNREADABLE_REMOTE: "published map is not a readable document",
}


class MapDocumentError(DocumentError):
    """A map document this runtime refuses to store or publish (typed ``code``,
    for ``LevelDocumentError``'s reason)."""

    messages = _REFUSAL_MESSAGES


class MapPullSummary(DocumentPullSummary):
    """The map pull's accounting, carried on a pull ack as ``result["map_sync"]``
    — :class:`DocumentPullSummary`'s arms. ``upstream_absent`` is never a delete,
    and here that ruling is the FIX: a catalogue entry silently removed on pull
    is the ``unnamed`` caption the owner reported."""

    __slots__ = ()


def _require_name(parsed: dict[str, Any]) -> None:
    """THIS family's extra fact: a non-empty string ``name``."""

    name = parsed.get("name")
    if not isinstance(name, str) or not name.strip():
        raise MapDocumentError(REFUSAL_NAME_INVALID)


#: The map family: one document per MAP ID (the launcher's ``SavedMapId``).
MAP_FAMILY = DocumentFamily(
    noun="map",
    published_prefix=MAP_PUBLISHED_PREFIX,
    max_bytes=MAX_MAP_DOCUMENT_BYTES,
    error=MapDocumentError,
    messages=_REFUSAL_MESSAGES,
    refusal_unreadable_local=REFUSAL_UNREADABLE_LOCAL,
    refusal_unreadable_remote=REFUSAL_UNREADABLE_REMOTE,
    token_field="map_token",
    document_path=lambda token: paths.map_path(token),
    store_root=lambda: paths.maps_root(),
    baseline_path=lambda realm_id: paths.map_baseline_path(realm_id),
    conflict_path=lambda realm_id, token: paths.map_conflict_path(realm_id, token),
    conflict_dir=lambda realm_id: paths.realm_sync_root() / paths.safe_path_token(realm_id) / "map_conflicts",
    sync_kind=SyncFamily.MAP,
    unreadable_reason="map_unreadable",
    summary_type=MapPullSummary,
    extra_check=_require_name,
)


# --- the three facts hermes reads (``document_family``) -----------------------


def validate_map_document(raw: bytes) -> dict[str, Any]:
    """Refuse anything that is not a size-bounded JSON object with ``version``
    and a non-empty ``name``. Returns the parsed object for the caller's
    accounting; never what is stored."""

    return validate_document(MAP_FAMILY, raw)


def map_document_hash(raw: bytes) -> str:
    """Semantic content hash of one map document — the MERGE key."""

    return document_hash(MAP_FAMILY, raw)


def stored_map_sha256(raw: bytes) -> str:
    """Hash of the STORED BYTES — the compare-and-set token, not the merge key."""

    return stored_sha256(raw)


def map_expectation_matches(stored: bytes | None, expect_sha256: str | None, *, provided: bool) -> bool:
    """Compare-and-set check (``document_family.expectation_matches``); the
    ``None`` arm catches two machines minting the same map id at once."""

    return expectation_matches(stored, expect_sha256, provided=provided)


def map_document_row(map_id: str, raw: bytes | None, *, full: bool = False) -> dict[str, Any]:
    """ONE map row, for every lane that reports a map.

    The CLI's ``map show``/``set`` and the RPC's ``runtime.map.get``/``.set``
    print it from HERE rather than from two builders that happen to agree today:
    the launcher's catalogue compares the ``sha256`` it read on one lane against
    the one it is handed on the other, so a key or a hash that differed between
    them would be a permanent false conflict.

    ``name`` and ``version`` are read for the CALLER's accounting only — and
    ``name`` is what the whole family is for, so it is on the DESCRIPTOR row
    that ``runtime.map.list`` returns without any document bytes. A stored
    document that will not parse leaves both ``null`` and keeps the row: a map
    this runtime cannot read is a fact about the store, and ``full`` still hands
    the bytes over, which is the only way an operator repairs one.
    """

    row: dict[str, Any] = {
        "map_id": map_id,
        "map_token": paths.safe_path_token(map_id),
        "present": raw is not None,
        "bytes": len(raw) if raw is not None else 0,
        "sha256": stored_map_sha256(raw) if raw is not None else None,
        "version": None,
        "name": None,
    }
    if raw is not None:
        try:
            parsed = validate_map_document(raw)
        except MapDocumentError:
            parsed = None
        if parsed is not None:
            row["version"] = parsed.get("version")
            row["name"] = parsed.get("name")
    if full:
        row["document"] = raw.decode("utf-8", errors="replace") if raw is not None else None
    return row


def map_name_holder(map_id: str, raw: bytes) -> str | None:
    """The OTHER map already holding this document's name, or ``None``.

    **Not a document-shape fact, and deliberately not part of
    :func:`validate_map_document`.** The bytes alone cannot answer it — it is a
    question about the rest of the catalogue — and the distinction decides where
    it may be asked:

    - **Asked** on the AUTHORING door, ``runtime.map.set`` (the argv ``harness
      map set`` was deleted 2026-10-02), where the launcher's picker is naming a
      map and two entries called "island" make the catalogue useless for the one
      job it has. Lane LM maps the refusal to a typed failure by the reason
      string ``name_taken``.
    - **Never asked** on the pull applier or the publish scan. A realm can carry
      two same-named maps — two machines named a scene the same thing before
      they ever met — and refusing one on arrival would DELETE a peer's
      catalogue entry to enforce a label. The whole family exists because a
      catalogue entry went missing on a second machine; reproducing that to
      protect uniqueness would be the defect wearing a validator's hat. The
      collision lands, both entries keep their ids, and the next authoring write
      on either machine is the one that has to resolve it.

    A map keeping its own name is never taken: ``map_id`` is excluded, so a
    re-save or a scene edit under an unchanged name passes. Compared on the
    stripped, case-folded name, because two captions that differ only in case or
    padding are the same caption to the operator reading them.

    Assumes ``raw`` has been validated; an unparseable stored map is skipped
    rather than allowed to refuse somebody else's write.
    """

    wanted = str(validate_map_document(raw).get("name", "")).strip().casefold()
    if not wanted:
        return None
    store = MapStore()
    mine = paths.safe_path_token(map_id)
    for token in store.list_map_tokens():
        if token == mine:
            continue
        other = store.read(token)
        if other is None:
            continue
        try:
            name = str(validate_map_document(other).get("name", "")).strip().casefold()
        except MapDocumentError:
            continue
        if name == wanted:
            return token
    return None


def map_baseline_key(map_token: str) -> str:
    """This family's baseline key, namespaced like every sibling family's."""

    return MAP_FAMILY.baseline_key(map_token)


def published_relative_path(map_id: str) -> str:
    """Where one map is published inside a realm subtree.

    ONE spelling, read by both the publish scan and the pull walk.
    """

    return f"{MAP_PUBLISHED_PREFIX}{paths.safe_path_token(map_id)}.json"


# --- the store door -----------------------------------------------------------


class MapStore(DocumentStore):
    """Read, write, clear and list the map catalogue — THE door
    (``document_family.DocumentStore``). **A clear is local**: a cleared map the
    realm still publishes comes back on the next pull, and that matters MORE
    here — a catalogue entry deleted on one machine is the reported defect."""

    family = MAP_FAMILY

    def list_map_tokens(self) -> list[str]:
        """Every map token this store holds, sorted."""

        return self.list_tokens()


# --- baseline sidecar (never synced, never published) ------------------------


def read_map_baseline(realm_id: str) -> dict[str, str]:
    return read_document_baseline(MAP_FAMILY, realm_id)


def write_map_baseline(realm_id: str, entries: dict[str, str]) -> None:
    write_document_baseline(MAP_FAMILY, realm_id, entries)


def update_map_baseline_after_publish(realm_id: str, hashes: dict[str, str]) -> None:
    """Record the published maps' hashes as the new baseline, so a publisher's
    next pull is not handed a held catalogue."""

    update_document_baseline_after_publish(MAP_FAMILY, realm_id, hashes)


# --- pull: adopt, keep or HOLD — whole document, never merged ----------------


def read_remote_maps(subtree) -> tuple[dict[str, bytes], list[dict[str, str]]]:
    """Map bytes carried by a pulled realm subtree, keyed by map token;
    ``(maps, refused)`` — an unreadable file is refused by name, never omitted."""

    return read_remote_documents(MAP_FAMILY, subtree)


def apply_map_pull(realm_id: str, subtree) -> MapPullSummary:
    """Adopt, keep or HOLD each pulled map — whole document, never merged.

    Runs inside ``pull_realm_sync`` beside :func:`level_sync.apply_level_pull`,
    and unlike that one it has NO ordering argument against the workspace
    records: a map is not addressed by a workspace. It is ordered against the
    level pull only in the sense that both must land before the launcher
    resolves a caption, and neither reads the other's files — a level's sidecar
    names a map id, and resolving that name is the LAUNCHER's step, not this
    module's.
    """

    return apply_document_pull(MAP_FAMILY, realm_id, subtree)  # type: ignore[return-value]
