"""Lens SOURCE SHAPES: what a source's answer looked like, with every value taken out (W1).

Plan ``planned/LENS_EXTENSIONS_2026-10-27.md`` §1 decisions 1–3. A source that changes shape
answers a shape reason (:data:`SHAPE_REASONS`) and every rule then answers ``unknown``, so a
broken feed reads as silence. This module is the pure half of telling the two apart:

* :func:`json_skeleton` / :func:`prometheus_skeleton` / :func:`sql_skeleton` — the answer's
  SKELETON: the JSON document's key paths with their JSON types (an array collapsed to its first
  element, depth at most :data:`MAXIMUM_DEPTH`, at most :data:`MAXIMUM_PATHS` paths); a Prometheus
  result's type plus each series' sorted label NAMES; a SQL row's column names with the storage
  class of each cell. A skeleton is a sorted tuple of ``(path, type)`` pairs and carries no value,
  so the transport's rule — nothing a server sends reaches the store but a typed number — holds:
  a renamed key changes it, a changed number never does.
* :func:`fingerprint` — sha256 of the canonical skeleton (:func:`canonical_skeleton`, at most
  :data:`MAXIMUM_SKELETON_BYTES`).
* :func:`source_broken` — decision 3: broken after :data:`BROKEN_AFTER_READS` consecutive
  shape-reason reads, or on ONE shape-reason read whose fingerprint differs from the last
  known-good one. A transport or availability failure (``timeout``, ``network``, ``http_status``…)
  is never shape drift.

``SHAPE_REASONS`` lives here, not beside ``ReadReason``: the reason enum is a ``lanes`` module
(``sources/transport.py``) and this one is ``models``, so the set is spelled as the enum's values
and ``tests/agent_runtime/lens/test_lens_source_shapes.py`` holds every member to a ``ReadReason``.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Sequence

__layer__ = "models"

#: The read reasons that say the source ANSWERED but not in the shape the feed reads.
SHAPE_REASONS = frozenset({
    "selector_missing", "not_a_number", "not_json", "type_mismatch", "no_series", "ambiguous_series",
})
#: Consecutive shape-reason reads that make a feed broken (the L1 gate's own failure count).
BROKEN_AFTER_READS = 3
MAXIMUM_DEPTH = 8
MAXIMUM_PATHS = 256
MAXIMUM_SKELETON_BYTES = 4096
#: A key longer than this is named by its length, never copied.
_MAXIMUM_KEY_CHARS = 64
_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_TRUNCATED = ("…", "truncated")

Skeleton = tuple[tuple[str, str], ...]

_JSON_TYPES: tuple[tuple[type, str], ...] = (
    (bool, "boolean"), (int, "number"), (float, "number"), (str, "string"), (dict, "object"), (list, "array"),
)
_SQL_TYPES: tuple[tuple[type, str], ...] = (
    (bool, "integer"), (int, "integer"), (float, "real"), (str, "text"), (bytes, "blob"),
)


def _type_name(value: Any, table: tuple[tuple[type, str], ...]) -> str:
    return next((name for kind, name in table if isinstance(value, kind)), "null")


def _segment(key: Any) -> str:
    text = str(key)
    if len(text) > _MAXIMUM_KEY_CHARS:
        return f"[<{len(text)} chars>]"
    return f".{text}" if _IDENTIFIER.fullmatch(text) else f"[{json.dumps(text, ensure_ascii=True)}]"


def json_skeleton(document: Any) -> Skeleton:
    """The document's key paths and JSON types, values removed (decision 1)."""

    out: list[tuple[str, str]] = []
    stack: list[tuple[str, Any, int]] = [("$", document, 0)]
    while stack and len(out) < MAXIMUM_PATHS:
        path, node, depth = stack.pop()
        out.append((path, _type_name(node, _JSON_TYPES)))
        if depth >= MAXIMUM_DEPTH:
            continue
        if isinstance(node, dict):
            stack.extend((path + _segment(key), node[key], depth + 1) for key in sorted(node, key=str, reverse=True))
        elif isinstance(node, list) and node:
            stack.append((path + "[]", node[0], depth + 1))
    return tuple(sorted(out))


def prometheus_skeleton(document: Any) -> Skeleton:
    """A query answer's result type and each series' sorted label names; any other shape is
    its JSON skeleton."""

    data = document.get("data") if isinstance(document, dict) else None
    result = data.get("result") if isinstance(data, dict) else None
    if not isinstance(data, dict) or not isinstance(data.get("resultType"), str):
        return json_skeleton(document)
    out = {("resultType", data["resultType"][:_MAXIMUM_KEY_CHARS])}
    for series in result if isinstance(result, list) else ():
        labels = series.get("metric") if isinstance(series, dict) else None
        names = sorted(_segment(name)[1:] for name in labels) if isinstance(labels, dict) else []
        out.add(("series", ",".join(names)))
        if len(out) >= MAXIMUM_PATHS:
            break
    return tuple(sorted(out))


def sql_skeleton(columns: Sequence[str], row: Sequence[Any] | None) -> Skeleton:
    """The row's column names and the storage class of each cell (``null`` with no row).

    Python's ``sqlite3`` reports a column's name but not its declared type, so the type is the
    cell's storage class — what the statement actually answered."""

    cells = list(row) if row is not None else [None] * len(columns)
    return tuple(sorted((f"column{_segment(name)}", _type_name(cell, _SQL_TYPES))
                        for name, cell in zip(columns[:MAXIMUM_PATHS], cells)))


def canonical_skeleton(skeleton: Skeleton) -> str:
    """The skeleton as canonical JSON, at most :data:`MAXIMUM_SKELETON_BYTES`: past the bound the
    last pairs are dropped and a ``truncated`` marker ends the list."""

    pairs = [list(pair) for pair in skeleton]
    text = json.dumps(pairs, ensure_ascii=True, separators=(",", ":"))
    while len(text) > MAXIMUM_SKELETON_BYTES and pairs:
        pairs = pairs[:-max(1, len(pairs) // 8)]
        text = json.dumps(pairs + [list(_TRUNCATED)], ensure_ascii=True, separators=(",", ":"))
    return text


def fingerprint(skeleton: Skeleton) -> str:
    return hashlib.sha256(canonical_skeleton(skeleton).encode("ascii")).hexdigest()


def source_broken(reasons: Sequence[str], *, latest_fingerprint: str | None,
                  known_good_fingerprint: str | None) -> bool:
    """Decision 3, over a feed's newest READ reasons (oldest first; ``watcher_offline`` and other
    rows that are not a read are the caller's to leave out).

    ``latest_fingerprint`` is the newest read's skeleton fingerprint (None when it had none — a
    body that is not JSON); ``known_good_fingerprint`` the last read that produced a value."""

    if not reasons or reasons[-1] not in SHAPE_REASONS:
        return False
    tail = list(reasons[-BROKEN_AFTER_READS:])
    if len(tail) == BROKEN_AFTER_READS and all(reason in SHAPE_REASONS for reason in tail):
        return True
    return known_good_fingerprint is not None and latest_fingerprint != known_good_fingerprint
