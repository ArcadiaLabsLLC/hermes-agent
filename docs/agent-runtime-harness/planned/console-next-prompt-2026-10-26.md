# Agent Console follow-up suggestions: audit and implementation plan

Status: **PLANNED — not implemented or authorized to execute.** Date: 2026-10-26.
Owner request: reuse next-prompt where appropriate, off by default in Harness global
settings, no invented confirmations, preserve the persona system, identify options
and API connections, and queue the work in its owning repositories.

This is the canonical cross-repository design. The Launcher implementation map is
`EterniaLauncher/docs/mission_control/planned/CONSOLE_NEXT_PROMPT_2026-10-26.md`.
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
| D7 retention | A: derived local cache, expires after 24 hours or any identity/revision/policy invalidation; B: upstream's seven-day persistence | **A**: suggestions can be recomputed; don't keep obsolete human-reply guesses across a week of work. Usage/deduplication metadata has bounded separate retention. |

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

Extract at most two actual user/final-assistant exchanges from the requested root's
committed, curated lineage. Reuse the final-answer pairing and head/tail clipping
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
to a menu of questions or reference intents. Useful follow-ups, conversational
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

Deduplicate with `(subject, source_turn_id, source_revision, policy_epoch,
model_revision, generation_policy_version)`. Multiple windows/subscribers share one job.
Per-process `_turn_seq` is insufficient across the serve/chat worker split and
restart. A durable atomic claim in the derived suggestion store fences publication;
crash recovery marks an uncertain dispatched call abandoned, rather than blindly
repeating a potentially billed completion. At-most-one publication is required;
exactly-once external billing cannot be promised across a provider crash boundary.

### 6.2 Explicit proposed resource budgets

These are proposed tunable defaults to qualify, not measured capacity claims:

| Resource | Initial bound / overload behavior |
|---|---|
| Inference | 2 running jobs per namespace; 1 per root; at most 32 pending distinct roots |
| Queue | Latest eligible revision replaces older pending work for that root; full queue reports `capacity_limited`, never blocks chat |
| Context | 4 messages; 1,200 Unicode code points per message (300 head/900 tail); additionally 4,096 input tokens including instructions; account clipping |
| Output | 256 output tokens; one cleaned free-form draft, at most 160 Unicode code points; no intent/template restriction |
| Deadline | 15-second auxiliary deadline initially; provider-aware cancellation and no detached unlimited retries |
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
| `runtime.console_suggestions.settings.set` | `install_id`, `expected_revision`, `enabled`, optional `auxiliary_override` (omitted: preserve; null: clear; provider/model object: set) | console; atomic validated result; toggle alone preserves inherited routing; same-account paired-console choice follows D4 target, no raw credential fields |
| `runtime.console_suggestions.settings.subscribe` / `.unsubscribe` | `install_id` on subscribe; owned `subscription_id` on unsubscribe | console; one connection-owned metadata baseline/watch, shared by the settings page and Console |
| notification `runtime.console_suggestions.settings.changed` | `subscription_id`, `seq`, settings revision, policy epoch and safe settings/readiness state | metadata-only push to authorized watchers; another window learns enable/disable without polling |
| `runtime.operator.conversation.suggestions.read` | exact target + `client_scope` | console; current state, identity, revision, reason; never generates by itself |
| `runtime.operator.conversation.suggestions.subscribe` | exact target + `client_scope` | console; connection-scoped id, current baseline/seq; may admit one latest-turn catch-up under global opt-in |
| `runtime.operator.conversation.suggestions.unsubscribe` | `subscription_id` | console; remove only this connection's subscription, idempotent |
| `runtime.operator.conversation.suggestions.dismiss` | exact target + `suggestion_id`, `expected_revision` | console; conditional dismissal; an old id cannot clear a newer suggestion |
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
Invalid shapes use -32602; stale target/revision follows 4090 + typed reason;
existing authorization refusals remain unchanged. Older manifests => unsupported,
not disabled or silently enabled. Do not bump unrelated parity envelope versions.


Subscribe installs its sink and snapshots the baseline atomically with updates;
buffer newer notifications until the subscribe reply is applied. Sequence gap,
reconnect, token revocation or runtime restart forces authorized revalidation and
fresh baseline. No stale cache gets painted while that happens. Dismiss is durable
for that source key; resubscribe/reconnect does not regenerate what the user hid.

Keep global policy observation separate from per-chat suggestion admission. A
single connection-owned metadata watch may remain while disabled; it does no
history read, provider probe, suggestion-store initialization or worker startup.
It is how another window learns an opt-in/disable and how enabled Consoles start
or stop per-chat subscriptions. Reconnect hydrates settings first. External
configuration changes use the existing configuration reload boundary to advance
the same revision/epoch and notify watchers; no second setting authority or file
poller. Auth revocation and connection teardown remove both kinds of watch.

## 8. Launcher behavior

Global Settings > Eternia Harness shows the target runtime, off-by-default switch,
inherited auxiliary routing/readiness and concise usage text. Model override and
reset-to-inherited are optional controls, never an enable prerequisite. No duplicated switch in Agent details
or Console menus. Save progress, refusal, disconnected, unsupported and target-
changed states are explicit. On account/edition/runtime change, discard the old
pending write target and re-read; never optimistically claim persisted success.

