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
