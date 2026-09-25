# Map CATALOGUE CLI tier: `hermes harness map …`.
#
# This module shares the Stage-42 envelope/printer/error helpers
# with every other tier — imported from hermes_cli.harness_support below, not
# inherited. Every write goes through the MapStore chokepoint, the same door
# realm sync's pull applier uses.
#
# THE CONTRACT: the launcher owns the map document's format (a MapDescriptor
# plus its SceneDocument) and hermes owns its transport and its NAME. `set`
# takes the launcher's bytes and stores them VERBATIM; `show --full` hands the
# same bytes back; `list` answers the catalogue question — what named maps does
# this install know about — without any document bytes at all, which is the
# whole reason the family exists. hermes validates three facts (UTF-8 JSON, a
# numeric `version`, a non-empty `name`) and reformats nothing.
#
# Design report: the owner's two machines, 2026-09-22 — a pulled level read
# `unnamed · yours` on the Mac because the catalogue naming it was machine-local
# SharedPreferences. Sibling of harness_parts/level.py in every other respect.

# A real module (lane H1, 2026-09-24): it imports everything it reads, and a
# test patches a name HERE, where this module looks it up — never on
# ``hermes_cli.harness`` (W0-G4, tests/tooling/test_harness_namespace_is_thin.py).

from __future__ import annotations

from pathlib import Path

from agent_runtime.root_observability import attach_root_observability
from hermes_cli.harness_support import (
    _object_envelope,
    _print_stage42,
    emit_harness_error,
)

__layer__ = "lanes"
__all__ = [
    "_cmd_map_clear",
    "_cmd_map_list",
    "_cmd_map_set",
    "_cmd_map_show",
]



def _map_store():
    from agent_runtime.map_sync import MapStore

    return MapStore()


def _map_id_for(args) -> str | None:
    """The map id this verb addresses.

    There is no active-map fallback and there will not be one: a level is
    addressed by the ACTIVE workspace because a workspace is a place an operator
    is standing, while a map id is a name in a catalogue and "the current map"
    is not a fact this runtime holds. An omitted ``--map`` is an invalid request,
    not a guess.
    """

    raw = getattr(args, "map", None)
    return (str(raw).strip() or None) if raw else None


def _load_map_bytes(raw: str) -> bytes:
    """Resolve a ``--document`` value to the EXACT bytes to store.

    Deliberately NOT ``_load_request_json``: that helper parses, and a parsed
    document re-serialized on the way to disk is the one thing this family
    promises never to do. A path is read as bytes; anything else is taken as the
    document text itself and encoded UTF-8.

    A path is the right call for anything real — Windows caps a command line at
    ~32 KB and a map carries a whole scene.
    """

    candidate = (raw or "").strip()
    if candidate[:1] not in {"{", "["}:
        try:
            path = Path(candidate)
            if path.is_file():
                return path.read_bytes()
        except OSError:
            # Not a usable path — fall through and take the literal as the
            # document, which is what the caller meant if it was not a filename.
            pass
    return candidate.encode("utf-8")


def _map_row(map_id: str, raw: bytes | None, *, full: bool) -> dict:
    """One map row, built by the store module's own builder.

    One builder across the two lanes, so the launcher's catalogue cannot key its
    compare-and-set on two spellings of the same hash.
    """

    from agent_runtime.map_sync import map_document_row

    return map_document_row(map_id, raw, full=full)


#: The ``--expect-sha256`` word that means "there must be nothing stored", for
#: an argv lane that cannot spell JSON ``null``. The RPC lane says it with a
#: real ``null``; this is the same claim in the one vocabulary argv has.
MAP_EXPECT_ABSENT = "none"

#: Exit family 4 (conflict) — see ``ERROR_EXIT_CODES``. The RPC lane answers the
#: identical condition with ``ERR_CONFLICT`` / ``reason: sha256_mismatch``.
MAP_CONFLICT_CODE = "map_sha256_mismatch"


def _map_expect_arg(args) -> tuple[bool, str | None]:
    """``(provided, sha)`` from ``--expect-sha256``, with argv's three states.

    Absent flag = unconditional; ``none`` = the map must be absent; a hex string
    = it must equal the stored bytes' sha256. A malformed token is refused as an
    invalid REQUEST rather than compared, because a comparison could only fail
    and a failed comparison is reported as a conflict — which would tell an
    operator with a typo that somebody else had written their map.
    """

    raw = getattr(args, "expect_sha256", None)
    if raw is None:
        return False, None
    token = str(raw).strip()
    if token.lower() in {MAP_EXPECT_ABSENT, "absent", "null"}:
        return True, None
    if len(token) != 64 or any(ch not in "0123456789abcdefABCDEF" for ch in token):
        raise ValueError(
            "--expect-sha256 takes 64 hex characters or 'none' (the map must be absent)"
        )
    return True, token


def _map_conflict(args, map_id: str, stored: bytes | None) -> int:
    """The compare-and-set refusal, in the exit taxonomy's words."""

    from agent_runtime.map_sync import stored_map_sha256

    current = stored_map_sha256(stored) if stored is not None else None
    return emit_harness_error(
        ValueError(
            "the stored map is not the one this command was based on: "
            f"stored sha256 is {current or 'absent'} for {map_id}"
        ),
        args=args,
        code=MAP_CONFLICT_CODE,
        reason="sha256_mismatch",
    )


def _map_id_or_refusal(args) -> tuple[str | None, int | None]:
    map_id = _map_id_for(args)
    if not map_id:
        return None, emit_harness_error(
            ValueError("no map selected; pass --map"), args=args, code="invalid_request"
        )
    return map_id, None


