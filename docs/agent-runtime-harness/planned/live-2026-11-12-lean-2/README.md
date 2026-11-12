# RT-LEAN-OPERATIVE-RULES — R4 clarify re-read after the token fix, 2026-11-12 (lane w1112b-ctt-hm2)

Owner 2026-11-12: "yes keep allowing it to use real turns" — "but account for it". Second real-model sitting, after
`RT-DISPATCH-DELIVERY-CLARIFY-TOKEN-MASKED` landed (`b636d3b44b`). The first sitting is `../live-2026-11-12-lean/README.md`.

## Setup

- Linux box, own Xvfb `:86`, QA copy of Eternia `d129f3e23e` through `launcher_qa` (`drive.dart`),
  `launch_or_attach {"profile": "stagec-smoke", "session": "hm2lean", "hermes_checkout": <this lane's hermes worktree at 4b25c65919>}`,
  NO `model_fixture`.
- A fresh lane namespace (`stagec-smoke-lane-c2568f2ec9`), seeded with `qa.runtime.workspace.seed` (Base, QA Agent A, QA Agent B).
  The serve ran with `HERMES_QA_PROVIDER_POOL=stagec-smoke` and no API key in its environment; every turn ran
  `gpt-6-luna` on `openai-codex` (the profile default) through the pool's account sign-in (plan limits).
- `agent_runtime.mission_chat.lean_operative_rules: true` in the namespace ROOT `config.yaml` before the launch that ran
  the sitting; `mission_chat_lean_operative_rules()` read `True` under the serve's environment. Removed afterwards.

## What was sent

ONE operator message to Base, the same words as the first sitting (QA Agent A's handle changed to this namespace's).
It does not mention `clarify_token`. Transcripts: [transcripts.txt](transcripts.txt).

## What the model did

1. Base dispatched QA Agent A (auto-detached to a background dispatch).
2. QA Agent A called `clarify` (Blue / Green). Ticket `clarify-b085548867a2`.
3. The delivery stored in Base's thread carries the token WHOLE: `clarify_token: clarify-b085548867a2` and
   `passing clarify_token=clarify-b085548867a2` (it was `clarif...7f38` in the first sitting).
4. Base answered with `agent_chat_send {"clarify_token": "clarify-b085548867a2", "message": "green", …}` — the token
   whole in the stored tool call too, no `session_id`.
5. The ticket settled `state: answered`, **`bound_via: clarify_token`**. The answer landed in QA Agent A's SAME thread
   (`…467666b1_305ab23ac321`), which answered "Green.", and Base told the operator what A asked and what it did.

## Verdict

- With `lean_operative_rules` on, one teammate clarify answer went back on its `clarify_token` — the R4 check holds.
  Nothing argues for moving the bullets into `harness-mission-lead`.
- Seen on the way (filed as a follow-up, already there before this fix): the console draws the delivery that carries
  the question as "Message hidden by redaction boundary." (`console_top.png`) — the history read's secret check hides
  any row with a `…_token: <value>` line, masked or not.

## Cost

One operator message. Agent turns: Base 3 (1 operator + 2 dispatch deliveries), QA Agent A 2 — 5 in all. API calls:
Base 5, QA Agent A 3 — 8 in all (`sessions.api_call_count`), every one `gpt-6-luna` through the pool's account sign-in.
No retries, no second operator message.
