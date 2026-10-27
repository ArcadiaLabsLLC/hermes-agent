"""The ``sql_readonly`` source: one read-only statement against a local SQLite file.

Plan ``p10-agent-2026-10-19.md`` §5.5 L4.3. ``sqlite3`` from the standard library;
three locks on writing, any one of which refuses a write:

* the statement must begin with ``SELECT`` or ``WITH`` (``feed.READ_ONLY_STATEMENT``),
  checked here again before the file is opened — a statement that does not is a
  ``statement_refused`` read that never reaches SQLite;
* the file is opened ``mode=ro`` (a URI open), and ``PRAGMA query_only`` is set, so
  a ``WITH … DELETE`` that passes the prefix still writes nothing;
* ``sqlite3`` executes one statement per call (a second is ``query_failed``).

The answer must be ONE row of ONE column holding a finite number: no row is
``no_series``, more than one row or column is ``ambiguous_series`` (picking one
would be a guess), and anything else is ``not_a_number``. A statement running past
:data:`TIMEOUT_SECONDS` is interrupted and read as ``timeout``.
"""

from __future__ import annotations

import sqlite3
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

from ..feed import READ_ONLY_STATEMENT
from ..shapes import sql_skeleton
from .http_json import number_of
from .transport import ReadReason, ReadResult, unavailable

__layer__ = "lanes"

TIMEOUT_SECONDS = 10.0
#: How many SQLite VM steps pass between two deadline checks.
_PROGRESS_STEPS = 10_000


def read(feed: dict[str, Any], *, headers: dict[str, str], client: Any = None, resolver: Any = None) -> ReadResult:
    source = feed["source"]
    if READ_ONLY_STATEMENT.match(source["query"]) is None:
        return unavailable(ReadReason.STATEMENT_REFUSED)
    deadline = time.monotonic() + TIMEOUT_SECONDS
    try:
        connection = sqlite3.connect(Path(source["database"]).as_uri() + "?mode=ro", uri=True,
                                     timeout=TIMEOUT_SECONDS)
    except (sqlite3.Error, ValueError):
        return unavailable(ReadReason.QUERY_FAILED)
    try:
        connection.execute("PRAGMA query_only = ON")
        connection.set_progress_handler(lambda: 1 if time.monotonic() > deadline else 0, _PROGRESS_STEPS)
        cursor = connection.execute(source["query"])
        rows = cursor.fetchmany(2)
        columns = [str(column[0]) for column in cursor.description or ()]
    except sqlite3.OperationalError as exc:
        return unavailable(ReadReason.TIMEOUT if "interrupt" in str(exc).lower() else ReadReason.QUERY_FAILED)
    except sqlite3.Error:
        return unavailable(ReadReason.QUERY_FAILED)
    finally:
        connection.close()
    return replace(_row_read(rows), shape=sql_skeleton(columns, rows[0] if rows else None))


def _row_read(rows: list[Any]) -> ReadResult:
    if not rows:
        return unavailable(ReadReason.NO_SERIES)
    if len(rows) > 1 or len(rows[0]) != 1:
        return unavailable(ReadReason.AMBIGUOUS_SERIES)
    number = number_of(rows[0][0])
    if number is None:
        return unavailable(ReadReason.NOT_A_NUMBER)
    return ReadResult(value=number, reason=ReadReason.OK)
