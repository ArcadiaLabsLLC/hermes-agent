"""Monotonic-clock helpers the fork shares: one owner each (program rule 15).

A stdlib-only leaf, like :mod:`agent_runtime.serde`, so any module may import it
without risking a cycle. ``now_iso`` is the millisecond, ``Z``-suffixed UTC
stamp ``serve_socket`` and ``serve_registry`` each spelled as ``_now_iso``
(god-file program §4; lane R3 folded the first). ``iso_timestamp`` is the
wall-clock normalizer lane R2 moved out of ``persona_chat_history``.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from functools import singledispatch

__layer__ = "models"
__all__ = ["elapsed_ms", "iso_timestamp", "now_iso"]


def elapsed_ms(started: object) -> int | None:
    """Milliseconds since a ``time.monotonic()`` reading, floored at 0.

    ``None`` when ``started`` is not a number — an unstamped segment has no
    duration, and reporting 0 would claim it had one.
    """

    try:
        began = float(started)  # type: ignore[arg-type]
    except Exception:  # noqa: BLE001 — an unreadable stamp has no duration
        return None
    return max(0, int((time.monotonic() - began) * 1000))


@singledispatch
def iso_timestamp(value: object) -> str | None:
    """Normalize a stored timestamp to one ISO-8601 ``Z`` form; ``None`` when it is not one.

    SessionDB stores message timestamps as epoch-seconds floats (``time.time()``),
    while harness-trace rows carry ISO strings (``Event.ts`` via ``to_jsonable``).
    The Launcher merges the two channels by parsing each ``ts`` with
    ``DateTime.tryParse`` and orders them — an epoch float is unparseable there, so
    without this the curated rows lose their time and the trace block jumps
    ahead of them. Project message and session timestamps in one comparable UTC
    format, and never pass raw unparseable values through the snapshot contract.

    One implementation per input type (``functools.singledispatch`` — the
    standard library's type table): ``datetime``, the two numeric types (epoch
    seconds, or milliseconds), ``str`` (a numeric string is an epoch, otherwise
    ISO-8601). ``bool`` and every other type answer ``None``.
    """

    return None


def _iso_z(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _iso_from_epoch(epoch: float) -> str | None:
    if epoch > 1e12:  # tolerate millisecond clocks
        epoch /= 1000.0
    try:
        return _iso_z(datetime.fromtimestamp(epoch, tz=timezone.utc))
    except (OverflowError, OSError, ValueError):
        return None


@iso_timestamp.register(datetime)
def _iso_from_datetime(value: datetime) -> str | None:
    return _iso_z(value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc))


@iso_timestamp.register(bool)
def _iso_from_bool(value: bool) -> str | None:
    return None


@iso_timestamp.register(int)
@iso_timestamp.register(float)
def _iso_from_number(value: float) -> str | None:
    return _iso_from_epoch(float(value))


@iso_timestamp.register(str)
def _iso_from_text(value: str) -> str | None:
    text = value.strip()
    if not text:
        return None
    try:
        epoch = float(text)
    except ValueError:
        pass
    else:
        return _iso_from_epoch(epoch)
    parse_text = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(parse_text)
    except ValueError:
        return None
    return _iso_z(parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc))


def now_iso() -> str:
    """Now, UTC, as ``YYYY-MM-DDTHH:MM:SS.mmmZ`` — the serve lane's stamp."""

    return (
        datetime.now(tz=timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )
