"""The durable record shape: what a turn record, and each of its elements, may say.

``_safe_record`` (the read projection), the journal metadata whitelist, the
runner's profile-timing block, the provider-refusal block, and the elements
(segment / tool) with their bounded sub-shapes (todo state, exit code, file
labels). One-directional sanitizers: each drops what it cannot read and
supplies nothing.
"""

from __future__ import annotations

from typing import Any

from agent_runtime.mission_chat_phases import TURN_PHASES_KEY, safe_turn_phases
from agent_runtime.run_budget import (
    ACCOUNTING_KEY as RUN_BUDGET_ACCOUNTING_KEY,
    safe_accounting_block as safe_run_budget_accounting,
)
from agent_runtime.serde import (
    non_negative_int,
    safe_assignment_text,
    safe_assignment_token,
    safe_block,
)

from agent_runtime.mission_chat_turns.states import TURN_STATE_COMPLETED, _record_state

__layer__ = "policy"


_MAX_ELEMENTS = 80
_MAX_TEXT = 20000


_SENSITIVE_FILE_MARKERS = ("private_token", "secret_token", "api_key", "apikey", "credential")




# ---------------------------------------------------------------------------
# Record / element normalization (unchanged from the monolith design)
# ---------------------------------------------------------------------------


def _safe_record(
    record: dict[str, Any],
    *,
    client_message_id: str,
) -> dict[str, Any] | None:
    turn_id = safe_assignment_token(record.get("turn_id")) or safe_assignment_token(client_message_id)
    if not turn_id:
        return None
    started_at = safe_assignment_text(record.get("started_at"), limit=80)
    safe = {
        "client_message_id": client_message_id,
        "turn_id": turn_id,
        "state": _record_state(record) or TURN_STATE_COMPLETED,
        "updated_at": safe_assignment_text(record.get("updated_at"), limit=80),
        # C8 turn-start anchor (write-ahead stamp). Absent on pre-C8 records —
        # consumers fall back to `updated_at`, never fabricate a start.
        **({"started_at": started_at} if started_at else {}),
        "elements": _safe_elements(record.get("elements")),
    }
    safe.update(_safe_journal_metadata(record))
    return safe


_JOURNAL_TEXT_FIELDS = {
    "root_chat_session_id": 240,
    "active_session_id": 240,
    "persona_instance_id": 200,
    "provider_request_id": 240,
    "provider_request_fingerprint": 128,
    "native_revision": 160,
    "native_assistant_message_id": 240,
    "stored_reply": _MAX_TEXT,
    "projection_revision": 160,
    "resolution": 80,
    "resolution_actor": 160,
    "resolution_reason": 320,
    "resolved_at": 80,
    "pending_user_message": 12000,
    # Wall-budget provenance. ``budget_trigger`` is the typed reason the
    # graceful checkpoint (or the last-resort hard wall) ended the turn;
    # ``budget_summary`` is the one-line window description an operator reads
    # without re-deriving the arithmetic.
    "budget_trigger": 80,
    "budget_summary": 400,
}


#: The ONE structured entry on a turn record, carried verbatim from
#: ``run_budget.RunBudgetLedger.accounting()`` — the whole "what bounded this
#: turn?" block (``bounded_by`` / ``trip_reason`` / ``enforcement`` /
#: ``tripped`` / ``budgets``), documented in
#: ``docs/agent-runtime-harness/archive/2026-08-22-pre-consolidation/run-budget-accounting.md`` §3.
#:
#: A pure chat turn produces NO run record (``runs/`` is the goal/task lane), so
#: before this the ledger reached the live envelope and then evaporated: the
#: cockpit had nowhere to read "this reply is short because the wall closed"
#: after the turn settled. The turn journal IS the chat lane's run record, so
#: the block lives here, under the same key and in the same shape every other
#: carrier uses.
#:
#: ABSENT STAYS ABSENT. Older records and turns that declared no budget get no
#: key — never an empty dict, because "nothing bounded this turn" and "nobody
#: accounted this turn" are different facts and a reader must be able to tell
#: them apart.
_JOURNAL_RUN_BUDGET_FIELD = RUN_BUDGET_ACCOUNTING_KEY

