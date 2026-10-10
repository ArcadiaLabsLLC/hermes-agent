"""Preview/apply history controls on one explicitly addressed operator chat."""
from __future__ import annotations

from contextlib import ExitStack, closing, contextmanager
from enum import StrEnum
import hashlib
import json
import re
import uuid

from . import chat_session_scope
from .chat_turn_reservations import unsettled_chat_receipts
from .conversation_owner import require_session_owner
from .locks import HarnessLockUnavailable, chat_history_admission_lock, chat_history_mutation_lock
from .operator_conversation import OperatorConversationRefused
from .operator_session_inspection import inspection_identity, operator_session_read
from .persona_chat_continuity.clarify_tickets import PersonaChatClarifyTicketStore
from .persona_chat_continuity.lease import PersonaChatBusyError, persona_chat_root_lease
from .mission_chat_turns.reads import mission_chat_turn_records
from .mission_chat_turns.states import INFLIGHT_TURN_STATES, SETTLING_TURN_STATES
from .history_cancellation import require_not_cancelled

__layer__ = "lanes"


class HistoryAction(StrEnum):
    BRANCH = "branch"
    REWIND = "rewind"


def _action(params):
    try:
        return HistoryAction(params.get("action"))
    except ValueError as exc:
        raise OperatorConversationRefused("invalid_history_action") from exc


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True).encode()).hexdigest()


def _scopes(params):
    return sorted({params["session_id"], params["persona_instance_id"], f"persona:{params['persona_id']}"})


def require_history_idle(params):
    from .serve_rpc.protocol import PEER_REQUESTED_BY_PREFIX
    session = params["session_id"]
    from .history_recovery import pending_history_operation
    pending = pending_history_operation(session)
    if pending is not None and pending != params.get("operation_id"):
        raise OperatorConversationRefused("history_recovery_required")
    protected = INFLIGHT_TURN_STATES | SETTLING_TURN_STATES
    if (any(turn["state"] in protected for turn in mission_chat_turn_records(session_id=session))
            or unsettled_chat_receipts(set(_scopes(params)), peer_prefix=PEER_REQUESTED_BY_PREFIX)
            or PersonaChatClarifyTicketStore().open_ticket_for_session(session)):
        raise OperatorConversationRefused("conversation_busy")


@contextmanager
def history_write_scope(params):
    """Fence history writes while serializing only the brief admission check.

    Translate acquisition refusals here, never errors from the caller after a
    mutation: an exception after ``yield`` may follow a committed write.
    """
    with ExitStack() as writer, ExitStack() as admission:
        try:
            for scope in _scopes(params):
                writer.enter_context(chat_history_mutation_lock(scope))
                admission.enter_context(chat_history_admission_lock(scope))
            writer.enter_context(persona_chat_root_lease(params["session_id"], observer_kind="history_control"))
        except (HarnessLockUnavailable, PersonaChatBusyError) as exc:
            raise OperatorConversationRefused("conversation_busy") from exc
        require_history_idle(params)
        admission.close()
        yield


