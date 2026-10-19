"""The WHOLE-DOCUMENT realm-sync family — one class, a descriptor per family.

Design: ``docs/agent-runtime-harness/planned/design-sweep-d2-2026-10-10.md``
§ D2.12. ``level_sync`` and ``map_sync`` were the same module twice; a third
family (prefab) would have been the third copy, so the class lives here and
each family is a :class:`DocumentFamily` descriptor plus its own row builder
and wire names.

**The class.** One document per entity, stored VERBATIM (hermes validates a
few facts and never rewrites the bytes), merged at whole-document granularity
through :func:`sync_merge.classify_three_way_pull`: adopt when the member has
nothing or an untouched copy, converge when identical, KEEP LOCAL when only
this machine edited, HOLD (local untouched, remote parked in a conflict
sidecar) when both diverged. A never-synced baseline sidecar per realm. No
revert arm here, and ``upstream_absent`` is NEVER a delete. Identity is the
JSON VALUE (:func:`document_hash`, canonical re-serialisation) so two
publishers differing only in whitespace converge; the compare-and-set token is
the STORED BYTES' hash (:func:`stored_sha256`), because the semantic hash would
call a re-serialisation a no-op and let a lost update through.

**Paths are read at call time.** A descriptor holds callables that resolve
``paths.*`` when called, never a resolved ``Path`` — ``HERMES_HOME`` is a
call-time fact.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, NamedTuple

from .models import RealmSyncArtifact

__layer__ = "stores"

__all__ = [
    "REFUSAL_MISSING_VERSION",
    "REFUSAL_NOT_AN_OBJECT",
    "REFUSAL_TOO_LARGE",
    "REFUSAL_UNREADABLE_DOCUMENT",
    "DocumentError",
    "DocumentFamily",
    "DocumentPublishScan",
    "DocumentPullSummary",
    "DocumentStore",
    "apply_document_pull",
    "document_hash",
    "document_publish_scan",
    "document_status_row",
    "expectation_matches",
    "read_document_baseline",
    "read_remote_documents",
    "stored_sha256",
    "update_document_baseline_after_publish",
    "validate_document",
    "write_document_baseline",
]

#: The bytes are not UTF-8, or not JSON at all.
REFUSAL_UNREADABLE_DOCUMENT = "unreadable_document"
#: Valid JSON, but not an object — so it cannot carry a ``version``.
REFUSAL_NOT_AN_OBJECT = "not_an_object"
#: No numeric ``version`` — the one schema fact every store on the other end gates on.
REFUSAL_MISSING_VERSION = "missing_version"
#: Over the family's ``max_bytes``.
REFUSAL_TOO_LARGE = "document_too_large"


class DocumentError(ValueError):
    """A document this runtime refuses to store or publish. Each family raises
    its own subclass (``LevelDocumentError``, ``MapDocumentError``) carrying the
    typed ``code`` every caller spends — the CLI's exit taxonomy, the publish
    scan's refusal list, the pull's per-entity isolation."""

    messages: Mapping[str, str] = {}

    def __init__(self, code: str, message: str | None = None):
        super().__init__(message or self.messages.get(code, code))
        self.code = code


@dataclass(frozen=True, slots=True)
class DocumentFamily:
    """One whole-document family. Everything family-specific the class needs."""

    #: ``"level"`` / ``"map"`` — the baseline key namespace (``<noun>:<token>``).
    noun: str
    #: Published subtree prefix, e.g. ``store/levels/``.
    published_prefix: str
    #: The receiving store's bound; larger is refused at both doors.
    max_bytes: int
    #: The family's :class:`DocumentError` subclass.
    error: type[DocumentError]
    #: Code -> sentence, for refusals named by code.
    messages: Mapping[str, str]
    #: ``unreadable_local_<noun>`` / ``unreadable_remote_<noun>``.
    refusal_unreadable_local: str
    refusal_unreadable_remote: str
    #: The conflict sidecar's token key (``workspace_token`` / ``map_token``).
    token_field: str
    #: Call-time path resolvers. A TOKEN is the document's path relative to
    #: ``store_root`` (and to the published prefix) without ``.json``, ``/``-joined:
    #: ``<workspace>`` for a level, ``<profile>/<prefab>`` for a prefab.
    document_path: Callable[[str], Path]
    store_root: Callable[[], Path]
    baseline_path: Callable[[str], Path]
    conflict_path: Callable[[str, str], Path]
    #: The directory the held (parked) documents live in, per realm.
    conflict_dir: Callable[[str], Path]
    #: The family's pull summary type (wire name kept per family).
    summary_type: type[DocumentPullSummary]
    #: The publish artifact kind (``SyncFamily`` value) and the scan's refusal
    #: reason for a listed document the store cannot read.
    sync_kind: str
    unreadable_reason: str
    #: A family's extra facts over the parsed object (the map's ``name``);
    #: raises the family's error.
    extra_check: Callable[[dict[str, Any]], None] | None = None
    #: Whether a numeric ``version`` is required (levels, maps: yes; the
    #: launcher's prefab wire carries ``v``, and hermes does not read it).
    require_version: bool = True
    #: Glob for the documents under a root: ``*.json`` (flat) or ``*/*.json``.
    glob: str = "*.json"

    def baseline_key(self, token: str) -> str:
        return f"{self.noun}:{token}"

    def refusal(self, key: str, code: str, *, message: str | None = None) -> dict[str, str]:
        return {"key": key, "code": code, "message": message or self.messages.get(code, code)}

    def published_root(self, subtree) -> Path:
        return Path(subtree).joinpath(*self.published_prefix.strip("/").split("/"))

    def published_relative_path(self, token: str) -> str:
        return f"{self.published_prefix}{token}.json"

    def tokens_under(self, root: Path) -> list[Path]:
        """The document files under ``root`` (sorted), by the family's glob."""

        if not root.is_dir():
            return []
        return sorted(path for path in root.glob(self.glob) if path.is_file())

    @staticmethod
    def token_of(path: Path, root: Path) -> str:
        return path.relative_to(root).with_suffix("").as_posix()