def _cmd_map_list(args) -> int:
    """`harness map list` — the catalogue, names and hashes, no documents.

    The verb the level family has no equivalent of, and the one the reported
    defect actually needs: a caption asks "what is this map called", and
    answering it must not cost a megabyte of scene per entry.
    """

    store = _map_store()
    rows = [_map_row(token, store.read(token), full=False) for token in store.list_map_tokens()]
    _print_stage42(
        attach_root_observability(_object_envelope("maps", {"maps": rows, "count": len(rows)})),
        args=args,
    )
    return 0


def _cmd_map_show(args) -> int:
    """`harness map show` — read one catalogue map back.

    ``--full`` carries the document itself; the metadata-only default is
    ``level show``'s, for its reason — a megabyte of JSON on a table print is not
    an answer anyone reads.

    A map id nothing holds is a REFUSAL rather than an empty row, matching
    ``runtime.map.get``: a map has no record apart from its document, so "no
    document" and "no such map" are one fact, and a nameless row is the caption
    this family exists to retire.
    """

    map_id, refusal = _map_id_or_refusal(args)
    if refusal is not None:
        return refusal
    store = _map_store()
    raw = store.read(map_id)
    if raw is None:
        return emit_harness_error(
            ValueError(f"unknown map: {map_id}"), args=args, code="not_found", reason="map_not_found"
        )
    row = _map_row(map_id, raw, full=bool(getattr(args, "full", False)))
    _print_stage42(attach_root_observability(_object_envelope("map", row)), args=args)
    return 0


def _cmd_map_set(args) -> int:
    """`harness map set` — store one catalogue map VERBATIM.

    The refusal taxonomy is the store door's own (``MapDocumentError.code``) so
    the launcher can say WHICH of the five it was — ``missing_name`` above all,
    which is the arm that stops a nameless entry from being published as a fix
    for a naming defect.

    ``--dry-run`` validates and reports what WOULD change without writing.
    """

    from agent_runtime.map_sync import (
        REFUSAL_NAME_TAKEN,
        MapDocumentError,
        map_expectation_matches,
        map_name_holder,
        validate_map_document,
    )

    map_id, refusal = _map_id_or_refusal(args)
    if refusal is not None:
        return refusal
    store = _map_store()
    try:
        raw = _load_map_bytes(args.document)
    except OSError as exc:
        return emit_harness_error(exc, args=args, code="invalid_payload")
    try:
        validate_map_document(raw)
    except MapDocumentError as exc:
        return emit_harness_error(exc, args=args, code="invalid_payload", reason=exc.code)
    # The same uniqueness question ``runtime.map.set`` asks, in the same words,
    # and asked on this door for the same reason: an operator naming a map by
    # hand is authoring, and the pull is not. ``map_name_holder``'s docstring
    # carries why the two doors differ.
    holder = map_name_holder(map_id, raw)
    if holder is not None:
        return emit_harness_error(
            ValueError(f"another map already holds this name: {holder}"),
            args=args,
            code="invalid_payload",
            reason=REFUSAL_NAME_TAKEN,
        )
    try:
        expect_provided, expect_sha256 = _map_expect_arg(args)
    except ValueError as exc:
        return emit_harness_error(exc, args=args, code="invalid_request")
    stored = store.read(map_id)
    # Checked on a dry run too: "would hermes take this document" and "is this
    # write still based on what is stored" are two different questions, and a dry
    # run that answered the first while ignoring the second would promise a write
    # the real call refuses.
    if not map_expectation_matches(stored, expect_sha256, provided=expect_provided):
        return _map_conflict(args, map_id, stored)

    if getattr(args, "dry_run", False):
        row = _map_row(map_id, raw, full=False)
        row["changed"] = stored != raw
        row["dry_run"] = True
        _print_stage42(attach_root_observability(_object_envelope("map", row)), args=args)
        return 0
    try:
        outcome = store.write(map_id, raw)
    except OSError as exc:
        return emit_harness_error(exc, args=args, code="runtime_unavailable")
    row = _map_row(map_id, raw, full=False)
    row["changed"] = bool(outcome["changed"])
    _print_stage42(attach_root_observability(_object_envelope("map", row)), args=args)
    return 0


def _cmd_map_clear(args) -> int:
    """`harness map clear` — remove one catalogue map.

    The argv mirror of ``runtime.map.clear``, over the same store door and the
    same compare-and-set token. ``cleared: false`` for a map nothing held is an
    accepted no-op, and a clear removes nothing from a REALM: the pull's
    ``upstream_absent`` arm is never a delete, so a map the realm still publishes
    comes back on the next pull.
    """

    from agent_runtime import paths
    from agent_runtime.map_sync import map_expectation_matches

    map_id, refusal = _map_id_or_refusal(args)
    if refusal is not None:
        return refusal
    store = _map_store()
    try:
        expect_provided, expect_sha256 = _map_expect_arg(args)
    except ValueError as exc:
        return emit_harness_error(exc, args=args, code="invalid_request")
    stored = store.read(map_id)
    if not map_expectation_matches(stored, expect_sha256, provided=expect_provided):
        return _map_conflict(args, map_id, stored)
    if getattr(args, "dry_run", False):
        row = {
            "map_id": map_id,
            "map_token": paths.safe_path_token(map_id),
            "cleared": stored is not None,
            "dry_run": True,
        }
        _print_stage42(attach_root_observability(_object_envelope("map", row)), args=args)
        return 0
    try:
        outcome = store.clear(map_id)
    except OSError as exc:
        return emit_harness_error(exc, args=args, code="runtime_unavailable")
    row = {
        "map_id": map_id,
        "map_token": paths.safe_path_token(map_id),
        "cleared": bool(outcome["changed"]),
    }
    _print_stage42(attach_root_observability(_object_envelope("map", row)), args=args)
    return 0