#: The runner's own per-run timing dict (``AgentRunResult.profile_timing``),
#: carried onto the turn record beside ``phases``.
#:
#: WHY, given ``phases`` already exists: the phase block is the HANDLER's
#: timeline (anchor → context → agent_ready → first byte), and its
#: ``write_ahead → agent_ready`` span is one number covering everything
#: ``profile_runner`` does inside it — runtime resolution, MCP admission, agent
#: construction. The runner measures those separately and then threw the
#: numbers away once the stream ended, so "which part of the 3 s bootstrap?"
#: was a log-grep. Persisting them makes each prep-cost remedy checkable
#: against a before/after receipt on the record itself.
#:
#: STRICTLY BOUNDED, and enforced here rather than trusted from the caller: the
#: runner's dict is an open namespace that also carries the run-budget block,
#: MCP transport labels and compaction receipts. Only three shapes are admitted
#: — ``*_ms`` durations, ``resident_actor_reused``, and ``resident_rebuild_*``
#: — every value coerced to a non-negative int. No free text can reach the
#: record through this key, by construction rather than by scrubbing.
#:
#: THE HANDLER CONTRIBUTES TOO, so this block is a SUPERSET of the runner's dict
#: rather than a copy of it (chat-turn-prep Stage 4). ``session_db_open_ms`` is
#: measured by ``_cmd_mission_chat_message`` around its own
#: ``_default_persona_session_db()`` call — a cost paid BEFORE the runner exists,
#: inside the ``request_received → context_built`` span, which the runner
#: therefore cannot see — and folded in at the persist site. The LIVE result
#: frame still carries the runner's dict unchanged; this block is the TURN's,
#: which is the one the durable record keeps.
TURN_PROFILE_TIMING_KEY = "profile_timing"

#: Ceilings. A turn is bounded by its wall budget; a "duration" of a day is a
#: corrupt row, not a slow one. Same reasoning as ``mission_chat_phases``.
_PROFILE_TIMING_MAX_MS = 24 * 60 * 60 * 1000
_PROFILE_TIMING_MAX_KEYS = 64
_PROFILE_TIMING_FLAG_KEY = "resident_actor_reused"
_PROFILE_TIMING_REBUILD_PREFIX = "resident_rebuild_"

#: chat-turn-prep Stage 6's two additional 0/1 shapes.
#:
#: ``*_cached`` — today only ``observability_catalog_cached``: whether the 15 s
#: installed-skill-catalog TTL held for this turn. §0.3 measured two uncontended
#: floors (≈430 ms with the memo warm, ≈840 ms once it had expired) and without
#: this bit a record cannot say which of them a turn paid.
#:
#: ``visibility_bundle_rebuild_*`` — CP-7: which chat-lane bundle key component
#: moved. Exactly the ``resident_rebuild_*`` family's shape and admitted the
#: same way, because it answers the same question one layer up. NAMES only: the
#: value is a ``1`` and the component rides in the KEY, so nothing out of the
#: key material can reach a durable record through it.
_PROFILE_TIMING_CACHED_SUFFIX = "_cached"
_PROFILE_TIMING_BUNDLE_REBUILD_PREFIX = "visibility_bundle_rebuild_"


def safe_turn_profile_timing(value: Any) -> dict[str, Any] | None:
    """Sanitize a runner timing dict for the durable record. ``None`` = no block.

    Same one-directional defense as :func:`safe_turn_phases`: it drops what it
    cannot read and supplies nothing. A key the runner never wrote stays absent
    — notably ``agent_construct_ms``, which is ABSENT on a turn that reused a
    resident actor because no construction happened, and must never be
    backfilled with ``0``.
    """

    if not isinstance(value, dict):
        return None
    block: dict[str, Any] = {}
    for key in sorted(value):
        if len(block) >= _PROFILE_TIMING_MAX_KEYS:
            break
        if not isinstance(key, str):
            continue
        if key.endswith("_ms"):
            ceiling = _PROFILE_TIMING_MAX_MS
        elif (
            key == _PROFILE_TIMING_FLAG_KEY
            or key.startswith(_PROFILE_TIMING_REBUILD_PREFIX)
            or key.startswith(_PROFILE_TIMING_BUNDLE_REBUILD_PREFIX)
            or key.endswith(_PROFILE_TIMING_CACHED_SUFFIX)
        ):
            ceiling = 1
        else:
            continue
        raw = value[key]
        # bool is an int subclass; the runner writes 1/0 for the flags, and a
        # True that arrived from some other producer is still that fact.
        if isinstance(raw, bool):
            block[key] = int(raw)
            continue
        if not isinstance(raw, (int, float)):
            continue
        coerced = int(raw)
        if coerced < 0 or coerced > ceiling:
            continue
        block[key] = coerced
    return block or None


