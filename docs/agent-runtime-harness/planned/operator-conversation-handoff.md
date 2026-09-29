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
`agent_runtime/serve_rpc/operator_conversation.py` exposes the methods;
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

## Lifecycle checkpoint

Live partial answers come from the existing bounded journal projection. Launcher
refreshes the authoritative read every two seconds while visible; this is not
token-by-token fan-out and does not compete with Mission Control's frame reader.
Settled history replaces live elements. No event cache or transcript store was added.

`operator_execution.py` scopes Stop to the original admission/session. The existing
receipt stores Stop intent and a normalized payload fingerprint. Reusing a new
receipt with changed content refuses; old receipts remain replay-only evidence.
`serve/operator_interrupt.py` binds upstream `InterruptScope` around the same
worker. A queued Stop prevents dispatch; a running Stop targets that worker only.
Uncertain/missing owners remain unconfirmed. Completion wins a late Stop.
Worker settlement is pinned to the serve's profile home.

The deterministic lane tests drive the real RPC context, admission, inflight
table, dispatch and settlement without a daemon, socket, model or extra thread.
They cover lost/repeated Stop acknowledgements, queued Stop, newer-turn isolation,
workspace refusal, completion racing Stop and restart with uncertain work.
Killing mutation: acknowledging Stop without calling upstream interruption makes
the running test fail (`stop_requested` instead of `finished`); restored.

## Still required before closing the queue row

- Reconcile with current main and run the focused compatibility checks.
- Native desktop acceptance. The required Launcher QA tools are unavailable;
  automated native-store fixtures are not a desktop or real-provider smoke test.

Do not replace these with another worker, replay authority or copied transcript.
