"""The context-window budget a row reports, and the derived fields an old row is backfilled with.

Separate because it is arithmetic over a row and the model's window, with its
own vocabulary of budget and compaction bases.
"""

from __future__ import annotations

from typing import Any

from hermes_cli.profiles import get_profile_dir

from .._upstream_doors import compression_threshold_for_model
from ..serde import safe_assignment_text, safe_assignment_token

__layer__ = "policy"
__all__ = [
    "_persona_instance_id",
    "_profile_persona_from_instance",
    "_profile_prompt_skills_need_snapshot",
    "_context_budget_needs_refresh",
    "CONTEXT_BUDGET_DRIFT_ALARM_HIGH",
    "CONTEXT_BUDGET_DRIFT_ALARM_LOW",
    "BUDGET_BASIS_METERED_FIRST_CALL",
    "BUDGET_BASIS_ESTIMATE_WITH_TOOLS",
    "BUDGET_BASIS_ESTIMATE_MESSAGES_ONLY",
    "COMPACTION_BASIS_LIVE_COMPRESSOR",
    "COMPACTION_BASIS_MODEL_RATIO",
    "_context_budget",
    "_profile_snapshot_skill_names",
]


def _persona_instance_id(instance: Any) -> str | None:
    return safe_assignment_token(
        getattr(instance, "id", None) or getattr(instance, "persona_instance_id", None)
    )


def _profile_persona_from_instance(instance: Any) -> Any | None:
    raw_persona_id = str(getattr(instance, "persona_id", "") or "").strip()
    profile = safe_assignment_token(getattr(instance, "profile_id", None))
    lowered = raw_persona_id.lower()
    if lowered.startswith("profile:"):
        profile = safe_assignment_token(raw_persona_id.split(":", 1)[1])
    elif lowered.startswith("profile_"):
        profile = safe_assignment_token(raw_persona_id[len("profile_") :])
    if not profile:
        return None
    display_name = (
        safe_assignment_text(getattr(instance, "display_name", None), limit=120)
        or f"{profile.replace('_', ' ').title()} Agent"
    )
    # Keep the synthetic profile persona on the same typed contract as every
    # persisted/catalog persona. Instance model/skill policy is applied with
    # ``dataclasses.replace`` by ``apply_instance_model_overrides``; returning a
    # SimpleNamespace here made any explicit profile-instance override crash the
    # entire Harness snapshot/stream before its first hydrate frame.
    from ..models import AgentPersona

    return AgentPersona(
        id=f"profile:{profile}",
        display_name=display_name,
        role="profile",
        model=None,
        provider=None,
        api_mode=None,
        hermes_profile=profile,
        skills=[],
        toolsets=["file", "search", "session_search", "todo", "skills"],
        system_prompt_path="",
    )


def _profile_prompt_skills_need_snapshot(item: dict[str, Any]) -> bool:
    persona_id = str(item.get("persona_id") or "").strip().lower()
    if not (persona_id.startswith("profile:") or persona_id.startswith("profile_")):
        return False
    skills = item.get("accessible_skills") or item.get("skills")
    if not isinstance(skills, list) or not skills:
        return True
    sources = {
        safe_assignment_token(entry.get("source"))
        for entry in skills
        if isinstance(entry, dict)
    }
    return "profile_skills_snapshot" not in sources


def _context_budget_needs_refresh(item: dict[str, Any]) -> bool:
    budget = item.get("context_budget")
    if not isinstance(budget, dict):
        return True
    if budget.get("used_tokens") is None and _estimate_used_tokens(item.get("final_model_input")) is not None:
        return True
    return False


_DEFAULT_COMPACTION_RATIO = 0.50


_CODEX_GPT55_WINDOW_CAP = 272_000


