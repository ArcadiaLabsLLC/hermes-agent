# Agent Console follow-up suggestions: completion plan

Status: planned, implementation explicitly deferred by the owner on 2026-10-27.
This update authorizes documentation and queue work only. It does not authorize
code changes, live enablement, provider calls or qualification runs. A later
implementation go-ahead releases this hold; do not add a separate confirmation flow.

The original implementation remains built. See [chat canon](../05-chat-turn-lane.md)
and [qualification evidence](../../downstream/console-next-prompt-2026-10-26.md).
This plan owns runtime completion only. Launcher presentation is owned by
`EterniaLauncher/docs/mission_control/planned/CONSOLE_NEXT_PROMPT_COMPLETION_2026-10-27.md`.
The 2026-10-26 archived design remains historical; this is its unbuilt follow-up.

## Stock capability versus our adaptation — final audit

The pinned plugin already provides free-form generation, host auxiliary routing,
context/cooldown tuning, final-reply context selection, language reinforcement,
output cleanup, persistence, failure classification and stale-turn rejection.
These are not inventions of this integration. Our first adaptation simplified
the language reminder and cleaner; the generation row restores omitted useful
behavior while retaining deliberate code/bracket and short-language acceptance.

Required native adaptations bind those capabilities to Agent Console's durable
persona chat, existing RPC and draft owners. Bounded scheduling, durable attempt
receipts and disable epochs are additional implementation choices for concurrent
native chats, not proof that the stock plugin lacked all lifecycle protection.
The explicit false default, no guessed manual outcomes, visible-chat generation
and 24-hour expiry are deliberate product differences. Keep them documented as
differences, not as prerequisites for a useful suggestion feature or proof of
superiority. The Launcher plan owns its separate UI parity inventory.

This completion pass extracts reusable helper logic behind the Console adapter
and extends that single implementation. It does not rebuild the scheduler/store,
introduce another generator or restore the Desktop REST stack.
Earlier question-only and empty-draft-only proposals were revised during planning;
they are not a shipped restriction to remove. Temporary mutation-test changes
were restored to verify tests; they were not product rollbacks.

## Fixed decisions and existing owners

- User-facing surface: Agent Console; feature: Follow-up suggestions. Global
  Settings > Eternia Harness > Agent Console remains the sole switch location.
- `agent_runtime/console_suggestions/settings.py::SuggestionSettings` and its
  existing config transaction remain the settings authority. The existing
  `plugins.entries.eternia-harness.settings.console_suggestions_enabled` defaults
  false. Scope remains the selected serving Harness, not a cross-install sync or
  a per-persona setting. Initially disabled means no suggestion generation/history
  work. Disabling admits no new work and invalidates pending output; an already
  issued provider request can finish under the existing cancellation/timeout
  contract, and its result must not publish. Do not promise retroactive zero cost.
- `agent_runtime/console_suggestions/generation.py::generate_suggestion` retains the registered `console_next_prompt`
  task through the existing plugin LLM facade. Inherited routing, optional
  provider/model/base_url override and reset preserve host authentication,
  fallback, timeout and unrelated auxiliary options. No new provider client.
- `agent_runtime/persona_chat_history/suggestion_context.py::suggestion_context` remains the
  history reader. Keep the current 2-10 message setting (default 4, whole pairs)
  and cooldown (default 3 seconds). Use actual user text and final persona replies.
  Do not copy persona system prompts, load extra memories, change persona models,
  execute persona tools, alter cached conversation prefixes or create a transcript.
- Existing native identity, committed-turn, root lease, policy epoch, retention,
  bounded scheduler and visibility rules stay authoritative. No second lifecycle,
  retry loop, model router, settings store or permission policy.

### Auxiliary task compatibility and coexistence

Preserving the host router does not mean preserving the stock task key. Stock
uses `auxiliary.next_prompt`; the built Console integration uses
`auxiliary.console_next_prompt`. A custom override on the former is not
automatically inherited by the latter. Default/reset resolves the serving head's
host routing, not the active persona model and not the stock task's override.
Qualification must cover both keys present and conflicting, stock-only override,
Console override/reset, and unrelated timeout/fallback/auth fields unchanged.
An operator may deliberately select the same route through existing Console
settings/config, but there is no automatic migration, dual-read fallback or write
to the stock slot in this plan. Make the effective task/route explicit in evidence.

Do not install or enable the stock Desktop plugin as a dependency. If it is
already used for other surfaces, leave its configuration alone and verify that
one native Console turn is served by one suggestion producer; do not widen its
hook platform allowlist to run both producers over the same Console turn.
These checks belong to RT-NEXT-PROMPT-PROVIDER-EVAL, not a new routing authority.

## Shared capability and Console adapter — planned separation

`RT-NEXT-PROMPT-SEPARATION` precedes generation parity. The current implementation
is not yet consumer-neutral: generation combines reusable prompt/cleanup logic
with Console task registration, while `ConsoleSuggestions` authorizes Console
subjects and reads persona history. Constructor injection alone does not remove
those assumptions. Extract the existing capability; do not copy it into a second
implementation or turn the Console service into an all-chat authority.