def _target(db, session_id, row_id=None, client_message_id=None, *, after_reply=False):
    from agent.context_compressor import user_originated_turn_view, retryable_user_text
    from .runtime_hud.envelopes import extract_runtime_context_envelope, extract_skill_preload_envelope
    from .persona_chat_history.text import _safe_display_body_text, _INTERNAL_SCAFFOLDING_MARKERS
    from .persona_chat_history.vocabulary import logical_persona_chat_client_message_id

    tip = db.resolve_resume_session_id(session_id)
    revision = db.history_control_revision(tip)
    stored = db.get_messages_as_conversation(tip, include_row_ids=True)
    users = [row for row in stored if user_originated_turn_view(row) is not None]
    matched = [row for row in users if (
        row.get("_row_id") == row_id if row_id is not None else
        logical_persona_chat_client_message_id(row.get("message_id")) == client_message_id)]
    if len(matched) != 1:
        raise OperatorConversationRefused("target_unavailable")
    target = matched[0]
    if after_reply:
        start = stored.index(target)
        end = next((index for index in range(start + 1, len(stored))
                    if user_originated_turn_view(stored[index]) is not None), len(stored))
        prefix = stored[start:end]
        closing_reply = prefix[-1]
        if (closing_reply.get("role") != "assistant" or closing_reply.get("tool_calls")
                or not closing_reply.get("content")):
            raise OperatorConversationRefused("reply_not_complete")
        ordinal = users.index(target)
        return dict(tip=tip, revision=revision, row_id=target["_row_id"],
                    boundary_row_id=closing_reply["_row_id"], ordinal=ordinal,
                    draft="", earlier_turns=ordinal + 1, affected_turns=0)
    # A repaired user/user pair or a compaction carrier is not the prompt the
    # Console selected. Refuse rather than silently combine/remove another ask.
    repaired = [row for row in db.get_messages_as_conversation(
        tip, include_row_ids=True, repair_alternation=True) if user_originated_turn_view(row) is not None]
    view = next((row for row in repaired if row.get("_row_id") == target["_row_id"]), None)
    if view is None or view.get("content") != target.get("content"):
        raise OperatorConversationRefused("target_requires_compaction_review")
    if user_originated_turn_view(target).get("content") != target.get("content"):
        raise OperatorConversationRefused("target_requires_compaction_review")
    try:
        draft = retryable_user_text(target.get("content"))
    except ValueError as exc:
        raise OperatorConversationRefused("prompt_attachments_not_restorable") from exc
    draft, _ = extract_runtime_context_envelope(draft)
    draft, _ = extract_skill_preload_envelope(draft)
    if not isinstance(draft, str) or not draft.strip() or "[Operator attached " in draft:
        raise OperatorConversationRefused("prompt_attachments_not_restorable")
    if any(marker in draft for marker in _INTERNAL_SCAFFOLDING_MARKERS) or target.get("finish_reason"):
        raise OperatorConversationRefused("target_unavailable")
    _, redaction = _safe_display_body_text(draft, fallback="", limit=64000)
    if redaction != "safe" or len(draft) > 64000:
        raise OperatorConversationRefused("prompt_not_restorable")
    if db.history_control_revision(tip) != revision:
        raise OperatorConversationRefused("history_changed")
    ordinal = next(i for i, row in enumerate(repaired) if row["_row_id"] == target["_row_id"])
    return dict(tip=tip, revision=revision, row_id=target["_row_id"], ordinal=ordinal,
                draft=draft, earlier_turns=ordinal, affected_turns=len(repaired) - ordinal)


def _plan(params, session):
    action = _action(params)
    row_id, client_id = params.get("row_id"), params.get("client_message_id")
    if row_id is not None and (type(row_id) is not int or row_id <= 0):
        raise OperatorConversationRefused("invalid_history_target")
    if row_id is None and (not isinstance(client_id, str) or not client_id or len(client_id) > 240):
        raise OperatorConversationRefused("invalid_history_target")
    boundary = params.get("boundary", "before_prompt")
    if boundary not in {"before_prompt", "after_reply"} or (boundary == "after_reply" and action != HistoryAction.BRANCH):
        raise OperatorConversationRefused("invalid_history_target")
    target = _target(session.db, params["session_id"], row_id, client_id, after_reply=boundary == "after_reply")
    target["boundary"] = boundary
    # A branch must contain the full visible prefix. Until native compressed
    # lineage copying is supported, never offer a misleading partial branch.
    if action == HistoryAction.BRANCH and target["tip"] != params["session_id"]:
        raise OperatorConversationRefused("branch_compressed_history_unavailable")
    identity = inspection_identity(params, session.owner)
    target["settings_revision"] = _digest([session.row.get("model_config"), session.row.get("cwd")])
    return {**identity, "action": action.value, **target,
            "preview_token": _digest({**identity, "action": action, **target})}


def preview_operator_history(params):
    with operator_session_read(params) as (_, session):
        require_history_idle(params)
        return _plan(params, session)


def _receipt_key(params):
    key = params.get("operation_id")
    if not isinstance(key, str) or re.fullmatch(r"[A-Za-z0-9_-]{16,100}", key) is None:
        raise OperatorConversationRefused("invalid_operation_id")
    return "operator_history:" + _digest([params["session_id"], params.get("client_scope"), key])


def _replay(db, key, request_digest):
    raw = db.get_meta(key)
    if raw is None:
        return None
    record = json.loads(raw)
    if record["request_digest"] != request_digest:
        raise OperatorConversationRefused("operation_payload_changed")
    return _with_branch_entry(db, {**record["result"], "replayed": True})


def operator_history_status(params):
    key = _receipt_key(params)
    with operator_session_read(params) as (_, session):
        raw = session.db.get_meta(key)
        return {**inspection_identity(params, session.owner), "operation_id": params["operation_id"],
                "state": "applied" if raw else "not_recorded",
                "result": _with_branch_entry(session.db, json.loads(raw)["result"]) if raw else None}


