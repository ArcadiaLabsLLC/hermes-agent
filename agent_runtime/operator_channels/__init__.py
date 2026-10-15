"""The Agent Console projection: one render contract per operator channel.

Package map (lane B3, sheet ``god-file-layout-sheets/operator_channels.md`` §1).
``operator_channel_summary`` is the one entry point (``snapshot/sections.py``,
``status.py``); everything else is reached from inside it. Layers point down
(models <- policy <- stores <- lanes <- wiring); this map is ``stores`` because
the highest layer it re-exports is ``stores``.

    agent_runtime/operator_channels/
      __init__.py           stores   this map; re-exports the entry point and the test-read names
      vocabulary.py         policy   the schema versions, the kind/status sets, the terminal-marker
                                     presentation, the two regexes, and the safe coercions that
                                     read them (_safe_conversation_text, first_present_text);
                                     the TRACE_*_STATUSES sets read by name (clock.parse_iso
                                     parses every stamp here)
      instances.py          stores   which instance a channel is: ChannelIdentity (the ONE
                                     derivation the build and the ancestry graph share), channel
                                     keys, recency, the merged trace, the newborn / dormant
                                     predicates, the ancestry graph
      summary.py            stores   operator_channel_summary + _OperatorChannelBuilder (build =
                                     identity -> sources -> conversation -> warnings -> row)
      conversation.py       policy   one channel's conversation: _conversation_contract,
                                     terminal-tool settling, order, dedupe (DEDUPE_RULES), cap
      history_messages.py   policy   a curated history row -> a conversation message
                                     (HistoryMessage phases; HISTORY_ROW_SHAPES)
      trace_messages.py     policy   a trace entry -> conversation messages (progress, thinking,
                                     subagent prompts, tool calls)

    entry point                                   opens
    operator_channel_summary                      summary -> instances, conversation
    _conversation_contract                        conversation -> history_messages, trace_messages
    _conversation_history_message                 history_messages
    _dedupe_conversation_messages / _turn_identity_dropped    conversation

``conversation.py`` is the sheet's ``contract.py``: that basename is taken twice
already in this tree, and a lane exemption keyed on it
(``test_snapshot_contract_version_authority``) would cover every copy.

``instances`` and ``summary`` are ``policy``: the canonical persona spelling
they read is ``persona_chat_history.vocabulary.canonical_chat_persona_id``, and
the projection itself performs no I/O.
"""

from __future__ import annotations

from . import conversation, history_messages, instances, summary, trace_messages, vocabulary
from .conversation import (
    DEDUPE_FLOW_KINDS,
    DEDUPE_RULES,
    DedupeState,
    __layer__,
    _apply_conversation_cap,
    _conversation_contract,
    _dedupe_conversation_messages,
    _drop_flow_echo,
    _drop_repeated_subagent_prompt,
    _drop_thinking_repeat,
    _latest_message_timestamp,
    _order_conversation_messages,
    _settle_terminal_tool_calls,
    _turn_identity_dropped,
    _turn_identity_mismatched,
)
from .history_messages import (
    AGENT,
    HIDDEN_REDACTION_STATUSES,
    HIDDEN_TEXT,
    HISTORY_ROW_SHAPES,
    HistoryMessage,
    OPERATOR,
    RowShape,
    SYSTEM,
    ShapeBuilder,
    __layer__,
    _carry_history_run_budget,
    _carry_turn_seq,
    _conversation_history_message,
    _delivery_block,
    _harness_delivery_shape,
    _operator_shape,
    _pre_trace_ack_shape,
    _relay_sender_instance_id,
    _relayed_shape,
    _reply_shape,
    _system_shape,
    history_row_shape,
)
from .instances import (
    ChannelIdentity,
    __layer__,
    _canonical_instance,
    _channel_key_for_instance,
    _instance_recency,
    _latest_history,
    _merged_trace,
    _newest_instance,
    _operator_conversation_relationships,
    _row_recency,
    _source_instance_ids_conflict,
    _trace_entry_key,
    _trace_entry_sort_key,
    channel_identity,
    is_dormant_channel,
    is_newborn_channel,
)
from .summary import (
    _OperatorChannelBuilder,
    __layer__,
    _emptiness_warnings,
    operator_channel_summary,
)
from .trace_messages import (
    TRACE_STATUS_KINDS,
    _TOOL_DETAIL_INT_FIELDS,
    _TOOL_DETAIL_STR_FIELDS,
    __layer__,
    _conversation_assignment_message,
    _conversation_kind_from_status,
    _conversation_title_for_kind,
    _conversation_tool_call_messages,
    _conversation_trace_message,
    _merge_tool_detail,
    _tool_call_message,
    _tool_status_token,
)
from .vocabulary import (
    FLOW_MESSAGE_KINDS,
    OPERATOR_CHANNELS_SCHEMA_VERSION,
    OPERATOR_CONVERSATION_SCHEMA_VERSION,
    TOOL_CALL_RUNNING,
    TRACE_BLOCKER_STATUSES,
    TRACE_FINAL_STATUSES,
    TRACE_HANDOFF_STATUSES,
    _CHAT_INSTANCE_MODES,
    _CONVERSATION_MESSAGE_CAP,
    _CONVERSATION_TRIMMABLE_KINDS,
    _SECRET_RE,
    _SETTLED_TOOL_CALL_STATUS,
    _TELEMETRY_SUMMARY_RE,
    _TERMINAL_TURN_MARKER_PRESENTATION,
    _TOOL_FAILED_STATUSES,
    _TOOL_OK_STATUSES,
    __layer__,
    _conversation_message_sort_key,
    _display_name_from_history,
    _safe_conversation_list,
    _safe_conversation_text,
    _safe_instance_id,
    _safe_session,
    first_present_text,
)

__layer__ = "stores"

__all__ = ["operator_channel_summary"]