| Responsibility | Planned home and dependency |
| --- | --- |
| Free-form prompt construction, language reminder, output cleanup/redaction, generation result shape | Proposed `agent_runtime/suggestions/`; lift existing logic from `agent_runtime/console_suggestions/generation.py::generate_suggestion` and `agent_runtime/suggestions/generation.py::clean_suggestion`. Consume bounded admitted messages and an explicitly supplied completion callable; return text/absence and actual provider/model/usage facts. No Console/persona identity, config lookup, transcript reader or RPC dependency. |
| Plugin registration and serving-head auxiliary connection | Existing `agent_runtime/console_suggestions/generation.py::register_suggestion_task` and the Console generation adapter bind the current plugin context and `console_next_prompt` task to the shared helper. The callback delegates to `ctx.llm.complete`; the shared helper does not select a model, construct a provider client or resolve credentials. |
| Console authorization, context selection and lifecycle | Existing `agent_runtime/console_suggestions/service.py::ConsoleSuggestions`, Console RPC and `agent_runtime/persona_chat_history/suggestion_context.py::suggestion_context` remain the adapter to existing owners. Validate exact subject, permissions and committed source before reading history or invoking generation; preserve invalidation and use-time checks. |
| Configuration, scheduling, receipts, retention and notifications | Existing Console settings/service/store/notification owners remain single instances. They coordinate this consumer; they are not a new cross-surface platform. Keep current storage and wire contracts. |

Dependency direction is Console adapter → shared suggestion helper → supplied
host completion operation. The shared helper must not import Console adapters,
persona history, operator authorization or settings. The adapter binds the exact
serving home across worker execution through the existing scope owner, preserving
persona isolation and auxiliary override/reset. It supplies only authorized recent
user/final-reply context; shared code cannot fetch additional history or act as a
persona. Keep redaction, no guessed manual outcomes and free-form output intact.

Use a small function/value contract for the one real consumer. Do not introduce
a generic conversation registry, adapter discovery framework, new service process,
second scheduler/store, transport, settings key or auxiliary task. Do not rename
`console_next_prompt`, the current SQLite file, RPC methods or preference keys as
a side effect of moving internal code. Remove relocated helper bodies and update
all imports/tests/attribution; no internal compatibility re-export or dual path.
Preserve behavior during extraction, then apply the existing parity row once in
the shared helper. Console-specific lifecycle policy stays in its adapter; a
speculative generalization of that lifecycle is outside this completion pass.
The extraction is complete with shared prompt/cleanup/result logic and one real
Console caller. It does not require moving scheduling, subscriptions or persistence
into a shared service merely to make their directory names generic. Keep the
completion callable narrow: it invokes the already-bound host LLM operation, with
no second dependency container or routing facade. Missing plugin context and
Console refusals stay adapter concerns; shared helpers must not import
`SuggestionRefused` from Console settings or invent a parallel error framework.
Preserve actual provider errors for the existing sanitized classifier. A shared
result is text-or-absence plus existing route/usage facts, not an intent taxonomy
or extra semantic filter on the plugin's contextual free-form suggestions.

The setting remains off by default under Global Settings > Eternia Harness >
Agent Console > Follow-up suggestions. Reusable code does not make that Console
setting apply to DMs. No DM endpoint, context reader, setting, history adapter,
membership policy, send integration or production registration is authorized.
A future DM consumer would keep messaging's own permissions/history/send owners
and supply its own authorized context and routing connection; no fake persona or
Console subject. Its enablement and provider policy remain future design work.

Boundary acceptance after implementation: exercise shared generation using
explicit messages/completion input without constructing a persona or Console
service; then exercise the real Console adapter to prove routing, authorization,
off-state zero history/model work, scope isolation and stale-result rejection.
Removing a Console consumer releases its existing observation/subscription;
ordinary persona chat and other still-bound consumers remain usable. Test the
last-consumer idle path separately from a disabled policy or unavailable plugin.
The false-default policy forbids generation and history reads, not the existing
lightweight settings observation needed to notice enablement. In-flight work
retains existing cancellation and stale-publication rules; no new unload protocol
or promise to cancel another window's work. Keep one producer and existing stored
receipts across the internal move. These checks join the existing qualification
rows, not a new DM test application or permanent benchmarking service.

## Runtime changes to plan

`RT-NEXT-PROMPT-GENERATION-PARITY`: after `RT-NEXT-PROMPT-SEPARATION`, extend
the extracted single shared generation helper with a final reminder grounded in
the latest user's language, using bounded/redacted
context already admitted by the existing reader. Conversation text remains data.
Preserve free-form requests, questions, conversational replies and statements
supported by user-provided facts. No question-only conversion, intent whitelist,
compulsory second model or guessed approvals/manual outcomes.

