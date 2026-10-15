"""The two envelope grammars a composed operator row carries: runtime_context and skill_preload.

Extract / render / delivery choice (snapshot vs unchanged, from the native
lineage alone) / revision for each; the lossless three-part split of a composed
row; ``EnvelopeCodec``, which reads and rewrites one envelope's body through the
same compiled pattern.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any, Iterable

__layer__ = "policy"


RUNTIME_CONTEXT_DELIVERY_SNAPSHOT = "snapshot"
RUNTIME_CONTEXT_DELIVERY_UNCHANGED = "unchanged"
RUNTIME_CONTEXT_DELIVERY_UNAVAILABLE = "unavailable"
_RUNTIME_CONTEXT_ENVELOPE_RE = re.compile(
    r'(?:\n\n)?<runtime_context context_id="(?P<context_id>ctx_[a-zA-Z0-9_-]+)" '
    r'revision="(?P<revision>hud_[a-f0-9]+|hud_unavailable)" '
    r'delivery="(?P<delivery>snapshot|unchanged|unavailable)">\n'
    r'(?P<body>.*?)\n</runtime_context>\s*\Z',
    re.DOTALL,
)
# Operator-turn skill-preload envelope. The required/queued skill preload rides
# the operator's user turn for the same prompt-cache reason the HUD does (see
# ``_mission_chat_user_message``), so — like the HUD — it needs a structural
# envelope the transcript projection can strip. Without one, the projection
# renders the whole skill body as operator-authored text (live 2026-07-23:
# "message launcher dev say hi" displayed with the full harness-runtime-model
# skill appended). Same grammar rules as the runtime-context envelope: strict
# attribute charset, well-formed-only, end-anchored extraction.
#
# Delivery mirrors the runtime-context contract: the full body is a
# ``snapshot`` sent only when no matching snapshot survives in the effective
# native lineage; otherwise a compact ``unchanged`` stub re-asserts the active
# skills. Required-preload skills ride EVERY chat turn, so without this a
# skill-bearing persona pays the full body per turn. ``revision``/``delivery``
# are optional in the extraction grammar so rows persisted by the envelope's
# first revision (no attributes) keep stripping.
SKILL_PRELOAD_DELIVERY_SNAPSHOT = "snapshot"
SKILL_PRELOAD_DELIVERY_UNCHANGED = "unchanged"
_SKILL_PRELOAD_ENVELOPE_RE = re.compile(
    r'(?:\n\n)?<skill_preload skills="(?P<skills>[a-zA-Z0-9_.:+-]*(?:,[a-zA-Z0-9_.:+-]+)*)"'
    r'(?: revision="(?P<revision>skills_[a-f0-9]+)" delivery="(?P<delivery>snapshot|unchanged)")?>\n'
    r'(?P<body>.*?)\n</skill_preload>\s*\Z',
    re.DOTALL,
)
_SKILL_PRELOAD_NAME_RE = re.compile(r"^[a-zA-Z0-9_.:+-]+$")


def extract_runtime_context_envelope(
    content: Any,
) -> tuple[str, dict[str, str] | None]:
    """Strip only our final, well-formed runtime envelope from a user row.

    Anchoring at the end is intentional: operator-authored text which happens to
    mention the tag remains ordinary transcript content.
    """

    text = content if isinstance(content, str) else str(content or "")
    match = _RUNTIME_CONTEXT_ENVELOPE_RE.search(text)
    if match is None:
        return text, None
    return text[: match.start()].rstrip(), {
        "context_id": match.group("context_id"),
        "revision": match.group("revision"),
        "delivery": match.group("delivery"),
    }


def runtime_context_delivery(
    native_history: Iterable[dict[str, Any]] | None,
    revision: str,
) -> str:
    """Choose snapshot vs delta without relying on resident-process memory.

    A full snapshot is resent when no matching snapshot remains in the effective
    native lineage. That makes cold resume and post-compression recovery safe.
    """

    if revision == "hud_unavailable":
        return RUNTIME_CONTEXT_DELIVERY_UNAVAILABLE
    for row in reversed(list(native_history or ())):
        if not isinstance(row, dict) or str(row.get("role") or "").lower() != "user":
            continue
        _, metadata = extract_runtime_context_envelope(row.get("content"))
        if (
            metadata is not None
            and metadata.get("revision") == revision
            and metadata.get("delivery") == RUNTIME_CONTEXT_DELIVERY_SNAPSHOT
        ):
            return RUNTIME_CONTEXT_DELIVERY_UNCHANGED
    return RUNTIME_CONTEXT_DELIVERY_SNAPSHOT


def render_runtime_context_envelope(
    *,
    context_id: str,
    revision: str,
    delivery: str,
    situational_hud_content: str | None,
    volatile_content: str | None = None,
) -> str:
    """Render the compact per-turn envelope appended to the operator message.

    ``volatile_content`` (today: the remaining wall-budget line) is emitted on
    EVERY delivery — snapshot, unchanged, and unavailable alike. That is the
    whole point of separating it from the hashed body: a cached "unchanged"
    stub would otherwise show the agent a stale countdown, which is worse than
    showing none, and folding it into the body would re-snapshot the entire HUD
    every turn.
    """

    if delivery == RUNTIME_CONTEXT_DELIVERY_SNAPSHOT:
        body = (situational_hud_content or "").strip()
        if not body:
            delivery = RUNTIME_CONTEXT_DELIVERY_UNAVAILABLE
            revision = "hud_unavailable"
    elif delivery == RUNTIME_CONTEXT_DELIVERY_UNCHANGED:
        body = (
            "Runtime Situation unchanged from the most recent full snapshot "
            f"for revision {revision}."
        )
    else:
        delivery = RUNTIME_CONTEXT_DELIVERY_UNAVAILABLE
        revision = "hud_unavailable"
        body = "Runtime Situation unavailable for this turn."
    volatile = (volatile_content or "").strip()
    if volatile:
        body = f"{body}\n{volatile}" if body else volatile
    return (
        f'<runtime_context context_id="{context_id}" revision="{revision}" '
        f'delivery="{delivery}">\n{body}\n</runtime_context>'
    )


def skill_preload_revision(skill_preload_content: str | None) -> str:
    """Return a stable revision for the exact preload content built this turn.

    Hashing the CONTENT (not the name list) means a skill edited on disk — or a
    changed queued/required set — re-snapshots, exactly like a changed runtime
    HUD does.
    """

    body = (skill_preload_content or "").strip()
    if not body:
        return "skills_unavailable"
    return "skills_" + hashlib.sha256(body.encode("utf-8", errors="replace")).hexdigest()[:16]


def skill_preload_delivery(
    native_history: Iterable[dict[str, Any]] | None,
    revision: str,
) -> str:
    """Choose snapshot vs unchanged without relying on resident-process memory.

    Mirror of :func:`runtime_context_delivery`: the full preload body is resent
    when no matching snapshot remains in the effective native lineage, so cold
    resume and post-compression recovery stay safe. History rows carry the skill
    envelope BEFORE the trailing runtime-context envelope, so the scan strips
    the HUD envelope first.
    """

    if revision == "skills_unavailable":
        return SKILL_PRELOAD_DELIVERY_SNAPSHOT
    for row in reversed(list(native_history or ())):
        if not isinstance(row, dict) or str(row.get("role") or "").lower() != "user":
            continue
        remainder, _ = extract_runtime_context_envelope(row.get("content"))
        _, metadata = extract_skill_preload_envelope(remainder)
        if (
            metadata is not None
            and metadata.get("revision") == revision
            and metadata.get("delivery") == SKILL_PRELOAD_DELIVERY_SNAPSHOT
        ):
            return SKILL_PRELOAD_DELIVERY_UNCHANGED
    return SKILL_PRELOAD_DELIVERY_SNAPSHOT


def render_skill_preload_envelope(
    *,
    skill_names: Iterable[str] | None,
    skill_preload_content: str | None,
    revision: str | None = None,
    delivery: str = SKILL_PRELOAD_DELIVERY_SNAPSHOT,
) -> str:
    """Wrap the per-turn skill preload in its structural envelope.

    Returns ``""`` when there is nothing to preload, so callers can keep the
    "join non-empty parts" composition unchanged. Names that fail the strict
    attribute charset are dropped from the attribute (the body still carries
    the full preload text) — the attribute exists for projection metadata and
    must never break extraction.

    ``delivery == "unchanged"`` swaps the full body for a compact stub that
    re-asserts the active skills against the earlier snapshot ``revision`` —
    the snapshot row itself stays in the native lineage the model reads.
    """

    body = (skill_preload_content or "").strip()
    if not body:
        return ""
    names = ",".join(
        name
        for name in (str(item or "").strip() for item in (skill_names or ()))
        if name and _SKILL_PRELOAD_NAME_RE.fullmatch(name)
    )
    resolved_revision = revision or skill_preload_revision(body)
    if delivery == SKILL_PRELOAD_DELIVERY_UNCHANGED:
        body = (
            "Skill instructions unchanged from the full snapshot for revision "
            f"{resolved_revision} earlier in this conversation. The listed "
            "skills remain active for this session."
        )
    else:
        delivery = SKILL_PRELOAD_DELIVERY_SNAPSHOT
    return (
        f'<skill_preload skills="{names}" revision="{resolved_revision}" '
        f'delivery="{delivery}">\n{body}\n</skill_preload>'
    )


def extract_skill_preload_envelope(
    content: Any,
) -> tuple[str, dict[str, Any] | None]:
    """Strip only our final, well-formed skill-preload envelope from a user row.

    Mirrors :func:`extract_runtime_context_envelope`: end-anchored so operator
    text that merely mentions the tag stays ordinary transcript content. Run it
    AFTER the runtime-context extraction — composition order is
    ``message · skill_preload · runtime_context``, so the skill envelope is
    end-anchored only once the HUD envelope has been stripped.
    """

    text = content if isinstance(content, str) else str(content or "")
    match = _SKILL_PRELOAD_ENVELOPE_RE.search(text)
    if match is None:
        return text, None
    skills = [name for name in match.group("skills").split(",") if name]
    metadata: dict[str, Any] = {"skills": skills}
    if match.group("revision") is not None:
        metadata["revision"] = match.group("revision")
        metadata["delivery"] = match.group("delivery")
    return text[: match.start()].rstrip(), metadata


@dataclass(frozen=True, slots=True)
class ComposedUserRow:
    """One composed operator user row, split into the parts it was joined from.

    Composition order is ``message · skill_preload · runtime_context``
    (``persona_runtime._mission_chat_user_message``) and the two envelopes are
    end-anchored, so the split is exact and lossless:
    ``message + skill_preload + runtime_context`` reproduces the input byte for
    byte, separators included. Absent envelopes are ``""``.

    This exists because the parts have DIFFERENT contracts and therefore
    different bounds — operator text must never be cut silently, the preload
    owns its own dedupe/revision machinery, the HUD is small and load-bearing —
    and a bound applied to the joined row cannot tell them apart. It mutilated
    all three (2026-08-09 F1).
    """

    message: str
    skill_preload: str
    runtime_context: str

    @property
    def joined(self) -> str:
        return f"{self.message}{self.skill_preload}{self.runtime_context}"

    @property
    def has_envelope(self) -> bool:
        return bool(self.skill_preload or self.runtime_context)


def split_composed_user_row(content: Any) -> ComposedUserRow:
    """Split a composed operator user row into its three parts.

    Each envelope is the RAW matched text — opening tag, body, closing tag, and
    the leading blank-line separator the composition joined it with — so a
    caller can rebound one part and rejoin without re-deriving any separator.

    The HUD envelope is stripped FIRST for the same reason
    :func:`skill_preload_delivery` strips it first: the skill envelope is
    end-anchored only once the runtime-context envelope is out of the way.
    """

    text = content if isinstance(content, str) else str(content or "")
    hud_match = _RUNTIME_CONTEXT_ENVELOPE_RE.search(text)
    if hud_match is None:
        head, runtime_context = text, ""
    else:
        head, runtime_context = text[: hud_match.start()], text[hud_match.start() :]
    skill_match = _SKILL_PRELOAD_ENVELOPE_RE.search(head)
    if skill_match is None:
        message, skill_preload = head, ""
    else:
        message, skill_preload = head[: skill_match.start()], head[skill_match.start() :]
    return ComposedUserRow(
        message=message, skill_preload=skill_preload, runtime_context=runtime_context
    )


@dataclass(frozen=True, slots=True)
class EnvelopeCodec:
    """Read and rewrite ONE envelope's body without respelling its grammar.

    Both operations go through the same compiled pattern, so "where the body
    is" and "where a replacement body goes" cannot drift apart. Callers that
    need to bound an envelope get its body, shrink it, and put it back —
    the opening tag and its attributes stay byte-exact, which is what keeps
    :func:`skill_preload_delivery`'s ``unchanged`` dedupe (which matches on
    ``revision``/``delivery``) working across a bound. Amputating the closing
    tag instead defeats that dedupe outright and re-ships the whole preload on
    every turn (2026-08-09 F1).
    """

    name: str
    pattern: Any

    def body(self, envelope: str) -> str | None:
        """The envelope's body, or ``None`` when *envelope* is not this grammar."""

        match = self.pattern.search(envelope)
        return None if match is None else match.group("body")

    def with_body(self, envelope: str, body: str) -> str | None:
        """*envelope* with its body replaced; everything else byte-exact."""

        match = self.pattern.search(envelope)
        if match is None:
            return None
        return envelope[: match.start("body")] + body + envelope[match.end("body") :]


SKILL_PRELOAD_CODEC = EnvelopeCodec("skill_preload", _SKILL_PRELOAD_ENVELOPE_RE)
RUNTIME_CONTEXT_CODEC = EnvelopeCodec("runtime_context", _RUNTIME_CONTEXT_ENVELOPE_RE)