#: Text fields whose EMPTY value is a recorded fact rather than an absence.
#:
#: Everything else above is dropped when empty, which is right for an id or a
#: fingerprint — there is no such thing as "the fingerprint was, meaningfully,
#: nothing". ``stored_reply`` is the exception: "the turn replied with nothing"
#: and "nobody recorded a reply here" are different facts about the turn, and
#: collapsing them had a live consequence. The replay branch admits a settled
#: turn on ``stored_reply is not None``, so a SILENT turn — model produced no
#: content, `ok` true, empty reply — failed that guard, fell through to the
#: live provider path and died there as ``chat_turn_not_submitted /
#: rejected_stale_transition``. The delivery drain derives its
#: ``client_message_id`` from the dispatch id precisely so a retry converges on
#: one turn; for silent turns that convergence was broken.
#:
#: Same principle the run-budget block states directly above: absent stays
#: absent, and recorded-empty stays recorded.
_JOURNAL_EMPTY_PRESERVING_FIELDS = frozenset({"stored_reply"})

#: The provider's own verdict on a turn it refused to run
#: (``mission_chat_outcome.ProviderRefusal.as_dict``), carried onto the record
#: as ONE structured entry — the same treatment the run-budget accounting gets,
#: and for the same reason: flattening it into six text fields would put six
#: more keys in a whitelist that is read as "what a turn record may say".
#:
#: SANITIZED HERE rather than trusted from the caller, because the values
#: originate in a provider's error body — attacker-influenced text on the far
#: side of an HTTP boundary. Only these seven keys are admitted, ``status_code``
#: and ``resets_in_seconds`` are coerced to ints, ``reset_at`` is admitted as a
#: number or a bounded string, and everything else is dropped. Absent stays
#: absent: a field the provider did not speak has no key.
_JOURNAL_PROVIDER_REFUSAL_FIELD = "provider_refusal"
_PROVIDER_REFUSAL_TEXT_FIELDS = {
    "reason": 120,
    "message": 400,
    "provider": 80,
    "model": 120,
    "failure_reason": 80,
}


def safe_provider_refusal(value: Any) -> dict[str, Any] | None:
    """The typed refusal block, or ``None`` when there is nothing readable."""

    if not isinstance(value, dict):
        return None
    try:
        status_code = int(value.get("status_code"))
    except (TypeError, ValueError):
        return None
    # A refusal with no status code is not a refusal — the status IS the
    # provider's verdict, and every consumer branches on it.
    block: dict[str, Any] = {"status_code": status_code}
    for key, limit in _PROVIDER_REFUSAL_TEXT_FIELDS.items():
        text = safe_assignment_text(value.get(key), limit=limit)
        if text:
            block[key] = text
    reset_at = value.get("reset_at")
    if isinstance(reset_at, bool):
        reset_at = None
    if isinstance(reset_at, (int, float)):
        block["reset_at"] = reset_at
    elif isinstance(reset_at, str):
        text = safe_assignment_text(reset_at, limit=80)
        if text:
            block["reset_at"] = text
    try:
        resets_in = int(value["resets_in_seconds"])
    except (KeyError, TypeError, ValueError):
        resets_in = None
    if resets_in is not None and resets_in > 0:
        block["resets_in_seconds"] = resets_in
    return block


