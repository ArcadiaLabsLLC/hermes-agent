"""The profile's context files and what each contributes to the prompt.

Separate because it owns the one six-name vocabulary (``SOUL.md`` … ``config.yaml``)
three readers used to spell by hand.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Mapping

from hermes_cli.profiles import get_profile_dir

from ..serde import non_negative_int
from .safe_views import _safe_preview

__layer__ = "policy"
__all__ = [
    "CONTEXT_FILES",
    "ContextFileKind",
    "OTHER_CONTEXT_FILE",
    "PromptContribution",
    "WorkspaceAgentsContext",
    "context_file_kind",
    "_profile_context_files",
    "_token_estimate_from_bytes",
    "_layer_text_size",
    "_soul_overlay_prompt_chars",
    "_workspace_agents_prompt_chars",
    "_mission_chat_identity_prompt_chars",
    "_mission_chat_identity_prompt_content",
    "_mission_chat_operative_rules_chars",
    "_mission_chat_operative_rules_content",
    "_attach_context_file_prompt_contributions",
    "_attach_skills_prompt_contribution",
]


@dataclass(frozen=True, slots=True)
class WorkspaceAgentsContext:
    """One explicitly selected workspace ``AGENTS.md`` and its safe receipt."""

    content: str | None
    receipt: dict[str, Any]


def _profile_context_files(profile: str) -> list[dict[str, Any]]:
    try:
        profile_dir = get_profile_dir(profile)
    except Exception:
        profile_dir = None
    files: list[dict[str, Any]] = []
    if profile_dir is None:
        return files
    candidates = [
        profile_dir / "SOUL.md",
        profile_dir / "memories" / "MEMORY.md",
        profile_dir / "memories" / "USER.md",
        profile_dir / ".skills_prompt_snapshot.json",
        profile_dir / "config.yaml",
    ]
    for path in candidates:
        files.append(_context_file_summary(path, included=path.exists()))
    return files


# --------------------------------------------------------------------------- #
# Per-item token attribution (2026-07-18): the operator asked to "see how many
# tokens each thing takes". Provider meters only whole API calls, so per-item
# numbers are necessarily ``bytes // 4`` (context files) / ``chars // 4``
# (prompt-layer text) ESTIMATES — labeled as such by the launcher, which
# reconciles them against the metered ``turn_usage.first_call_prompt_tokens``
# with one clamped residual row. Hermes emits the raw sizes because the launcher
# only receives redaction-safe previews, not the underlying files/layer text.
# --------------------------------------------------------------------------- #

def _token_estimate_from_bytes(byte_count: int | None) -> int | None:
    """Rough token estimate for a stored file: ``bytes // 4``.

    ``None`` (no estimate) when the byte count is unknown — an absent estimate
    is honest; a fabricated one would masquerade as a measurement.
    """
    if not isinstance(byte_count, int) or byte_count <= 0:
        return None
    return byte_count // 4


def _layer_text_size(text: str | None) -> dict[str, int]:
    """``{chars, token_estimate}`` for a prompt-layer's actual text.

    Returns an EMPTY dict when the layer's text is not available at this seam
    (e.g. the Hermes-core block is assembled later in the
    turn) — the launcher then attributes those layers to the residual instead of
    inventing a number. A present-but-empty layer (a blank surface prompt) is a
    real ``0``, distinct from absent.
    """
    if not isinstance(text, str):
        return {}
    chars = len(text)
    return {"chars": chars, "token_estimate": chars // 4}


# --------------------------------------------------------------------------- #
# T8 (2026-07-18): per-file IN-PROMPT contribution. The loaded-file
# ``token_estimate`` (``bytes // 4``) answers "how big is the file"; these
# additive ``prompt_chars`` / ``prompt_token_estimate`` fields answer "how much
# of that file actually landed in the assembled prompt this turn" — wildly
# different for the 41 KB skills snapshot (renders to ~9 KB of index text) and
# ``config.yaml`` (never pasted → a deliberate 0). Only files whose contributed
# text is REACHABLE at the T5 assembly seam get the fields; everything else is
# left untouched so the launcher keeps the honest loaded-file chip rather than a
# guess. Both numbers ride the row.
# --------------------------------------------------------------------------- #

def _set_row_prompt_contribution(row: dict[str, Any], chars: int | None) -> None:
    """Attach ``prompt_chars`` + ``prompt_token_estimate`` (``chars // 4``) to a
    context-file row. A ``None``/negative char count leaves the row untouched
    (the field stays ABSENT → the launcher omits the in-prompt chip); a real 0
    (config.yaml) is a deliberate zero, distinct from absent."""

    if not isinstance(row, dict) or chars is None or chars < 0:
        return
    row["prompt_chars"] = chars
    row["prompt_token_estimate"] = chars // 4


def _soul_overlay_prompt_chars(persona: Any) -> int | None:
    """Chars of the persona's own soul overlay as PASTED into the surface
    message, or ``None`` when no overlay resolves. Uses the SAME function the
    assembly pastes with (``persona_runtime._safe_read_soul_overlay``), so the
    SOUL.md row's in-prompt number is exact, not a re-derivation."""

    try:
        from ..persona_runtime import _mission_chat_soul_overlay

        soul = _mission_chat_soul_overlay(persona)
        return len(soul) if isinstance(soul, str) and soul else None
    except Exception:
        return None


def _workspace_agents_prompt_chars(
    workspace_agents: "WorkspaceAgentsContext | None",
) -> int | None:
    """Chars of the workspace-AGENTS.md PART pasted into the surface message
    (fixed preamble + stripped body), or ``None`` when nothing was injected.
    Reuses ``persona_runtime.MISSION_CHAT_WORKSPACE_AGENTS_PREAMBLE`` so the
    measured part can never drift from the text actually pasted."""

    if workspace_agents is None or workspace_agents.content is None:
        return None
    try:
        from ..persona_runtime import MISSION_CHAT_WORKSPACE_AGENTS_PREAMBLE

        body = str(workspace_agents.content or "").strip()
        return len(MISSION_CHAT_WORKSPACE_AGENTS_PREAMBLE) + len(body)
    except Exception:
        return None


def _mission_chat_identity_prompt_chars(persona: Any) -> int | None:
    """Exact chars of the generated Mission Control runtime-identity block."""

    try:
        from ..persona_runtime import _mission_chat_identity_prompt

        return len(_mission_chat_identity_prompt(persona))
    except Exception:
        return None


def _mission_chat_identity_prompt_content(persona: Any) -> str | None:
    """Captured text of the generated Mission Control identity layer."""

    try:
        from ..persona_runtime import _mission_chat_identity_prompt

        return _mission_chat_identity_prompt(persona)
    except Exception:
        return None


def _mission_chat_operative_rules_chars() -> int | None:
    """Exact chars of the stable Mission Control operator-channel rules."""

    try:
        from ..persona_runtime import _mission_chat_operative_rules

        return len(_mission_chat_operative_rules())
    except Exception:
        return None


def _mission_chat_operative_rules_content() -> str | None:
    """Captured text of the stable Mission Control channel-rules layer."""

    try:
        from ..persona_runtime import _mission_chat_operative_rules

        return _mission_chat_operative_rules()
    except Exception:
        return None


def _attach_context_file_prompt_contributions(
    context_files: list[dict[str, Any]],
    *,
    soul_chars: int | None,
    workspace_chars: int | None,
    memory_loaded: bool = False,
) -> None:
    """Attach the per-file in-prompt contribution to the rows reachable at this
    PRE-turn seam: SOUL.md (soul overlay), the workspace AGENTS.md row (workspace
    part), and config.yaml (a deliberate 0 — consumed as configuration, never
    pasted). MEMORY.md / USER.md receive an inclusion status here, while their
    token estimate remains the loaded-file estimate because the later memory
    dedup/sanitize pipeline is not reproducible at this seam.
    ``.skills_prompt_snapshot.json`` is attached POST-turn (it needs the
    constructed agent's resolved tool set — see
    ``attach_prompt_observability_turn_results``)."""

    contribution = PromptContribution(soul_chars=soul_chars, memory_loaded=memory_loaded)
    for row in context_files:
        if not isinstance(row, dict):
            continue
        # A guard on a different key: the workspace AGENTS.md receipt is
        # attributed by its row ``kind``, never by its file name (a profile's
        # own AGENTS.md shares the name and is not pasted here).
        if row.get("kind") == "workspace_context":
            _set_row_prompt_contribution(row, workspace_chars)
            row["prompt_included"] = workspace_chars is not None
            row["prompt_status"] = "injected" if workspace_chars is not None else "not_injected"
            continue
        entry = CONTEXT_FILES.get(str(row.get("name") or ""))
        if entry is not None and entry.contribution is not None:
            entry.contribution(row, contribution)


def _attach_skills_prompt_contribution(
    context: dict[str, Any], final_model_input: dict[str, Any] | None
) -> None:
    """Attach the rendered skills-index chars (recorded on ``final_model_input``
    by the profile runner, measured against the agent's real tool set) to the
    ``.skills_prompt_snapshot.json`` row. POST-turn only: the render needs the
    constructed agent, which does not exist at the pre-turn build. Absent field →
    the row keeps its loaded-file chip (never fabricated)."""

    if not isinstance(final_model_input, dict):
        return
    chars = non_negative_int(final_model_input.get("skills_prompt_chars"))
    if chars is None:
        return
    files = context.get("context_files")
    if not isinstance(files, list):
        return
    for row in files:
        if isinstance(row, dict) and row.get("name") == ".skills_prompt_snapshot.json":
            _set_row_prompt_contribution(row, chars)
            row["prompt_included"] = chars > 0
            row["prompt_status"] = "injected" if chars > 0 else "empty"
            break


def _context_file_summary(path: Path, *, included: bool) -> dict[str, Any]:
    data: dict[str, Any] = {
        "path": str(path),
        "name": path.name,
        "kind": _file_kind(path),
        "included": bool(included),
        "status": "loaded" if included else "missing_or_not_configured",
    }
    if not included:
        return data
    try:
        raw = path.read_bytes()
    except OSError as exc:
        data["status"] = "unreadable"
        data["error"] = type(exc).__name__
        return data
    data["sha256"] = hashlib.sha256(raw).hexdigest().upper()
    data["bytes"] = len(raw)
    estimate = _token_estimate_from_bytes(len(raw))
    if estimate is not None:
        data["token_estimate"] = estimate
    preview = context_file_kind(path.name).preview
    if preview is not None:
        data["preview"] = preview(raw)
    return data


def _file_kind(path: Path) -> str:
    return context_file_kind(path.name).kind


# ── the context-file vocabulary: one table, three readers ────────────────────
#
# ``_file_kind`` (the row's ``kind``), ``_context_file_summary`` (its preview)
# and ``_attach_context_file_prompt_contributions`` (its pre-turn in-prompt
# contribution) each used to spell the six names by hand. They read this table
# now, so a seventh context file is one row here (program rule 12).


@dataclass(frozen=True, slots=True)
class PromptContribution:
    """What the pre-turn seam knows about the pasted parts: the SOUL overlay's
    chars and whether the persona loads its profile memory."""

    soul_chars: int | None
    memory_loaded: bool


@dataclass(frozen=True, slots=True)
class ContextFileKind:
    """One context file's row ``kind``, its preview, and its pre-turn contribution.

    ``preview`` is ``None`` for a file whose body is never previewed;
    ``contribution`` is ``None`` for a file whose in-prompt share is not
    reachable at the pre-turn seam (``.skills_prompt_snapshot.json`` is attached
    post-turn; a profile ``AGENTS.md`` is not pasted by this lane).
    """

    kind: str
    preview: Callable[[bytes], str] | None = None
    contribution: Callable[[dict[str, Any], PromptContribution], None] | None = None


def _text_preview(raw: bytes) -> str:
    return _safe_preview(raw.decode("utf-8", errors="replace"))


def _withheld_preview(message: str) -> Callable[[bytes], str]:
    return lambda _raw: message


def _soul_contribution(row: dict[str, Any], contribution: PromptContribution) -> None:
    soul_chars = contribution.soul_chars
    _set_row_prompt_contribution(row, soul_chars)
    row["prompt_included"] = soul_chars is not None
    row["prompt_status"] = "injected" if soul_chars is not None else "not_injected"


def _memory_contribution(row: dict[str, Any], contribution: PromptContribution) -> None:
    memory_loaded = contribution.memory_loaded
    has_content = bool(row.get("included")) and int(row.get("bytes") or 0) > 0
    row["prompt_included"] = bool(memory_loaded and has_content)
    row["prompt_status"] = (
        "injected" if memory_loaded and has_content else "empty" if memory_loaded else "skipped"
    )


def _observed_only_contribution(row: dict[str, Any], contribution: PromptContribution) -> None:
    _set_row_prompt_contribution(row, 0)
    row["prompt_included"] = False
    row["prompt_status"] = "observed_only"


CONTEXT_FILES: Mapping[str, ContextFileKind] = MappingProxyType({
    "SOUL.md": ContextFileKind("soul", _text_preview, _soul_contribution),
    "MEMORY.md": ContextFileKind("memory", _text_preview, _memory_contribution),
    "USER.md": ContextFileKind("user_memory", _text_preview, _memory_contribution),
    "AGENTS.md": ContextFileKind("project_context", _text_preview),
    ".skills_prompt_snapshot.json": ContextFileKind(
        "skills",
        _withheld_preview("Skills prompt snapshot present; body withheld from observability preview."),
    ),
    "config.yaml": ContextFileKind(
        "profile_config",
        _withheld_preview("Profile config present; raw values withheld from observability preview."),
        _observed_only_contribution,
    ),
})
#: Any other file: a generic kind, no preview, no pre-turn contribution.
OTHER_CONTEXT_FILE = ContextFileKind("context_file")


def context_file_kind(name: str) -> ContextFileKind:
    return CONTEXT_FILES.get(name, OTHER_CONTEXT_FILE)
