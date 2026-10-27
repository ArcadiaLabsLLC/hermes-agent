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

## Fixed decisions and existing owners

- User-facing surface: Agent Console; feature: Follow-up suggestions. Global
  Settings > Eternia Harness > Agent Console remains the sole switch location.
- `agent_runtime/console_suggestions/settings.py::SuggestionSettings` and its
  existing config transaction remain the settings authority. The existing
  `plugins.entries.eternia-harness.settings.console_suggestions_enabled` defaults
  false. Scope remains the selected serving Harness, not a cross-install sync or
  a per-persona setting. Disabled means no suggestion generation/history work.
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

## Runtime changes to plan

`RT-NEXT-PROMPT-GENERATION-PARITY`: extend the existing generation helper with a
final reminder grounded in the latest user's language, using bounded/redacted
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

Expand the existing `RT-NEXT-PROMPT-PROVIDER-EVAL` row, not a second evaluation
authority. Freeze a representative corpus and scoring rubric before paid runs:
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

Hard acceptance: off-state zero provider calls; no persona/config mutation;
override/reset retains host routing; no cross-subject publication; disable
invalidates queued/in-flight output; no draft auto-send. Fixtures prove these
contracts; quality and latency need live evidence. Suggested ship criteria are
zero observed fabricated user actions/approvals in the fixed corpus and no
regression in relevance/language scores or primary-turn latency against baseline;
zero observed events is not a guarantee of semantic truth. Publish all misses.

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
Runtime work is `RT-NEXT-PROMPT-GENERATION-PARITY` and the existing
`RT-NEXT-PROMPT-PROVIDER-EVAL` in the runtime queue. Both remain deferred.
