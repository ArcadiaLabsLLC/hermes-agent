# Runtime model — explanatory notes

The preloaded `SKILL.md` carries the rules, names, paths and commands a turn
needs. This file carries the explanation behind four of its sections, moved
here on 2026-09-24 so the preload stays under its byte ceiling
(`agent_runtime/skill_install.py::SKILL_SIZE_CEILINGS`). Nothing here overrides
the head; read it when you need the why.

## The work contracts — load by role and order size

This package is how to OPERATE the runtime. The work itself has its own
contracts — separate skills, loaded to match the work, never folded in here:

- `harness-dev-delivery` — the ALWAYS-ON contract for every dev chat turn,
  one-line fix included: repo discipline, focused self-tests, commit hygiene,
  the cross-stack contract packet, honest reporting.
- `staged-deep-audit-delivery` — the LOAD-ON-ORDER process for a staged,
  multi-stage implementation order: the trigger checklist plus the
  stage → docs → deep-audit → prove loop. It wraps dev-delivery's rules and
  never replaces them.
- `eternia-writing-plans` — the plan-document quality bar, when the
  deliverable is an implementation-ready plan rather than code.
- QA turns load `harness-qa-verdict` INSTEAD of the dev contract: evidence
  discipline and the narrowest proof command. QA judges work; it never
  patches code.


## Removed — unlearn these

These verbs, fields, and rules were removed on 2026-07-30. Do not reach for them, do not
expect their output shapes, and do not repeat them to an operator as if they were live:

- `hermes harness task show <id> --json`, `task list`, `task create --start-daemon`,
  `task history`, `task unblock/cancel/archive` — there are no goals or tasks.
- `hermes harness blueprint list/run --bind`, and the `.mission_plan` field on anything
  (with its `.stages`, `.edges`, `.agent_topology`) — there is no stage graph. The old
  default graph `neko_two_dev_default` = **Neko scope → Backend Dev → Launcher Dev**, and
  the rule that **QA is a node only if the selected blueprint binds it**, are both gone:
  no blueprint binds anyone, and QA is just another agent you can message.
- `run show` / `proof list` / `worker list` / `lane list` / `swarm status|enable`, `tick`,
  and `run-until-settled` — no runs, no proof gates, no worker sessions, no lanes, and no
  burn-in certification gate.
- The `mission_goal_create` tool and the `--allow-mission-goal` opt-in on `mission-chat
  message` — no chat turn can create a goal, because there are no goals.

`harness snapshot --json` is contract 54 and carries no goal, stage, run, proof, or
incident sections. If you are looking for one, it is gone, not missing.


## Persona chat continuity

**Message the on-level instance.** Persona instances and their chat roots use
one chat lane. Legacy lifecycle metadata does not create a separate routing
class and does not change whether an exact, owned chat root can receive a turn.

`PersonaInstance.default_chat_session_id` is the operator-chat pointer. Hermes
mints every new root; callers may use a local draft identity only while waiting
for the `open-chat --new-session` result.

The pointer can go stale: `mission-chat message` may reject a roster-listed
root with `unknown_chat_session` ("unknown explicit persona chat root"). Do not
keep retrying it — mint a fresh root with `open-chat --new-session
--idempotency-key <key>` and message that. The roster and chat roots hang off
the runtime ROOT, not the profile home: under the wrong store root,
`persona list` returns an empty roster and chat roots resolve nowhere, while
the wrong HOME gives you the right roster with the wrong profile answers
(admission, model, auth) — measured 2026-08-28, see the Non-negotiables above
and `references/operations.md`, "Roots".

Treat `session_id` in chat commands as the stable root. Native compression may
rotate `active_session_id`; it does not change the root selected by Mission
Control. Runtime-state projections are observer-qualified: only the owning
long-lived serve process may report `hot`, `busy`, `cold`, or `failed` from its
resident registry; external CLI snapshots report `unknown`.

If a turn returns `chat_turn_outcome_unknown`, do not retry it. Resolve the
exact `(root, client_message_id, turn_id)` tuple with `turn-resolve ...
--action abandon`, then send the text as a new turn with a fresh client
message ID.

`chat_turn_provider_refused` is the OPPOSITE fault and takes the opposite
action: the model provider authored a definite "this did not run" (a plan quota
wall, a rejected credential, a model the account cannot reach), so there is
nothing to resolve and `turn-resolve` will refuse it. The frame carries a typed
`provider_refusal: {status_code, reason, message, reset_at, resets_in_seconds,
provider, model}` — read `reason`, never the prose — and the journal settles at
`provider_refused`. Wait out the reset (or fix the credential) and send a NEW
client message id.


## Delegation — helpers without context bloat

*(Absorbed `harness-continuity` 2026-08-28; full recipe and the return-summary
flag set: `references/operations.md`, "Delegation".)*

- Message exactly ONE helper at a time — `agent_chat_send` from inside a turn,
  or `mission-chat message` against its chat root. A message is the whole
  handoff: narrow objective, explicit stop condition, the parent session id.
- **Never slurp.** Do not read or paste the helper's full transcript, raw
  logs, or hidden reasoning into the parent. Carry pointers: the parent gets
  one bounded summary plus artifact/proof refs, nothing more.
- The first-class return is `persona instance return-summary` (Operate table
  above): posts a redaction-safe bounded message into the parent session,
  records lineage via `returned_to`, emits `steer.returned`. The summary is
  hard-truncated and refs are capped — send pointers, not payload.
- Progress is what the helper says in chat plus the artifacts it names (the
  daemon/run-row `progress_peek` died 2026-07-30). Intervene only on a stall,
  an explicit block, or scope drift — by another message on the SAME chat
  root, so the helper keeps its context and prompt cache.
