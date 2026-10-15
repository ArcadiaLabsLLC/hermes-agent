"""The composed-user-content bound: per-part ceilings, typed bound notes, redaction."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any

from ..redaction import TEXT_SECRET_ASSIGNMENT_RE, TEXT_SECRET_KEYS

__layer__ = "policy"

logger = logging.getLogger(__name__)


# Single-homed in ``agent_runtime.redaction`` — see the header there for the
# JSON blind spot every local spelling shared. group(1) is still the key, so
# the ``\1: [redacted]`` rebuild below is unchanged; the value shape widens
# from ``[^\s,;]+`` to ``\S+``, which only removes MORE of the offending run.
_SECRET_RE = TEXT_SECRET_ASSIGNMENT_RE

#: Total ceiling for ONE composed operator user row (message · skill_preload ·
#: runtime_context). Runtime envelopes share the space left after the admitted operator text.
#: The operator text is never truncated here; admission owns its limit.
#:
#: 262,144 characters is ~4.6x the largest real preload measured on this lane (qa's
#: ``launcher-mcp-operations``, formerly ``launcher-stagec-mcp-screenshot``,
#: 54 KB) and it is paid at most ONCE per
#: thread: turn 2+ delivers the compact ``unchanged`` stub, so steady-state rows
#: are a few hundred bytes.
_MAX_USER_ROW_CONTENT = 262_144

#: Priority slice for the runtime-context (HUD) envelope. Served FIRST, because
#: it is the smallest load-bearing part: the wall-budget countdown, roster,
#: scope, and steering lines. Under the previous single flat cap it composed
#: LAST and was therefore the first thing amputated — on exactly the personas
#: whose turns run long enough for a budget warning to matter.
_MAX_RUNTIME_CONTEXT_CONTENT = 32_000

#: Runtime-envelope parts that may produce typed bound notes.
BOUND_PART_SKILL_PRELOAD = "skill_preload"
BOUND_PART_RUNTIME_CONTEXT = "runtime_context"

#: The parts that make up a row's ``content``, and therefore the only ones whose
#: losses belong in the content arithmetic.
CONTENT_BOUND_PARTS = frozenset(
    {
        BOUND_PART_SKILL_PRELOAD,
        BOUND_PART_RUNTIME_CONTEXT,
    }
)

BOUND_ACTION_TRUNCATED = "truncated"
BOUND_ACTION_DROPPED = "dropped"

#: In-band marker for bounded free text. Unchanged spelling — a persisted row
#: carrying it must keep reading the same way it always has.
_TRUNCATION_MARKER = " … [truncated]"


@dataclass(frozen=True, slots=True)
class ContentBoundNote:
    """One part of a composed row that did not survive its bound intact."""

    part: str
    action: str
    original_chars: int
    bounded_chars: int
    limit: int


@dataclass(frozen=True, slots=True)
class BoundedUserContent:
    """A bounded composed user row, plus what the bound did to it.

    ``notes`` is the whole point. A bound that silently amputates structured
    content mid-token is worse than one that cuts a part and says so, and the
    2026-08-09 F1 finding is what that costs: 37% of a required skill delivered
    mid-sentence, the HUD gone entirely, and — because the amputation took the
    ``</skill_preload>`` closing tag with it — the ``unchanged`` dedupe made
    structurally unreachable, re-shipping ~3.7 k tokens every turn forever.
    """

    text: str
    notes: tuple[ContentBoundNote, ...] = ()
    #: Length of the content this bound was applied TO, measured after redaction
    #: and before any part was cut. Carried so the caller can prove the arithmetic
    #: closes — ``source_chars - len(text)`` must equal the loss the notes
    #: account for. A residue means content left through a path with no note on
    #: it, which is the exact class of defect the notes exist to retire.
    source_chars: int = 0

    @property
    def bounded(self) -> bool:
        return bool(self.notes)

    @property
    def accounted_loss(self) -> int:
        """Characters the notes explain."""

        return sum(max(0, note.original_chars - note.bounded_chars) for note in self.notes)


def _redacted(value: Any) -> str:
    text = str(value or "").replace("\x00", " ")
    # Native history has always treated explicit secret fields as sensitive,
    # including short values upstream's general text heuristics leave intact.
    # Preserve JSON siblings and leave non-secret argument bytes unchanged.
    try:
        parsed = json.loads(text)
    except (ValueError, RecursionError):
        parsed = None
    changed = False

    def redact_fields(item):
        nonlocal changed
        if isinstance(item, dict):
            for key, child in item.items():
                if re.search(r"(?:" + TEXT_SECRET_KEYS + r")$", key, re.IGNORECASE):
                    item[key] = "[redacted]"
                    changed = True
                else:
                    redact_fields(child)
        elif isinstance(item, list):
            for child in item:
                redact_fields(child)

    if isinstance(parsed, (dict, list)):
        try:
            redact_fields(parsed)
        except RecursionError:
            return "[redacted]"
        if changed:
            text = json.dumps(parsed, ensure_ascii=False)
    try:
        from agent.redact import redact_sensitive_text

        return redact_sensitive_text(text, force=True)
    except Exception:
        return _SECRET_RE.sub(r"\1: [redacted]", text)


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    keep = max(0, limit - len(_TRUNCATION_MARKER))
    return text[:keep].rstrip() + _TRUNCATION_MARKER


def _bound_envelope(
    envelope: str, *, limit: int, part: str, codec: Any
) -> tuple[str, ContentBoundNote | None]:
    """Bound one envelope by shrinking its BODY, never its tags.

    The opening tag and its attributes are what every downstream consumer reads:
    the transcript projection strips on them, and the skill preload's
    ``unchanged`` dedupe matches on ``revision``/``delivery``. Cutting through
    them is what turned a size problem into a correctness one.

    The whole part is dropped only when the budget cannot hold the tags at all —
    at that size there is no well-formed envelope to emit, and an honest absence
    beats a broken one.
    """

    original = len(envelope)
    if original <= limit:
        return envelope, None
    body = codec.body(envelope)
    if body is None:
        # Not this grammar (a legacy row, a hand-edited one): treat it as opaque
        # free text rather than hand-editing tags we did not parse.
        bounded = _truncate(envelope, limit)
        return bounded, ContentBoundNote(
            part=part,
            action=BOUND_ACTION_TRUNCATED,
            original_chars=original,
            bounded_chars=len(bounded),
            limit=limit,
        )
    body_limit = limit - (original - len(body))
    if body_limit <= len(_TRUNCATION_MARKER):
        return "", ContentBoundNote(
            part=part,
            action=BOUND_ACTION_DROPPED,
            original_chars=original,
            bounded_chars=0,
            limit=limit,
        )
    bounded = codec.with_body(envelope, _truncate(body, body_limit)) or ""
    return bounded, ContentBoundNote(
        part=part,
        action=BOUND_ACTION_TRUNCATED,
        original_chars=original,
        bounded_chars=len(bounded),
        limit=limit,
    )


def bound_composed_user_content(value: Any) -> BoundedUserContent:
    """Bound one operator user row PER PART, in priority order.

    Order of service is the contract, not an implementation detail:

    1. the runtime-context (HUD) envelope — smallest, load-bearing, must always
       arrive;
    2. the operator's own text — reserved intact before envelope allocation;
    3. the skill preload — largest and the only part with its own re-delivery
       machinery, so it absorbs whatever room is left.

    Plain native user rows retain their full text, including historical rows.
    """

    # Function-local by the same precedent ``prompt_observability`` documents:
    # ``runtime_hud`` pulls a sizeable dependency graph and this module is
    # imported very early. It is guaranteed importable on any lane that composes
    # an envelope (``mission_chat_turn_context`` imports it at module scope), so
    # no defensive swallow — a silent degrade here would restore F1.
    from ..runtime_hud.envelopes import (
        RUNTIME_CONTEXT_CODEC,
        SKILL_PRELOAD_CODEC,
        split_composed_user_row,
    )

    text = _redacted(value)
    parts = split_composed_user_row(text)
    if not parts.has_envelope:
        return BoundedUserContent(text=text, source_chars=len(text))

    notes: list[ContentBoundNote] = []
    message = parts.message
    remaining = max(0, _MAX_USER_ROW_CONTENT - len(message))

    hud, note = _bound_envelope(
        parts.runtime_context,
        limit=min(_MAX_RUNTIME_CONTEXT_CONTENT, remaining),
        part=BOUND_PART_RUNTIME_CONTEXT,
        codec=RUNTIME_CONTEXT_CODEC,
    )
    if note is not None:
        notes.append(note)
    remaining -= len(hud)

    preload, note = _bound_envelope(
        parts.skill_preload,
        limit=max(0, remaining),
        part=BOUND_PART_SKILL_PRELOAD,
        codec=SKILL_PRELOAD_CODEC,
    )
    if note is not None:
        notes.append(note)

    if notes:
        logger.warning(
            "persona chat user row bounded before the wire: %s",
            ", ".join(
                f"{item.part}={item.action}({item.original_chars}->{item.bounded_chars}"
                f"/{item.limit})"
                for item in notes
            ),
        )
    return BoundedUserContent(
        text=f"{message}{preload}{hud}",
        notes=tuple(notes),
        source_chars=len(text),
    )


def _redacted_content(value: Any) -> BoundedUserContent:
    """Redact a native row without competing with upstream's size policy."""
    text = _redacted(value)
    return BoundedUserContent(text=text, source_chars=len(text))
