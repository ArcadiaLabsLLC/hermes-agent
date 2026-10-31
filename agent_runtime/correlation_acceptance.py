"""CI-3: one gesture's correlation token, read in order across the two processes' logs.

Plan ``docs/agent-runtime-harness/planned/correlation-id-coverage.md`` P1. The acceptance is a
grep, scripted: perform one office gesture, then require, for its minted token, IN ORDER —

1. ``send``  — the launcher's ``office_write_sent`` transport receipt (``receipts.jsonl``, NDJSON,
   ``"corr": <token>``, ``"at"`` UTC ISO);
2. ``serve`` — the serve child's ``office_write op=… corr=<token>`` line
   (``agent_runtime.serve_rpc.office_read.log_office_write``, in ``agent.log``; its ``asctime`` is
   LOCAL time, converted with the reading machine's offset unless one is given);
3. ``fold``  — the launcher's ``fold_applied`` receipt whose ``corr`` label names the token (a
   comma-joined set: one fold can carry several gestures).

It READS logs and nothing else — no ``.hermes`` writes, no serve. The launcher spellings are
the other repository's contract (``EterniaLauncher/lib/core/services/hermes/runtime/data/
mission_transport_receipt.dart``, ``toWireJson``); a rename there makes this report ``missing``,
never a pass. ``scripts/correlation_id_acceptance.py`` is the argv and the exit code.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Iterable

__layer__ = "policy"
__all__ = ["HOPS", "VERDICT_JOINED", "VERDICT_MISSING", "VERDICT_OUT_OF_ORDER", "Hop", "join_token", "read_hops"]

#: The three hops, in the order a gesture must produce them.
HOPS = ("send", "serve", "fold")

VERDICT_JOINED = "joined"
VERDICT_MISSING = "missing"
VERDICT_OUT_OF_ORDER = "out_of_order"

#: launcher receipt kind -> hop (``missionTransportReceiptWireName``: snake_case of the enum name)
_RECEIPT_HOPS = {"office_write_sent": "send", "fold_applied": "fold"}
_SERVE_LINE = re.compile(r"^(?P<stamp>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3}) .*?office_write op=(?P<op>\S+) corr=(?P<corr>\S+)")


@dataclass(frozen=True)
class Hop:
    hop: str
    at: datetime  # aware, UTC
    source: str
    detail: str


def _receipt_hop(line: str, token: str, source: str) -> Hop | None:
    try:
        row = json.loads(line)
    except ValueError:
        return None
    if not isinstance(row, dict):
        return None
    hop = _RECEIPT_HOPS.get(str(row.get("kind") or ""))
    if hop is None or token not in str(row.get("corr") or "").split(","):
        return None
    try:
        at = datetime.fromisoformat(str(row.get("at") or ""))
    except ValueError:
        return None
    at = at if at.tzinfo is not None else at.replace(tzinfo=UTC)
    return Hop(hop, at.astimezone(UTC), source, str(row.get("detail") or ""))


def _serve_hop(line: str, token: str, source: str, serve_offset: timedelta) -> Hop | None:
    match = _SERVE_LINE.search(line)
    if match is None or match["corr"] != token:
        return None
    local = datetime.strptime(match["stamp"], "%Y-%m-%d %H:%M:%S,%f")
    return Hop("serve", (local - serve_offset).replace(tzinfo=UTC), source, match["op"])


def read_hops(token: str, sources: Iterable[tuple[str, Iterable[str]]], *, serve_offset: timedelta) -> list[Hop]:
    """Every hop line for *token* across *sources* (``(name, lines)``), sorted by instant."""

    hops: list[Hop] = []
    for name, lines in sources:
        for line in lines:
            if token not in line:
                continue
            hop = _receipt_hop(line, token, name) or _serve_hop(line, token, name, serve_offset)
            if hop is not None:
                hops.append(hop)
    return sorted(hops, key=lambda item: item.at)


def join_token(token: str, sources: Iterable[tuple[str, Iterable[str]]], *, serve_offset: timedelta) -> dict:
    """The report: each hop's FIRST sighting, and whether send <= serve <= fold held."""

    hops = read_hops(token, sources, serve_offset=serve_offset)
    first: dict[str, Hop] = {}
    for hop in hops:
        first.setdefault(hop.hop, hop)
    missing = [name for name in HOPS if name not in first]
    if missing:
        verdict = VERDICT_MISSING
    else:
        instants = [first[name].at for name in HOPS]
        verdict = VERDICT_JOINED if instants == sorted(instants) else VERDICT_OUT_OF_ORDER
    return {
        "token": token,
        "verdict": verdict,
        "missing": missing,
        "hops": {name: {"at": hop.at.isoformat(), "source": hop.source, "detail": hop.detail}
                 for name, hop in first.items()},
        "sightings": len(hops),
    }
