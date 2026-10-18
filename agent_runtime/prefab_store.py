"""USER PREFABS -- a profile's shelf of saved group fragments, stored verbatim.

Owner ruling 2026-09-30 (``EterniaLauncher/docs/spatial/planned/
SPATIAL_QUEUE_RULINGS_2026-09-30.md``): a user prefab store beside saved maps,
per profile. The launcher's ``UserPrefabStore`` port
(``EterniaLauncher/lib/core/spatial/editor/prefabs/user_prefab.dart``) has a
SharedPreferences implementation; this is the store its hermes implementation
binds, through ``runtime.prefab.*`` (``agent_runtime/serve_rpc/prefab.py``).

**What a prefab IS here.** The launcher's own wire, one document per prefab:
``{v, id, label, savedAt, document}`` where ``document`` is the v9 FRAGMENT
scene document. hermes reads four facts -- UTF-8 JSON, an object, a non-empty
string ``label``, an object ``document`` -- and stores the bytes it was handed.
Keyed by ``(profile, prefab_id)``: the profile is the launcher's profile key and
the id is the launcher-minted one; neither is re-derived from the bytes.

**Realm-synced** (design-sweep-d2 § D2.12) as the third whole-document family
on ``realm_sync/document_family.py``: :data:`PREFAB_FAMILY` is one descriptor,
published at ``store/prefabs/<profile>/<prefab>.json``, so a profile's shelf
follows the profile NAME across machines (owner ruling 2026-10-10). Adopt, keep
or HOLD per prefab; ``upstream_absent`` never deletes; no revert arm. A profile
the peer does not have gets the files, and nothing reads them until it does.
"""

from __future__ import annotations

import hashlib
from typing import Any

from . import paths
from .realm_sync.document_family import (
    DocumentError,
    DocumentFamily,
    DocumentPullSummary,
    apply_document_pull,
    document_hash,
    read_document_baseline,
    update_document_baseline_after_publish,
    validate_document,
)
from .realm_sync.families import SyncFamily

__layer__ = "stores"

#: The map catalogue's bound: a fragment is a slice of one scene document.
MAX_PREFAB_DOCUMENT_BYTES = 1024 * 1024

REFUSAL_UNREADABLE_DOCUMENT = "unreadable_document"
REFUSAL_NOT_AN_OBJECT = "not_an_object"
#: No non-empty string ``label`` -- the shelf's caption and the label rule's subject.
REFUSAL_LABEL_INVALID = "label_invalid"
#: No object ``document`` -- nothing a drop could lay.
REFUSAL_FRAGMENT_MISSING = "fragment_missing"
REFUSAL_TOO_LARGE = "document_too_large"
#: Another prefab on this profile's shelf already holds the label (case-folded,
#: stripped) -- the launcher's own rule. Asked by the authoring verb, never by
#: :func:`validate_prefab_document`: the bytes alone cannot answer it.
REFUSAL_LABEL_TAKEN = "label_taken"
#: The LOCAL stored prefab exists and will not read (the pull refuses rather
#: than adopting over a file nobody has seen).
REFUSAL_UNREADABLE_LOCAL = "unreadable_local_prefab"
#: A published prefab file that will not read on arrival.
REFUSAL_UNREADABLE_REMOTE = "unreadable_remote_prefab"

_MESSAGES = {
    REFUSAL_UNREADABLE_DOCUMENT: "prefab document is not readable UTF-8 JSON",
    REFUSAL_NOT_AN_OBJECT: "prefab document is not a JSON object",
    REFUSAL_LABEL_INVALID: "prefab document carries no non-empty label",
    REFUSAL_FRAGMENT_MISSING: "prefab document carries no fragment document object",
    REFUSAL_TOO_LARGE: "prefab document is larger than the store accepts",
    REFUSAL_UNREADABLE_LOCAL: "stored prefab is not a readable document",
    REFUSAL_UNREADABLE_REMOTE: "published prefab is not a readable document",
}


class PrefabDocumentError(DocumentError):
    """A prefab document this runtime refuses to store; ``code`` is the typed reason."""

    messages = _MESSAGES


class PrefabPullSummary(DocumentPullSummary):
    """The prefab pull's accounting, carried on a pull ack as
    ``result["prefab_sync"]``; tokens are ``<profile>/<prefab>``."""

    __slots__ = ()


def _require_label_and_fragment(parsed: dict[str, Any]) -> None:
    """The prefab's facts past "a JSON object": a non-empty ``label`` and an
    object ``document`` (hermes does not read the launcher's ``v``)."""

    label = parsed.get("label")
    if not isinstance(label, str) or not label.strip():
        raise PrefabDocumentError(REFUSAL_LABEL_INVALID)
    if not isinstance(parsed.get("document"), dict):
        raise PrefabDocumentError(REFUSAL_FRAGMENT_MISSING)


def _split_token(token: str) -> tuple[str, str]:
    profile, _, prefab_id = token.partition("/")
    return profile, prefab_id


#: The prefab family: one document per ``(profile, prefab)``, token ``<profile>/<prefab>``.
PREFAB_FAMILY = DocumentFamily(
    noun="prefab",
    published_prefix="store/prefabs/",
    max_bytes=MAX_PREFAB_DOCUMENT_BYTES,
    error=PrefabDocumentError,
    messages=_MESSAGES,
    refusal_unreadable_local=REFUSAL_UNREADABLE_LOCAL,
    refusal_unreadable_remote=REFUSAL_UNREADABLE_REMOTE,
    token_field="prefab_token",
    document_path=lambda token: paths.prefab_path(*_split_token(token)),
    store_root=lambda: paths.prefab_shelves_root(),
    baseline_path=lambda realm_id: paths.prefab_baseline_path(realm_id),
    conflict_path=lambda realm_id, token: paths.prefab_conflict_path(realm_id, *_split_token(token)),
    conflict_dir=lambda realm_id: paths.prefab_conflicts_root(realm_id),
    summary_type=PrefabPullSummary,
    sync_kind=SyncFamily.PREFAB,
    unreadable_reason="prefab_unreadable",
    extra_check=_require_label_and_fragment,
    require_version=False,
    glob="*/*.json",
)