# --- the facts hermes reads ---------------------------------------------------


def validate_document(family: DocumentFamily, raw: bytes) -> dict[str, Any]:
    """Refuse anything that is not a size-bounded JSON object with a numeric
    ``version`` (plus the family's ``extra_check``).

    Returns the parsed object for the CALLER's accounting. **It is never what
    gets stored** — every writer writes ``raw``.
    """

    if len(raw) > family.max_bytes:
        raise family.error(REFUSAL_TOO_LARGE)
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise family.error(REFUSAL_UNREADABLE_DOCUMENT) from exc
    if not isinstance(parsed, dict):
        raise family.error(REFUSAL_NOT_AN_OBJECT)
    version = parsed.get("version")
    if family.require_version and (not isinstance(version, (int, float)) or isinstance(version, bool)):
        raise family.error(REFUSAL_MISSING_VERSION)
    if family.extra_check is not None:
        family.extra_check(parsed)
    return parsed


def document_hash(family: DocumentFamily, raw: bytes) -> str:
    """Semantic content hash — the MERGE key. Parses and re-serialises
    canonically (sorted keys, no whitespace); the stored bytes are untouched.
    An unvalidated ``raw`` raises the family's error."""

    parsed = validate_document(family, raw)
    canonical = json.dumps(parsed, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def stored_sha256(raw: bytes) -> str:
    """Hash of the STORED BYTES — the compare-and-set token, not the merge key."""

    return hashlib.sha256(raw).hexdigest()


def expectation_matches(stored: bytes | None, expect_sha256: str | None, *, provided: bool) -> bool:
    """Does the store still hold what a compare-and-set caller last read?

    - ``provided=False`` (the caller omitted the key) — UNCONDITIONAL.
    - ``expect_sha256 is None`` — "there must be nothing stored", the arm that
      catches two machines authoring one entity at once.
    - a hex string — it must equal the sha256 of the STORED BYTES (compared
      case-insensitively; never the semantic hash).
    """

    if not provided:
        return True
    current = stored_sha256(stored) if stored is not None else None
    if expect_sha256 is None:
        return current is None
    return current is not None and current.lower() == str(expect_sha256).lower()


# --- the store door -----------------------------------------------------------


class DocumentStore:
    """Read, write, clear and list one family's documents — THE door. The verbs
    and the pull applier both write through it, so "hermes accepted this
    document" means one thing on this machine."""

    family: DocumentFamily

    def __init__(self, family: DocumentFamily | None = None):
        if family is not None:
            self.family = family

    def read(self, token: str) -> bytes | None:
        """The stored bytes, or ``None`` when nothing is stored (not an error)."""

        path = self.family.document_path(token)
        try:
            return path.read_bytes() if path.is_file() else None
        except OSError:
            return None

    def write(self, token: str, raw: bytes) -> dict[str, Any]:
        """Store ``raw`` VERBATIM after validating it. BYTES, never text mode: a
        text write translates ``\\n`` to the host's line ending, rewriting every
        line of a document hermes promised not to touch."""

        from utils import atomic_write_bytes

        validate_document(self.family, raw)
        path = self.family.document_path(token)
        before = self.read(token)
        if before == raw:
            return {"path": path, "changed": False}
        atomic_write_bytes(path, raw)
        return {"path": path, "changed": True}

    def clear(self, token: str) -> dict[str, Any]:
        """Delete one document; ``changed`` says whether one was there (an
        idempotent clear). **Local only**: removes nothing from a realm and writes
        no baseline, so a document the realm still publishes comes back on the
        next pull — ``upstream_absent`` is never a delete."""

        path = self.family.document_path(token)
        existed = path.is_file()
        try:
            path.unlink(missing_ok=True)
        except OSError:
            if path.is_file():
                raise
            existed = False
        return {"path": path, "changed": existed}

    def list_tokens(self) -> list[str]:
        """Every token this store holds, sorted."""

        root = self.family.store_root()
        return [self.family.token_of(path, root) for path in self.family.tokens_under(root)]


# --- baseline sidecar (never synced, never published) ------------------------


def read_document_baseline(family: DocumentFamily, realm_id: str) -> dict[str, str]:
    path = family.baseline_path(realm_id)
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    entries = raw.get("entries") if isinstance(raw, dict) else None
    return {str(k): str(v) for k, v in entries.items()} if isinstance(entries, dict) else {}


def write_document_baseline(family: DocumentFamily, realm_id: str, entries: dict[str, str]) -> None:
    from utils import atomic_json_write

    atomic_json_write(
        family.baseline_path(realm_id),
        {"schema_version": 1, "entries": entries},
        indent=2,
        sort_keys=True,
    )


def update_document_baseline_after_publish(family: DocumentFamily, realm_id: str, hashes: dict[str, str]) -> None:
    """Record the published documents' hashes as the new baseline. Without it a
    member who publishes and then pulls reads what they just shipped as
    edited-on-both-sides, and this family answers that with a HOLD."""

    baseline = read_document_baseline(family, realm_id)
    for token, body_hash in hashes.items():
        baseline[family.baseline_key(token)] = body_hash
    write_document_baseline(family, realm_id, baseline)


# --- publish: one scan, and the status row it counts --------------------------


class DocumentPublishScan(NamedTuple):
    """What ONE pass over a family's store says this realm publishes: the
    artifacts, the content hashes the publish records as its new baseline, and
    the documents that would not travel (typed rows, never a silent omission —
    a peer would read the absence as a removal)."""

    artifacts: list[RealmSyncArtifact]
    hashes: dict[str, str]
    refused: list[dict[str, Any]]


def document_publish_scan(family: DocumentFamily, wanted: set[str] | None = None) -> DocumentPublishScan:
    """Every stored document (``wanted``: only those tokens) as a verbatim
    artifact. A document that will not read publishes NOTHING and is refused
    typed: publish copies verbatim, so it would travel and every peer's pull
    would refuse it, keeping the failure from the one operator whose disk holds
    the broken file."""

    store = DocumentStore(family)
    artifacts: list[RealmSyncArtifact] = []
    hashes: dict[str, str] = {}
    refused: list[dict[str, Any]] = []
    for token in store.list_tokens():
        if wanted is not None and token not in wanted:
            continue
        raw = store.read(token)
        if raw is None:
            # Listed by the walk and unreadable by the store's own read (an
            # OSError it swallows): the same typed row an undecodable document
            # gets — from the publish's side the two are one fact.
            refused.append({family.token_field: token, "reason": family.unreadable_reason, "error": "OSError"})
            continue
        try:
            hashes[token] = document_hash(family, raw)
        except family.error as exc:
            refused.append({family.token_field: token, "reason": exc.code, "error": type(exc).__name__})
            continue
        source = family.document_path(token)
        artifacts.append(
            RealmSyncArtifact(
                kind=family.sync_kind,
                source=source,
                relative_path=family.published_relative_path(token),
                destination=source,
            )
        )
    return DocumentPublishScan(artifacts=artifacts, hashes=hashes, refused=refused)


def document_status_row(family: DocumentFamily, realm_id: str, scan: DocumentPublishScan) -> dict[str, Any]:
    """``{publishable, unpublished, held, refused}`` — ``unpublished`` is the
    publish scan's own hash-vs-baseline compare spent as a count (one walk's
    arithmetic in two shapes, never two walks); ``held`` is the parked tokens."""

    baseline = read_document_baseline(family, realm_id)
    unpublished = sum(
        1 for token, body_hash in scan.hashes.items() if baseline.get(family.baseline_key(token)) != body_hash
    )
    conflicts = family.conflict_dir(realm_id)
    held = [family.token_of(path, conflicts) for path in family.tokens_under(conflicts)]
    return {
        "publishable": len(scan.artifacts),
        "unpublished": unpublished,
        "held": sorted(held),
        "refused": list(scan.refused),
    }


# --- pull: adopt, keep or HOLD — whole document, never merged ----------------


def read_remote_documents(family: DocumentFamily, subtree) -> tuple[dict[str, bytes], list[dict[str, str]]]:
    """Document bytes carried by a pulled realm subtree, keyed by token.

    ``(documents, refused)``. A file under the prefix that will not read is
    REFUSED by name rather than omitted: an omission is indistinguishable from
    "the realm stopped publishing it", which drives ``upstream_absent``.
    """

    root = family.published_root(subtree)
    documents: dict[str, bytes] = {}
    refused: list[dict[str, str]] = []
    for path in family.tokens_under(root):
        token = family.token_of(path, root)
        try:
            raw = path.read_bytes()
            validate_document(family, raw)
        except (OSError, family.error) as exc:
            code = getattr(exc, "code", family.refusal_unreadable_remote)
            refused.append(
                family.refusal(token, family.refusal_unreadable_remote, message=family.messages.get(code, code))
            )
            continue
        documents[token] = raw
    return documents, refused


@dataclass(slots=True)
class DocumentPullSummary:
    """Typed accounting for one family's pull, carried on a pull ack under the
    family's wire name (``result["level_sync"]``, ``result["map_sync"]``).

    - ``adopted`` — the realm's document was written whole, through the store door.
    - ``converged`` — local already equals remote; nothing written.
    - ``kept_local`` — this machine changed it and the realm did not.
    - ``held`` — BOTH sides changed it; local untouched, remote parked.
    - ``upstream_absent`` — the realm no longer carries a document this baseline
      says it published. **Never a delete**; the baseline is kept.
    - ``refused`` — a published document that will not read, or a local one.

    ``source`` is ``None`` when the subtree carries no directory for the family
    at all (an older publisher); absence is never a removal, so the key is
    emitted unconditionally.
    """

    adopted: list[str] = field(default_factory=list)
    converged: list[str] = field(default_factory=list)
    kept_local: list[str] = field(default_factory=list)
    held: list[str] = field(default_factory=list)
    upstream_absent: list[str] = field(default_factory=list)
    refused: list[dict[str, str]] = field(default_factory=list)
    source: str | None = None

    @property
    def changed(self) -> bool:
        return bool(self.adopted)

    def as_dict(self) -> dict[str, Any]:
        return {
            "adopted": sorted(set(self.adopted)),
            "converged": sorted(set(self.converged)),
            "kept_local": sorted(set(self.kept_local)),
            "held": sorted(set(self.held)),
            "upstream_absent": sorted(set(self.upstream_absent)),
            "refused": list(self.refused),
            "source": self.source,
        }


def apply_document_pull(family: DocumentFamily, realm_id: str, subtree) -> DocumentPullSummary:
    """Adopt, keep or HOLD each pulled document — whole document, never merged."""

    from ..sync_merge import PullAction, classify_three_way_pull

    summary = family.summary_type()
    if not family.published_root(subtree).is_dir():
        # Not published. Never a removal — no baselined document is touched, so
        # an older peer in the rotation cannot strand this machine's documents.
        return summary
    summary.source = "subtree"
    remote, refused = read_remote_documents(family, subtree)
    summary.refused.extend(refused)

    store = DocumentStore(family)
    baseline = read_document_baseline(family, realm_id)
    prefix = family.baseline_key("")
    baselined = {key[len(prefix) :] for key in baseline if key.startswith(prefix)}
    for token in sorted(set(remote) | baselined):
        remote_raw = remote.get(token)
        # A token that refused above is neither adopted nor treated as absent:
        # it is already named on ``refused`` and must not fall into the
        # upstream_absent arm, which is delete-SHAPED reporting about a file that
        # is right there and merely would not open.
        if remote_raw is None and any(row["key"] == token for row in refused):
            continue
        try:
            local_raw = store.read(token)
            local_hash = document_hash(family, local_raw) if local_raw is not None else None
        except family.error:
            summary.refused.append(family.refusal(token, family.refusal_unreadable_local))
            continue
        if remote_raw is None:
            summary.upstream_absent.append(token)
            continue
        remote_hash = document_hash(family, remote_raw)
        decision = classify_three_way_pull(local_hash, remote_hash, baseline.get(family.baseline_key(token)))
        if decision.action is PullAction.NOOP:
            summary.converged.append(token)
            continue
        if decision.action is PullAction.KEEP_LOCAL:
            summary.kept_local.append(token)
            continue
        if decision.action is PullAction.CONFLICT:
            summary.held.append(token)
            _park_held_document(family, realm_id, token, remote_raw, local_hash, remote_hash)
            continue
        if decision.action is PullAction.ARCHIVE_LOCAL:
            # Unreachable with ``remote_raw`` in hand — the classifier only
            # answers ARCHIVE_LOCAL for an absent remote, which the arm above
            # already took. Named rather than folded into the adopt arm so a
            # future classifier change cannot silently start overwriting a
            # document on a removal decision.
            summary.upstream_absent.append(token)
            continue
        store.write(token, remote_raw)
        baseline[family.baseline_key(token)] = remote_hash
        summary.adopted.append(token)
    if summary.adopted:
        write_document_baseline(family, realm_id, baseline)
    return summary


def _park_held_document(
    family: DocumentFamily,
    realm_id: str,
    token: str,
    remote_raw: bytes,
    local_hash: str | None,
    remote_hash: str | None,
) -> None:
    """Park the document a HOLD refused to adopt. Best-effort: a sidecar this
    machine cannot write is not a reason to clobber the document the hold
    protects. The remote bytes ride as TEXT so the parked copy is the one the
    publisher wrote."""

    from utils import atomic_json_write

    try:
        atomic_json_write(
            family.conflict_path(realm_id, token),
            {
                "schema_version": 1,
                "realm_id": realm_id,
                family.token_field: token,
                "local_hash": local_hash,
                "remote_hash": remote_hash,
                "remote_document": remote_raw.decode("utf-8", errors="replace"),
            },
            indent=2,
            sort_keys=True,
        )
    except Exception:  # the HOLD stands with or without its receipt
        pass
