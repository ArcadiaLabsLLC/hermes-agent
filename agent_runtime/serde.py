from __future__ import annotations

import json
import os
import tempfile
from dataclasses import fields, is_dataclass
from datetime import datetime, timezone
from enum import Enum
from functools import lru_cache, singledispatch
from pathlib import Path
from types import NoneType, UnionType
from typing import Any, get_args, get_origin, get_type_hints


def to_jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return {field.name: to_jsonable(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, datetime):
        value = value.astimezone(timezone.utc)
        return value.isoformat(timespec="microseconds").replace("+00:00", "Z")
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, list):
        return [to_jsonable(item) for item in value]
    if isinstance(value, tuple):
        return [to_jsonable(item) for item in value]
    if isinstance(value, frozenset):
        return [to_jsonable(item) for item in sorted(value, key=str)]
    if isinstance(value, dict):
        return {str(key): to_jsonable(item) for key, item in value.items()}
    return value


def from_jsonable(cls: type[Any], raw: Any) -> Any:
    return _coerce(cls, raw)


def upgrade(raw: dict[str, Any]) -> dict[str, Any]:
    """Schema upgrade hook. Stage 1 only ships v1 records."""
    if not isinstance(raw, dict):
        return raw
    version = raw.get("schema_version", 1)
    if version != 1:
        raise ValueError(f"unsupported schema_version: {version}")
    return raw


@lru_cache(maxsize=None)
def _dataclass_type_hints(cls: type[Any]) -> dict[str, Any]:
    return get_type_hints(cls)


def _coerce(annotation: Any, raw: Any) -> Any:
    if raw is None:
        return None

    origin = get_origin(annotation)
    args = get_args(annotation)

    if origin is UnionType or origin is getattr(__import__("typing"), "Union"):
        non_none = [arg for arg in args if arg is not NoneType]
        if raw is None:
            return None
        for arg in non_none:
            try:
                return _coerce(arg, raw)
            except Exception:
                continue
        return raw

    if origin is list:
        item_type = args[0] if args else Any
        return [_coerce(item_type, item) for item in raw]

    if origin is dict:
        value_type = args[1] if len(args) == 2 else Any
        return {str(key): _coerce(value_type, value) for key, value in raw.items()}

    if origin is frozenset:
        item_type = args[0] if args else Any
        return frozenset(_coerce(item_type, item) for item in raw)

    if annotation is Any:
        return raw

    if annotation is datetime:
        if isinstance(raw, datetime):
            return raw
        text = str(raw)
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        return datetime.fromisoformat(text)

    if isinstance(annotation, type) and issubclass(annotation, Enum):
        return annotation(raw)

    if isinstance(annotation, type) and is_dataclass(annotation):
        upgraded = upgrade(raw)
        hints = _dataclass_type_hints(annotation)
        kwargs = {}
        for field in fields(annotation):
            if field.name in upgraded:
                kwargs[field.name] = _coerce(hints.get(field.name, Any), upgraded[field.name])
        return annotation(**kwargs)

    return raw


# ---------------------------------------------------------------------------
# Wire-shape coercion — ONE home, so the next helper has somewhere to land.
#
# Pass 2 of the dead-code audit found four of these copied across the
# transport/projection cluster, three of them hidden by word-order-inverted or
# differently-abbreviated names (`_atomic_write_json` vs `_write_json_atomic`;
# `_text` vs `_optional_text`). A duplicate is only invisible while it has
# nowhere obvious to live. This module is a stdlib-only leaf with no relative
# imports, so anything in the package may depend on it without risking a
# cycle — which is exactly why it is the home.
# ---------------------------------------------------------------------------


def section_rows(value: Any) -> list:
    """A snapshot section S4 emits as an id-keyed map, read as an ordered list
    of rows (map values).

    Also accepts a plain list (sections S4 does not key) and ``None`` (absent
    section), so a reader never has to branch on which shape it got.
    """

    if isinstance(value, dict):
        return list(value.values())
    if isinstance(value, list):
        return list(value)
    return []


def optional_text(value: Any) -> str | None:
    """``None`` in, ``None`` out; blank-after-strip is also ``None``.

    The honest name for what three copies of ``_text`` were doing: the return
    is optional, and a whitespace-only wire value is an absent one.
    """

    if value is None:
        return None
    text = str(value).strip()
    return text or None


