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
from .transport import ReadReason, ReadResult, fetch_json, unavailable

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


def read(feed: dict[str, Any], *, headers: dict[str, str], client: Any = None, resolver: Any = None) -> ReadResult:
    source = feed["source"]
    document, failed = fetch_json(source["url"], headers=headers, allow_private=feed.get("allow_private_network", False),
                                  client=client, resolver=resolver)
    if failed is not None:
        return failed
    return document_read(document, source["selector"], 200)