Improve the existing cleaner for known output labels, matched straight/curly
quotation wrappers and complete no-suggestion sentinels with punctuation. Do not
blindly copy upstream's broad prefix rejection or blanket bracket rejection:
`NULL handling`, code expressions, literal brackets and short Chinese/Japanese
replies remain valid. A sentinel must be the whole normalized response. Preserve
the existing 160-code-point ceiling, redaction and first-message output contract.
Avoid stripping meaningful Markdown/code characters from actual user text.

Tests must distinguish harmless formatting from substantive text: English and
Spanish labels, curly quotes, sentinel punctuation, useful short multilingual
replies, code/brackets, latest-user language differing from the topic, and unknown
manual outcomes. Prompt assertions alone cannot prove language quality or honesty;
pair boundary tests with the real-provider evaluation below.

## Existing API connections (reuse; no new RPC required)

| Owner / entry point | Consumer and contract |
| --- | --- |
| `agent_runtime/serve_rpc/console_suggestions.py` | Existing authenticated settings get/set/subscribe/unsubscribe and conversation read/subscribe/unsubscribe/dismiss dispatch |
| `runtime.console_suggestions.settings.*` | Harness global controls; partial revision-checked writes, inherited route/override/reset and epoch invalidation |
| `runtime.operator.conversation.suggestions.*` | Exact install/account/workspace/persona/instance/root subject; conditional use-time read and entry dismissal |
| `agent_runtime/console_suggestions/service.py::suggestion_failure_reason` | Existing sanitized auth/rate_limit/timeout/provider/storage reasons; Launcher renders them, never exception text or credentials |
| `agent_runtime/console_suggestions/notifications.py` | Existing revisioned changed notifications and subscription ownership; no polling lane |
| `agent_runtime/console_suggestions/generation.py::generate_suggestion` | Actual provider/model/usage result for qualification; provider cost may be unavailable and must be labeled unknown |

## Qualification after implementation authorization

After separation and generation parity, expand the existing
`RT-NEXT-PROMPT-PROVIDER-EVAL` row, not a second evaluation authority. Include
the shared-helper/Console-adapter boundary acceptance above. Freeze a representative
corpus and scoring rubric before paid runs:
multilingual and mixed-language conversations, code, completed tasks, grounded
statements, pending structured controls, unknown manual outcomes and older intent.
Compare landed baseline versus proposed refinement on the same corpus, route and
context size; use several samples and report sample counts and limitations.

Record relevance, language consistency, fabricated-action/approval rate, false
rejection rate, unchanged acceptance/edit burden where human observation exists,
and actual route, tokens, available cost, error rate and p50/p95 completion-to-ready
latency. Do not substitute a model judge's score for measured human acceptance.
Pair with `MC-NEXT-PROMPT-QUALIFY` for Developer/bundled and local/remote native
acceptance and idle-box cold/warm/immediate-next-send timing. Record environment,
paired revisions, sample count and pass/fail criteria before measurement; no
unmeasured claim of superiority to Codex or Claude.

Hard acceptance: initially off means zero provider calls; disable means no new
calls and no stale publication (already-issued calls may finish); no persona
mutation or config writes except the explicitly requested suggestion settings;
override/reset retains host routing; no cross-subject publication; disable
invalidates queued/in-flight output; no draft auto-send. Fixtures prove these
contracts; quality and latency need live evidence. Suggested ship criteria are
zero observed fabricated user actions/approvals in the fixed corpus and no
regression in relevance/language scores or primary-turn latency against baseline;
zero observed events is not a guarantee of semantic truth. Publish all misses.
Use a finite evaluation corpus and existing test/evidence mechanisms, not a new
benchmark service, permanent acceptance tracker or general telemetry pipeline.
Reuse baseline receipts for unchanged contracts; rerun affected behavior and
native acceptance, not every historical test because documentation changed.

## Deliberately outside this completion pass

Keep the recent-context window until evaluation demonstrates missing earlier
intent; any expansion must use the existing history owner. Automatic ignored-
suggestion backoff is postponed pending acceptance/cost evidence; no silent
suppression or tracking service. Explicit Copy is optional and excluded from the
selected scope. Retain the existing visible-chat generation and 24-hour retention.

## Provenance and queue ownership

Audited next-prompt 0.3.1 at `c200200d6678dc6b093bab03c2e00a4f5a5043ed`;
retain existing MIT attribution for adapted helpers. Upstream prompt/cleanup:
[pinned source](https://github.com/soymarketing/hermes-plugin-next-prompt/blob/c200200d6678dc6b093bab03c2e00a4f5a5043ed/__init__.py).
Product comparisons are UX references, not implementation authority or evidence
of parity: [Codex](https://learn.chatgpt.com/docs/features/composer-predictions),
[Claude Code](https://code.claude.com/docs/en/interactive-mode#prompt-suggestions).
Runtime work is `RT-NEXT-PROMPT-SEPARATION`, `RT-NEXT-PROMPT-GENERATION-PARITY`
and the existing `RT-NEXT-PROMPT-PROVIDER-EVAL` in the runtime queue. All remain deferred.
