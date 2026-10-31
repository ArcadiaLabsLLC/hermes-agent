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

## Chat lifetime and activity correction

Message binding schedules when a skill is introduced; it does not expire its
instructions after that turn. Upstream's preload text explicitly activates
guidance for the session. No lifetime or skill configuration is changed here.

The existing `skill_load_history` reader now includes native user-row preload
snapshots as well as successful `skill_view` results. It strips the runtime HUD
with the canonical envelope codec; unchanged stubs and prose mentions add no
loads. `runtime.operator.conversation.skills` history adds
`preloadHistoryIncluded: true`, so clients can refuse an incomplete older
reader rather than claiming no composer skills are active. Existing lineage,
profile and account checks still own the read. No client or runtime skill store
is added. History is evidence of loaded guidance, never proof of model use.

The composer distinguishes pending additions from native loaded/required
skills. Loaded skills cannot be removed by deleting a draft chip; a new chat
starts with its own native context.

Correction verification: 18 activity/native inspection/child-address cases pass;
the duplicate-helper and routing censuses pass (14 cases). Disabling user-row
preload extraction killed both the activity and real native-session inspection
regressions (2 failed). Restoring it passes. A child-reader fixture now carries
the native catalogue's required `name` field. Changed-file Ruff and pre-push
checks pass; no turn builder, loader, queue or configuration writer changed.

The full-tree `scripts/check` Ruff lane also reports pre-existing findings in
untouched files (including `agent_runtime/chat_head_migration.py` and
`agent_runtime/correlation_acceptance.py`). This change does not repair those
unrelated files. Other full-check lanes passed after the normalizer's added
validation was extracted into its own bounded helper.
