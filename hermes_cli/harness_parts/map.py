# Map CATALOGUE CLI tier: `hermes harness map …`.
#
# This module shares the Stage-42 envelope/printer/error helpers
# with every other tier — imported from hermes_cli.harness_support below, not
# inherited. Every write goes through the MapStore chokepoint, the same door
# realm sync's pull applier uses.
#
# THE CONTRACT: the launcher owns the map document's format (a MapDescriptor
# plus its SceneDocument) and hermes owns its transport and its NAME. `show
# --full` hands the stored bytes back VERBATIM. The argv `map list`, `map set`
# and `map clear` were deleted 2026-10-02 (owner ruling: the launcher calls
# them only as `runtime.map.list` / `.set` / `.clear`, no operator or script
# uses the argv form); the read stays for operators.
#
# Design report: the owner's two machines, 2026-09-22 — a pulled level read
# `unnamed · yours` on the Mac because the catalogue naming it was machine-local
# SharedPreferences. Sibling of harness_parts/level.py in every other respect.

# A real module (lane H1, 2026-09-24): it imports everything it reads, and a
# test patches a name HERE, where this module looks it up — never on
# ``hermes_cli.harness`` (W0-G4, tests/tooling/test_harness_namespace_is_thin.py).

from __future__ import annotations


from agent_runtime.root_observability import attach_root_observability
from hermes_cli.harness_support import (
    _object_envelope,
    _print_stage42,
    emit_harness_error,
)

__layer__ = "lanes"
__all__ = [
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


def _map_row(map_id: str, raw: bytes | None, *, full: bool) -> dict:
    """One map row, built by the store module's own builder.

    One builder across the two lanes, so the launcher's catalogue cannot key its
    compare-and-set on two spellings of the same hash.
    """

    from agent_runtime.map_sync import map_document_row

    return map_document_row(map_id, raw, full=full)


def _map_id_or_refusal(args) -> tuple[str | None, int | None]:
    map_id = _map_id_for(args)
    if not map_id:
        return None, emit_harness_error(
            ValueError("no map selected; pass --map"), args=args, code="invalid_request"
        )
    return map_id, None


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
