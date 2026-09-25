"""The row and source shape every lane emits: bounded operator text, the ISO
stamps, progress, the row, the preview, the source entry and the per-lane cap."""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from typing import Any

from ..parity import ProjectionAccountant
from ..redaction import TEXT_SECRET_ASSIGNMENT_RE

from .vocabulary import SOURCE_OK, SOURCE_UNAVAILABLE, TAIL_PREVIEW_LIMIT, _FALLBACK_STALE_IDLE_SECONDS, _FALLBACK_STALE_IN_TOOL_SECONDS, _MAX_ROWS_PER_SOURCE

__layer__ = "policy"


def _safe_text(value: Any, *, limit: int) -> str:
    """Whitespace-collapsed, secret-masked, length-bounded operator text.

    Mirrors ``snapshot._safe_text``'s ruling: repo paths are the CONTENT on an
    operator console, not a leak, so only secret-shaped assignments are masked —
    and they are masked in place rather than dropping the whole string.
    """

    if value is None:
        return ""
    text = " ".join(str(value).split())
    if not text:
        return ""
    text = TEXT_SECRET_ASSIGNMENT_RE.sub(lambda m: f"{m.group(1)}: [redacted]", text)
    if len(text) > limit:
        return text[: max(0, limit - 1)] + "…"
    return text


def _iso(epoch: Any) -> str:
    """UTC ISO-8601 for an epoch-seconds value; empty string when unusable."""

    try:
        seconds = float(epoch)
    except (TypeError, ValueError):
        return ""
    if seconds <= 0:
        return ""
    try:
        return datetime.fromtimestamp(seconds, timezone.utc).isoformat()
    except (OverflowError, OSError, ValueError):
        return ""


def _parse_iso(text: Any) -> float | None:
    """Epoch seconds for an ISO-8601 stamp, or None when unparseable.

    Accepts the ``Z`` suffix the turn journal writes. A naive stamp is read as
    UTC — the journal writes UTC — rather than as local time, which would make
    ``elapsed_seconds`` jump by the machine's offset.
    """

    raw = str(text or "").strip()
    if not raw:
        return None
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


def _iso_from_naive_local(text: Any) -> str:
    """UTC ISO-8601 for the naive LOCAL stamp the process registry emits.

    ``process_registry.list_sessions`` formats ``started_at`` with
    ``time.localtime`` and no offset, so the string is unanchored: two rows on
    one wire would carry stamps in different frames of reference depending on
    which lane produced them, and any consumer parsing them (the launcher's
    elapsed clock, this module's own ``--issued-at`` replay guard) would be off
    by the machine's UTC offset without anything looking wrong.

    Normalizing HERE rather than in ``process_registry`` is deliberate: that
    function has other consumers (the ``process`` tool's ``list`` action, the
    goal-loop judge) whose displayed output would change under them. The
    projection is the boundary that publishes a wire contract, so the
    projection is where the stamp gets anchored.

    Already-anchored input is passed through, and anything unparseable is
    returned empty rather than guessed at.
    """

    raw = str(text or "").strip()
    if not raw:
        return ""
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return ""
    if parsed.tzinfo is None:
        # `astimezone()` on a naive datetime interprets it as local time, which
        # is exactly what `time.localtime` produced.
        parsed = parsed.astimezone()
    return parsed.astimezone(timezone.utc).isoformat()


def _elapsed(started_epoch: float | None, *, now: float) -> int:
    if started_epoch is None:
        return 0
    return int(max(0.0, now - started_epoch))


def _module(name: str):
    """The already-imported module, or None.

    Deliberately ``sys.modules.get`` and never ``importlib.import_module``: a
    read-only projection must not pay an import cost — or, for
    ``tools.process_registry``, construct a tool singleton — as a side effect of
    being asked a question.

    Residency is a NECESSARY condition for a live answer, never a sufficient
    one: see the module docstring. Callers must prove ownership separately.
    """

    return sys.modules.get(name)


def _stale_thresholds() -> tuple[float, float]:
    """``(idle, in_tool)`` stale seconds, read from the ONE authority that owns them.

    ``tools.async_delegation`` defines these for its own stale monitor. Reading
    them off the resident module keeps this projection's staleness verdict
    identical to the monitor's instead of standing up a second set of numbers
    that could silently drift apart.
    """

    mod = _module("tools.async_delegation")
    if mod is None:
        return _FALLBACK_STALE_IDLE_SECONDS, _FALLBACK_STALE_IN_TOOL_SECONDS
    return (
        float(getattr(mod, "_STALE_IDLE_SECONDS", _FALLBACK_STALE_IDLE_SECONDS)),
        float(getattr(mod, "_STALE_IN_TOOL_SECONDS", _FALLBACK_STALE_IN_TOOL_SECONDS)),
    )