def optional_str(value: Any) -> str | None:
    """A stripped non-empty ``str``, else ``None`` — a non-string is NOT coerced.

    The config spelling of :func:`optional_text`: a YAML value that is not a
    string (a number, a list, a mapping) is an absent opinion here, never its
    ``str()``. Lane 2B-C folded ``config._clean_config_str`` onto it;
    ``mission_chat_outcome._text`` folds in its lane.
    """

    if not isinstance(value, str):
        return None
    return value.strip() or None


def safe_text(value: Any, *, limit: int) -> str | None:
    """``value`` as ONE bounded line: NULs dropped, whitespace collapsed, cut to
    ``limit``; ``None`` when nothing is left.

    The one owner of the rule (program rule 15). :func:`safe_assignment_text`
    is its empty-string spelling for the store rows that persist ``""``; the
    mission-chat stream reads this one.
    """

    return " ".join(str(value or "").replace("\x00", " ").split())[:limit] or None


def bounded_text(value: Any, limit: int) -> str:
    """``str(value)`` cut to ``limit``; ``None`` is ``""``. No strip, no collapse.

    The bound for a field stored VERBATIM (a dispatch's ask and reply, a peer's
    media reference): unlike :func:`safe_text` it keeps the text exactly as
    written, only shorter. ``chat_turn``, ``mission_chat_outcome`` and
    ``persona_open_chat`` carry the same body as ``_text`` and fold here in
    their lanes.
    """

    if value is None:
        return ""
    return str(value)[:limit]


def safe_block(value: Any, *, limit: int) -> str | None:
    """Newline-PRESERVING bounded text; ``None`` when nothing is left.

    Where :func:`safe_text` whitespace-collapses, this keeps line structure
    (a key-per-line tool-input block stays readable): NULs become spaces, line
    endings normalise to LF, and text past ``limit`` is cut with a visible
    ``…(rest truncated)…`` marker rather than silently.
    """

    text = str(value or "").replace("\x00", " ").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        return None
    if len(text) > limit:
        text = f"{text[:limit]}\n…(rest truncated)…"
    return text


def safe_int(value: Any) -> int | None:
    """``int(value)``, or ``None`` when it does not coerce. Never raises."""

    try:
        return int(value)
    except Exception:  # noqa: BLE001 — a coercion answers None, it does not raise
        return None


def non_negative_int(value: Any) -> int | None:
    """``int(value)`` when it coerces and is >= 0, else ``None``. Never raises.

    The count/size reading of a foreign field: a negative or unreadable value is
    no measurement, and ``0`` is a real one (unlike :func:`positive_int`).
    """

    parsed = safe_int(value)
    return parsed if parsed is not None and parsed >= 0 else None


def strict_int(value: Any) -> int | None:
    """:func:`safe_int`, but a ``bool`` is not a number here (``True`` is not exit code 1)."""

    return None if isinstance(value, bool) else safe_int(value)


@singledispatch
def number_or_bounded_text(value: Any, *, limit: int) -> int | float | str | None:
    """A foreign field that may be a NUMBER or a TEXT: the number as given, the
    text as :func:`safe_text` bounds it, anything else ``None``.

    ``bool`` is not a number here (``True`` is not a timestamp). One owner for
    the three-arm coercion the provider-refusal block carried inline
    (``reset_at``: an epoch or an ISO string, from a provider's error body).
    One implementation per input type (``functools.singledispatch`` — the
    standard library's type table, as :func:`agent_runtime.clock.iso_timestamp`).
    """

    return None


@number_or_bounded_text.register(bool)
def _number_or_text_from_bool(value: bool, *, limit: int) -> None:
    return None


@number_or_bounded_text.register(int)
@number_or_bounded_text.register(float)
def _number_or_text_from_number(value: float, *, limit: int) -> int | float:
    return value


@number_or_bounded_text.register(str)
def _number_or_text_from_text(value: str, *, limit: int) -> str | None:
    return safe_text(value, limit=limit)


