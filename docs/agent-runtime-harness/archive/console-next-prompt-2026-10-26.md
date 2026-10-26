> Historical design and audit, archived after the owner authorized implementation on 2026-10-26.
> Runtime/UI facts now live in chat/transport/lifecycle canon; qualification notes distinguish tested behavior from remaining live evidence.
> The original deferral language below is historical, not a current implementation hold.

# Agent Console follow-up suggestions: audit and implementation plan

Status: **PLANNED — not implemented or authorized to execute.** Date: 2026-10-26.
Owner request: reuse next-prompt where appropriate, off by default in Harness global
settings, no invented confirmations, preserve the persona system, identify options
and API connections, and queue the work in its owning repositories.

This is the canonical cross-repository design. The Launcher implementation map is
`EterniaLauncher/docs/mission_control/archive/CONSOLE_NEXT_PROMPT_2026-10-26.md`.
Work/status belongs only in the two domain queues. The retained hold row
`RT-NEXT-PROMPT-DECISIONS` defers implementation; this document is not permission to
install a plugin, enable generation, change live configuration, or start a lane.

## 1. Audit basis and conclusion

Source audit baselines: Hermes `24bef38e9b`, Launcher `18cec6ea3f`. The external
source is next-prompt 0.3.1 at `c200200d6678dc6b093bab03c2e00a4f5a5043ed`, exactly
the revision in `plugin-catalog/next-prompt.yaml`. Audited source, documentation,
interfaces and test locations; did not install or execute the plugin, spend model
calls, benchmark a provider, or claim live integration proof. Revalidate symbols
when implementing because other work is advancing both repositories.

**Conclusion:** reuse the plugin's small Python generation/context-processing ideas
and suitable tests with attribution; build a first-class fork-owned service and
native Launcher presentation. It is not a drop-in install and does not require
Hermes Desktop, its web server, React, or a second agent execution engine.

External source anchors (all pinned, rather than moving main):

