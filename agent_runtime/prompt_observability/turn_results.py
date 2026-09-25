"""What a finished turn adds to its row, and the slim copy the final chat frame carries.

Separate because the turn commit calls it after the model returns — a second
entry point, not a phase of the build.
"""

from __future__ import annotations

from typing import Any, Iterable

from ..persona_assignments import safe_assignment_text, safe_assignment_token
from .context_budget import _context_budget
from .context_files import _attach_skills_prompt_contribution
from .safe_views import _safe_final_model_input, _safe_turn_usage
from .skills_context import used_skills_context

__layer__ = "lanes"
__all__ = [
    "attach_prompt_observability_turn_results",
    "CHAT_FINAL_OBSERVABILITY_FIELDS",
    "slim_chat_final_observability",
    "_safe_model_selection",
    "_safe_persona_id",
]


def attach_prompt_observability_turn_results(
    context: dict[str, Any],
    *,
    final_model_input: dict[str, Any] | None = None,
    model_selection: dict[str, Any] | None = None,
    turn_usage: dict[str, Any] | None = None,
    trace_events: Iterable[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """C1 build-once seam: PATCH the pre-turn row with the turn's results.

    The mission-chat turn used to build the observability row TWICE per turn —
    a pre-turn build (record-at-injection: history, skills, context files,
    HUD) and a post-turn FULL rebuild that re-read SessionDB history and
    re-scanned the skill catalog just to attach what the turn produced. This
    attaches exactly the turn-result fields (``final_model_input``,
    ``turn_usage``, trace-derived ``used_skills``, ``model_selection``, and the
    recomputed ``context_budget``) onto the pre-turn object instead. The
    record-at-injection fields are deliberately NOT touched: the peek shows
    exactly what was fed, never a post-hoc re-derivation.

    Lives here, not in the CLI lane (``harness_parts/persona/``), because it is
    the row's own lifecycle, unit-tested beside the row it mutates.
    Mutates ``context`` in place and returns it.
    """

    # T8: the rendered skills-index chars are only knowable once the agent is
    # constructed (they depend on its resolved tool set) — attach them to the
    # .skills_prompt_snapshot.json row here, from the raw turn result, before
    # final_model_input is sanitized/evicted.
    _attach_skills_prompt_contribution(context, final_model_input)
    context["final_model_input"] = _safe_final_model_input(final_model_input)
    if model_selection is not None:
        context["model_selection"] = _safe_model_selection(model_selection)
    context["turn_usage"] = _safe_turn_usage(turn_usage)
    context["used_skills"] = used_skills_context(
        final_model_input=final_model_input,
        trace_events=trace_events,
        queued_skills=context.get("preloaded_skills_loaded") or [],
        required_preload_skills=context.get("required_preload_skills") or [],
    )
    context["context_budget"] = _context_budget(
        model_selection if model_selection is not None else context.get("model_selection"),
        final_model_input,
        turn_usage,
    )
    return context


#: C3 (2026-07-17): the slim typed subset of the per-turn observability row that
#: the terminal ``chat.final`` frame — and the mission-chat failure frames that
#: carry observability — embed on the wire. The FULL row used to ride every
#: terminal frame (~26 KB post-C1, still mostly ``final_model_input`` + prompt
#: layers + context files + chat history), yet the launcher decodes only these
#: fields off the LIVE frame: the Context peek's primary source is the snapshot
#: frame's ``chat_contexts``, and this block is its zero-fetch live fallback
#: (situational HUD + turn usage), while the Skills HUD prefers the frame
#: context and degrades honestly to ``instance.skills`` when the fallback lacks
#: skill lists. Ruling §7.3 (settled by the operator): keep EXACTLY these keys.
#: ``chat_id`` / ``chat_title`` are included because the launcher
#: ``MissionPromptChatContext`` parser consumes them (chat identity in the
#: fallback window). Deliberately NOT shipped: the skill LISTS
#: (``accessible_skills`` / ``available_skills`` + their refs),
#: ``final_model_input``, ``prompt_layers``, ``context_files``,
#: ``chat_history_context`` — the complete record-at-injection truth stays on
#: disk in the persisted ctx row (archive-never-delete) and the turn store keeps
#: the element/replay authority.
CHAT_FINAL_OBSERVABILITY_FIELDS: tuple[str, ...] = (
    "context_id",
    "chat_id",
    "chat_title",
    "turn_usage",
    "model_selection",
    "context_budget",
    "situational_hud",
    "situational_hud_revision",
    "situational_hud_delivery",
    "used_skills",
)


def slim_chat_final_observability(
    context: dict[str, Any] | None,
) -> dict[str, Any]:
    """Project a built observability row down to the ``chat.final`` wire subset.

    Pure and side-effect-free, beside the row it projects, and called at the
    CLI lane's emit site (``harness_parts/persona/``). ONE shape (ruling 0): always returns the same key
    set, and the collection-typed fields keep their empty shape (``{}`` / ``[]``)
    even if the row lacked them, so the launcher never decodes a ``null`` where
    it expects a map or list. Never mutates ``context`` and never re-derives
    anything — the record-at-injection fields it reads were resolved once,
    upstream, on the row this projects from.
    """

    if not isinstance(context, dict):
        return {}
    slim: dict[str, Any] = {key: context.get(key) for key in CHAT_FINAL_OBSERVABILITY_FIELDS}
    if slim.get("situational_hud") is None:
        slim["situational_hud"] = {}
    if slim.get("used_skills") is None:
        slim["used_skills"] = []
    if slim.get("model_selection") is None:
        slim["model_selection"] = {}
    return slim


def _safe_model_selection(value: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    allowed = {
        "default_provider",
        "default_model",
        "chat_provider",
        "chat_model",
        "effective_provider",
        "effective_model",
        "model_is_default",
        "scope",
    }
    result: dict[str, Any] = {}
    for key in allowed:
        item = value.get(key)
        if isinstance(item, bool):
            result[key] = item
        elif isinstance(item, str) and item.strip():
            result[key] = safe_assignment_text(item, limit=220)
        elif item is None and key in {"chat_provider", "chat_model"}:
            result[key] = None
    return result


def _safe_persona_id(value: Any) -> str:
    raw = str(value or "").strip()
    if raw.lower().startswith("profile:"):
        profile = safe_assignment_token(raw.split(":", 1)[1])
        return f"profile:{profile}" if profile else "profile:unknown"
    return safe_assignment_token(raw) or "unknown"
