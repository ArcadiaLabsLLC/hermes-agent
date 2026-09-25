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

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import paths

__layer__ = "stores"

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

#: The bytes are not UTF-8, or not JSON at all.
REFUSAL_UNREADABLE_DOCUMENT = "unreadable_document"
#: Valid JSON, but not an object.
REFUSAL_NOT_AN_OBJECT = "not_an_object"
#: No numeric ``version`` — the fact every store on the other end gates on.
REFUSAL_MISSING_VERSION = "missing_version"
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
#: Over :data:`MAX_MAP_DOCUMENT_BYTES`.
REFUSAL_TOO_LARGE = "document_too_large"
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


def _refusal(key: str, code: str, *, message: str | None = None) -> dict[str, str]:
    return {"key": key, "code": code, "message": message or _REFUSAL_MESSAGES.get(code, code)}


class MapDocumentError(ValueError):
    """A map document this runtime refuses to store or publish.

    Carries the typed ``code`` for ``LevelDocumentError``'s reason: the CLI's
    exit taxonomy, the publish scan's refusal list and the pull's per-entity
    isolation all spend the code, and none of them should be re-deriving it from
    a sentence.
    """

    def __init__(self, code: str, message: str | None = None):
        super().__init__(message or _REFUSAL_MESSAGES.get(code, code))
        self.code = code


# --- the three facts hermes reads -------------------------------------------


def validate_map_document(raw: bytes) -> dict[str, Any]:
    """Refuse anything that is not a size-bounded JSON object with ``version``
    and a non-empty ``name``.

    Returns the parsed object for the CALLER's accounting (the CLI prints the
    name it accepted). **It is never what gets stored** — every writer in this
    module writes ``raw``.
    """

    if len(raw) > MAX_MAP_DOCUMENT_BYTES:
        raise MapDocumentError(REFUSAL_TOO_LARGE)
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise MapDocumentError(REFUSAL_UNREADABLE_DOCUMENT) from exc
    if not isinstance(parsed, dict):
        raise MapDocumentError(REFUSAL_NOT_AN_OBJECT)
    version = parsed.get("version")
    if not isinstance(version, (int, float)) or isinstance(version, bool):
        raise MapDocumentError(REFUSAL_MISSING_VERSION)
    name = parsed.get("name")
    if not isinstance(name, str) or not name.strip():
        raise MapDocumentError(REFUSAL_NAME_INVALID)
    return parsed


