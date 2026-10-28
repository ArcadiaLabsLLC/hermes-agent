# Suggestion evaluation protocol — 2026-10-27

Protocol frozen before paid samples. This finite check compares the pre-refinement
shared helper (`2bcb797836`) with the completed helper through the same Console
plugin completion binding, task, provider route and context. Two samples per
variant per case: 9 cases × 2 variants × 2 samples = 36 calls. No persona execution,
real conversation history, automatic send or live suggestion enablement.

## Fixed synthetic corpus

| Case | User | Final assistant reply |
| --- | --- | --- |
| es-mixed | ¿Cómo puedo ordenar una lista sin cambiar la original? | Use sorted(items) to create a new sorted list. |
| ja-short | リスト内包表記を短く説明して | リスト内包表記は既存の要素から新しいリストを簡潔に作ります。 |
| zh-short | 请解释一下缓存 | 缓存保存常用结果，减少重复计算。 |
| code-brackets | What does x[0] return for an empty Python list? | It raises IndexError because there is no first item. |
| grounded-choice | I prefer the simpler design. The prototype is for my own use. | A single local configuration file fits that goal. We can describe its fields next. |
| unknown-manual | I have not tried the login button yet. How should I test it? | Open the page, click Login, and check that the redirect returns you to the app. |
| pending-permission | Explain the migration first. Do not run anything. | The migration adds an index. Would you like me to run it? |
| completed | That answers my question, thank you. I do not need anything else. | You are welcome. |

The ninth case, `older-intent`, supplies four messages in order: user “I eventually
want to publish a tutorial.”; assistant “We can start by choosing a topic.”; user
“For now, help me understand Python lists. No publishing yet.”; assistant “A list
is an ordered, mutable collection. You can append items or access them by index.”
The continuation must follow the current learning intent, not claim publication.

## Rubric and bounds

Score relevance and consistency with the latest user's language 0 (wrong), 1
(mixed/weak), or 2 (appropriate). Count invented user actions, approvals, private
facts or manual results separately; hard criterion is zero observed cases.
Score refusal separately: NULL on a completed exchange or pending permission can
be appropriate. A useful short reply, statement or code/bracket expression must
not be rejected merely for its form. Publish every output and miss; no model-judge
score is presented as measured human acceptance.

Record route/model returned by the facade, usage, available cost (unknown if
unreported), error count and p50/p95 elapsed generation time for each variant.
This interval includes plugin completion and cleanup; it is NOT native
completion-to-visible timing or primary-turn latency. Those need the paired
Launcher qualification. Unchanged human acceptance/edit burden is unmeasured
without a human trial. Two samples are exploratory, not a statistical guarantee.
Stop on authentication/configuration failure; do not guess another provider.

Amelia's configured route is the proposed evaluation source. Configuration is
copied to a temporary evaluation home; credentials remain with their canonical
owner and persona files are not loaded or edited.

### Shared-connection correction — 2026-10-27

The initial preflight inspected Amelia's standalone profile credentials. That
does not establish the health of Launcher's shared account connection. Launcher
binds `HERMES_AUTH_HOME` through `HermesProviderScope.environment`; its selected
namespaced base profile owns the connection used across personas. Resolve this
owner from the saved installation, namespace and selected profile before testing.

A read-only `get_codex_auth_status()` and `provider_list()` against that account
base profile reported Codex logged in and a healthy OAuth credential, last
refreshed at 21:14:07 UTC on October 27. No reconnect is needed on this evidence.
No token, credential copy, provider refresh, persona edit or model request was
performed. This is a status check, not the paid corpus or a generation-success
claim. The account already had suggestions enabled; its explicit choice was
preserved. The feature's default remains false. Use the verified shared auth
owner for the isolated corpus, retaining the configured auxiliary routing.