def _safe_journal_metadata(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, Any] = {}
    from ..auxiliary_chat import safe_auxiliary_result

    auxiliary = safe_auxiliary_result(value.get("auxiliary_result"))
    if auxiliary is not None:
        result["auxiliary_result"] = auxiliary
    for key, limit in _JOURNAL_TEXT_FIELDS.items():
        text = safe_assignment_text(value.get(key), limit=limit)
        if text:
            result[key] = text
        elif key in _JOURNAL_EMPTY_PRESERVING_FIELDS and value.get(key) is not None:
            # An empty value that was WRITTEN is a fact, not an absence — the
            # same distinction the run-budget block above is careful about.
            result[key] = ""
    run_budget = safe_run_budget_accounting(value.get(_JOURNAL_RUN_BUDGET_FIELD))
    if run_budget is not None:
        result[_JOURNAL_RUN_BUDGET_FIELD] = run_budget
    refusal = safe_provider_refusal(value.get(_JOURNAL_PROVIDER_REFUSAL_FIELD))
    if refusal is not None:
        result[_JOURNAL_PROVIDER_REFUSAL_FIELD] = refusal
    # Turn-latency phase spans (schema v3). Same absent-stays-absent rule the
    # run-budget block states above, applied one level deeper: the block itself
    # is absent on a v2 record, and INSIDE the block a phase the turn never
    # reached has no key. ``safe_turn_phases`` drops what it cannot read and
    # supplies nothing, so a reader can never mistake "did not happen" for
    # "happened at millisecond zero".
    phases = safe_turn_phases(value.get(TURN_PHASES_KEY))
    if phases is not None:
        result[TURN_PHASES_KEY] = phases
    # The runner's own breakdown of the bootstrap the phase block spans in one
    # number (see TURN_PROFILE_TIMING_KEY). Absent stays absent: a turn whose
    # runner reported nothing gets no key rather than an empty dict.
    profile_timing = safe_turn_profile_timing(value.get(TURN_PROFILE_TIMING_KEY))
    if profile_timing is not None:
        result[TURN_PROFILE_TIMING_KEY] = profile_timing
    for key in (
        "provider_submitted",
        "native_committed",
        "projection_committed",
        "projection_event_emitted",
        # True on any turn the wall budget ended — including the graceful case
        # that still projected a real reply, so "why is this reply short?" is
        # answerable from the record instead of from the operator's memory.
        "budget_exhausted",
    ):
        if key in value:
            result[key] = bool(value.get(key))
    return result