def map_document_hash(raw: bytes) -> str:
    """Semantic content hash of one map document — the MERGE key.

    Parses and re-serialises canonically (sorted keys, no whitespace) so the
    merge keys on the JSON VALUE. The stored bytes are untouched by this;
    nothing here is ever written back.
    """

    parsed = validate_map_document(raw)
    canonical = json.dumps(parsed, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def stored_map_sha256(raw: bytes) -> str:
    """Hash of the STORED BYTES — the compare-and-set token, not the merge key.

    Named apart from :func:`map_document_hash` for the reason
    ``stored_level_sha256`` states: a re-indentation changes THIS one, which is
    what a compare-and-set caller needs, while the semantic hash would call that
    write a no-op and let a lost update through.
    """

    return hashlib.sha256(raw).hexdigest()


def map_expectation_matches(
    stored: bytes | None, expect_sha256: str | None, *, provided: bool
) -> bool:
    """Does the store still hold what a compare-and-set caller last read?

    The level family's three states, unchanged:

    - ``provided=False`` — UNCONDITIONAL.
    - ``expect_sha256 is None`` — "there must be nothing stored", the arm that
      catches two machines minting the same map id at once.
    - a hex string — it must equal the sha256 of the STORED BYTES.
    """

    if not provided:
        return True
    current = stored_map_sha256(stored) if stored is not None else None
    if expect_sha256 is None:
        return current is None
    return current is not None and current.lower() == str(expect_sha256).lower()


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

    - **Asked** on the two AUTHORING doors, ``runtime.map.set`` and
      ``harness map set``, where a human or the launcher's picker is naming a
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

    return f"map:{map_token}"


def published_relative_path(map_id: str) -> str:
    """Where one map is published inside a realm subtree.

    ONE spelling, read by both the publish scan and the pull walk.
    """

    return f"{MAP_PUBLISHED_PREFIX}{paths.safe_path_token(map_id)}.json"


def map_token_for_published_path(rel: str) -> str | None:
    """The map token a published path names, or ``None`` if it is not one.

    The exact inverse of :func:`published_relative_path` over the tokens that
    function can produce — a nested path under the prefix is NOT one of them and
    answers ``None`` rather than a guess.
    """

    text = str(rel).replace("\\", "/")
    if not text.startswith(MAP_PUBLISHED_PREFIX) or not text.endswith(".json"):
        return None
    tail = text[len(MAP_PUBLISHED_PREFIX) : -len(".json")]
    if not tail or "/" in tail:
        return None
    return tail


# --- the store door ---------------------------------------------------------


class MapStore:
    """Read, write, clear and list the map catalogue.

    THE door. Both the CLI verbs and the realm-sync pull applier write through
    it, so "hermes accepted this map" means one thing on this machine.
    """

    def read(self, map_id: str) -> bytes | None:
        """The stored bytes, or ``None`` when the catalogue holds no such map."""

        path = paths.map_path(map_id)
        try:
            return path.read_bytes() if path.is_file() else None
        except OSError:
            return None

    def write(self, map_id: str, raw: bytes) -> dict[str, Any]:
        """Store ``raw`` VERBATIM after validating it, and report what happened.

        ``newline=""`` is load-bearing rather than tidy, for the reason
        ``LevelStore.write`` states: the default translates ``\\n`` to the host's
        line ending, which on Windows would make hermes rewrite every line of a
        document it promised not to touch, and the publish lane's own EOL
        canonicalisation would then report a change on a no-op set.
        """

        from utils import atomic_write_text

        validate_map_document(raw)
        path = paths.map_path(map_id)
        before = self.read(map_id)
        if before == raw:
            return {"path": path, "changed": False}
        atomic_write_text(path, raw.decode("utf-8"), newline="")
        return {"path": path, "changed": True}

    def clear(self, map_id: str) -> dict[str, Any]:
        """Delete one catalogue entry, and say whether one was there.

        ``changed: False`` for a map nothing held is an honest answer, not an
        error — the reading that makes a clear IDEMPOTENT for a launcher that
        retries.

        **A clear is local.** It removes nothing from a realm and writes no
        baseline: the pull's ``upstream_absent`` arm is deliberately never a
        delete, so a cleared map that the realm still publishes comes back on the
        next pull. That is the family's ruling, inherited whole from the level
        family, and it matters MORE here — a catalogue entry deleted on one
        machine is the reported defect reproduced on purpose.
        """

        path = paths.map_path(map_id)
        existed = path.is_file()
        try:
            path.unlink(missing_ok=True)
        except OSError:
            if path.is_file():
                raise
            existed = False
        return {"path": path, "changed": existed}

    def list_map_tokens(self) -> list[str]:
        """Every map token this store holds, sorted."""

        root = paths.maps_root()
        if not root.is_dir():
            return []
        return sorted(path.stem for path in root.glob("*.json") if path.is_file())


# --- baseline sidecar (never synced, never published) ------------------------


def read_map_baseline(realm_id: str) -> dict[str, str]:
    path = paths.map_baseline_path(realm_id)
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    entries = raw.get("entries") if isinstance(raw, dict) else None
    return {str(k): str(v) for k, v in entries.items()} if isinstance(entries, dict) else {}


def write_map_baseline(realm_id: str, entries: dict[str, str]) -> None:
    from utils import atomic_json_write

    atomic_json_write(
        paths.map_baseline_path(realm_id),
        {"schema_version": 1, "entries": entries},
        indent=2,
        sort_keys=True,
    )


def update_map_baseline_after_publish(realm_id: str, hashes: dict[str, str]) -> None:
    """Record the published maps' hashes as the new baseline.

    Without it a member who publishes and then pulls reads the catalogue they
    just shipped as locally-edited-and-remotely-changed, and this family answers
    a two-sided divergence with a HOLD — so the publisher would be handed a held
    catalogue over content nobody disagreed about.
    """

    baseline = read_map_baseline(realm_id)
    for token, body_hash in hashes.items():
        baseline[map_baseline_key(token)] = body_hash
    write_map_baseline(realm_id, baseline)


# --- pull: adopt, keep or HOLD — whole document, never merged ----------------


def read_remote_maps(subtree) -> tuple[dict[str, bytes], list[dict[str, str]]]:
    """Map bytes carried by a pulled realm subtree, keyed by map token.

    ``(maps, refused)``. A file under the prefix that will not read is REFUSED
    by name rather than omitted: an omission is indistinguishable from "the realm
    stopped publishing this map", which drives the ``upstream_absent`` arm, and
    answering a read failure with a removal-shaped decision is the mistake this
    family cannot afford to make about a catalogue.
    """

    root = Path(subtree).joinpath(*MAP_PUBLISHED_PREFIX.strip("/").split("/"))
    maps: dict[str, bytes] = {}
    refused: list[dict[str, str]] = []
    if not root.is_dir():
        return maps, refused
    for path in sorted(root.glob("*.json")):
        if not path.is_file():
            continue
        token = path.stem
        try:
            raw = path.read_bytes()
            validate_map_document(raw)
        except (OSError, MapDocumentError) as exc:
            code = getattr(exc, "code", REFUSAL_UNREADABLE_REMOTE)
            refused.append(
                _refusal(token, REFUSAL_UNREADABLE_REMOTE, message=_REFUSAL_MESSAGES.get(code, code))
            )
            continue
        maps[token] = raw
    return maps, refused


@dataclass(slots=True)
class MapPullSummary:
    """Typed accounting for the map pull, carried on a pull ack as
    ``result["map_sync"]``.

    The level family's arms, meaning the same things:

    - ``adopted`` — the realm's map was written whole, through the store door.
    - ``converged`` — local already equals remote; nothing written.
    - ``kept_local`` — this machine changed the map and the realm did not.
    - ``held`` — BOTH sides changed it; local untouched, remote parked.
    - ``upstream_absent`` — the realm no longer carries a map this baseline says
      it published. **Never a delete**, and here that ruling is the FIX: a
      catalogue entry silently removed on pull is the ``unnamed`` caption the
      owner reported, produced by hermes instead of by SharedPreferences.
    - ``refused`` — a published map that will not read, or a local one that will.

    ``source`` is ``None`` when the subtree carries no map directory at all — an
    older publisher, or a realm whose install never saved a named map. Absence is
    never a removal, which is why the key is emitted unconditionally.
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

    from .sync_merge import PullAction, classify_three_way_pull

    summary = MapPullSummary()
    root = Path(subtree).joinpath(*MAP_PUBLISHED_PREFIX.strip("/").split("/"))
    if not root.is_dir():
        # Not published. Never a removal — no baselined map is touched, so an
        # older peer in the rotation cannot strand this machine's catalogue.
        return summary
    summary.source = "subtree"
    remote, refused = read_remote_maps(subtree)
    summary.refused.extend(refused)

    store = MapStore()
    baseline = read_map_baseline(realm_id)
    prefix = map_baseline_key("")
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
            local_hash = map_document_hash(local_raw) if local_raw is not None else None
        except MapDocumentError:
            summary.refused.append(_refusal(token, REFUSAL_UNREADABLE_LOCAL))
            continue
        if remote_raw is None:
            summary.upstream_absent.append(token)
            continue
        remote_hash = map_document_hash(remote_raw)
        decision = classify_three_way_pull(
            local_hash, remote_hash, baseline.get(map_baseline_key(token))
        )
        if decision.action is PullAction.NOOP:
            summary.converged.append(token)
            continue
        if decision.action is PullAction.KEEP_LOCAL:
            summary.kept_local.append(token)
            continue
        if decision.action is PullAction.CONFLICT:
            summary.held.append(token)
            _write_conflict_sidecar(realm_id, token, remote_raw, local_hash, remote_hash)
            continue
        if decision.action is PullAction.ARCHIVE_LOCAL:
            # Unreachable with ``remote_raw`` in hand — the classifier only
            # answers ARCHIVE_LOCAL for an absent remote, which the arm above
            # already took. Named rather than folded into the adopt arm so a
            # future classifier change cannot silently start overwriting a
            # catalogue entry on a removal decision.
            summary.upstream_absent.append(token)
            continue
        store.write(token, remote_raw)
        baseline[map_baseline_key(token)] = remote_hash
        summary.adopted.append(token)
    if summary.adopted:
        write_map_baseline(realm_id, baseline)
    return summary


def _write_conflict_sidecar(
    realm_id: str,
    map_token: str,
    remote_raw: bytes,
    local_hash: str | None,
    remote_hash: str | None,
) -> None:
    """Park the catalogue entry a HOLD refused to adopt.

    Best-effort: a sidecar this machine cannot write is not a reason to clobber
    the map the hold exists to protect. The remote bytes are carried as TEXT
    rather than re-parsed JSON so the parked copy is the one the publisher wrote.
    """

    from utils import atomic_json_write

    try:
        atomic_json_write(
            paths.map_conflict_path(realm_id, map_token),
            {
                "schema_version": 1,
                "realm_id": realm_id,
                "map_token": map_token,
                "local_hash": local_hash,
                "remote_hash": remote_hash,
                "remote_document": remote_raw.decode("utf-8", errors="replace"),
            },
            indent=2,
            sort_keys=True,
        )
    except Exception:  # noqa: BLE001 — the HOLD stands with or without its receipt
        pass