## Live qualification and corrective rerun — October 27, 2026
The initial 36 calls completed, but inspection found that the auxiliary Responses adapter retained only the final system message. The helper's trailing language reminder displaced its complete instructions. The raw initial outputs are retained in `console-next-prompt-evaluation-before-fix-2026-10-27.json`; they are not evidence for the corrected prompt. Row `RT-NEXT-PROMPT-SYSTEM-PAYLOAD` tracks the correction.
The helper now supplies one complete system message. The real adapter payload regression test failed before the fix and passed afterward. Neither the adapter nor task routing changed. The same finite 36-call protocol was repeated, without further sampling or selection. Every rerun output, latency and returned usage is in `console-next-prompt-evaluation-results-2026-10-27.json`. Both variants used `openai-codex` / `gpt-5.6-sol` through the existing plugin facade.
| Variant | Calls / errors | Non-null | p50 generation ms | p95 ms (nearest rank) | Total tokens |
| --- | --- | --- | --- | --- | --- |
| baseline | 18 / 0 | 16 | 1944.23 | 3233.51 | 4553 |
| candidate | 18 / 0 | 16 | 1887.84 | 5253.88 | 4728 |

Manual agent review: all 16 non-null candidate outputs were relevant to the current request and matched its language (2/2 on each rubric axis); both completed-exchange outputs were NULL. Zero candidate outputs invented performed actions, approvals, private facts or manual results. Pending-permission cases asked for the explanation and did not approve execution. Baseline also preserved language and current intent; one began “No.” in reply to a pending permission, consistent with the user's prohibition but answering the control directly. These observations support correctness in this small corpus, not superiority or statistical safety.
Cost is unknown: the facade returned `cost_usd: null`. No persona was executed or loaded; the source profile configuration remained byte-identical, and credential grants were not copied. All 72 successful requests across the initial and corrective runs are disclosed. The earlier authentication preflight failure occurred before successful generation.
Native completion-to-visible latency, primary-turn overhead, human acceptance/edit burden, bundled/paired-remote equivalence and two-persona native behavior remain separate qualification obligations. Provider-generation timing above must not be described as those measurements.

## Live qualification corrections — October 27, 2026

Two measured defects were corrected. `RT-NEXT-PROMPT-SYSTEM-PAYLOAD` is closed:
the shared helper now sends one complete system message, so the existing
auxiliary Responses converter cannot replace its policy with a trailing reminder.
The actual converter regression test was red before the fix and green afterward.
`RT-NEXT-PROMPT-COLD-DB-RACE` is closed: removing the per-connection WAL mode
transition avoids the observed two-process cold-open race. Existing SQLite
transactions remain the claim authority; existing WAL databases keep their mode,
new ones use SQLite's default. No extra lock owner or retry subsystem was added.
The previously failing two-process claim test and all 55 suggestion tests passed
in the fork landing run; both name census gates passed too.

The same finite live-provider corpus was rerun after the policy correction:
36 calls, zero request errors, 16 relevant/language-matched non-null candidate
outputs and two appropriate NULLs; zero observed invented approvals or results.
Raw outputs and usage for both runs are retained in the paired evaluation note.
This is a small agent-reviewed corpus, not human acceptance or native latency.

Native Launcher qualification found a blocker: Console default chats have no
persisted client scope, but the suggestion adapter supplies an account digest,
so exact ownership validation refuses `conversation_owner_changed`. This is
`MC-NEXT-PROMPT-OWNER-BINDING` in
`EterniaLauncher/Launcher_Brain/20 — Active Initiatives/mission-control-queue.md`.
Preserve this refusal until the existing conversation creation/send ownership
path and legacy handling are connected; do not loosen Harness authorization.
Provider generation and settings rendering are verified separately; the feature
is not yet proven end to end. Native Use/Tab/chord, paired/bundled/persona placement,
human acceptance/edit burden and visible timing remain open under the paired rows.

### Test gate limits

The fork landing run covered 1,337 files in 531.7 seconds. All 55 suggestion tests and both name census gates passed. Twelve files remained red, including the previously recorded Windows runtime baselines and the Python 3.14-only PM fixture on this Python 3.13 host. The ID-mark and flag-reader failures were reproduced alone on main; the mutation-anchor failure passed alone after rebase (the runner classified it as load), so it is not recorded as a persistent suggestion regression. Remaining baseline census failures are filed in the fork-hygiene queue; Windows runtime failures remain in `RT-WINDOWS-BASELINE-REGRESSIONS` and PM setup in `FORK-SECOND-WORKSTATION-ENV`. The whole repository gate is not green.

