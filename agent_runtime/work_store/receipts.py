"""Work receipts — one JSON log line per write, read back from the serve log (plan §6.2).

Observability lands as log receipts, never as new keys on a parity envelope: the serve log IS the
receipt log. ``emit`` returns the record it logged so a caller can also put it on its RPC reply.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

__layer__ = "models"
__all__ = ["emit"]

logger = logging.getLogger("agent_runtime.work_store.receipts")


def emit(kind: str, **fields: Any) -> dict[str, Any]:
    """Log ``{"kind": kind, "at": <utc>, **fields}`` as one sorted JSON line; return the record."""

    record = {"kind": kind, "at": datetime.now(UTC).isoformat(timespec="seconds"), **fields}
    from ..namespace import namespace_stamp  # the store this receipt was written in (RT-NAMESPACE-STAMP)

    logger.info("%s", json.dumps({"namespace": namespace_stamp(), **record}, sort_keys=True, default=str))
    return record
