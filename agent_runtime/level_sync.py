"""A workspace's LEVEL as a realm-syncable family — the fifth one.

**The ruling this implements** (owner, 2026-09-10, launcher R15): a Mission
Control workspace can have its own level, and *"realm sync sounds good, deploy"*
is the transport for setting a REALM's default workspace's level from the
launcher's map picker. The launcher's own note
(``EterniaLauncher/docs/spatial/subsystems/one-engine-one-catalogue-levels-per-workspace.md``,
"R15's office half LANDED … and its realm half did NOT") measured why the
launcher could not do this alone and named this change: the realm store's file
kinds are hermes's, an unknown path is DROPPED on pull
(``realm_sync._destination_for_sync_path`` → ``None``), and
``publish_realm_sync`` ``rmtree``s the realm subtree and rebuilds it from the
artifact list — so a file the launcher planted is deleted at the next publish.

**hermes does not read this document, and that is the contract.** The bytes are
the launcher's ``SceneSerializer`` output VERBATIM. This module validates
exactly two facts — it decodes as UTF-8 JSON, and the object carries a
``version`` — and stores what it was handed byte for byte. It does not
reformat, re-indent, re-key or renumber anything, because the day the backend's
level routes land (contract §6.2) the transport is supposed to be swappable
without a format change, and a hermes that had normalised the bytes would have
made itself a second author of a document it does not own.

**What "one document" buys.** Unlike the office (per-actor 3-way merge), a level
is ONE document, so it merges at whole-document granularity exactly like
``flow_graph_sync``: adopt when the member has nothing or an untouched copy,
converge when identical, KEEP LOCAL when only this machine edited, HOLD when
both diverged. Same shared classifier (:func:`sync_merge.classify_three_way_pull`),
same never-synced baseline sidecar, same loud conflict — no clock, no
last-writer-wins.

**Identity is the JSON VALUE, not the formatting.** The content hash parses and
re-serialises canonically before hashing, so an indentation or key-order
difference between two publishers converges instead of conflicting, while the
STORED bytes stay the ones their author wrote. That is the one place this module
looks at the document's shape, and it still needs no knowledge of the schema.
"""

from __future__ import annotations

from typing import Any

from . import paths
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
    "LEVEL_FAMILY",
    "LEVEL_PUBLISHED_PREFIX",
    "MAX_LEVEL_DOCUMENT_BYTES",
    "REFUSAL_MISSING_VERSION",
    "REFUSAL_NOT_AN_OBJECT",
    "REFUSAL_TOO_LARGE",
    "REFUSAL_UNREADABLE_DOCUMENT",
    "REFUSAL_UNREADABLE_LOCAL",
    "REFUSAL_UNREADABLE_REMOTE",
    "LevelDocumentError",
    "LevelPullSummary",
    "LevelStore",
    "apply_level_pull",
    "level_baseline_key",
    "level_document_hash",
    "level_document_row",
    "level_expectation_matches",
    "published_relative_path",
    "read_level_baseline",
    "read_remote_levels",
    "stored_level_sha256",
    "update_level_baseline_after_publish",
    "validate_level_document",
    "write_level_baseline",
]

#: Published subtree prefix for this family. Unknown to every older hermes:
#: ``_destination_for_sync_path`` answers ``None`` for it through the final
#: fallthrough, so an older member SKIPS the artifact rather than writing it
#: somewhere wrong. Degrading to "no level replication" is the whole
#: version-skew story, and it is the door the canvas projection walked through.
LEVEL_PUBLISHED_PREFIX = "store/levels/"

#: The launcher's own store bound (``LocalSceneStore.maxPayloadBytes``),
#: mirrored rather than exceeded. A document larger than this could not be
#: written by the store on the receiving end, so accepting it here would publish
#: something every member is guaranteed to refuse — and it would do it into a
#: git repo, where the cost is permanent. Refused loudly at both doors instead.
MAX_LEVEL_DOCUMENT_BYTES = 1024 * 1024