def _progress(
    *,
    api_calls: Any = None,
    in_tool: Any = None,
    seconds_since_progress: Any = None,
    available: bool,
) -> dict[str, Any]:
    """The row's progress block.

    ``available: False`` emits explicit nulls plus ``source: "unavailable"``
    rather than zeros — a zero here reads as "idle right now", which is a
    different (and unproven) claim from "this lane cannot see progress".
    """

    if not available:
        return {
            "api_calls": None,
            "in_tool": None,
            "seconds_since_progress": None,
            "source": SOURCE_UNAVAILABLE,
        }
    return {
        "api_calls": int(api_calls) if isinstance(api_calls, (int, float)) else None,
        "in_tool": in_tool if isinstance(in_tool, str) and in_tool else bool(in_tool) if in_tool is not None else None,
        "seconds_since_progress": (
            round(float(seconds_since_progress), 1)
            if isinstance(seconds_since_progress, (int, float))
            else None
        ),
        "source": SOURCE_OK,
    }


def _row(
    *,
    kind: str,
    stable_id: str,
    label: str,
    status: str,
    source_lane: str,
    command: str = "",
    pid: Any = None,
    pid_verified: bool = False,
    persona_id: str = "",
    persona_instance_id: str = "",
    session_id: str = "",
    started_at: str = "",
    elapsed_seconds: int = 0,
    progress: dict[str, Any] | None = None,
    tail_preview: str = "",
    cancellable: bool = False,
) -> dict[str, Any]:
    return {
        "work_id": f"{kind}:{stable_id}",
        "kind": kind,
        "label": label,
        "command": command,
        "pid": int(pid) if isinstance(pid, int) or (isinstance(pid, str) and pid.isdigit()) else None,
        "pid_verified": bool(pid_verified),
        "owner": {
            "persona_id": persona_id or None,
            "persona_instance_id": persona_instance_id or None,
            "session_id": session_id or None,
        },
        "status": status,
        "started_at": started_at,
        "elapsed_seconds": int(max(0, elapsed_seconds)),
        "progress": progress if progress is not None else _progress(available=False),
        "tail_preview": tail_preview,
        "source_lane": source_lane,
        "cancellable": bool(cancellable),
    }


def _preview(text: Any, accountant: ProjectionAccountant | None) -> str:
    """Bounded, secret-masked inline preview; truncation declared by design."""

    raw = str(text or "")
    if not raw:
        return ""
    stripped = _strip_ansi(raw)
    bounded = _safe_text(stripped, limit=TAIL_PREVIEW_LIMIT)
    if accountant is not None and len(" ".join(stripped.split())) > TAIL_PREVIEW_LIMIT:
        accountant.drop(
            "tail_truncated",
            detail=f"preview bounded to {TAIL_PREVIEW_LIMIT} chars",
            by_design=True,
        )
    return bounded


def _strip_ansi(text: str) -> str:
    """ANSI-strip through the repo's one implementation when it is resident.

    Terminal output previews come from a PTY, so escape sequences are the norm
    rather than the exception. The stripper lives beside the process registry;
    when that tree is not loaded (durable lane) the checkpoint carries no output
    anyway, so the untouched text is returned rather than importing a tool
    module into a projection.
    """

    try:
        from tools.ansi_strip import strip_ansi
    except Exception:
        return text
    try:
        return strip_ansi(text)
    except Exception:
        return text


def _source(
    status: str,
    *,
    lane: str = "",
    reason: str = "",
    detail: str = "",
    live_enrichment_error: str = "",
) -> dict[str, Any]:
    """One lane's CONTRACT health entry. Ambient facts do not belong here.

    ``detail`` is reserved for the bounded machine token an UNAVAILABLE lane
    attaches (an exception class name) — never prose, and never anything the
    filesystem or the environment decides. Machine-local context rides
    :func:`_ambient_context` instead, where no consumer is asked to parse it
    back out of a sentence.

    ``live_enrichment_error`` is the typed counterpart of the old
    ``"; live enrichment failed: TypeError"`` suffix: a lane whose durable
    answer stands but whose live enrichment raised is still ``ok``, and the
    reader must be able to see the difference without sentence-matching.
    """

    entry: dict[str, Any] = {"status": status}
    if lane:
        entry["lane"] = lane
    if reason:
        entry["reason"] = reason
    if detail:
        entry["detail"] = _safe_text(detail, limit=240)
    if live_enrichment_error:
        entry["live_enrichment_error"] = _safe_text(live_enrichment_error, limit=80)
    return entry


def _cap(
    rows: list[dict[str, Any]],
    *,
    source: str,
    accountant: ProjectionAccountant | None,
) -> list[dict[str, Any]]:
    if len(rows) <= _MAX_ROWS_PER_SOURCE:
        return rows
    if accountant is not None:
        accountant.drop(
            "lane_capped",
            count=len(rows) - _MAX_ROWS_PER_SOURCE,
            entity_id=source,
            detail=f"{source} lane bounded to {_MAX_ROWS_PER_SOURCE} rows",
            by_design=True,
        )
        accountant.mark_truncated()
    return rows[:_MAX_ROWS_PER_SOURCE]
