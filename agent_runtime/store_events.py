"""The one way a store appends its DOMAIN event (program rule 15).

Every store that writes a file also appends a typed ``EventLog`` event for the
mutation — the standing store rule: an event-less write is invisible to the
watermark-gated snapshot/serve pipeline. The append itself is best-effort BY
CONTRACT: the file write has already happened, so a failed append is logged and
swallowed rather than turned into a failed write the caller would retry.

Callers: ``office_store`` (through ``OfficeStore._emit``, which adds the
gesture token first), ``store`` (every workspace / realm / persona write),
``board_store`` (``BoardStore._emit``) and ``dispatch_store`` (``db._emit``,
over a fresh ``EventLog()``). ``serve``'s ``_emit`` is a FRAME
writer, not this — it is named here so nobody folds it.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from hermes_time import now

from agent_runtime.events import EventLog
from agent_runtime.models import Event

__layer__ = "stores"

__all__ = ["emit_store_event"]


def emit_store_event(
    event_log: EventLog, event_type: str, payload: Mapping[str, Any], *, domain: str
) -> None:
    """Append ``event_type`` with ``payload`` minus its ``None`` fields; never raises.

    ``None`` is filtered, not written, so a field that is absent for this event
    keeps the payload byte-identical to an event that never had the key.
    ``domain`` names the store in the warning a failed append leaves behind.
    """

    try:
        body = {key: value for key, value in payload.items() if value is not None}
        event_log.append(Event(now(), event_type, None, None, None, body))
    except Exception:
        logging.getLogger(__name__).warning(
            "%s event append failed: %s", domain, event_type, exc_info=True
        )
