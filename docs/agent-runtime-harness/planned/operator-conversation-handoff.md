# Exact operator conversation attachment

In progress. This checkpoint is not the full handoff acceptance.
Launcher tracking: `EterniaLauncher/docs/companion/planned/CROSS_INTERFACE_RECOVERY_2026-09-28.md`.

## Implemented boundary

`runtime.operator.conversation.read` reads existing SessionDB history, native
turn records and clarify tickets. `runtime.operator.conversation.message`
validates the exact installation/workspace/instance/session, then calls the
existing `perform_chat_turn`. It neither selects a default nor starts another
conversation worker. Reads close their database handle and cannot mint sessions.

Ownership: `agent_runtime/operator_conversation.py` validates and composes reads;
`agent_runtime/serve_rpc/operator_conversation.py` exposes the two methods;
`persona_chat_history.messages.existing_persona_chat_messages` reuses curation.
SessionDB, `mission_chat_turns`, `chat_turn_reservations` and clarify tickets remain
the only native authorities. No upstream-owned file was changed.

## Evidence

`tests/agent_runtime/test_operator_conversation_attachment.py`: two tests pass
against real profile stores and the real dispatcher, without serve or models.
They cover A → B → A isolation, paged history, pending question identity,
original Mission Control send → attachment replay (one spawn), and refusal of
foreign/missing sessions, changed targets and replacement requests.

Killing mutation: removing the install guard made the A → B read incorrectly
succeed (`KeyError: 'error'` at the required refusal). Restored; both tests pass.
Launcher additionally exercises its real adapter and encrypted recovery after
lost acknowledgement and client reconstruction, with one native admission.

## Still required before closing the queue row

- Attach to current live operator output through its existing observation owner;
  the checkpoint provides history and journal status, not token-stream parity.
- Execution-scoped Stop in the existing serve owner, using upstream interrupt
  scopes and durable native evidence. The current method honestly advertises
  `can_interrupt: false`; the independent-conversation interrupt is not reusable
  against an operator-owned session.
- Native desktop acceptance and focused regression qualification of that wiring.

Do not replace these with another worker, replay authority or copied transcript.
