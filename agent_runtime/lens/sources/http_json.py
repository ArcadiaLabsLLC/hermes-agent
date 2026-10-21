"""The ``http_json`` poll source: GET a JSON document, take one number by selector.

The selector is the reference's bounded path (``$.a.b[0]``); the value it lands
on must be a finite JSON number — a boolean, a string or a missing key is an
``unavailable`` read with its typed reason, never a guessed number.
"""

from __future__ import annotations

import math
import re
from typing import Any

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


def read(feed: dict[str, Any], *, headers: dict[str, str], client: Any = None, resolver: Any = None) -> ReadResult:
    source = feed["source"]
    document, failed = fetch_json(source["url"], headers=headers, allow_private=feed.get("allow_private_network", False),
                                  client=client, resolver=resolver)
    if failed is not None:
        return failed
    found, value = select(document, source["selector"])
    if not found:
        return unavailable(ReadReason.SELECTOR_MISSING, 200)
    number = number_of(value)
    if number is None:
        return unavailable(ReadReason.NOT_A_NUMBER, 200)
    return ReadResult(value=number, reason=ReadReason.OK, http_status=200)
