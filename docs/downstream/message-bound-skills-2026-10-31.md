# Message-bound skill selection — 2026-10-31

The approved Eternia composer picker needs skill selection bound to a particular
message, including queued follow-ups and retries. The legacy session-level
next-turn queue cannot provide that identity.

`runtime.chat.message` now advertises `skills`, a list of skill names.
The existing normalizer lowers it to repeatable `mission-chat message --skill`
arguments. The existing turn-context builder combines those message-local names
with required preloads and the legacy queue using the existing resolver,
compatibility policy and skill loader. It validates selected skills before
consuming any legacy queue. The message's existing idempotency/journal path owns
replay; selection adds no queue, assignment, permission or global skill store.

Native skill inspection reports `requiredEveryTurn` from the existing
`required_preload_skill_ids` policy, so the picker does not infer load policy.

Validation: 110 tests across six files passed (message selection,
turn context, RPC params, RPC turn handling, serve routing, native inspection).
Dropping the builder's `requested_skills` argument killed two new regressions:
the first message lost `picked-a`, and invalid selection stopped refusing before
legacy-queue consumption (2 failed, 4 passed). Mutation reverted; tests green.
The changed-file Ruff check and code-health ratchet passed.

The full-tree `scripts/check` Ruff lane also reports pre-existing findings in
untouched files (including `agent_runtime/chat_head_migration.py` and
`agent_runtime/correlation_acceptance.py`). This change does not repair those
unrelated files. Other full-check lanes passed after the normalizer's added
validation was extracted into its own bounded helper.