- [Generation and hooks](https://github.com/soymarketing/hermes-plugin-next-prompt/blob/c200200d6678dc6b093bab03c2e00a4f5a5043ed/__init__.py): `_get_settings`, `_build_context`, `_prompt_messages`, `_clean`, `_generate_suggestion`, `_on_post_llm_call`, `register`.
- [Manifest](https://github.com/soymarketing/hermes-plugin-next-prompt/blob/c200200d6678dc6b093bab03c2e00a4f5a5043ed/plugin.yaml): Python `enabled` default is true.
- [Desktop](https://github.com/soymarketing/hermes-plugin-next-prompt/blob/c200200d6678dc6b093bab03c2e00a4f5a5043ed/desktop/plugin.js): `defaultEnabled: false`, `composer.underside`, `host.composer.insertText`, REST polling.
- [Persistence](https://github.com/soymarketing/hermes-plugin-next-prompt/blob/c200200d6678dc6b093bab03c2e00a4f5a5043ed/store.py): call-time profile path, SQLite WAL, one row/session, 200 rows, seven-day suggestion TTL.
- [REST](https://github.com/soymarketing/hermes-plugin-next-prompt/blob/c200200d6678dc6b093bab03c2e00a4f5a5043ed/dashboard/plugin_api.py): GET suggestion and POST dismiss keyed by session.
- [Tests](https://github.com/soymarketing/hermes-plugin-next-prompt/tree/c200200d6678dc6b093bab03c2e00a4f5a5043ed/tests): Python backend and mocked JS SDK tests; useful starting coverage, not evidence for Launcher integration.
- [License](https://github.com/soymarketing/hermes-plugin-next-prompt/blob/c200200d6678dc6b093bab03c2e00a4f5a5043ed/LICENSE): MIT notice accompanies any copied/adapted source and distributions.

### 1.1 Findings and disposition

| Finding | Evidence | Required disposition / row |
|---|---|---|
| Desktop off does not establish generation off | Manifest and `_get_settings` default true; JS defaults false | One runtime-owned false default and effective gate; `RT-NEXT-PROMPT-CONTRACT` |
| Settings API mismatch in the pinned versions | Plugin reads `_ctx.settings`; `hermes_cli/plugins.py::PluginContext` exposes `get_config`/`set_config`, with no `settings` property found | Do not reuse this reader: its exception fallback selects true. Use the harness setting authority; `RT-NEXT-PROMPT-CONTRACT` |
| Operator lane is excluded | `_UI_PLATFORMS` admits empty/desktop/tui; `agent_runtime/persona_runtime.py::PERSONA_CHAT_SCRATCH_SOURCE` is `tool` | Use a verified operator-root completion, not a widened platform allowlist; `RT-NEXT-PROMPT-LIFECYCLE` |
| Native session id is not always the durable operator root | `agent_runtime/persona_runtime.py::GPTPersonaRuntime.mission_chat_reply`, `agent_runtime/persona_chat_actor_prewarm.py`, `agent_runtime/persona_chat_identity.py` | Root/turn/revision identity from existing owners; never key by display name or scratch id; `RT-NEXT-PROMPT-LIFECYCLE` |
| Raw hook history is a poor Console context boundary | Plugin uses hook `conversation_history`; Console composes operator envelopes and native compression lineage | Extract actual user text and final persona replies through existing curation, with bounded reads; `RT-NEXT-PROMPT-CONTEXT` |
| Output instructions invent human outcomes | `_SYSTEM_PROMPT` asks to confirm a requested check and guess its result | Replace that policy and its confirming examples/tests; `RT-NEXT-PROMPT-CONTEXT` |
| Hook timing precedes durable Console settlement | `agent/turn_finalizer.py::_apply_output_hooks` versus `hermes_cli/harness_parts/persona/chat_turn_commit/settle.py::_SettlePhases._project` | Generate only from persisted terminal projection; enqueue after root lease release; `RT-NEXT-PROMPT-LIFECYCLE` |
| One daemon thread per eligible turn is not a scale policy | Plugin `_spawn`, process-local `_turn_seq` and `_last_suggestion_time` | Bounded owner, durable deduplication/revision fence, no per-chat thread; `RT-NEXT-PROMPT-LIFECYCLE` |
| A disable can race an in-flight result | `_generate_suggestion` checks turn sequence, not a live enabled epoch before publishing | Disable/re-enable epochs invalidate queued, running and cached old results; `RT-NEXT-PROMPT-LIFECYCLE` |
| Plugin REST and React do not match Launcher | `dashboard/plugin_api.py`, `desktop/plugin.js` | Existing authenticated RPC/notifications plus Dart ports; `RT-NEXT-PROMPT-RPC`, `MC-NEXT-PROMPT-CLIENT` |
| Simple session-only caching is insufficient across runtime/account/root changes | Existing `exact_operator_target`, `existing_chat_session`, Launcher `HermesConversationRuntime` | Scope every operation and subscription; conditional dismissal by suggestion id; `RT-NEXT-PROMPT-RPC` |
| Global settings cannot accidentally mean the active persona's profile | `agent_runtime/harness_settings.py::harness_setting` reads the currently scoped config | Explicit serving head-home authority, independent of persona execution scopes; `RT-NEXT-PROMPT-CONTRACT` |

These are integration findings, not claims that the uninstalled plugin currently
breaks Launcher. No general plugin framework or persona refactor is needed.

### 1.2 Final parity and gap audit — 2026-10-26

Rechecked Hermes `70fc450e13`, Launcher `180f2a40b1` and the pinned upstream
sources above. The following corrections are **plan changes only**, with work
assigned to existing rows; none is implemented or live-qualified here.

| Finding | Evidence and disposition | Owning rows |
|---|---|---|
| F1: context was frozen at four messages and cooldown disappeared | Upstream manifest exposes a 2–10 message window and cooldown, defaults 4/3 seconds. Preserve optional tuning, bounded reads and per-root coalescing; no mandatory setup | `RT-NEXT-PROMPT-CONTRACT`, `RT-NEXT-PROMPT-CONTEXT`, `RT-NEXT-PROMPT-LIFECYCLE`, `MC-NEXT-PROMPT-SETTINGS` |
| F2: empty-draft-only use and permanent focus prohibition narrow the feature | Upstream `useSuggestion` inserts a block into the focused composer; Launcher `ConversationDraftReceiver` already appends without replacement. Allow explicit additive insertion into a nonempty draft; only automatic focus changes are prohibited | `MC-NEXT-PROMPT-COMPOSER` |
| F3: keyboard/action parity was underspecified | Upstream registers a use shortcut and use/dismiss palette actions. Provide focused native actions plus a collision-checked shortcut; do not claim Launcher already has the plugin's global palette/keybind registry | `MC-NEXT-PROMPT-COMPOSER`, `MC-NEXT-PROMPT-QUALIFY` |
| F4: a new 15-second deadline conflicts with inherited routing | Upstream sends no explicit timeout; host task defaults are 60 seconds and provider progress/retry semantics differ. Preserve the configured host timeout/progress policy and bound actual outstanding calls, not just UI waits | `RT-NEXT-PROMPT-CONTRACT`, `RT-NEXT-PROMPT-LIFECYCLE` |
| F5: copying `_clean` can suppress valid text | Broad brackets, a `NULL` prefix and minimum character count can discard code references or short non-Latin replies. Adapt cleanup, recognize exact no-suggestion sentinels and test valid short/code-bearing text. The 160-character maximum is upstream parity, not an added restriction | `RT-NEXT-PROMPT-CONTEXT` |
| F6: cold serve, execution scope and atomic config publication need proof | `PluginContext` registration alone does not prove an enabled cold serve owns `ctx.llm`; auxiliary runtime-main ContextVars can outrank config. Bind service-owned runtime/auth scope, serialize the complete settings transaction, and fence restart/external edits | `RT-NEXT-PROMPT-CONTRACT`, `RT-NEXT-PROMPT-LIFECYCLE` |
| F7: cache loss and permanent deduplication were conflated | A missing payload can mean expired/evicted/dismissed, not a turn never attempted. Bound catch-up by source age, retain content-free terminal receipts, and prevent repeated calls on reconnect/typing | `RT-NEXT-PROMPT-LIFECYCLE` |
| F8: failure dismissal and partial settings updates lacked wire semantics | Upstream failure notes are dismissible. Use one entry-id contract for suggestion/failure entries; field-scoped writes let disable succeed independently of an unavailable model picker; API-off state must refuse chat subscriptions server-side | `RT-NEXT-PROMPT-RPC`, `MC-NEXT-PROMPT-CLIENT`, `MC-NEXT-PROMPT-SETTINGS` |

Intentional differences retained: false-default runtime gate, visible-Console
generation with latest-turn catch-up, 24-hour derived content retention,
authenticated native transport, and no fabricated manual outcomes or approval
bypass. No clipboard fallback is needed with a mounted native composer: a failed
insertion preserves the entry for retry. Persona prompts, skills, memory, model
choices and chat ownership remain untouched. These integration boundaries do not
turn free-form suggestions into a fixed intent menu. Global keybinding-editor or
global command-palette construction is not a prerequisite for this feature.

## 2. Decisions, alternatives, and fixed requirements

### 2.1 Fixed by the owner

- Suggestions are **off by default** in global Settings > Eternia Harness; no silent opt-in
  on upgrade, edition switch, install repair, profile creation or reconnect.
- No invented confirmations, outcomes, approvals, facts known only to the user,
  or claims that the user performed a step. A draft is not evidence or consent.
- Preserve persona identity, soul/system guidance, model cascade, profile binding,
  skills, tool permissions, memory opt-ins, chat ownership and history.
- Planning and queue changes only in this task. No implementation starts yet.
- Preserve next-prompt's contextual **free-form next-message suggestions**. Use
  existing auxiliary-model routing by default; a task-specific model override is
  optional, not a setup prerequisite. These revised choices were selected by the
  owner on 2026-10-26 and supersede the original constrained-renderer/model gate.

No new confirmation dialog is required to enable/disable the setting, dismiss a
suggestion or insert a draft. The user's direct action is sufficient. Existing
chat approvals retain their current authority; the planning-only boundary here
does not introduce a product approval flow.

### 2.2 Options and revised design baseline

The owner's 2026-10-26 follow-up adopts the revised recommendations for the plan,
while explicitly withholding implementation. Preserve option IDs: D2 and D3 now
select B; D1 and D4-D7 retain A. Alternatives remain documented for comparison,
not as unanswered approvals or additional product settings.

| ID | Options and tradeoff | Recommendation |
|---|---|---|
| D1 reuse | A: adapt minimal Python helpers/test cases into a fork-owned subsystem, pin attribution; B: maintain a separate adapted next-prompt plugin and require its install/version; C: write generation from scratch | **A**: one bundled lifecycle and no optional Desktop dependency. B preserves more upstream packaging but adds discovery, upgrades and two configuration owners. C loses useful source/test reuse. |
| D2 wording | A: constrain generation to reference/question intents and trusted templates; B: retain contextual free-form next-message text, with anti-fabrication instructions, output checks and evaluation | **B, selected**: preserves the plugin's core experience, including useful conversational replies. A restricts expressiveness and is not the v1 baseline. Prompting and screening reduce fabricated human claims but cannot guarantee their absence; no template whitelist or compulsory second-model call. |
| D3 model | A: require a separately selected auxiliary provider/model before generation; B: use existing host auxiliary routing, with an optional task-specific override | **B, selected**: works with an already configured Harness and avoids mandatory setup. Preserve host routing/auth/fallback policy and report the effective route/usage; never copy or mutate persona model settings. No override does not mean `model_unconfigured`. |
| D4 global scope | A: all eligible Console chats on the selected runtime/account namespace, no per-persona switch; B: synchronize the preference across installations | **A**: matches a concrete runtime settings target; cross-machine synchronization is additional product work. The selected install is displayed beside the control. |
| D5 when to generate | A: only while an authorized visible Console subscribes, including one catch-up for its latest settled turn; B: every eligible Console turn even with no UI attached | **A**: same global opt-in, fewer invisible calls and bounded idle cost. B helps background-chat return latency but incurs ongoing usage. |
| D6 delivery | A: RPC subscribe/read/dismiss plus revisioned notifications and reconnect hydration; B: post-turn bounded polling | **A**: follows the existing PUSH/CALL ruling. No dashboard server or polling every hidden chat. B is a fallback only if an explicitly supported transport cannot push, not a parallel default. |
| D7 retention | A: derived local cache, expires after 24 hours or any identity/revision/policy invalidation; B: upstream's seven-day persistence | **A**: avoid keeping obsolete human-reply guesses across a week of work. Expiry does not trigger regeneration for the same source; bounded content-free attempt receipts prevent repeated spend. |

`RT-NEXT-PROMPT-DECISIONS` now records the selected baseline and the owner's
explicit implementation deferral. It does not ask for the same choices again.
Only a later implementation request releases that hold; no work starts from this
documentation update. A later design change must update the plan and owning rows.

## 3. Persona-preserving architecture

Proposed flow (all new suggestion-specific components below are UNBUILT):

```text
Existing Console turn -> native commit -> persisted projected journal state
  -> post-root-lease, nonblocking suggestion admission (if enabled + visible)
  -> exact root/instance/account check -> bounded curated context
  -> existing auxiliary route -> free-form completion (no tools, no persona execution)
  -> output cleanup/redaction + source/state checks -> fenced cache publish
  -> existing authenticated RPC notification -> scoped Dart port -> suggestion pill
  -> explicit user click -> existing draft owner -> ordinary user Send later
```

### 3.1 Identity and authority

Use one immutable suggestion subject: runtime install identity + account/client
scope + workspace + persona id + instance id + durable root chat id. Resolve the
persona profile server-side from the existing binding; never accept a filesystem
home or profile override from the client. The settings scope is the serving
head/runtime namespace, not this persona profile. Cache physical location stays
inside that namespace; profile identity remains part of provenance/freshness.

Record source turn id, native lineage revision/tip, persona/instance identity
revision, policy epoch, effective routing revision and generation-policy version. The
native tip may change on compression; the root does not. Re-read authoritative
revisions before publication and consumption. Branch, rollback, redo, new chat,
profile change, deletion/retirement and account/runtime switch invalidate an old
result; another window cannot dismiss a newer result with an old click.

Reuse `agent_runtime/operator_conversation.py::exact_operator_target` and
`agent_runtime/operator_session_inspection.py::operator_session_read` / `inspection_identity`.
These already join exact install/workspace/persona/instance to an existing chat
and its owner. `agent_runtime/persona_chat_history/messages.py::existing_chat_session` opens a
read-only, owner-checked SessionDB; it must not mint, select, resume or rebind a
chat just to produce a suggestion. Unknown/legacy owner cases follow the existing
owner authority, with no suggestion-specific bypass.

### 3.2 What cannot change

No suggestion output enters persona context, SessionDB messages, memory, skills,
toolsets, system prompts, soul overlays, task queues or approvals. No suggestion
job creates a persona, actor, worker conversation or agent turn. It does not add
identity fields to `PERSONA_IDENTITY_FIELDS` / `INSTANCE_IDENTITY_FIELDS`, reset
resident actors, change prompt-cache prefixes, consume a permission grant, or
advance the current-chat pointer. Merely displaying, dismissing or inserting a
draft does not write chat history. Sending remains the existing user-send path.

Once the user actually sends that editable draft, it is ordinary user text and
follows existing history/memory policy. The non-mutation rule above concerns
generation, display and insertion; it does not intercept a later user-authored turn.

The predictor sees which assistant replies belong to the selected persona, but
does not load the persona's private system/soul files or memory. Persona behavior
is already expressed in the visible exchange. This preserves each persona's
execution while making a suggestion for the human, not speaking as that persona.

Non-goals: independent Intelligence conversations, Discussions, delegated workers,
Work/cron, agent relays, messaging-platform turns, Desktop/TUI, and general
autocomplete. They require their own admission review; `platform=tool` alone is
not an admission fact. A Console root shared with messaging/relay traffic needs
origin evidence from its actual turn, not just a root that once had a subscriber.

## 4. Global settings and model connection

### 4.1 Proposed settings contract

Use `plugins.entries.eternia-harness.settings.console_suggestions_enabled`,
declared as bool/default false in `plugins/eternia-harness/plugin.yaml`. It is
read/written through `agent_runtime/harness_settings.py` under the **explicit
serving head-home scope** from `agent_runtime/profile_home.py::get_hermes_head_home`. The current
`harness_setting` helper alone is not a global-scope guarantee. An absent, unreadable
or invalid value cannot enable generation; expose the latter as a settings error.

Capture that authority at serve startup; require
`agent_runtime/profile_home.py::hermes_head_home_is_authoritative` where a persona
scope could be active. The resolver's ambient-home fallback is not a safe global
target. Settings never follow a per-instance chat-head migration. Preserve
`save_plugin_setting` managed-install/administrator-managed-key refusals; expose
`writable: false` with a typed reason rather than bypass those controls. Bundled
edition and administrator-managed configuration are distinct cases to qualify.

One authoritative writer serializes compare-and-set updates. Proposed response:
`contract`, `install_id`, `scope` (runtime namespace), `enabled`,
`settings_revision`, `policy_epoch`, `writable`, `model_status`, `routing_mode`
(`inherited` or `override`), and safe resolved provider/model labels when known.
The enable key is the configuration truth; epoch/revision
are derived execution metadata, not a second enabled preference. Reads require
no model call, plugin install, provider login or actor startup.

Publish disable before acknowledging its successful write: block new admission,
cancel queued jobs, invalidate old epochs/cache, notify active subscribers.
Already dispatched provider calls may still bill; cancel where supported and
discard their results regardless. Off->on never resurrects an old epoch. A
storage failure reports a refusal and the actual state, not a successful toggle.
Concurrent writes use `expected_revision`; stale writers refetch, never overwrite.

Retain upstream's optional tuning under the same global settings owner:
`console_suggestions_max_context_messages` defaults to 4 (integer 2–10, pairing
follows upstream's last-N/2-exchanges rule), and
`console_suggestions_cooldown_seconds` defaults to 3 (nonnegative integer).
Expose these as optional advanced controls under Eternia Harness, not additional
enable prerequisites or per-persona switches. They share the same revision and
managed-key rules; changing them invalidates incompatible queued/cached work.

The transaction validates only fields the caller changes. A toggle-only disable
must work even when an existing model override or tuning value is invalid; it
must not resolve a provider or wait for an in-flight call. Explicit override
reset restores the host's routing bundle without erasing unrelated auxiliary
limits/custom configuration or credentials; implement against the host's real
schema, not a handwritten provider/model-only replacement map.

`hermes_cli/plugins_state.py::save_plugin_setting` writes one setting at a time.
It is a locking/writer precedent, not an existing atomic multi-field API. The
contract slice must use that canonical locking/config-write authority to commit
the requested settings/auxiliary changes in one transaction or refuse the whole
explicit bundle. Publish the matching revision/epoch only after commit. Bind
cache validity to the persisted config revision and a restart generation, so a
crash between config commit and notification cannot resurrect old content. On
ordinary admission/read/publish paths, the canonical config reader must observe
external changes; malformed/disabled config immediately blocks publication.
No claim of a global reload push hook is made by this audit: prove its actual
connection or add one runtime-scoped invalidation seam in the contract row.

### 4.2 Auxiliary provider/auth connection

Register a unique `console_next_prompt` task through the existing
`PluginContext.register_auxiliary_task` on the eternia-harness plugin. It must not
collide with upstream next-prompt's `next_prompt` task or share its enable switch.
Route through the host-owned `ctx.llm` / `agent/plugin_llm.py::PluginLlm` facade,
backed by `agent/auxiliary_client.py`. Task routing is `auxiliary.console_next_prompt`
in the serving head configuration. Preserve provider trust/override gates and the
existing namespace auth-home resolver; no raw key passes through Dart or a new
HTTP client. Resolve the global auxiliary configuration in its own explicit scope,
not an ambient persona-worker thread. No blanket `allow_*_override` grant.

Under selected D3 B, use the host's existing auxiliary resolution, authentication
and fallback policy. `hermes_cli/plugins_aux_tasks.py::build_auxiliary_task_entry`
already defaults an unpinned task to provider `auto` and an empty model. Leave
those host defaults in place; the new task name is for ownership/accounting, not
a requirement for a separate provider account or model selection. Do not replace
the host's routing policy with a suggestion-specific cascade or a blanket ban
on its existing fallback behavior. Record the **actual** provider/model used.

An optional override belongs to `auxiliary.console_next_prompt` and follows host
validation/trust controls. Clearing it restores inherited routing. Neither action
writes persona or primary-model fields. Inherited configuration changes invalidate
affected cached suggestions just as explicit override changes do. Report
`model_unconfigured` only when no usable host route can resolve, not merely when
the suggestion override is absent; auth/transport/provider failures remain typed
unavailable states. Unresolved route metadata may be unknown until dispatch;
do not run a model or quota probe to fill it while off.

Prove cold-serve ownership explicitly: `plugins/eternia-harness/__init__.py::register`
registers the task once with the existing manager, and an enabled serve receives
the manager-owned `ctx.llm` without starting a persona turn or hand-constructing
`PluginContext`. CLI parser setup alone is not proof that this happened. Failure
to obtain that capability is a typed unavailable state, never silent success.
No upstream next-prompt cache import, plugin installation, enable-state copy or
`auxiliary.next_prompt` rewrite accompanies this feature.

The service's executor must bind its captured runtime/account auth-home context
on every job. `agent/auxiliary_client.py::_read_main_field` prioritizes runtime
overrides; use the existing `scoped_runtime_main` ownership correctly so a copied
persona-worker ContextVar cannot override the serving runtime's inherited route.
Do not copy a persona's soul/system/memory, mutate process environment per job,
or bypass the host facade. Test concurrent personas plus a cold serve with no
previous actor, including runtime-main and read-projection contamination cases.

Use `PluginLlm.complete` for free-form text. Structured-output support is not a
prerequisite and must not be used to force a finite intent/reference schema.
Cleanup, length/shape checks and secret redaction apply to returned text before
publication; empty or rejected output yields no suggestion, not a fabricated
template or a second model invocation by default.

Avoid copying the plugin's unconditional `temperature=0.3`: let the provider
capability layer determine supported parameters. Preserve host OAuth/refresh,
timeouts, cancellation and usage accounting. Attribute auxiliary usage separately
from the persona turn; don't add it to the persona's response token totals.

Existing provider API: `agent_runtime/serve_rpc/provider.py` registers
`runtime.provider.list`, `.usage`, `.signin.begin` / `.poll` / `.complete` /
`.cancel`, `.refresh` and `.signout`, backed by
`agent_runtime/provider_account.py` and `agent_runtime/provider_signin.py`.
See [provider method contract](../runtime-provider-methods.md) for transport
restrictions and deadlines. Reuse the existing provider connection UI only on
explicit user action. `runtime.provider.configure` and `runtime.default_model.set`
change primary model policy: neither is a setter for the new auxiliary slot.
The new settings method validates/writes only an explicitly requested override;
ordinary enable/disable must not pin a model or change primary fields.
`runtime.provider.list` can make a quota/auth probe; never call
it as a hidden per-turn or disabled-path readiness poll.

## 5. Context and the no-invented-confirmations policy

Extract the configured bounded window of actual user/final-assistant exchanges
from the requested root's committed, curated lineage (default two exchanges,
up to five). Reuse the final-answer pairing and head/tail clipping
idea from `_build_context`, not its raw hook-history input. Existing anchors are
`agent_runtime/persona_chat_history/messages.py`, `agent_runtime/persona_chat_history/curation.py`, `agent_runtime/persona_chat_history/operator_envelopes.py`, and
`agent_runtime/persona_chat_continuity/content.py`. Do not expose injected HUD, workspace prompt,
private guidance, intermediate narration, tool payloads, reasoning or attachments.
Apply the existing secret redactor before auxiliary dispatch and on generated
candidate text. An uncertain/unreadable redaction status means no publication.

The current public history API bounds its returned page but curation can walk the
whole lineage before slicing. Do not call it per poll or assume `limit=4` proves
bounded computation. `RT-NEXT-PROMPT-CONTEXT` must add a bounded projection at the
existing history owner (or use a bounded immutable post-commit capture), preserving
identical curation/redaction. No new full-history scanner or shadow transcript.

Selected D2 B preserves one short contextual free-form next message in the
conversation's language. Reuse/adapt next-prompt's prompt construction and output
cleanup, including complete model-authored sentences, instead of reducing output
to a menu of questions or reference intents. Match the latest user's language and
writing style, not the topic's language. Useful follow-ups, conversational
replies and user-grounded statements remain eligible; suppress when no useful
continuation exists. Do not ban all affirmative language or require literal
source-span matches for every sentence.

Replace the original instructions/examples that tell the model to guess a manual
check's outcome. Instruct it not to invent actions the user took, test results,
private facts or approvals. For an unanswered manual check, it may suggest a
useful clarification/request or return no suggestion; it must not predict success
as fact. Suppress suggestions while a structured approval/clarification request
is pending. Existing response controls retain their authority, and a suggested
draft is never evidence that the user consented or performed an action.

Apply output cleanup, bounded text validation, redaction and known-state checks;
evaluate adversarial, multilingual and ordinary conversational cases. Do not
claim these checks or a phrase blacklist guarantee semantic truth for arbitrary
free-form output. Record observed fabrication and over-suppression rates during
qualification; positive cases must prove ordinary contextual replies survive.
No constrained-template fallback, extra confirmation dialog or mandatory second
model judge is part of this baseline. Unsupported/invalid output yields no
suggestion with a reason; it does not change the persona's response.

Do not copy upstream cleanup bugs as policy: bracketed code such as `config[0]`,
literal `<Widget>` references, and `NULL handling` are not automatically blanks
or the no-suggestion sentinel. Recognize exact sentinel responses after label/
quote cleanup; distinguish unfinished placeholders from literal content. Valid
short non-Latin replies need no arbitrary three-character minimum, and supported
model languages need no Launcher-locale allowlist. Keep one concise suggestion
and the existing 160-code-point maximum; these are plugin parity, not an invented
restriction. Never silently truncate an overlong candidate into a different claim.

## 6. Lifecycle, storage, and scale

### 6.1 Trigger and freshness

`hermes_cli/harness_parts/persona/chat_turn_commit/settle.py::_SettlePhases._project`
records `TURN_STATE_PROJECTED` and calls
`hermes_cli/harness_parts/persona/chat_events.py::_publish_persona_chat_projection_event` only after persistence.
This event contains root, instance, turn and native revision, but it is a durable
event-log notification, not a ready-made plugin callback with full authorization.
Consume it through an existing bounded serve subscriber, or add a narrow
fork-owned post-lease enqueue callback. Do not do transcript reads, provider
resolution or inference inside `_project` or the root lease. `_defer_auto_title`
documents why post-terminal-frame still held the root busy; its deferred object
can enqueue bounded work, never run the new LLM call synchronously.

Admission requires: enabled epoch, explicit eligible Console origin, persisted
successful final text, exact owner/instance/root, current revision, no active or
queued next turn, no unresolved approval/clarify, and a visible authorized
subscriber (D5 A). Provider refusal, cancellation, partial or unknown settlement,
prewarm and duplicate settle replay do not generate. Catch-up on subscribing
reads only the latest eligible turn and applies the same checks.

Draft text is not an admission or subscription gate and is not sent to the model.
Typing alone does not invalidate or regenerate a suggestion: it is based on the
settled conversation, not keystroke autocomplete. The next actual send, source
revision or authoritative approval-state change still invalidates it. Apply the
configured per-root cooldown using the shared scheduler and latest-work coalescing;
no timer/thread per draft or new call for every subscribe transition.

Deduplicate with `(subject, source_turn_id, source_revision, policy_epoch,
model_revision, generation_policy_version)`. Multiple windows/subscribers share one job.
Per-process `_turn_seq` is insufficient across the serve/chat worker split and
restart. A durable atomic claim in the derived suggestion store fences publication;
crash recovery marks an uncertain dispatched call abandoned, rather than blindly
repeating a potentially billed completion. At-most-one publication is required;
exactly-once external billing cannot be promised across a provider crash boundary.

Separate payload retention from attempt receipts. Mark generated, suppressed,
failed, dismissed and uncertain-dispatch terminal outcomes without retaining
prompt text. An evicted payload or reconnect is not permission to repeat the
same paid attempt. Catch-up admits only a previously unattempted latest eligible
source within the content-retention window (24 hours), never historical backlog.
Terminal receipts outlive that window; after receipt pruning the source is too
old for catch-up. A fresh turn permits a new attempt, matching upstream's failure
recovery. Document deliberate invalidation from explicit routing/policy changes;
hide/show, typing, process restart and cache pressure alone cannot retry spending.
Separate the durable attempt key from the ephemeral delivery fence: a new serve
restart generation invalidates publication, but must not make an already attempted
source look new. Persist the deliberate config/model/policy generation used by
receipts; do not use a fresh process nonce as permission to call again. Never evict
a receipt while its source is still catch-up eligible to satisfy the count cap;
refuse admission until safe pruning is possible. Test more than 4,096 recent
sources as well as the ordinary 1,000-root load.

### 6.2 Explicit proposed resource budgets

These are proposed tunable defaults to qualify, not measured capacity claims:

| Resource | Initial bound / overload behavior |
|---|---|
| Inference | 2 running jobs per namespace; 1 per root; at most 32 pending distinct roots |
| Queue | Latest eligible revision replaces older pending work for that root; full queue reports `capacity_limited`, never blocks chat |
| Context | Configurable 2–10 messages, default 4; 1,200 Unicode code points per message (300 head/900 tail), plus fixed instructions; fit the host model's input limit by dropping older exchanges first, preserving latest-user language and accounting clipping; no fixed 4,096-token cap that silently defeats the selected window |
| Output | 256 output tokens; one cleaned free-form draft, at most 160 Unicode code points; no intent/template restriction |
| Deadline | Use configured host auxiliary timeout/progress/retry policy (registered task default 60 seconds); no new 15-second cutoff. A timeout value is not a guaranteed end-to-end wall bound; cancellation and real outstanding calls must be qualified |
| Cooldown | Preserve configurable per-root cooldown, default 3 seconds; shared bounded scheduler, latest-source coalescing, no typing/reconnect regeneration |
| Cache | At most 256 pending subjects; 24-hour TTL plus immediate invalidation; oldest expired/unused entries first, eviction accounted |
| Dedup receipts | Bounded age/count (initial 7 days / 4,096 terminal records); active claims not evicted; pressure refuses admission rather than losing a live fence |
| Subscriptions | At most 8 per authenticated connection and 64 per namespace; idempotent same-target subscribe; explicit `subscription_limit` |
| Settings watch | One metadata-only watch per connection, at most 64 per namespace; no context, cache creation or inference while off |
| Fan-out | Coalesce latest state per subscription; bounded output buffer; slow subscriber receives resync/closure, never unbounded text buffering |

Service ownership is the serve namespace, with orderly shutdown/unsubscribe and
profile/home binding at job execution. Use a shared bounded executor, not one
daemon thread or one poll timer per conversation. SQLite WAL can be reused as a
mechanism, with a schema suited to root/revision/epoch ownership. Store is derived
local state, excluded from realm transcript sync; delete its rows on chat/account
erasure and retention cleanup. No orphan queue survives namespace teardown.

Off fast path does not open the suggestions DB, curate history, resolve a model,
schedule work or allocate a worker. Existing config caching may be used with
explicit invalidation; do not reparse YAML for every stream token. Low-priority
jobs must not steal the main chat's connection slots; qualify shared provider-pool
contention, local-model/GPU contention and same-root immediate-next-send latency.
If isolation cannot keep chat latency stable, lower concurrency or skip a job;
do not weaken existing turn-time budgets.

Count actual provider work, including cancellation tails, against capacity.
`agent/auxiliary_client.py::_run_protected_sync_provider_call` can release its
owner while a provider daemon remains alive. Do not treat a discarded result or
completed UI future as a freed inference slot and launch unlimited replacements.
Prefer a bounded synchronous facade call whose slot remains held until completion,
with immediate epoch invalidation for UI disable; use host cancellation only when
its completion can be accounted for. Never close a shared provider client to
cancel one suggestion. If supported cancellation accounting needs a narrow host
seam, record it in the lifecycle slice rather than claiming a false two-call bound.

## 7. API map and proposed wire contract

### 7.1 Existing connections to extend

| Boundary | Existing owner / symbols | Use |
|---|---|---|
| Setting schema/read | `plugins/eternia-harness/plugin.yaml::config_schema`, `agent_runtime/harness_settings.py::harness_setting` | Declare false default; explicit head scope |
| Config write | `hermes_cli/plugins_state.py::save_plugin_setting`; `PluginContext.set_config` | Reuse atomic configuration writer, add typed compare-and-set owner |
| Head/auth identity | `agent_runtime/profile_home.py::get_hermes_head_home`, `get_hermes_auth_home`; `agent_runtime/profile_context.py` | Separate global settings/model policy from persona execution |
| Aux registration/call | `PluginContext.register_auxiliary_task`, `agent/plugin_llm.py::PluginLlm.complete`, `hermes_cli/plugins_aux_tasks.py::build_auxiliary_task_entry` | Existing auto routing/auth/fallback/usage; optional task override; no provider SDK in Launcher |
| Exact conversation | `agent_runtime/operator_conversation.py::exact_operator_target`, `agent_runtime/operator_session_inspection.py::operator_session_read` | Verify install, workspace, persona, instance, root and owner |
| Read context | `agent_runtime/persona_chat_history/messages.py::existing_chat_session`; existing curation/redaction owners | Bounded owner-checked committed projection |
| Turn trigger | `hermes_cli/harness_parts/persona/chat_turn_commit/settle.py::_SettlePhases._project`, `hermes_cli/harness_parts/persona/chat_events.py::_publish_persona_chat_projection_event` | Persisted eligible turn; enqueue after root lease |
| RPC registration | `agent_runtime/serve_rpc/registry.py::method`, `manifest`, `agent_runtime/serve_rpc/__init__.py` | Add a fork-owned method family; explicit tier and advertised capabilities |
| Authorization | `agent_runtime/call_authorization.py::RpcCaller`, `LOCAL_CONSOLE_METHODS`; `agent_runtime/conversation_owner.py` | Transport-proven caller, never a client-asserted identity |
| Push | `agent_runtime/serve_rpc/protocol.py::RpcContext`, `notification`; `agent_runtime/serve_office_subscriptions.py` connection teardown/baseline pattern | Targeted subscription with atomic baseline+sequence, not roster-wide core rebuild |
| Launcher route | `EterniaLauncher/lib/core/services/hermes/runtime/hermes_runtime_route_provider.dart`, `HermesConversationRuntime.destination` | Always the conversation's own runtime, no remote->local fallback |
| Dart RPC pattern | `EterniaLauncher/lib/app/agent_console/agent_console_controls_binding.dart`, `EterniaLauncher/lib/app/agent_console/agent_console_turn_audit_binding.dart`, `MissionMethodLaneClient.invoke` | Exact-target ports, capability gating and typed outcomes |
| Dart push | `EterniaLauncher/lib/core/services/hermes/runtime/data/serve/mission_serve_rpc_lane.dart::MissionServeRpcLane`, serve session `onRpcNotification` | Bind one lifecycle-managed notification subscription |
| Settings surface | `EterniaLauncher/lib/features/account/tabs/settings/harness/harness_settings_section.dart::SettingsHarnessSection`; Harness default-model ports/binding pattern | One switch and model readiness inside existing global page |
| Draft insertion | `EterniaLauncher/lib/features/agent_console/panel/agent_console_composer_section.dart`, `ConversationDraftDelivery`, `ConversationDraftReceiver` | Existing account/conversation draft owner, no send authority |

### 7.2 New methods (proposed names; none exists yet)

All belong to the existing serve JSON-RPC transport; no new socket, REST service,
MCP tool, raw YAML write, shell command or argv fallback.

| Method | Parameters beyond request id | Tier / result |
|---|---|---|
| `runtime.console_suggestions.settings.get` | `install_id` | console; settings/readiness/revision, no inference |
| `runtime.console_suggestions.settings.set` | `install_id`, `expected_revision`, and changed fields only: optional `enabled`, `max_context_messages`, `cooldown_seconds`, `auxiliary_override` (omitted: preserve; null: clear; validated task-route object: set) | console; atomic field-scoped result; disable-only needs no model/tuning validation; preserve unrelated host route fields; no raw credential fields |
| `runtime.console_suggestions.settings.subscribe` / `.unsubscribe` | `install_id` on subscribe; owned `subscription_id` on unsubscribe | console; one connection-owned metadata baseline/watch, shared by the settings page and Console |
| notification `runtime.console_suggestions.settings.changed` | `subscription_id`, `seq`, settings revision, policy epoch and safe settings/readiness state | metadata-only push to authorized watchers; another window learns enable/disable without polling |
| `runtime.operator.conversation.suggestions.read` | exact target + `client_scope` | console; current state, identity, revision, reason; never generates by itself |
| `runtime.operator.conversation.suggestions.subscribe` | exact target + `client_scope` | console; connection-scoped id, current baseline/seq; may admit one latest-turn catch-up under global opt-in |
| `runtime.operator.conversation.suggestions.unsubscribe` | `subscription_id` | console; remove only this connection's subscription, idempotent |
| `runtime.operator.conversation.suggestions.dismiss` | exact target + `entry_id`, `expected_revision` | console; idempotent conditional dismissal of ready or failure entry; an old id cannot clear a newer entry |
| notification `runtime.operator.conversation.suggestions.changed` | `subscription_id`, `seq`, exact identity, `policy_epoch`, source turn/revision, state | only the authorized subscribed connection; no JSON-RPC id |

Exact target follows existing operator APIs: `install_id`, nullable `workspace_id`,
`persona_id`, `persona_instance_id`, `session_id`, and owner `client_scope` validated
against transport/session authority. Do not invent a new runtime-id spelling in
the adapter. Response includes `contract: 1` and echoes target provenance.
`settings.set` uses existing namespace credential ownership; if remote model
catalog selection is unavailable, refuse that operation explicitly, never borrow
the local catalog. The plain enable/disable may operate on a named paired runtime
only with the existing Console grant and stale-target checks.

States: `disabled`, `model_unconfigured`, `idle`, `queued`, `generating`, `ready`,
`none`, `unavailable`. `none` carries a reason such as `no_useful_suggestion`,
`manual_confirmation_required`, `source_changed`, `capacity_limited` or `expired`.
`unavailable` has a safe enum reason (auth/rate_limit/timeout/storage/provider),
never provider text, tokens, prompt fragments or private filesystem paths.
Freeze a discriminated state union in paired fixtures: `ready` has `entry_id` and
free-form `text`; a dismissible generation failure in `unavailable` has `entry_id`
and safe `reason`, never draft text. Both carry exact subject, source revision,
`entry_revision` and epoch. Settings writes compare `expected_revision` with
`settings_revision`; dismissal compares it with `entry_revision`, not the source
turn or settings revision. Idle/queued/generating/none carry no insertable text. Distinguish a durable
source failure entry from connection/model-readiness state, which is not dismissed
as if it were generated content. Include context/cooldown and inherited/override
route state in settings snapshots; the route object follows the host's existing
supported task fields rather than inventing a provider/model-only replacement.
Invalid shapes use -32602; stale target/revision follows 4090 + typed reason;
existing authorization refusals remain unchanged. Older manifests => unsupported,
not disabled or silently enabled. Do not bump unrelated parity envelope versions.


Subscribe installs its sink and snapshots the baseline atomically with updates;
buffer newer notifications until the subscribe reply is applied. Sequence gap,
reconnect, token revocation or runtime restart forces authorized revalidation and
fresh baseline. No stale cache gets painted while that happens. Dismiss is durable
for that source key; resubscribe/reconnect does not regenerate what the user hid.
The server gates conversation read/subscribe before history, cache initialization
or admission when off; return disabled without registering a chat sink. Disable
invalidates existing chat subscriptions after their terminal policy notification.
UI gating alone is not the zero-work boundary. Auth revocation removes sinks and
prevents queued push delivery; never log the free-form payload on these paths.

Keep global policy observation separate from per-chat suggestion admission. A
single connection-owned metadata watch may remain while disabled; it does no
history read, provider probe, suggestion-store initialization or worker startup.
It is how another window learns an opt-in/disable and how enabled Consoles start
or stop per-chat subscriptions. Reconnect hydrates settings first. External
configuration changes must advance the same revision/epoch through the verified
invalidation owner in section 4.1; an existing global reload callback is not yet
proven. Canonical config is checked at read/admission/publication, with no second
setting authority or per-chat file poller. Auth revocation and connection teardown
remove both kinds of watch.

## 8. Launcher behavior

Global Settings > Eternia Harness shows the target runtime, off-by-default switch,
inherited auxiliary routing/readiness and concise usage text. Model override and
reset-to-inherited and advanced context-window/cooldown tuning are optional
controls, never an enable prerequisite. Disable writes only the toggle, even if
a picker is disconnected or an unsubmitted tuning draft is invalid. No duplicated switch in Agent details
or Console menus. Save progress, refusal, disconnected, unsupported and target-
changed states are explicit. On account/edition/runtime change, discard the old
pending write target and re-read; never optimistically claim persisted success.

The Console feature owns a small presentation controller through a typed port;
application composition binds RPC/push, following existing controls/audit adapters.
Subscribe only when a real, visible eligible chat is idle; a nonempty draft is
not an admission, presentation or insertion prohibition and is never model input;
dispose on hide/account/route change. Keep one subscription owner when the Console
moves between floating, docked and fullscreen hosts; no reparent-triggered
generation. No per-chat suggestion calls or timers for a hidden/disabled/
unsupported surface; a shared runtime settings watch is metadata-only.

Show one compact dismissible pill for `ready`, outside message history. It carries
no persona avatar or appearance of an agent answer. Do not automatically shift
composer focus, replace a user's draft or show a loading spinner that competes
with the main agent. Suppress while sending, streaming, approval/clarify pending,
source changed, or the next send is queued. Typing alone neither hides the entry
nor triggers generation. Generation failure does not fail chat; a small accessible,
dismissible explanation uses the same entry identity without repeated toast spam.

Explicit Use revalidates captured conversation identity, entry id/epoch and source
revision at the actual insertion boundary, then uses the existing draft owner.
Read the current same-chat draft after any asynchronous checks: insert into an
empty draft or append one separated block to existing text, preserving its text,
selected content and attachments. Add no attachments from the suggestion. Defer
insertion during IME composition and revalidate after it ends. Only successful
explicit use may focus the composer and place the caret after the inserted block.
Dismiss only after successful insertion; failure leaves the suggestion available.
Do not use the shared delivery mechanism's delayed-wait behavior to insert after
the user has switched chats. If dismissal ack is lost after insertion, hide that
exact suggestion locally, reconcile idempotently, and never insert it twice.
No clipboard fallback, auto-send, permission response or draft overwrite.

Expose discoverable native Use suggestion and Dismiss suggestion actions and a
focused shortcut, preferring upstream `mod+shift+y` only after collision checking.
Use existing Console action/menu and Flutter focus/Shortcuts owners; do not route
through the unrelated DM slash-command registry. Modal focus and another window's
composer must never be captured. A Launcher global command palette/rebinding editor
was not verified, so constructing one is not a prerequisite; record the shipped
native action/shortcut mapping and any conflict-driven alternative in qualification.

## 9. Work breakdown and dependency order

IDs are stable; the queues alone hold status and claims. Each build slice lands
with its behavior tests and source provenance, not a later testing-only promise.

| Row | Deliverable / acceptance | Depends on |
|---|---|---|
| `RT-NEXT-PROMPT-DECISIONS` | Record selected revised baseline; hold all build work until the owner later requests implementation | Owner's explicit deferral |
| `RT-NEXT-PROMPT-CONTRACT` | False-default head-scoped settings, optional context/cooldown, atomic partial writes and restart/external-edit fencing; cold-serve host auxiliary registration/context ownership; disabled zero-call proof (F1/F4/F6) | Decision row |
| `RT-NEXT-PROMPT-CONTEXT` | Pinned helper reuse/notice, configurable bounded curated context, free-form suggestions, valid short/code-bearing output, anti-fabrication and over-suppression evaluation, persona non-mutation proofs (F1/F5) | Contract |
| `RT-NEXT-PROMPT-LIFECYCLE` | Post-lease admission, shared cooldown, bounded actual provider calls including cancellation tails, separate receipts/cache, restart/disable/deletion fences and usage (F1/F4/F6/F7) | Context |
| `RT-NEXT-PROMPT-RPC` | Advertised partial-settings and ready/failure entry contracts, server off gate, authorization, atomic subscribe baseline, push lifecycle, conditional dismiss, old-client fixtures (F8) | Lifecycle |
| `MC-NEXT-PROMPT-CLIENT` | Typed entry union/partial settings, per-runtime RPC/push binding, capability gating, target/race tests (F8) | RPC |
| `MC-NEXT-PROMPT-SETTINGS` | Global Settings > Eternia Harness switch, optional override/reset and context/cooldown; disable independent of unrelated invalid fields, target provenance and persisted false default (F1/F8) | Client |
| `MC-NEXT-PROMPT-COMPOSER` | Native pill and use/dismiss actions, focused shortcut, visible subscription independent of draft emptiness, guarded additive insertion, failure dismissal, IME and all placements (F2/F3/F8) | Settings |
| `MC-NEXT-PROMPT-QUALIFY` | Paired-version native proof across F1–F8 and measured latency/scale outcomes; docs folded into canon only when built | Composer and all Hermes acceptance evidence |

No generic plugin install row or backend-service change is required by the
recommended design. If D1 B or D4 B is selected, revise the dependency graph and
add the actual owner-repo rows before implementing that larger scope.

## 10. Acceptance and scale qualification

| Case | Required evidence |
|---|---|
| Default/off | Fresh config, upgrade, repair, restart and malformed-config cases yield no auxiliary calls, history scans, suggestion DB creation or workers. A disabled button is not the proof. |
| Toggle races | Disable before enqueue, while queued, during provider call and before publish; off/on epoch; stale writer; no old result becomes ready. |
| Settings/cold serve (F1/F6/F8) | Fresh serve without prior persona execution obtains manager-owned facade/task; concurrent persona/runtime-main and config-read scopes cannot contaminate the route. Context 2/4/10, odd-value pairing and cooldown 0/3; disable with invalid unsubmitted tuning or unavailable picker; atomic multi-field failure, external edit and crash between config commit/push; managed-key refusals. |
| Persona preservation | Two personas/two profiles, two instances of one persona and two roots per instance; compare prompts/cache identity/model overrides/permissions/skills/memory config before and after; no mutations or cross-chat leakage. |
| Root lifecycle | Compression, redo, rollback, branch, new root, retired instance, deleted chat, erasure, account/edition/runtime switch; stale candidates disappear and cannot be inserted. |
| Free-form quality and human truth | Positive fixtures preserve contextual replies and user-grounded statements, not just questions; unanswered manual checks, fabricated test results, approvals, personal details, prompt injection and multilingual cases are evaluated. Suppress during structured approval/clarification. Report observed fabrication and false-rejection rates; no blanket truth guarantee. |
| Cleanup parity (F5) | Literal code brackets/tags, `NULL handling`, exact sentinel, short non-Latin replies, latest-user language versus topic language, 160-code-point boundary and overlong candidate; no locale allowlist, blanket bracket rejection or silent truncation. |
| Authorization | Wrong install/workspace/persona/instance/root/client_scope; read-only/revoked peer; foreign subscription id; reconnect same account versus changed account. Refuse before history/inference. |
| Persistence/fan-out | Two processes/windows request one source concurrently; duplicate settled event, crash at claim/dispatch/publish/dismiss boundaries; DB locked/corrupt, full cache, stale dismissal; no duplicate publication or hidden retry spend. |
| Receipt/capacity fences (F4/F7) | Payload expiry/eviction without receipt loss, stale source after receipt pruning, new process nonce without retry, more than 4,096 recent sources, failed/uncertain/dismissed reconnect; bounded actual outstanding calls when UI cancellation completes before provider termination. |
| Provider | No suggestion-specific override uses the existing auxiliary route; override and reset follow host policy without changing persona/primary models. Cover inherited route changes, host-authorized fallback, actual-route reporting, missing/revoked auth, rate limit, timeout, cancellation and local model busy; no structured-output dependency or new mandatory setup. |
| UI (F2/F3/F8) | Explicit use appends safely to the current nonempty draft; typing during async checks, IME composition, retained text/selection contents/attachments, focus only after explicit use; modal/two-window shortcut scope, failure dismissal, stale entry, wrong chat while insertion awaits, host moves, hidden pane, old runtime; no send or overwrite. |
| Slow host route (F4) | Configured local/reasoning model completes beyond 15 seconds without a feature-specific cutoff; host timeout/progress/retry remains effective and real running calls stay bounded. |
| Scale | Fake deterministic load: 1,000 distinct completed roots, 64 subscribers, duplicate reconnects and source churn; assert 2 active/32 pending and O(active work + bounded cache), not unbounded threads/timers. Real provider smoke only on an isolated opt-in profile after authorization. |
| Latency | Compare off/on cold/warm/immediate-next-send timings on an idle box with unchanged primary model; no delay to first text, final delivery or root release beyond existing budgets; report auxiliary time separately. No guessed performance win. |

Existing regression anchors: `tests/agent_runtime/test_harness_settings.py`,
`tests/agent_runtime/test_operator_session_inspection.py`, `tests/agent_runtime/test_operator_session_controls.py`,
`tests/agent_runtime/test_instance_conversation_owner.py`, `tests/agent_runtime/test_persona_chat_runtime_identity.py`,
`tests/agent_runtime/test_persona_chat_history_curation.py`, `tests/agent_runtime/test_terminal_turn_settlement.py`.
Add focused fork-owned suggestion tests beside these; do not append to upstream
tests. Reuse external cases only after changing the invented-confirmation policy.
Launcher anchors and proposed tests are in its handoff. Run selected checks under
each repository's test instructions; no full suite for this documentation task.

For positive controls, deliberately bypass epoch checks, swap persona/root targets,
drop structured-approval suppression, clear by session instead of suggestion id, remove the
queue bound, or call the model on the disabled path: the corresponding test must
fail. Provider-text regexes and mocked UI screenshots alone cannot qualify these
contracts. Also reject a usable inherited route merely because its task override
is absent, or replace every free-form reply with a question template: the routing
and positive quality tests must catch those regressions. Final live proof names
both code revisions, isolated namespace, effective auxiliary route/override,
measured costs/timings, fabrication/over-suppression findings and limitations.

## 11. Delivery and documentation retirement

Implementation requires the owner's go-ahead; rows remain blocked until then.
When authorized, land Hermes contracts and capability fixtures before the Launcher
consumer. Publish neither half as enabled by default. Preserve the pinned source
notice/provenance and record any helper deliberately not reused. Verify both
Developer and bundled editions include only the required fork modules and license;
the upstream Desktop plugin remains independently installable and disabled here.

On completion, fold verified runtime facts into chat/transport/lifecycle canon
and Launcher behavior into its chat surface canon. Move this audit/decision
evidence to the archive with shipping SHAs, update all pointers, and delete the
completed queue rows. Unproven load or provider cases remain named work, never
represented as shipped capability.