def validate_prefab_document(raw: bytes) -> dict[str, Any]:
    """The parsed object, for the caller's accounting. Never what gets stored."""

    return validate_document(PREFAB_FAMILY, raw)


def prefab_document_hash(raw: bytes) -> str:
    """Semantic content hash (canonical JSON) — the pull's MERGE key, apart from
    :func:`stored_prefab_sha256`, the compare-and-set token (maps keep the same
    distinction)."""

    return document_hash(PREFAB_FAMILY, raw)


def prefab_token(profile: str, prefab_id: str) -> str:
    """The family token for one prefab: ``<profile token>/<prefab token>``."""

    return f"{paths.safe_path_token(profile)}/{paths.safe_path_token(prefab_id)}"


def read_prefab_baseline(realm_id: str) -> dict[str, str]:
    return read_document_baseline(PREFAB_FAMILY, realm_id)


def update_prefab_baseline_after_publish(realm_id: str, hashes: dict[str, str]) -> None:
    update_document_baseline_after_publish(PREFAB_FAMILY, realm_id, hashes)


def apply_prefab_pull(realm_id: str, subtree) -> PrefabPullSummary:
    """Adopt, keep or HOLD each pulled prefab — whole document, never merged."""

    return apply_document_pull(PREFAB_FAMILY, realm_id, subtree)  # type: ignore[return-value]


def stored_prefab_sha256(raw: bytes) -> str:
    """Hash of the STORED BYTES -- the compare-and-set token."""

    return hashlib.sha256(raw).hexdigest()


def prefab_expectation_matches(stored: bytes | None, expect_sha256: str | None, *, provided: bool) -> bool:
    """The map family's three states: unconditional, "nothing stored", or the stored bytes' sha."""

    if not provided:
        return True
    current = stored_prefab_sha256(stored) if stored is not None else None
    if expect_sha256 is None:
        return current is None
    return current is not None and current.lower() == str(expect_sha256).lower()


def prefab_document_row(profile: str, prefab_id: str, raw: bytes | None, *, full: bool = False) -> dict[str, Any]:
    """ONE prefab row for every verb; ``label`` / ``saved_at`` null when the bytes will not parse."""

    row: dict[str, Any] = {
        "profile": profile,
        "prefab_id": prefab_id,
        "prefab_token": paths.safe_path_token(prefab_id),
        "present": raw is not None,
        "bytes": len(raw) if raw is not None else 0,
        "sha256": stored_prefab_sha256(raw) if raw is not None else None,
        "label": None,
        "saved_at": None,
    }
    if raw is not None:
        try:
            parsed = validate_prefab_document(raw)
        except PrefabDocumentError:
            parsed = None
        if parsed is not None:
            row["label"] = parsed["label"]
            saved_at = parsed.get("savedAt")
            row["saved_at"] = saved_at if isinstance(saved_at, str) else None
    if full:
        row["document"] = raw.decode("utf-8", errors="replace") if raw is not None else None
    return row


class PrefabStore:
    """Read, write, clear and list one profile's shelf. THE door for ``runtime.prefab.*``."""

    def __init__(self, profile: str) -> None:
        self.profile = profile

    def read(self, prefab_id: str) -> bytes | None:
        path = paths.prefab_path(self.profile, prefab_id)
        try:
            return path.read_bytes() if path.is_file() else None
        except OSError:
            return None

    def write(self, prefab_id: str, raw: bytes) -> dict[str, Any]:
        """Store ``raw`` VERBATIM (bytes: no line-ending translation) after validating it."""

        from utils import atomic_write_bytes

        validate_prefab_document(raw)
        path = paths.prefab_path(self.profile, prefab_id)
        if self.read(prefab_id) == raw:
            return {"path": path, "changed": False}
        atomic_write_bytes(path, raw)
        return {"path": path, "changed": True}

    def clear(self, prefab_id: str) -> dict[str, Any]:
        """Delete one prefab; ``changed: False`` when none was there (idempotent for a retry)."""

        path = paths.prefab_path(self.profile, prefab_id)
        existed = path.is_file()
        try:
            path.unlink(missing_ok=True)
        except OSError:
            if path.is_file():
                raise
            existed = False
        return {"path": path, "changed": existed}

    def list_prefab_tokens(self) -> list[str]:
        root = paths.prefabs_root(self.profile)
        if not root.is_dir():
            return []
        return sorted(path.stem for path in root.glob("*.json") if path.is_file())

    def label_holder(self, prefab_id: str, raw: bytes) -> str | None:
        """The OTHER prefab on this shelf already holding ``raw``'s label, or ``None``.

        A prefab keeping its own label is never taken (its own token is skipped);
        an unreadable stored prefab is skipped rather than allowed to refuse a write.
        """

        wanted = str(validate_prefab_document(raw)["label"]).strip().casefold()
        mine = paths.safe_path_token(prefab_id)
        for token in self.list_prefab_tokens():
            if token == mine:
                continue
            other = self.read(token)
            if other is None:
                continue
            try:
                label = str(validate_prefab_document(other)["label"]).strip().casefold()
            except PrefabDocumentError:
                continue
            if label == wanted:
                return token
        return None
