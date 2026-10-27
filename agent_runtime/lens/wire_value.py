"""Strict, bounded, canonical JSON — the wire floor every Lens contract stands on.

Ported from Companion's ``eternia_monitor_contracts/lib/src/wire_value.dart``
(plan ``docs/agent-runtime-harness/planned/eternia-lens-in-hermes.md`` §3). The
rules are the reference's: an unknown key, a missing key, a duplicate key, a
non-finite number and an oversize document all REFUSE — nothing is coerced,
dropped or defaulted. Every refusal is a :class:`WireError` carrying a typed
:class:`WireRefusal`, so a caller branches on the code, never on prose.

Canonical form (the digest input): keys sorted, no whitespace, an integral float
written as an integer, UTF-8. ``canonical_digest`` is SHA-256 over those bytes.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import datetime, timezone, UTC
from enum import Enum
from typing import Any, Callable, Iterable, TypeVar

__layer__ = "models"

#: The reference's budgets (bytes of UTF-8).
MAXIMUM_ENVELOPE_BYTES = 512 * 1024
MAXIMUM_MANIFEST_BYTES = 64 * 1024
#: Structural budgets of the strict decoder (the reference's ``_JsonBoundary``).
MAXIMUM_DEPTH = 24
MAXIMUM_NODES = 16384
#: The largest integer JSON carries exactly (2^53 - 1).
MAXIMUM_SAFE_INTEGER = 9007199254740991

_OPAQUE_ID = re.compile(r"^[A-Za-z0-9_.:@-]+$")
_DIGEST = re.compile(r"^[a-f0-9]{64}$")

E = TypeVar("E", bound=Enum)
T = TypeVar("T")


class WireRefusal(str, Enum):
    """Why a value was refused at the wire. The code IS the contract."""

    OVER_BUDGET = "over_budget"
    INVALID_JSON = "invalid_json"
    DUPLICATE_KEY = "duplicate_key"
    NON_FINITE = "non_finite"
    EXPECTED_OBJECT = "expected_object"
    UNKNOWN_KEY = "unknown_key"
    MISSING_KEY = "missing_key"
    INVALID_STRING = "invalid_string"
    INVALID_IDENTITY = "invalid_identity"
    INVALID_INTEGER = "invalid_integer"
    INVALID_NUMBER = "invalid_number"
    EXPECTED_BOOLEAN = "expected_boolean"
    UNKNOWN_ENUM = "unknown_enum"
    INVALID_LIST = "invalid_list"
    INVALID_TIME = "invalid_time"
    INVALID_DIGEST = "invalid_digest"
    INVALID_VALUE = "invalid_value"
    #: An ``investigate`` monitor sealed with no ``persona_id`` (p10-agent §5.2 decision 1).
    PERSONA_REQUIRED = "persona_required"
    #: A money ``best_of`` sealed with a member lacking ``product`` labels, or labelled ``unknown`` (W5).
    EQUIVALENCE_UNLABELLED = "equivalence_unlabelled"
    #: A money ``best_of`` sealed over members that differ in ``condition`` or ``variant`` (W5).
    EQUIVALENCE_MISMATCH = "equivalence_mismatch"
    #: ``lens_propose`` of a money ``best_of`` without one ``equivalence`` entry per member (W5).
    EQUIVALENCE_UNJUSTIFIED = "equivalence_unjustified"
    #: A ``schedule`` on a ``notify`` monitor: a scheduled run forges a turn or is meaningless.
    SCHEDULE_NEEDS_INVESTIGATE = "schedule_needs_investigate"
    #: A ``schedule`` the monitor's ``daily_turn_cap`` would clip every day.
    SCHEDULE_OVER_CAP = "schedule_over_cap"


class WireError(ValueError):
    """A refused value. ``code`` is typed; ``detail`` names the field, never a value."""

    def __init__(self, code: WireRefusal, detail: str = "") -> None:
        super().__init__(f"{code.value}: {detail}" if detail else code.value)
        self.code = code
        self.detail = detail


def require(condition: bool, detail: str, code: WireRefusal = WireRefusal.INVALID_VALUE) -> None:
    if not condition:
        raise WireError(code, detail)


# --- the strict decoder -------------------------------------------------------


def _pairs_without_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            raise WireError(WireRefusal.DUPLICATE_KEY, key)
        out[key] = value
    return out


def _refuse_constant(name: str) -> Any:
    raise WireError(WireRefusal.NON_FINITE, name)


def _check_shape(value: Any, depth: int, budget: list[int]) -> None:
    budget[0] += 1
    if depth > MAXIMUM_DEPTH or budget[0] > MAXIMUM_NODES:
        raise WireError(WireRefusal.OVER_BUDGET, "depth or node budget")
    children: Iterable[Any] = ()
    if isinstance(value, dict):
        children = value.values()
    elif isinstance(value, list):
        children = value
    for child in children:
        _check_shape(child, depth + 1, budget)


def decode_strict_json(source: str | bytes, *, maximum_bytes: int = MAXIMUM_ENVELOPE_BYTES) -> Any:
    """Decode ``source``, refusing what the standard decoder would silently accept."""

    raw = source.encode("utf-8") if isinstance(source, str) else bytes(source)
    if len(raw) > maximum_bytes:
        raise WireError(WireRefusal.OVER_BUDGET, "byte budget")
    try:
        text = raw.decode("utf-8")
        value = json.loads(text, object_pairs_hook=_pairs_without_duplicates, parse_constant=_refuse_constant)
    except WireError:
        raise
    except (UnicodeDecodeError, ValueError) as exc:
        raise WireError(WireRefusal.INVALID_JSON, type(exc).__name__) from exc
    _check_shape(value, 0, [0])
    return value


# --- canonical form -----------------------------------------------------------


def _canonical_object(value: dict) -> dict:
    if any(not isinstance(key, str) for key in value):
        raise WireError(WireRefusal.EXPECTED_OBJECT, "non-string key")
    return {key: canonical(value[key]) for key in sorted(value)}


def _canonical_array(value: list | tuple) -> list:
    return [canonical(item) for item in value]


def _canonical_number(value: float) -> int | float:
    number = finite_number(value)
    return int(number) if float(number).is_integer() else number


def _canonical_scalar(value: Any) -> Any:
    return value


#: Exact JSON type -> its canonical form. ``bool`` is listed before it could fall
#: to ``int``: the lookup is by exact type, so ``True`` is a scalar, never ``1``.
_CANONICAL_BY_TYPE: dict[type, Callable[[Any], Any]] = {
    dict: _canonical_object,
    list: _canonical_array,
    tuple: _canonical_array,
    bool: _canonical_scalar,
    str: _canonical_scalar,
    type(None): _canonical_scalar,
    int: _canonical_number,
    float: _canonical_number,
}


def canonical(value: Any) -> Any:
    """The canonical tree: sorted keys, integral floats as ints, finite numbers only."""

    form = _CANONICAL_BY_TYPE.get(type(value))
    if form is None:
        raise WireError(WireRefusal.INVALID_VALUE, f"non-JSON {type(value).__name__}")
    return form(value)


def canonical_json(value: Any) -> str:
    return json.dumps(canonical(value), separators=(",", ":"), ensure_ascii=False, sort_keys=True)


def canonical_bytes(value: Any) -> bytes:
    return canonical_json(value).encode("utf-8")


def canonical_digest(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


# --- typed readers (each refuses; none coerces) --------------------------------


def checked_object(value: Any, required: Iterable[str], optional: Iterable[str] = ()) -> dict[str, Any]:
    """A closed object: every required key present, no key outside required|optional."""

    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise WireError(WireRefusal.EXPECTED_OBJECT)
    required, allowed = set(required), set(required) | set(optional)
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise WireError(WireRefusal.UNKNOWN_KEY, unknown[0])
    missing = sorted(required - set(value))
    if missing:
        raise WireError(WireRefusal.MISSING_KEY, missing[0])
    return dict(value)


#: The control characters a MULTI-LINE text (``bounded_string(..., layout=True)``, a SQL
#: statement) may carry: tab, line feed, carriage return. Every other one still refuses.
LAYOUT_CHARACTERS = frozenset("\t\n\r")


def bounded_string(value: Any, *, maximum: int = 160, empty: bool = False, layout: bool = False) -> str:
    allowed = LAYOUT_CHARACTERS if layout else frozenset()
    if (
        not isinstance(value, str)
        or (not empty and not value)
        or len(value.encode("utf-8", "surrogatepass")) > maximum
        or any((ord(ch) < 32 and ch not in allowed) or 0xD800 <= ord(ch) <= 0xDFFF for ch in value)
    ):
        raise WireError(WireRefusal.INVALID_STRING)
    return value


def opaque_id(value: Any) -> str:
    text = bounded_string(value)
    if not _OPAQUE_ID.match(text):
        raise WireError(WireRefusal.INVALID_IDENTITY)
    return text


def bounded_int(value: Any, *, minimum: int = 0, maximum: int = MAXIMUM_SAFE_INTEGER) -> int:
    # JSON 5.0 decodes as float; the reference's ``is int`` refuses it, and so do we.
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise WireError(WireRefusal.INVALID_INTEGER)
    return value


def finite_number(value: Any) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or abs(value) > MAXIMUM_SAFE_INTEGER
    ):
        raise WireError(WireRefusal.INVALID_NUMBER)
    return float(value)


def boolean_value(value: Any) -> bool:
    if not isinstance(value, bool):
        raise WireError(WireRefusal.EXPECTED_BOOLEAN)
    return value


def enum_value(value: Any, enum: type[E]) -> E:
    for item in enum:
        if item.value == value:
            return item
    raise WireError(WireRefusal.UNKNOWN_ENUM, enum.__name__)


def bounded_list(value: Any, read: Callable[[Any], T], *, minimum: int = 0, maximum: int = 256) -> list[T]:
    if not isinstance(value, list) or not minimum <= len(value) <= maximum:
        raise WireError(WireRefusal.INVALID_LIST)
    return [read(item) for item in value]


def utc_time(value: Any) -> datetime:
    """A canonical UTC instant: ``YYYY-MM-DDTHH:MM:SS.mmmZ`` and nothing else."""

    text = bounded_string(value, maximum=32)
    try:
        parsed = datetime.strptime(text, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC)
    except ValueError as exc:
        raise WireError(WireRefusal.INVALID_TIME) from exc
    if format_utc(parsed) != text:
        raise WireError(WireRefusal.INVALID_TIME, "not canonical")
    return parsed


def format_utc(moment: datetime) -> str:
    if moment.tzinfo is None:
        raise WireError(WireRefusal.INVALID_TIME, "naive datetime")
    moment = moment.astimezone(UTC)
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"


def digest_value(value: Any) -> str:
    text = bounded_string(value, maximum=64)
    if not _DIGEST.match(text):
        raise WireError(WireRefusal.INVALID_DIGEST)
    return text


def optional(value: Any, read: Callable[[Any], T]) -> T | None:
    return None if value is None else read(value)