The Console feature owns a small presentation controller through a typed port;
application composition binds RPC/push, following existing controls/audit adapters.
Subscribe only when a real, visible eligible chat is idle and its draft is empty;
dispose on hide/account/route change. Keep one subscription owner when the Console
moves between floating, docked and fullscreen hosts; no reparent-triggered
generation. No per-chat suggestion calls or timers for a hidden/disabled/
unsupported surface; a shared runtime settings watch is metadata-only.

Show one compact dismissible pill for `ready`, outside message history. It carries
no persona avatar or appearance of an agent answer. Do not shift composer focus,
replace a user's draft or show a loading spinner that competes with the main
agent. Suppress while typing, sending, streaming, approval/clarify pending, source
changed, or the next send is queued. Generation failure does not fail chat; a
small accessible explanation is available without repeated toast spam.

Click revalidates captured conversation identity, suggestion id/epoch and the
empty draft, then inserts through the existing draft owner with no attachments.
Dismiss only after successful insertion; failure leaves the suggestion available.
Do not use the shared delivery mechanism's delayed-wait behavior to insert after
the user has switched chats. If dismissal ack is lost after insertion, hide that
exact suggestion locally, reconcile idempotently, and never insert it twice.
No clipboard fallback, auto-send, permission response or draft overwrite.

## 9. Work breakdown and dependency order

IDs are stable; the queues alone hold status and claims. Each build slice lands
with its behavior tests and source provenance, not a later testing-only promise.

| Row | Deliverable / acceptance | Depends on |
|---|---|---|
| `RT-NEXT-PROMPT-DECISIONS` | Record selected revised baseline; hold all build work until the owner later requests implementation | Owner's explicit deferral |
| `RT-NEXT-PROMPT-CONTRACT` | False-default, explicitly head-scoped settings and unique auxiliary slot; atomic revision/epoch writer; capability and model readiness contracts; disabled zero-call proof | Decision row |
| `RT-NEXT-PROMPT-CONTEXT` | Pinned helper reuse/notice, bounded curated context, contextual free-form suggestions, anti-fabrication and over-suppression evaluation, persona non-mutation proofs | Contract |
| `RT-NEXT-PROMPT-LIFECYCLE` | Post-lease admission, bounded queue/cache/claims, stale/disable/deletion fences, separate usage; duplicate windows and crashes covered | Context |
| `RT-NEXT-PROMPT-RPC` | Advertised RPC family, authorization, atomic subscribe baseline, push lifecycle, conditional dismiss, old-client compatibility fixtures | Lifecycle |
| `MC-NEXT-PROMPT-CLIENT` | Typed Dart data/ports and per-runtime RPC/push binding, capability gating, target/race tests | RPC |
| `MC-NEXT-PROMPT-SETTINGS` | Global Settings > Eternia Harness switch, inherited auxiliary readiness and optional override/reset; target provenance and persisted false default | Client |
| `MC-NEXT-PROMPT-COMPOSER` | Native pill, visibility subscription, guarded draft insertion, all Console placements and accessibility | Settings |
| `MC-NEXT-PROMPT-QUALIFY` | Paired-version native proof and measured latency/scale outcomes; opening docs folded into canon only when built | Composer and all Hermes acceptance evidence |

No generic plugin install row or backend-service change is required by the
recommended design. If D1 B or D4 B is selected, revise the dependency graph and
add the actual owner-repo rows before implementing that larger scope.

## 10. Acceptance and scale qualification

| Case | Required evidence |
|---|---|
| Default/off | Fresh config, upgrade, repair, restart and malformed-config cases yield no auxiliary calls, history scans, suggestion DB creation or workers. A disabled button is not the proof. |
| Toggle races | Disable before enqueue, while queued, during provider call and before publish; off/on epoch; stale writer; no old result becomes ready. |
| Persona preservation | Two personas/two profiles, two instances of one persona and two roots per instance; compare prompts/cache identity/model overrides/permissions/skills/memory config before and after; no mutations or cross-chat leakage. |
| Root lifecycle | Compression, redo, rollback, branch, new root, retired instance, deleted chat, erasure, account/edition/runtime switch; stale candidates disappear and cannot be inserted. |
| Free-form quality and human truth | Positive fixtures preserve contextual replies and user-grounded statements, not just questions; unanswered manual checks, fabricated test results, approvals, personal details, prompt injection and multilingual cases are evaluated. Suppress during structured approval/clarification. Report observed fabrication and false-rejection rates; no blanket truth guarantee. |
| Authorization | Wrong install/workspace/persona/instance/root/client_scope; read-only/revoked peer; foreign subscription id; reconnect same account versus changed account. Refuse before history/inference. |
| Persistence/fan-out | Two processes/windows request one source concurrently; duplicate settled event, crash at claim/dispatch/publish/dismiss boundaries; DB locked/corrupt, full cache, stale dismissal; no duplicate publication or hidden retry spend. |
| Provider | No suggestion-specific override uses the existing auxiliary route; override and reset follow host policy without changing persona/primary models. Cover inherited route changes, host-authorized fallback, actual-route reporting, missing/revoked auth, rate limit, timeout, cancellation and local model busy; no structured-output dependency or new mandatory setup. |
| UI | Empty/typed draft race, wrong chat while insertion awaits, dismissed source reconnect, floating/docked/fullscreen move, hidden pane, old runtime; no send or overwrite. |
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
