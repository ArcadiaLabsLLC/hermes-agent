"""The ``peers join`` payload grammar: parse the pasted payload, clean the
candidate list it carries.
"""

from __future__ import annotations

import json
from typing import Any

from agent_runtime.gateway_endpoints.addresses import (
    MAX_CANDIDATE_ENDPOINTS,
    _WILDCARD_HOSTS,
)
from hermes_cli.harness_support import emit_harness_error

__layer__ = "policy"


def _parse_join_payload(raw: Any, args) -> dict[str, Any] | None:
    """The join payload as fields, or ``None`` with the refusal already printed.

    Accepts BOTH halves of R3: the JSON blob a QR carries, and a bare
    eight-character code with ``--host`` / ``--port`` / ``--fingerprint``
    supplied beside it. One parser, so the typed and the scanned paths cannot
    disagree about what a payload means.
    """

    text = str(raw or "").strip()
    fields: dict[str, Any] = {}
    if text.startswith("{"):
        try:
            decoded = json.loads(text)
        except (json.JSONDecodeError, ValueError) as exc:
            emit_harness_error(
                exc,
                args=args,
                code="invalid_payload",
                reason="payload_not_json",
                message=f"the join payload is not JSON: {exc}",
            )
            return None
        if not isinstance(decoded, dict):
            emit_harness_error(
                RuntimeError("payload_not_an_object"),
                reason="payload_not_an_object",
                args=args,
                code="invalid_payload",
                message="the join payload must be a JSON object",
            )
            return None
        fields = decoded
    else:
        fields = {"peer_code": text}

    # Flags OVERRIDE the payload rather than filling in behind it. An operator
    # who typed --host did so because the payload's address is wrong for their
    # network (a second interface, a NAT, a machine that moved), and a merge that
    # preferred the payload would silently ignore the correction.
    overridden = bool(getattr(args, "host", None)) or bool(getattr(args, "port", None))
    for flag, key in (
        ("host", "host"),
        ("port", "port"),
        ("fingerprint", "cert_fingerprint"),
    ):
        value = getattr(args, flag, None)
        if value:
            fields[key] = value

    code = str(fields.get("peer_code") or "").strip().upper()
    # R-D3's list, read here so the dial loop below never has to know which
    # spelling of a payload it was given. Three sources, in this order:
    #
    # * ``--host/--port`` — a SINGLE candidate. An operator (or the launcher's
    #   redeemer, which passes one candidate per run) who names an address means
    #   that address and not a list to fall back through.
    # * the payload's ``endpoints``, which is what every writer on this lane has
    #   emitted since R-D3.
    # * the payload's legacy ``host``/``port`` as a one-row list, which is what
    #   an install that predates this key sends. Not a compatibility shim to
    #   delete later: a bare code typed with --host/--port arrives the same way.
    candidates = _clean_candidates(fields.get("endpoints"))
    host = str(fields.get("host") or "").strip()
    try:
        port = int(fields.get("port") or 0)
    except (TypeError, ValueError):
        port = 0
    if candidates and not (host and port):
        # A payload carrying only the list still names a first candidate, and
        # ``host``/``port`` are that row by contract — so filling them in here is
        # reading the contract, not guessing.
        host, port = candidates[0]["host"], candidates[0]["port"]
    if overridden or not candidates:
        candidates = [{"host": host, "port": port}] if host and port else []
    missing = [
        name
        for name, value in (("peer_code", code), ("host", host), ("port", port))
        if not value
    ]
    if missing:
        emit_harness_error(
            RuntimeError("incomplete_payload"),
            reason="incomplete_payload",
            args=args,
            code="invalid_payload",
            message=(
                f"the join payload is missing {', '.join(missing)}. Paste the "
                "join_payload string from `harness gateway peers pair` on the "
                "other install, or pass the code with --host/--port. A payload "
                "carrying `code` rather than `peer_code` is a DEVICE pairing "
                "payload and cannot be joined as a peer."
            ),
        )
        return None
    return {
        "peer_code": code,
        "host": host,
        "port": port,
        "endpoints": candidates,
        "install_id": str(fields.get("install_id") or "").strip() or None,
        "cert_fingerprint": str(fields.get("cert_fingerprint") or "").strip() or None,
    }


def _clean_candidates(raw: Any) -> list[dict]:
    """A payload's ``endpoints`` as rows this verb can dial, order preserved.

    Deliberately forgiving about the CONTENTS and strict about the SHAPE: a row
    without a usable host or port is dropped rather than refusing the whole
    payload, because the list is advertisement — the far install offered every
    address it could think of — and one unusable row is not a reason to refuse
    an edge that three good rows would have made. A payload with nothing usable
    in it falls through to the legacy ``host``/``port`` above and is refused
    there, by name, if those are absent too.
    """

    if not isinstance(raw, list):
        return []
    rows: list[dict] = []
    for item in raw[:MAX_CANDIDATE_ENDPOINTS]:
        if not isinstance(item, dict):
            continue
        host = str(item.get("host") or "").strip()
        try:
            port = int(item.get("port") or 0)
        except (TypeError, ValueError):
            continue
        if not host or host.lower() in _WILDCARD_HOSTS or not port:
            continue
        row = {"host": host, "port": port}
        if row not in rows:
            rows.append(row)
    return rows