def _with_branch_entry(db, result):
    if result["action"] != HistoryAction.BRANCH:
        return result
    from .persona_chat_history.history_rows import _history_row
    child = result["result_session_id"]
    row = db.get_session(child)
    if row is None:
        raise OperatorConversationRefused("branch_unavailable")
    entry = _history_row(row, persona_id=result["persona_id"], instance_id=result["persona_instance_id"],
                         session_id=child, session_db=db, message_tail=1)
    return {**result, "branch": entry}


def operator_history_origin(params):
    from .persona_chat_history.history_rows import _history_row
    with operator_session_read(params) as (_, session):
        config = json.loads(session.row.get("model_config") or "{}")
        source = config.get("_branched_from")
        row = session.db.get_session(source) if source else None
        origin = None
        if row is not None:
            require_session_owner(row, params.get("client_scope"))
            origin = _history_row(row, persona_id=params["persona_id"], instance_id=params["persona_instance_id"],
                                  session_id=source, session_db=session.db, message_tail=1)
        return {**inspection_identity(params, session.owner), "origin": origin}


def apply_operator_history(params):
    from hermes_state_history_controls import HistoryControlError
    from hermes_state_errors import (SessionActiveWriteGuardError, SessionTurnLeaseLostError,
                                    SessionCompressionInProgressError, CompressionSessionClosedError)
    from hermes_state_rewind import RewindTargetUnavailableError

    key = _receipt_key(params)
    request_digest = _digest(params)
    with operator_session_read(params) as (_, session):
        replay = _replay(session.db, key, request_digest)
        if replay is not None:
            return replay
        scope = session.scope
    try:
        with history_write_scope(params):
            with operator_session_read(params) as (_, session):
                require_not_cancelled(session.db, key)
                replay = _replay(session.db, key, request_digest)
                if replay is not None:
                    return replay
                plan = _plan(params, session)
                if plan["preview_token"] != params.get("preview_token"):
                    raise OperatorConversationRefused("history_changed")
                config = json.loads(session.row.get("model_config") or "{}")
                title = session.row.get("title") or "Conversation"
            db = chat_session_scope.open_chat_session_db(scope, access=chat_session_scope.SessionDbAccess.WRITE)
            if db is None:
                raise OperatorConversationRefused("session_db_unavailable")
            with closing(db):
                require_session_owner(db.get_session(params["session_id"]), params.get("client_scope"))
                return _with_branch_entry(db, _apply_native(db, params, plan, config, title, key, request_digest))
    except HistoryControlError as exc:
        raise OperatorConversationRefused(exc.reason) from exc
    except RewindTargetUnavailableError as exc:
        # The canonical rewind wraps writer ValueErrors. Preserve the pin's
        # refusal, rather than reporting an unknown outcome after no write.
        reason = exc.__cause__.reason if isinstance(exc.__cause__, HistoryControlError) else "target_unavailable"
        raise OperatorConversationRefused(reason) from exc
    except (SessionActiveWriteGuardError, SessionTurnLeaseLostError, SessionCompressionInProgressError) as exc:
        raise OperatorConversationRefused("conversation_busy") from exc
    except CompressionSessionClosedError as exc:
        raise OperatorConversationRefused("history_changed") from exc


def _apply_native(db, params, plan, config, title, key, request_digest):
    result = {**inspection_identity(params, params.get("client_scope")), "action": plan["action"],
              "operation_id": params["operation_id"], "draft": plan["draft"], "replayed": False,
              "result_session_id": params["session_id"], "affected_turns": plan["affected_turns"]}
    if plan["action"] == HistoryAction.BRANCH:
        child = f"persona_chat_{params['persona_instance_id']}_{uuid.uuid4().hex[:12]}"
        result["result_session_id"] = child
        # Explicit branch root: do not inherit compression/default-root/cache identity.
        for name in ("mission_chat_root_id", "_reset_from", "_delegate_from", "cache_scope_id"):
            config.pop(name, None)
        config.update(_branched_from=params["session_id"], persona_id=params["persona_id"],
                      persona_instance_id=params["persona_instance_id"],
                      mission_chat_root_id=child, history_source_session=params["session_id"])
    receipt = (key, json.dumps({"request_digest": request_digest, "result": result}))
    if plan["action"] == HistoryAction.BRANCH:
        db.branch_before_message(plan["tip"], plan.get("boundary_row_id", plan["row_id"]), child_session_id=child,
            after_reply=plan["boundary"] == "after_reply",
            expected_history_digest=plan["revision"], operation_receipt=receipt,
            model_config=config, title=f"{title[:160]} · branch")
    else:
        db.rewind_user_turn(plan["tip"], plan["ordinal"], require_retryable=True,
            expected_history_digest=plan["revision"], operation_receipt=receipt)
    return result