#: The LOCAL stored level exists and will not read. Refused rather than reported
#: absent: absent drives the ADOPT arm, and adopting over a file this machine
#: could not read would overwrite an environment nobody has seen.
REFUSAL_UNREADABLE_LOCAL = "unreadable_local_level"
#: A published level file that will not read on arrival.
REFUSAL_UNREADABLE_REMOTE = "unreadable_remote_level"

_REFUSAL_MESSAGES = {
    REFUSAL_UNREADABLE_DOCUMENT: "level document is not readable UTF-8 JSON",
    REFUSAL_NOT_AN_OBJECT: "level document is not a JSON object",
    REFUSAL_MISSING_VERSION: "level document carries no numeric version",
    REFUSAL_TOO_LARGE: "level document is larger than the store accepts",
    REFUSAL_UNREADABLE_LOCAL: "stored level is not a readable document",
    REFUSAL_UNREADABLE_REMOTE: "published level is not a readable document",
}


class LevelDocumentError(DocumentError):
    """A level document this runtime refuses to store or publish (typed ``code``)."""

    messages = _REFUSAL_MESSAGES


class LevelPullSummary(DocumentPullSummary):
    """The level pull's accounting, carried on a pull ack as
    ``result["level_sync"]`` — :class:`DocumentPullSummary`'s arms."""

    __slots__ = ()


#: The level family: one document per WORKSPACE, keyed by its token.
LEVEL_FAMILY = DocumentFamily(
    noun="level",
    published_prefix=LEVEL_PUBLISHED_PREFIX,
    max_bytes=MAX_LEVEL_DOCUMENT_BYTES,
    error=LevelDocumentError,
    messages=_REFUSAL_MESSAGES,
    refusal_unreadable_local=REFUSAL_UNREADABLE_LOCAL,
    refusal_unreadable_remote=REFUSAL_UNREADABLE_REMOTE,
    token_field="workspace_token",
    document_path=lambda token: paths.level_path(token),
    store_root=lambda: paths.levels_root(),
    baseline_path=lambda realm_id: paths.level_baseline_path(realm_id),
    conflict_path=lambda realm_id, token: paths.level_conflict_path(realm_id, token),
    summary_type=LevelPullSummary,
)


# --- the two facts hermes reads (``document_family``) -------------------------


def validate_level_document(raw: bytes) -> dict[str, Any]:
    """Refuse anything that is not a size-bounded JSON object with a ``version``.
    Returns the parsed object for the caller's accounting; never what is stored."""

    return validate_document(LEVEL_FAMILY, raw)


def level_document_hash(raw: bytes) -> str:
    """Semantic content hash of one level document — the merge key."""

    return document_hash(LEVEL_FAMILY, raw)


def stored_level_sha256(raw: bytes) -> str:
    """Hash of the STORED BYTES — the compare-and-set token, not the merge key."""

    return stored_sha256(raw)


def level_expectation_matches(stored: bytes | None, expect_sha256: str | None, *, provided: bool) -> bool:
    """Compare-and-set check (``document_family.expectation_matches``). The
    ``None`` arm is how a first write says *I believe I am authoring this
    workspace's level*."""

    return expectation_matches(stored, expect_sha256, provided=provided)