def positive_int(value: Any, *, default: int | None = None) -> int | None:
    """``int(value)`` when it coerces and is > 0, else ``default``. Never raises.

    ``positive_int(x, default=0)`` is the non-negative count a token or call
    tally wants: a negative or unreadable value counts as none. A ``bool`` is not
    a count (``True`` is not 1): lane R3 folded ``profile_runner._positive_int``,
    whose budgets refused it, onto this owner.
    """

    parsed = strict_int(value)
    return parsed if parsed is not None and parsed > 0 else default


def positive_float(value: Any) -> float | None:
    """A positive, finite ``float(value)``, or ``None``. Never raises; a ``bool`` is
    not a number here. The run-budget seconds owner (lane R3 folded
    ``profile_runner._positive_float``; ``mcp_admission``'s copy folds in its lane).
    """

    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number <= 0 or number != number or number == float("inf"):
        return None
    return number


def safe_id(value: Any) -> str | None:
    """Sanitize a wire id into one safe to use as a filename or map key.

    ``None`` for anything that sanitizes away entirely, so a caller cannot
    silently address a row keyed on the empty string.
    """

    text = str(value or "").strip()
    if not text:
        return None
    cleaned = "".join(ch if ch.isalnum() or ch in "_.:-" else "_" for ch in text)
    return cleaned.strip("._:-")[:120] or None


def write_json_atomic(path: Path, record: dict[str, Any]) -> None:
    """tmp + rename, so a reader never sees a half-written record.

    The temp file is created in the DESTINATION directory (``os.replace`` is
    only atomic within a filesystem) and is unlinked on any failure, including
    ``KeyboardInterrupt`` — hence ``BaseException``.

    NOT the same helper as upstream's ``utils.atomic_json_write``, and it must
    not be folded into it. That one fsyncs and preserves mode/owner (correct
    for secret-bearing files) but opens the temp file in Python's default text
    mode, so on Windows it writes CRLF. Every record written through THIS one —
    the serve registry, the socket owner lock — is read back and compared as
    LF-canonical bytes, which is why ``newline="\\n"`` is pinned here. Two
    writers, two different guarantees, deliberately.
    """

    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(record, ensure_ascii=False, default=str, indent=2) + "\n"
    handle = tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        newline="\n",
        dir=str(path.parent),
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    )
    try:
        with handle:
            handle.write(payload)
        os.replace(handle.name, path)
    except BaseException:
        try:
            os.unlink(handle.name)
        except OSError:
            pass
        raise


def read_json(path: Path) -> Any:
    """``path``'s JSON, read as UTF-8; raises on a missing or undecodable file.

    The one plain reader (program rule 15); callers that must survive a bad
    file catch around it. ``store_file_io.read_json_object`` is the stricter,
    secure-path form and stays separate.
    """

    return json.loads(path.read_text(encoding="utf-8"))


def safe_assignment_token(value: Any) -> str:
    """``value`` as an id-safe token (alnum plus ``_ - .``, trimmed, at most 120
    characters); ``""`` when nothing survives. The persona-assignment rows'
    spelling — unlike :func:`safe_id` it keeps no ``:`` and never returns ``None``."""
    text = "".join(ch if ch.isalnum() or ch in {"_", "-", "."} else "_" for ch in str(value or "").strip())
    return text.strip("._-")[:120]


def safe_optional_token(value: Any) -> str | None:
    token = safe_assignment_token(value)
    return token or None


def dedupe_tokens(values: list[str] | None) -> list[str]:
    """Normalize + de-duplicate a parent-id list, preserving first-seen order.

    The first surviving token is treated as the PRIMARY parent everywhere
    (the ``spawned_by`` mirror, the projection's home owner), so order matters.
    """
    seen: set[str] = set()
    result: list[str] = []
    for value in values or []:
        token = safe_optional_token(value)
        if token and token not in seen:
            seen.add(token)
            result.append(token)
    return result


def safe_assignment_text(value: Any, *, limit: int) -> str:
    """:func:`safe_text`, spelled ``""`` for an empty value (store rows persist ``""``)."""
    return safe_text(value, limit=limit) or ""


def is_hex(text: str, length: int) -> bool:
    """Is ``text`` exactly ``length`` LOWERCASE hex digits? The one spelling.

    Lowercase only, because every caller has already lowered (or must not
    accept an upper-case spelling of an id it will compare byte-for-byte).
    """
    return len(text) == length and all(ch in "0123456789abcdef" for ch in text)
