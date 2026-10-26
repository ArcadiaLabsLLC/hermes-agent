# Planned — a blocked terminal command: fixable vs final, and an operator allow-once (RT-SAFETY-BLOCK-RECOVERY-AND-OVERRIDE, 2026-10-25)

**Owner domain:** the chat turn lane ([05-chat-turn-lane.md](../05-chat-turn-lane.md)), tool admission.
**Status:** RULED 2026-10-25 (lane w1025b-h-misc, by the wave brief's "go with recommendations"); build rows in §4.
**Read (code, no live turn):** hermes `origin/main` `eed79e6933` — `tools/terminal_tool_guards.py::_blocked_json`
and `self_repo_block` (upstream), `tools/self_repo_guard.py::_block_message` (upstream),
`tools/self_repo_guard_vars.py::unresolved_message` (fork), `tools/approval.py::submit_pending` /
`resolve_gateway_approval` (upstream), the plugin's `transform_tool_result` hook (`hermes_cli/plugins.py`).

## 0. The owner's words (2026-10-22)

"why does it just stop after turn why doesn't it try again in the same turn? or start a new one?" and "we
should have a safety bypass aswell in the permissions".

## 1. What the code says

- The block is an ordinary tool RESULT: `_blocked_json` returns `{"exit_code": 1, "error": …, "status":
  "blocked"}` and nothing in the conversation loop ends a turn on it. So the stop is the MODEL's — and the
  FINAL text tells it to: "To change this checkout, stop Hermes, run the command externally, then restart
  Hermes." The FIXABLE text (`unresolved_message`, fork) already says how to respell.
- The envelope does not say which class it is, so neither the model nor the Launcher can branch on it.

## 2. Decisions (`Decided (plan):`)

1. **Measure one live blocked turn before building any retry.** The code says the runtime does not stop the
   turn; the live read confirms whether the model does. Owed on the owner's serve (a live proof, §4).
2. **The class is a typed field, added by a fork seam, never an upstream edit.** The eternia-harness plugin's
   `transform_tool_result` hook adds `block_class: "fixable" | "final"` to a terminal result whose `status` is
   `blocked`, deciding by the fork's own classifier beside `unresolved_message` (`self_repo_guard_vars.py`
   grows `block_class(error_text)`: the unresolved-variable refusal is `fixable`, every other self-repo block
   `final`). The model and the Launcher read one field.
3. **The fixable class is retried by the model, in the same turn, once.** No runtime retry loop: the fixable
   text already names the respelling, and a tool-guidance line (the plugin's
   `eternia-harness.tool-guidance` section) says a `fixable` block is answered by respelling once, a `final`
   block by saying so and offering a new turn.
4. **Allow-once goes through upstream's approval queue, never a second store.** A `final` self-repo block
   would surface as the same allow/deny card and `/approve` the dangerous-command guard uses
   (`submit_pending` / `resolve_gateway_approval`), recorded with who allowed it. The guard consulting the
   queue is a change inside upstream's `self_repo_block`, so it is an UPSTREAM PR first (an operator
   allow-once for the self-repo guard serves upstream's users too); the fork does not carry it.
5. **No blanket off switch.** The permission mode never disables the guard; allow-once is per command.

## 3. The Launcher half

The approval card already renders for dangerous-command approvals; an allow-once self-repo block reuses it
once §2.4 lands upstream. Nothing to build launcher-side before that.

## 4. Build rows

- hermes `RT-SAFETY-BLOCK-CLASS-FIELD` — §2.2 + §2.3 (classifier, `transform_tool_result` seam, guidance line).
- hermes `RT-SAFETY-BLOCK-LIVE-READ` — §2.1, one blocked turn on the owner's serve, read from its transcript.
- hermes `RT-SAFETY-BLOCK-ALLOW-ONCE` — §2.4, upstream PR for the self-repo guard consulting the approval queue.
