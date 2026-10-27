# Planned — retire `kill_active` / `killed_previous` from chat open

**Status:** planned 2026-10-27 (planning lane w1027k-h-plan), replanning row
`RT-CHAT-SWAP-KILL-ACTIVE-NOOP`. Supersedes
[`chat-swap-kill-active-guard.md`](chat-swap-kill-active-guard.md) (left in place).
Owner doc: [`../01-system-architecture.md`](../01-system-architecture.md).

## Problem

`kill_active` is accepted on every chat-open lane and reported back as
`"killed_previous": true`, but nothing is killed. Re-anchored against the tree on
2026-10-27:

- **Accepted, never acted on.** `agent_runtime/persona_assignments/chat_binding.py`
  takes `kill_active` on `open_chat` and its bind helper and never reads it in the
  body. It is threaded in from `agent_runtime/persona_open_chat.py` (RPC params),
  `agent_runtime/chat_verbs/instance_create.py`, `agent_runtime/serve_rpc/twin_params.py`
  (accepted keys), `agent_runtime/persona_chat_continuity/mint_receipts.py` (a receipt
  field), and the CLI's `--kill-active` on create and open-chat
  (`hermes_cli/harness_parts/persona/lifecycle_commands.py`,
  `hermes_cli/harness_parts/persona/chat_open.py`).
- **Reported as done.** `"killed_previous": bool(kill_active)` is an echo of the
  caller's own flag in `lifecycle_commands.py` and twice in `chat_open.py`.
- **It now opens a review that guards nothing.** In `chat_open.py`, a coordinator
  passing `--kill-active` is sent through `review_coordinator_budget("persona.instance.close", …)`
  and may be told to confirm a close that will not happen.
- **One lane already refuses it honestly.** `agent_runtime/serve_rpc/operator_conversation.py`
  answers `kill_active` on `runtime.operator.conversation.message` with
  `replace_not_allowed`; that stays.
- **The launcher still sends it.** Its persona capability manifest declares the
  `kill_active` argument and `--kill-active` argv segment
  (launcher `lib/core/services/hermes/runtime/data/capabilities/harness_persona_capabilities.dart`),
  and the lowering forwards it when an action sets it
  (launcher `lib/features/mission_control/data/mission_open_chat_lowering.dart`,
  `lib/features/mission_control/data/bridge/mission_action_chat_twin_lane.dart`).
  Nothing in the launcher reads `killed_previous`.

## Decisions

1. **Drop it; do not redefine it.** There are no runs to cancel since the mission-lane
   removal; the only concurrency object is the per-turn chat-root lease, and the verb
   that ends a turn in flight already exists (`runtime.operator.conversation.stop`).
   Turning `kill_active` into "break the lease" would give `chat_busy` a second meaning
   on the open path and add a second way to stop a turn. Not a product choice: the
   flag has done nothing a user could see since the lane went.
2. **Stop the lie first, refuse later.** Hermes cannot refuse the key while the
   launcher still sends it (a refused open is a user-visible failure), so the work is
   two slices with the launcher between them.
3. **The coordinator review goes with the flag.** It reviews a close that is never
   performed; removing it changes no outcome except an empty confirm prompt.

## Slices

**S1 — no more `killed_previous`, no review, key ignored** (row `RT-CHAT-SWAP-KILL-ACTIVE-NOOP`, READY)

- `hermes_cli/harness_parts/persona/chat_open.py` — delete the `kill_active` coordinator
  branch and both `killed_previous` keys; `--kill-active` stays parsed but unread.
- `hermes_cli/harness_parts/persona/lifecycle_commands.py` — delete `killed_previous`
  and the forwarding.
- `hermes_cli/harness_parts/parser/persona.py` — the `--kill-active` help text says
  "retired: accepted and ignored".
- `agent_runtime/persona_assignments/chat_binding.py`, `agent_runtime/persona_assignments/store.py`,
  `agent_runtime/persona_chat_continuity/mint_receipts.py`,
  `agent_runtime/work_store/persona_turn.py`,
  `hermes_cli/harness_parts/persona/chat_turn_commit/admit.py` — the parameter and
  receipt field go.
- `agent_runtime/persona_open_chat.py`, `agent_runtime/chat_verbs/instance_create.py`,
  `agent_runtime/serve_rpc/twin_params.py` — still ACCEPT the key (so nothing the
  launcher sends is refused) and no longer forward it.
- `tests/fixtures/hermes_cli_contract.json` — regenerate if the `--kill-active` help text
  is part of the dump.

**S2 — refuse the key** (row `RT-KILL-ACTIVE-REFUSE`, BLOCKED on the launcher row below)

- `agent_runtime/persona_open_chat.py`, `agent_runtime/chat_verbs/instance_create.py`,
  `agent_runtime/serve_rpc/twin_params.py` — remove `kill_active` from the accepted
  keys, so a sender is told `-32602` with `reason: "kill_active_retired"`.
- `hermes_cli/harness_parts/parser/persona.py` — remove `--kill-active`.
- `tests/agent_runtime/serve_rpc_manifest.expected.json` — the two `kill_active`
  entries go.

**Launcher row (files in the launcher's Mission Control queue):** stop declaring and
forwarding `kill_active` (manifest, lowering, twin lane). Verbatim row in the lane report.

## Test plan

- *S1, no echo:* `persona instance open-chat --kill-active --json` returns no
  `killed_previous` key. **Killing mutation:** restore `"killed_previous": …` in
  `chat_open.py` → red.
- *S1, no review:* a coordinator open-chat with `--kill-active` returns exit 0 and no
  `persona.instance.close` confirm payload. **Killing mutation:** restore the
  `elif coordinator_id and kill_active` branch → red.
- *S1, still accepted (positive control):* the RPC `runtime.persona.instance.open_chat` with
  `kill_active: true` binds as it does without it. **Killing mutation:** drop the key
  from the accepted set in S1 → red.
- *S2, refused:* the same RPC answers `-32602` `kill_active_retired`.
  **Killing mutation:** leave the key in the accepted set → red.

## Open questions

None for the owner.