def level_document_row(
    workspace_id: str, raw: bytes | None, *, full: bool = False
) -> dict[str, Any]:
    """ONE level row, for every lane that reports a level.

    ``present: false`` is an honest empty, never an error — most workspaces
    never had a level applied.

    The CLI's ``level show``/``set`` and the RPC's ``runtime.level.get``/``set``
    both print it, and they print it from HERE rather than from two builders
    that happen to agree today: the launcher's store compares the ``sha256`` it
    read on one lane against the one it is handed on the other, so a key or a
    hash that differed between them would be a permanent false conflict.

    ``version`` is read for the CALLER's accounting only. A stored document that
    will not parse leaves it ``null`` and keeps the row — a level this runtime
    cannot read is a fact about the store, and ``full`` still hands the bytes
    over, which is the only way an operator repairs one.
    """

    row: dict[str, Any] = {
        "workspace_id": workspace_id,
        "workspace_token": paths.safe_path_token(workspace_id),
        "present": raw is not None,
        "bytes": len(raw) if raw is not None else 0,
        "sha256": stored_level_sha256(raw) if raw is not None else None,
        "version": None,
    }
    if raw is not None:
        try:
            row["version"] = validate_level_document(raw).get("version")
        except LevelDocumentError:
            row["version"] = None
    if full:
        row["document"] = raw.decode("utf-8", errors="replace") if raw is not None else None
    return row


def level_baseline_key(workspace_token: str) -> str:
    """This family's baseline key, namespaced like every sibling family's."""

    return LEVEL_FAMILY.baseline_key(workspace_token)


def published_relative_path(workspace_id: str) -> str:
    """Where one workspace's level is published inside a realm subtree.

    ONE spelling, and both the publish scan and the pull walk read it from here:
    the office family's ``store/office/<token>/…`` is assembled at three sites
    and they have to agree by inspection, which is the drift this avoids.
    """

    return f"{LEVEL_PUBLISHED_PREFIX}{paths.safe_path_token(workspace_id)}.json"


# --- the store door -----------------------------------------------------------


class LevelStore(DocumentStore):
    """Read and write one workspace's level document — THE door
    (``document_family.DocumentStore``). Absence is not an error: most
    workspaces never had a level applied. A clear is local; the realm's level
    comes back on the next pull."""

    family = LEVEL_FAMILY

    def list_workspace_tokens(self) -> list[str]:
        """Every workspace token this store holds a level for, sorted."""

        return self.list_tokens()


# --- baseline sidecar (never synced, never published) ------------------------


def read_level_baseline(realm_id: str) -> dict[str, str]:
    return read_document_baseline(LEVEL_FAMILY, realm_id)


def write_level_baseline(realm_id: str, entries: dict[str, str]) -> None:
    write_document_baseline(LEVEL_FAMILY, realm_id, entries)


def update_level_baseline_after_publish(realm_id: str, hashes: dict[str, str]) -> None:
    """Record the published levels' hashes as the new baseline, so a publisher's
    next pull is not handed a held environment over content nobody disagreed about."""

    update_document_baseline_after_publish(LEVEL_FAMILY, realm_id, hashes)


# --- pull: adopt, keep or HOLD — whole document, never merged ----------------


def read_remote_levels(subtree) -> tuple[dict[str, bytes], list[dict[str, str]]]:
    """Level bytes carried by a pulled realm subtree, keyed by workspace token;
    ``(levels, refused)`` — an unreadable file is refused by name, never omitted."""

    return read_remote_documents(LEVEL_FAMILY, subtree)


def apply_level_pull(realm_id: str, subtree) -> LevelPullSummary:
    """Adopt, keep or HOLD each pulled level — whole document, never merged.

    Runs inside ``pull_realm_sync`` AFTER the generic overwrite loop, which is
    what materialises ``store/workspaces/*``: a level is addressed BY a
    workspace, so landing one before its workspace record exists would leave an
    environment for a workspace nothing on this machine can name. It does NOT
    gate on the workspace existing, though — the generic loop already ran, and
    refusing a level because a workspace record failed to arrive would discard
    the operator's environment over somebody else's failure.

    **Order against the office is deliberate and is a no-op by design.** R7 says
    a level is the ENVIRONMENT and the office's actors are the CONTENTS placed on
    it, stored separately and never merged; neither applier reads the other's
    files, so this runs beside the office rather than inside its ordering
    argument.
    """

    return apply_document_pull(LEVEL_FAMILY, realm_id, subtree)  # type: ignore[return-value]