def _static_context_window(model: str, provider: str | None) -> int | None:
    """Resolve a model's context window from the static fallback map.

    Network-free (this runs in the per-turn observability path) — mirrors the
    longest-key-first substring fallback in ``agent.model_metadata`` and applies
    the known ChatGPT-Codex OAuth cap (gpt-5.5 → 272K instead of the 1.05M raw).
    """
    name = (model or "").lower()
    if not name:
        return None
    try:
        from agent.model_metadata import DEFAULT_CONTEXT_LENGTHS
    except Exception:
        return None
    window: int | None = None
    for key in sorted(DEFAULT_CONTEXT_LENGTHS, key=len, reverse=True):
        if key.lower() in name:
            try:
                window = int(DEFAULT_CONTEXT_LENGTHS[key])
            except (TypeError, ValueError):
                window = None
            break
    if not window:
        return None
    prov = (provider or "").lower()
    if window > _CODEX_GPT55_WINDOW_CAP and "codex" in prov and "gpt-5.5" in name:
        window = _CODEX_GPT55_WINDOW_CAP
    return window


def _compaction_ratio(model: str, provider: str | None) -> float:
    """The fraction of the window at which Hermes compacts (0.5 default)."""
    try:
        override = compression_threshold_for_model(
            model, provider, allow_codex_gpt55_autoraise=True
        )
        if isinstance(override, (int, float)) and 0 < float(override) <= 1:
            return float(override)
    except Exception:
        pass
    return _DEFAULT_COMPACTION_RATIO


# How ``context_budget.used_tokens`` was derived. The provider's meter is the
# only authority; the estimates exist for the window BEFORE a call has returned
# (or when a turn failed before any call) and must be labeled as such — an
# unlabeled estimate reads as truth and silently under-reports (it cannot see
# tool schemas, which are ~12K tokens on a typical mission-chat turn).
#: Bounds outside which recorded-vs-metered token drift is reported as a typed
#: alarm row on ``context_budget``. Deliberately wide: the recorded estimate is
#: a bytes//4 heuristic and healthy turns on this lane measured 0.62–1.0, so a
#: narrow band would cry wolf every turn and be ignored — which is exactly how
#: the 5.48 reading on the 2026-08-09 200 k turn went unread while F1 ran live.
CONTEXT_BUDGET_DRIFT_ALARM_HIGH = 2.0


CONTEXT_BUDGET_DRIFT_ALARM_LOW = 0.25


BUDGET_BASIS_METERED_FIRST_CALL = "metered_first_call"


BUDGET_BASIS_ESTIMATE_WITH_TOOLS = "estimate_messages_plus_tools"


BUDGET_BASIS_ESTIMATE_MESSAGES_ONLY = "estimate_messages_only"


#: Where ``context_budget.compaction_tokens`` came from. ``live_compressor`` is
#: a READING off the object that will do the compacting; ``model_ratio`` is the
#: ``window x compaction_ratio`` DERIVATION, which is all that was available
#: before the turn started recording the compressor and is still the answer for
#: any lane that does not (batch, gateway, CLI).
COMPACTION_BASIS_LIVE_COMPRESSOR = "live_compressor"


COMPACTION_BASIS_MODEL_RATIO = "model_ratio"


def _tool_schema_json_bytes(final_model_input: dict[str, Any] | None) -> int | None:
    if not isinstance(final_model_input, dict):
        return None
    schema = final_model_input.get("tool_schema")
    if not isinstance(schema, dict):
        return None
    raw = schema.get("json_bytes")
    return raw if isinstance(raw, int) and raw > 0 else None


