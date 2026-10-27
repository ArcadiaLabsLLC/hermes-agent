# Planned — a child spawned in a default-bound persona turn keeps the binding

**Status:** planned 2026-10-27 (planning lane w1027k-h-plan), replanning row
`RT-PERSONA-BINDING-ENV-REPLAN`. Supersedes the stage table of
[`persona-binding-env-authority.md`](persona-binding-env-authority.md) (left in place;
other lanes triage `planned/`). Owner doc: [`../05-chat-turn-lane.md`](../05-chat-turn-lane.md).

## Problem

The 2026-08-22 plan listed B-2 (a child spawned inside a persona turn carries the
binding), B-3 (the launcher's global home demoted to a default) and B-4 (binding on
create) as not started. Re-read against the tree on 2026-10-27:

- **B-2 is built for every profile except `default`.** `persona_profile_context`
  (`agent_runtime/profile_context.py`) binds the profile home in a ContextVar, and
  the terminal tool's child-env builder bridges it into the child as `HERMES_HOME`
  (`tools/environments/local.py::_apply_profile_home`, then
  `agent_runtime/run_context.py::apply_run_context_child_env` for the runtime root and
  auth home). `tests/agent_runtime/test_persona_binding_child_env.py` pins it. A child
  `hermes` started in a turn bound to profile `launcher-qa` therefore sees
  `HERMES_HOME=<root>/profiles/launcher-qa`, and `hermes_cli/main.py::_apply_profile_override`
  trusts it on the `Path(hermes_home_env).parent.name == "profiles"` rung.
- **The live bypass left is the `default` profile.** `hermes_cli/profiles.py::get_profile_dir`
  maps `default` to the hermes ROOT, not to `profiles/default`. A child of a
  default-bound turn gets `HERMES_HOME=<root>`, the `profiles` rung declines it, and the
  pre-parse falls through to the sticky `active_profile` marker. If the operator ever ran
  `hermes profile use <x>`, the child silently runs as `<x>` — the exact "env picks the
  profile instead of the binding" class the ruling retires.
- **B-3 is shipped.** The launcher's settings copy reads "Default profile home"
  (launcher commit `53d96d4ab`, recorded in the launcher's
  `Launcher_Brain/20 — Active Initiatives/plan-eg-weakness-escalation-ledger.md` E6; its
  only open item is a Stage C screenshot, tracked there, not here).
- **B-4 is shipped.** `agent_runtime/agent_create/request.py` reads and validates
  `hermes_profile` on create.
- **The chat-head ladder is not the gap.** Per-profile chat heads
  (`RT-CHAT-HEAD-PER-PROFILE`, landed) record each conversation's head on the instance
  (`INSTANCE_RECORDED`, `agent_runtime/chat_session_scope.py`). A spawned child is a
  new process with its own session, not the persona's conversation, so it needs no
  rung of its own in `chat_session_scope`; the binding it must carry is the profile
  HOME, which is the pre-parse's question, not the ladder's.

## Decisions

1. **B-2's remaining slice is one marker, not a new ladder rung.** When
   `_apply_profile_home` bridges a bound home override, it also writes
   `HERMES_PROFILE_PINNED=1` into the child env. Why: the child must be told "this
   `HERMES_HOME` is a binding, not an ambient root", and only the parent knows that.
2. **`_apply_profile_override` treats the marker like a supervised child.** Beside
   `_under_gateway_supervisor(argv)` (upstream's own precedent: a supervised
   default-profile child must not follow `active_profile`, #74872), a fork-marked
   condition skips the sticky marker when `HERMES_PROFILE_PINNED` is set, and the
   receipt `HERMES_PROFILE_RESOLUTION` reads `binding_pinned`. An explicit `--profile`
   still wins (it is consumed before this rung).
3. **The marker is written only when a home was BOUND.** An unbound persona's child
   keeps inheriting the serve's ambient env exactly as today; the marker never appears
   on a context with no override, so a systemd unit pointing `HERMES_HOME` at the root
   keeps honouring `hermes profile use` (#22502 stays intact).
4. **B-3 and B-4 close here.** No row is owed for either; the screenshot stays on the
   launcher ledger.

## Slices

**S1 — pin the bound home across the spawn** (one slice, row `RT-PERSONA-BINDING-ENV-REPLAN`)

- `tools/environments/local.py` — `_apply_profile_home` writes `HERMES_PROFILE_PINNED=1`
  when `get_hermes_home_override()` answered.
- `hermes_cli/main.py` — `_apply_profile_override`: one fork-marked condition skipping
  the `active_profile` read when the marker is set; receipt value `binding_pinned`.
- `tests/agent_runtime/test_persona_binding_child_env.py` — new cases below.
- `tests/hermes_cli/test_apply_profile_override_downstream.py` — new cases below.
- `docs/agent-runtime-harness/05-chat-turn-lane.md` — one sentence where the persona
  binding is described.

## Test plan

- *Child env carries the marker under a default binding*: bind a persona to
  `default` (home = the tmp root), build the child env through the production
  factory, assert `HERMES_PROFILE_PINNED == "1"` and `HERMES_HOME == <root>`.
  **Killing mutation:** delete the marker write in `_apply_profile_home` → red.
- *Positive control*: the same factory with NO binding has no marker.
  **Killing mutation:** write the marker unconditionally → red.
- *Pre-parse honours it*: tmp root with `active_profile` = `other`,
  `HERMES_HOME=<root>`, `HERMES_PROFILE_PINNED=1`, no `--profile` → `HERMES_HOME`
  unchanged and receipt `binding_pinned`. **Killing mutation:** remove the fork
  condition → `HERMES_HOME` becomes `<root>/profiles/other`, red.
- *Positive control*: the same tmp root without the marker still follows
  `active_profile` (the #22502 behaviour). **Killing mutation:** skip the sticky read
  whenever `HERMES_HOME` is set → red.
- *Explicit flag still wins*: marker set plus `--profile x` → profile `x`.

## Open questions

None for the owner.
