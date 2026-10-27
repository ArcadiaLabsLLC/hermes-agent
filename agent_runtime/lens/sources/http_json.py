"""The ``http_json`` poll source: GET a JSON document, take one number by selector.

The selector is the reference's bounded path (``$.a.b[0]``); the value it lands
on must be a finite JSON number — a boolean, a string or a missing key is an
``unavailable`` read with its typed reason, never a guessed number.
"""

from __future__ import annotations

import math
import re
from dataclasses import replace
from typing import Any

from ..shapes import json_skeleton
from .transport import ReadReason, ReadResult, Validators, fetch_json, unavailable

__layer__ = "lanes"

_SEGMENT = re.compile(r"\.([A-Za-z_][A-Za-z0-9_]*)|\[([0-9]{1,4})\]")


def select(document: Any, selector: str) -> tuple[bool, Any]:
    """``(found, value)`` for a validated ``$...`` selector."""

    node = document
    for name, index in _SEGMENT.findall(selector[1:]):
        if name:
            if not isinstance(node, dict) or name not in node:
                return False, None
            node = node[name]
        else:
            position = int(index)
            if not isinstance(node, list) or position >= len(node):
                return False, None
            node = node[position]
    return True, node


def number_of(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def document_read(document: Any, selector: str, http_status: int | None = None) -> ReadResult:
    """The number ``selector`` lands on in ``document``, carrying the document's skeleton (W1)."""

    found, value = select(document, selector)
    number = number_of(value) if found else None
    if not found:
        result = unavailable(ReadReason.SELECTOR_MISSING, http_status)
    elif number is None:
        result = unavailable(ReadReason.NOT_A_NUMBER, http_status)
    else:
        result = ReadResult(value=number, reason=ReadReason.OK, http_status=http_status)
    return replace(result, shape=json_skeleton(document))


def read(feed: dict[str, Any], *, headers: dict[str, str], client: Any = None, resolver: Any = None,
         validators: Validators | None = None) -> ReadResult:
    """One read; with ``validators`` it is conditional and a ``304`` answers ``not_modified``."""

    source = feed["source"]
    document, failed = fetch_json(source["url"], headers=headers, allow_private=feed.get("allow_private_network", False),
                                  client=client, resolver=resolver, validators=validators)
    if failed is not None:
        return _replayed(failed, validators)
    result = document_read(document, source["selector"], 200)
    if validators is not None:
        validators.answer = result
    return result


def _replayed(failed: ReadResult, validators: Validators | None) -> ReadResult:
    """A ``304``: the document is the one the validators name, so its read answers again —
    a value under ``not_modified``, a failed selection under its own reason (its skeleton kept)."""

    answer = None if validators is None else validators.answer
    if failed.reason is not ReadReason.NOT_MODIFIED or answer is None:
        return failed
    reason = ReadReason.NOT_MODIFIED if answer.value is not None else answer.reason
    return replace(answer, reason=reason, http_status=failed.http_status)
