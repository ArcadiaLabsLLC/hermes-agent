from __future__ import annotations

import json

from .serde import to_jsonable

__layer__ = "policy"


def emit_json(data) -> str:
    return json.dumps(to_jsonable(data), indent=2, ensure_ascii=False, sort_keys=True)


def emit_json_line(data) -> str:
    """ONE line of the same JSON :func:`emit_json` writes.

    A verb that emits a payload per stage as the stage lands is a stream, and a
    stream's framing is the newline — so its encoder may not be the indenting
    one. Everything else is deliberately identical: the same ``to_jsonable``
    normalization, the same key order, the same escaping, so a consumer that
    parses a line here and a block there gets the same object out of both.

    The return value can never contain a newline: ``json.dumps`` escapes a
    ``\\n`` inside a string value as ``\\\\n``, which is what makes a payload
    carrying a multi-line refusal (charsheet ``compose`` writes several) safe to
    frame this way at all.
    """
    return json.dumps(
        to_jsonable(data), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


#: The stage-42 envelope schema every harness ``--json`` object/list carries.
#: Here, below both doors, since the realm verbs' method twins return the same
#: envelopes the argv verbs print (``hermes_cli.harness_support`` re-exports).
STAGE42_SCHEMA_VERSION = 1


def list_envelope(item_kind: str, items: list[dict], *, cursor: str | None = None, truncated: bool = False) -> dict:
    return {
        "schema_version": STAGE42_SCHEMA_VERSION,
        "kind": "list",
        "item_kind": item_kind,
        "count": len(items),
        "items": items,
        "cursor": cursor,
        "truncated": bool(truncated),
    }


def object_envelope(kind: str, item: dict, *, warnings: list[dict] | None = None) -> dict:
    data = {"schema_version": STAGE42_SCHEMA_VERSION, "kind": kind, **item}
    if warnings:
        data["warnings"] = warnings
    return data


def sort_rows(rows: list[dict], sort_key: str | None) -> list[dict]:
    """``--sort key`` / ``--sort -key``: a stable string sort; no key, no sort."""
    key = str(sort_key or "").strip()
    if not key:
        return rows
    reverse = key.startswith("-")
    if reverse:
        key = key[1:]
    return sorted(rows, key=lambda item: str(item.get(key, "")), reverse=reverse)