def _estimate_used_tokens(final_model_input: dict[str, Any] | None) -> int | None:
    """Heuristic bytes//4 estimate of the assembled prompt.

    Counts the recorded messages PLUS the tool-schema wire size when it is
    known: the schemas ship on every API call, so an estimate without them is
    not "roughly right", it is missing the second-largest block.
    """
    if not isinstance(final_model_input, dict):
        return None
    messages = final_model_input.get("messages")
    if not isinstance(messages, list):
        return None
    total_bytes = 0
    for message in messages:
        if not isinstance(message, dict):
            continue
        raw = message.get("bytes")
        if isinstance(raw, int) and raw > 0:
            total_bytes += raw
        else:
            total_bytes += len(str(message.get("content") or "").encode("utf-8"))
    total_bytes += _tool_schema_json_bytes(final_model_input) or 0
    if total_bytes <= 0:
        return None
    return max(1, total_bytes // 4)


def _metered_assembled_tokens(turn_usage: dict[str, Any] | None) -> int | None:
    """The assembled-context size as the provider metered it, or None.

    Row 1 of the usage ledger is the only honest answer: that call carried the
    system prompt + user message + tool schemas and nothing else. Later calls
    also carry tool results (loop growth), which is turn burn, not context size.
    A single-call turn's total is by definition its first call.
    """
    if not isinstance(turn_usage, dict):
        return None
    first = turn_usage.get("first_call_prompt_tokens")
    if isinstance(first, int) and first > 0:
        return first
    api_calls = turn_usage.get("api_calls")
    prompt_tokens = turn_usage.get("prompt_tokens")
    if api_calls == 1 and isinstance(prompt_tokens, int) and prompt_tokens > 0:
        return prompt_tokens
    return None


def _live_compaction_threshold(final_model_input: dict[str, Any] | None) -> int | None:
    """The compaction threshold the live compressor holds, or None.

    Reads the row `profile_runner._chat_compaction_observability` records.
    Returns None — never a guess — when the turn did not record one, so the
    caller falls back to the model-ratio derivation and LABELS it as such.
    """

    if not isinstance(final_model_input, dict):
        return None
    row = final_model_input.get("context_compaction")
    if not isinstance(row, dict):
        return None
    value = row.get("effective_threshold_tokens")
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        return None
    return value


def _context_budget(
    model_selection: dict[str, Any] | None,
    final_model_input: dict[str, Any] | None,
    turn_usage: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Per-model context budget for the Sent-to-model bar: window + compaction line.

    ``used_tokens`` prefers the provider-metered first-call prompt (the exact
    assembled context, tool schemas included) and falls back to a labeled
    estimate only when no call has completed. ``used_basis`` says which, so the
    UI never renders a guess as a measurement. Returns None (UI omits the bar)
    when the model/window can't be resolved.
    """
    sel = model_selection if isinstance(model_selection, dict) else {}
    model = sel.get("effective_model") or sel.get("chat_model") or sel.get("default_model")
    provider = sel.get("effective_provider") or sel.get("chat_provider") or sel.get("default_provider")
    if not model:
        return None
    window = _static_context_window(str(model), provider)
    if not window:
        return None
    ratio = _compaction_ratio(str(model), provider)
    estimate = _estimate_used_tokens(final_model_input)
    metered = _metered_assembled_tokens(turn_usage)
    if metered is not None:
        used = metered
        basis = BUDGET_BASIS_METERED_FIRST_CALL
    else:
        used = estimate
        basis = (
            BUDGET_BASIS_ESTIMATE_WITH_TOOLS
            if _tool_schema_json_bytes(final_model_input) is not None
            else BUDGET_BASIS_ESTIMATE_MESSAGES_ONLY
        )
    # T5 (2026-08-09): `window x compaction_ratio` is a DERIVATION, not a
    # reading — it cannot see the mission-chat lane's compaction cap, so it
    # reported 892,500 on a root the compressor would compact at 150,000. When
    # the turn recorded what the live compressor actually holds, that is the
    # answer, and `compaction_basis` says which of the two this is so the UI
    # never renders a derivation as a measurement.
    derived_compaction = int(window * ratio)
    effective_compaction = _live_compaction_threshold(final_model_input)
    budget = {
        "model": safe_assignment_text(str(model), limit=120),
        "provider": safe_assignment_token(provider) if provider else None,
        "window_tokens": int(window),
        "compaction_ratio": round(float(ratio), 4),
        "compaction_tokens": (
            effective_compaction if effective_compaction is not None else derived_compaction
        ),
        "compaction_basis": (
            COMPACTION_BASIS_LIVE_COMPRESSOR
            if effective_compaction is not None
            else COMPACTION_BASIS_MODEL_RATIO
        ),
        "compaction_tokens_model_ratio": derived_compaction,
        "used_tokens": used,
        "used_basis": basis,
        # Back-compat for launcher builds that predate `used_basis`; they render
        # a tilde off this bool. Derived, never independently decided.
        "used_estimated": basis != BUDGET_BASIS_METERED_FIRST_CALL,
        "estimate_tokens": estimate,
    }
    # Drift is the tripwire the old design lacked: when the estimate and the
    # meter both exist and disagree badly, the estimator has lost an input class
    # (as it did with tool schemas) and says so instead of failing silently.
    if metered is not None and estimate is not None and estimate > 0:
        ratio = round(metered / estimate, 2)
        budget["estimate_drift_ratio"] = ratio
        # T4: the ratio existed and NOTHING READ IT — 5.48 sat in the record on
        # the 200 k turn while the wire-vs-record bug (F1) ran live. A number
        # only alarms when something decides it is out of band, so the decision
        # is made here, once, and rides the SAME block the launcher already
        # decodes off the `chat.final` frame.
        alarm_direction = _drift_alarm_direction(ratio)
        if alarm_direction is not None:
            budget["estimate_drift_alarm"] = {
                "schema_version": 1,
                "direction": alarm_direction,
                "ratio": ratio,
                "low": CONTEXT_BUDGET_DRIFT_ALARM_LOW,
                "high": CONTEXT_BUDGET_DRIFT_ALARM_HIGH,
                "summary": (
                    "Provider metered far MORE than the recorded prompt accounts for; "
                    "the record is missing an input class."
                    if alarm_direction == "metered_exceeds_record"
                    else
                    "Provider metered far LESS than the recorded prompt accounts for; "
                    "something between composition and the wire dropped content."
                ),
            }
    # T4: the exact, non-statistical companion to the ratio above. The recorded
    # user row now carries whether the WIRE copy differed from the COMPOSED one
    # (profile_runner._wire_user_message); when it did, say so on the frame
    # rather than leaving it buried in the evicted final_model_input payload.
    wire_drift = _wire_drift_row(final_model_input)
    if wire_drift is not None:
        budget["wire_drift"] = wire_drift
    return budget


def _drift_alarm_direction(ratio: float) -> str | None:
    """Which way the drift broke band, or ``None`` while it is in band."""

    if ratio >= CONTEXT_BUDGET_DRIFT_ALARM_HIGH:
        return "metered_exceeds_record"
    if ratio <= CONTEXT_BUDGET_DRIFT_ALARM_LOW:
        return "record_exceeds_metered"
    return None


def _wire_drift_row(final_model_input: dict[str, Any] | None) -> dict[str, Any] | None:
    """Typed frame row for a turn whose wire user text differed from composed.

    ``None`` when nothing is recorded, when the wire copy was unreadable, or
    when the two matched — the frame stays quiet on a healthy turn and speaks
    only when the composition did not survive to the wire.
    """

    if not isinstance(final_model_input, dict):
        return None
    receipt = final_model_input.get("user_message_wire")
    if not isinstance(receipt, dict) or not receipt.get("bounded"):
        return None
    composed = receipt.get("composed_chars")
    wire = receipt.get("wire_chars")
    if not isinstance(composed, int) or not isinstance(wire, int):
        return None
    return {
        "schema_version": 1,
        "kind": "user_message_bounded_before_wire",
        "composed_chars": composed,
        "wire_chars": wire,
        "dropped_chars": max(0, composed - wire),
    }


def _profile_snapshot_skill_names(profile: str) -> list[str]:
    """Skill names compiled into the profile's prompt (the skills snapshot).

    Used when a persona declares no per-agent skill subset (e.g. a bare profile
    identity) — the profile still compiles its skills snapshot into the prompt,
    so reporting zero would contradict the loaded `.skills_prompt_snapshot.json`.
    """
    try:
        profile_dir = get_profile_dir(profile)
    except Exception:
        return []
    if profile_dir is None:
        return []
    path = profile_dir / ".skills_prompt_snapshot.json"
    try:
        import json

        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    entries = data.get("skills") if isinstance(data, dict) else None
    if not isinstance(entries, list):
        return []
    names: list[str] = []
    for entry in entries:
        if isinstance(entry, dict):
            name = str(entry.get("skill_name") or entry.get("frontmatter_name") or "").strip()
            if name:
                names.append(name)
    return names