def _utc_now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _safe_elements(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    elements: list[dict[str, Any]] = []
    for raw in value[:_MAX_ELEMENTS]:
        if not isinstance(raw, dict):
            continue
        kind = safe_assignment_token(raw.get("kind"))
        element_id = safe_assignment_text(raw.get("id"), limit=240)
        turn_id = safe_assignment_token(raw.get("turn_id"))
        try:
            seq = int(raw.get("seq"))
        except Exception:
            continue
        if kind not in {"segment", "tool"} or not element_id or not turn_id:
            continue
        base: dict[str, Any] = {
            "kind": kind,
            "id": element_id,
            "turn_id": turn_id,
            "seq": seq,
            "state": safe_assignment_token(raw.get("state")) or "settled",
        }
        if kind == "segment":
            base.update(
                {
                    "seg_type": safe_assignment_token(raw.get("seg_type")) or "answer",
                    "text": safe_assignment_text(raw.get("text"), limit=_MAX_TEXT) or "",
                    "ttft_ms": non_negative_int(raw.get("ttft_ms")),
                    "duration_ms": non_negative_int(raw.get("duration_ms")),
                    "redacted": bool(raw.get("redacted")),
                }
            )
        else:
            files = raw.get("files")
            safe_files = [_safe_file_label(item) for item in files[:20]] if isinstance(files, list) else []
            base.update(
                {
                    "name": safe_assignment_token(raw.get("name")) or "tool",
                    "args": safe_assignment_text(raw.get("args"), limit=800),
                    "command": safe_assignment_text(raw.get("command"), limit=1000),
                    "status": safe_assignment_token(raw.get("status")) or None,
                    "summary": safe_assignment_text(raw.get("summary"), limit=1200),
                    "detail": safe_assignment_text(raw.get("detail"), limit=1200),
                    "output": safe_assignment_text(raw.get("output"), limit=_MAX_TEXT),
                    "exit_code": _safe_exit_code(raw.get("exit_code")),
                    "duration_ms": non_negative_int(raw.get("duration_ms")),
                    "files": [item for item in safe_files if item],
                    "redacted": bool(raw.get("redacted")),
                    # Generic tool input/result record — block-preserving bound
                    # (safe_assignment_text would fold the key-per-line contract
                    # the console dropdown renders into one line). Scrubbed and
                    # bounded upstream at the progress sink.
                    "tool_input": safe_block(raw.get("tool_input"), limit=1200),
                    "tool_result": safe_block(raw.get("tool_result"), limit=1800),
                }
            )
            # T7: preserve the todo tool's structured checklist (id/content/status)
            # so the operator console can render it after the turn persists. Bounded
            # again here (defence in depth over the producer cap).
            # T9d: keep an explicit EMPTY list too (`is not None`, not truthiness) —
            # a cleared checklist persists as `todo_state: []` so a reloaded turn
            # clears the panel exactly like the live lane. `_safe_todo_state`
            # returns None only for a truly absent/non-list value, so non-todo
            # elements still gain no key.
            todo_state = _safe_todo_state(raw.get("todo_state"))
            if todo_state is not None:
                base["todo_state"] = todo_state
            # Patch observability: the diff artifact's path and its +/− counts,
            # re-bounded here (defence in depth over the producer cap) so a
            # reloaded turn offers the same viewer affordance the live one did.
            # Keyed absent-when-absent — a non-patch element gains nothing.
            patch_artifact = safe_assignment_text(raw.get("patch_artifact"), limit=500)
            if patch_artifact:
                base["patch_artifact"] = patch_artifact
            patch_mode = safe_assignment_token(raw.get("patch_mode"))
            if patch_mode:
                base["patch_mode"] = patch_mode
            for count_key in ("patch_adds", "patch_dels"):
                count = non_negative_int(raw.get(count_key))
                if count is not None:
                    base[count_key] = count
        elements.append(base)
    return sorted(elements, key=lambda item: (int(item.get("seq") or 0), str(item.get("id") or "")))


# Turn-store caps for the T7 todo checklist. Compact by design — a checklist row
# is a short line and the elements ride the snapshot frame; the producer already
# bounds this, and this is the defence-in-depth boundary for foreign/legacy rows.
_TODO_STATE_MAX_ITEMS = 64
_TODO_STATE_MAX_CONTENT = 240
_TODO_STATE_VALID_STATUS = {"pending", "in_progress", "completed", "cancelled"}


def _safe_todo_state(value: Any) -> list[dict[str, str]] | None:
    """Bounded, validated todo checklist for persistence.

    Keeps only ``{id, content, status}`` per item, caps item count and content
    length, and normalises unknown statuses to ``pending``. Returns ``None`` only
    when ``value`` is not a list (absent / non-todo element), so a non-todo
    element never gains the key.

    T9d: a list ``value`` — including an explicit empty one — returns a list
    (possibly ``[]``). The empty list is the cleared-checklist signal and must
    survive persistence so a reloaded turn clears the panel exactly like the live
    lane; ``items or None`` would have collapsed it back to absence."""

    if not isinstance(value, list):
        return None
    items: list[dict[str, str]] = []
    for raw in value[:_TODO_STATE_MAX_ITEMS]:
        if not isinstance(raw, dict):
            continue
        item_id = safe_assignment_text(raw.get("id"), limit=120) or "?"
        content = safe_assignment_text(raw.get("content"), limit=_TODO_STATE_MAX_CONTENT) or "(no description)"
        status = str(raw.get("status") or "").strip().lower()
        if status not in _TODO_STATE_VALID_STATUS:
            status = "pending"
        items.append({"id": item_id, "content": content, "status": status})
    return items


def _safe_exit_code(value: Any) -> int | None:
    # Exit codes can be negative (signal terminations), so unlike non_negative_int we
    # keep the sign; just bound it to a sane range.
    try:
        parsed = int(value)
    except Exception:
        return None
    return parsed if -256 <= parsed <= 256 else None


def _safe_file_label(value: Any) -> str | None:
    text = safe_assignment_text(value, limit=240)
    if not text:
        return None
    lowered = text.lower()
    if any(marker in lowered for marker in _SENSITIVE_FILE_MARKERS):
        return None
    return text
