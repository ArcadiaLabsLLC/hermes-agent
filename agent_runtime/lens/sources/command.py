"""The ``command_allowlisted`` source: one argv from the sealed manifest's allow list.

Plan ``p10-agent-2026-10-19.md`` §5.5 L4.3. The feed's ``argv`` runs only when it
EQUALS one of the feed's ``allow`` lists (compared here again, so a hand-built feed
cannot skip the manifest's check — an argv outside the list is ``command_refused``
and nothing starts), and only from a sealed manifest (``sources.read_feed_source``
answers ``not_sealed`` to a preview of a draft). No shell: the argv is handed to
the OS as a list (``shell=False``), stdin is empty, the run is capped at
:data:`TIMEOUT_SECONDS` (``timeout``) and stdout at :data:`MAXIMUM_OUTPUT_BYTES`
(``too_large``). A command that does not start or exits non-zero is
``command_failed``; stderr is never read into the store.

Stdout is a JSON document (a bare ``42`` is one) and the feed's ``extract`` — the
poll door's bounded ``$.a.b[0]`` selector — takes the number.
"""

from __future__ import annotations

import json
import subprocess
from typing import Any

from .http_json import document_read
from .transport import ReadReason, ReadResult, unavailable

__layer__ = "lanes"

TIMEOUT_SECONDS = 10.0
MAXIMUM_OUTPUT_BYTES = 64 * 1024


def allowed(source: dict[str, Any]) -> bool:
    """True when the source's argv is exactly one of its allow lists."""

    argv = list(source["argv"])
    return any(list(entry) == argv for entry in source["allow"])


def read(feed: dict[str, Any], *, headers: dict[str, str], client: Any = None, resolver: Any = None) -> ReadResult:
    source = feed["source"]
    if not allowed(source):
        return unavailable(ReadReason.COMMAND_REFUSED)
    try:
        done = subprocess.run(list(source["argv"]), shell=False, stdin=subprocess.DEVNULL, capture_output=True,
                              timeout=TIMEOUT_SECONDS, check=False,
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except subprocess.TimeoutExpired:
        return unavailable(ReadReason.TIMEOUT)
    except (OSError, ValueError):
        return unavailable(ReadReason.COMMAND_FAILED)
    if done.returncode != 0:
        return unavailable(ReadReason.COMMAND_FAILED)
    if len(done.stdout) > MAXIMUM_OUTPUT_BYTES:
        return unavailable(ReadReason.TOO_LARGE)
    try:
        document = json.loads(done.stdout.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return unavailable(ReadReason.NOT_JSON)
    return document_read(document, source["extract"])
