---
type: queue
program: mission-control
status: open
tags: [queue, program/mission-control, runtime]
---

# Runtime — the hermes half of the Mission Control queue

- **`RT-AGENT-CONSOLE-STEP-6` — Step 6: expose profile delegation defaults and execution-host spawning pause through the existing owned subagent connection.** Owner approved 2026-10-16. Reuse native config read/write/managed policy and native pause state; preserve exact owner/generation checks across native, isolated compute and operator paths, with per-seam footprint accounting and behavioral proof. No parallel settings or execution authority. · fork / Agent Console · NEEDS PLAN 2026-10-16: (lane r-chatsend) the isolated-compute host routes children only by name lists in upstream files (`tui_gateway/compute_host.py` observe allowlist + `_control_ack`'s steer/stop set, `tui_gateway/host_supervisor.py` route classification), so a pause/defaults verb there grows the upstream footprint and moves `tests/fixtures/upstream_footprint.json`, which a queue lane may not edit; and no Step 6 page exists beside Steps 4–5 (`docs/downstream/agent-console-subagents-*.md`) to fix the verbs, the per-host pause owner (`tools.delegate_tool_registry.set_spawn_paused` is process-global) and the managed-config write refusal. Needs a design lane with fixture authority


## Ownership refresh — 2026-10-08

The 2026-10-07 sol-runtime worker is idle after its completed batch; the coordinator finished reviewing the waves. Its eight unfinished claims below are released before reassignment. Release does not mark work done or discard prior branch changes, PENDING verdicts, prerequisites or capture evidence. New work must take a fresh claim. The later daily-upstream lane is a separate assignment.

Mission Control is one surface across two repos. **This file holds the rows whose fix lives in this repository**; the launcher's half is `EterniaLauncher/Launcher_Brain/20 — Active Initiatives/mission-control-queue.md`, and a finding that needs both sides is filed on the side that must move first, with the other side named in the row. Ruling: [[0012 — The hermes half of Mission Control is queued here, split by ownership]] (amends [[0011 — One brain per repo, one Mission Control queue in the launcher]]).

Rows are one line and a pointer; claim with `**TAKEN <date> <who>**` before starting; the landing commit deletes the row; a ` · VERDICT <date>:` suffix is an owner decision, not lane work. Repo-relative paths are this repo's; another repo's file is cited with its prefix in backticks (`EterniaLauncher/…`).

**The three headings are the [[Fork Boundary Map]]'s three kinds of file**, and they decide what a lane may do:

| heading | what it means | what a lane does |
|---|---|---|
| Fork-owned | the file is absent from `upstream/main` (`agent_runtime/`, `hermes_cli/harness*`, fork-only modules and tests) | refactor freely; never conflicts on merge |
| Seams | an upstream file the fork already edits (`gateway/hosted_rooms.py`, `agent/credential_pool.py`, `hermes_cli/auth.py`, `hermes_cli/codex_models.py`, …) | ADDITIVE edits only, one import and one call at a stable point; every sync conflicts here |
| Upstream-owned | an upstream file the fork does not touch | never edited here: a caller-side memo or seam on our side, a marker, or an upstream issue/PR |

Rows below were moved verbatim from the launcher queue on 2026-09-22 (their provenance headings are kept as sub-headings). Fork-hygiene findings the launcher queue carried (CI, the suite, the mutation gate, upstream reds) went to [[fork-hygiene-queue]] in the same commit.

## Fork-owned

### Filed on arrival — 2026-10-16 (lane r-realm-lens, branch `q/r-realm-lens`)

- **`RT-LENS-L1-LIVE-PROOF` — Lens L1 has no live proof: a real HTTP feed polled by a running serve, an Episode raised, and the stored evidence row read back redacted** · fork / runtime · r-realm-lens `13cf04f76fa` (no serve started) · BLOCKED 2026-10-16: owner sitting — live: needs an operator serve with `plugins/eternia-lens` shipped

- **`RT-LENS-FOLD-RIDES-METHOD` — The Lens fold rides the method lane only (`runtime.lens.fold`); carrying it on the push-lane snapshot is a new top-level key in `agent_runtime/snapshot/sections.py` plus a regen of the cross-stack `tests/fixtures/stream_frames/` — do it in the same sitting as the launcher's fold painter** · fork / lens + snapshot · `agent_runtime/lens/snapshot_fold.py` docstring; launcher `mission-control-queue.md` L1 fold row · hermes moves first, launcher consumes · READY 2026-10-18 · RULED 2026-10-18: one top-level `lens` snapshot section, landed in the same sitting as the launcher's fold painter (owner)

### Filed on arrival — 2026-10-16 (build lane h-bundle-speed, branch `build/h-bundle-speed`)


### Filed on arrival — 2026-10-16 (build lane h3-runser, branch `build/h3-runser`)

- **`RT-POSIX-TURNS-SERIALIZE-BEHIND` — POSIX turns still serialize behind one process lock: the fork writes `HOME` per profile turn because upstream's in-process `expanduser`/`Path.home()` readers have no context hook** · upstream door (run-serialization decision 3) · `agent_runtime/profile_context.py::persona_profile_context` (the `HOME` write and its pinned-readers comment) · draft the one upstream door for a context-aware home hook (`~` in `skills.external_dirs`, the `~/.codex` / `~/.qwen` credential files); once it lands, delete `_PROCESS_HOME_LOCK` on the h3-runser branch and POSIX gets per-root turns like Windows · BLOCKED 2026-10-18: upstream — issue text: "`os.path.expanduser`/`Path.home()` readers (`~` in `skills.external_dirs`, the `~/.codex` / `~/.qwen` credential files) take no home hook, so an embedder serving several profiles in one process must write `HOME` and serialise turns; add one context-aware home resolver those readers call" · no fork-owned caller to memo (the readers are upstream)
- **`RT-SETTLE-PUSH-LIVE-PROOF` — CLI route S4's push half is unproven live: a re-armed settle was due but no listener was attached, so no delivery was observed** · fork / RPC lane · `hermes_cli/harness_parts/serve/settle_push.py::SettlePush._push_due_settles` · with a launcher (or a `harness stream` client) attached, re-arm an undelivered settle from a shell and record the pushed frame and the ack · BLOCKED 2026-10-16: owner sitting — live serve; needs a running serve with a launcher or `harness stream` listener attached (r-turnrec may not start one)

### Filed on arrival — 2026-10-16 (build lane h1-lineage)


### Filed on arrival — 2026-10-16 (build lane h4-seeds)

### Filed on arrival — 2026-10-16 (release merge v0.22.2, daily branch at upstream acc3cada0da)

- **`RT-LIVE-PROFILE-VAULT-ALIASES` — Owner, optional: the live profile `config.yaml` still lists the five pre-fold `browser_vault_*` tool names in its chat-lane defer list; they work only through the `_FOLDED_TOOL_NAMES` alias in `agent_runtime/config/knobs.py::chat_lane_defer_tools`** · fork-owned · q/vault lane `f522492a3b3` · replace them with `browser_vault`, then the alias can be dropped at a later release · BLOCKED 2026-10-16: owner sitting — edit the live profile `config.yaml` chat-lane defer list on the Windows box



### Filed on arrival — 2026-10-15 (launcher lane w1015i-mc)


### Filed on arrival — 2026-10-15 (orchestrator: QA bundle build under load)


### Filed on arrival — 2026-10-15 (owner sitting: first real QA bundle build)


### Filed on arrival — 2026-10-15 (owner sitting: send-prep live proof)




- **`RT-CONNECTIONS-TRACE-MISSING` — Connections: trace the missing browser sign-in `done` event for the isolated QA profile.** Owner report/review 2026-10-14: ChatGPT or Codex Subscription web sign-in completed, but the login-stream `done` event did not reach the Launcher and the pane remained pending; the selected isolated profile subsequently had a credential entry and canonical `logged_in=true`. Root cause is unproven: no historical completion frame was captured. Start at producer `hermes_cli/provider_browser_login.py::run_browser_login` (`send` of `done`), trace `agent_runtime/serve_rpc/provider_signin.py` and the consumer `EterniaLauncher/lib/shared/provider_connections/provider_connection_state.dart::ProviderSetupController` under the same profile; capture redacted lifecycle/transport evidence and pin reliable terminal delivery. The Launcher projection reconciliation on `fix/sol-connect-20261014` is a safety net, not the root-cause fix. Preserve the QA binding; never capture credentials or account identifiers. · fork / launcher seam · found 2026-10-14 sol-connect review · code read 2026-10-15: run_browser_login sends done only after _save_codex_tokens returns, ProviderSignIns._pump folds it only while the session is ACTIVE, and the registry lives in one serve process, so a serve restart between the credential write and the next poll answers login_not_found to a pane still pending · BLOCKED 2026-10-16: owner sitting — one live ChatGPT/Codex browser sign-in on the isolated QA profile (Windows box), capturing the poll replies and the serve pid

### Filed on arrival — 2026-10-15 (lane w1015h-prov)


### Filed on arrival — 2026-10-15 (launcher lane w1015h-misc-l)


### Filed on arrival — 2026-10-15 (launcher lane w1015h-mc-l)


### Filed on arrival — 2026-10-15 (lane w1015h-comp-l)


### Filed on arrival — 2026-10-15 (lane live-qa)

- **`RT-QA-REUSE-PHANTOM-INSTANCE` — Asked "is there an existing QA session I can reuse to take a Launcher screenshot?", Base answered "Yes" and named instance `personainst_qa_cf20b758ee50`, which is not on the roster (the roster has `personainst_qa`), from four `session_search` calls and no roster/state receipt, and offered reuse instead of a fresh QA instance per task** — the F4/F5 failure of `EterniaLauncher/docs/mission_control/SIX_SCREENSHOT_FINDINGS_2026-10-01.md` reproduced after HQ1/HQ2; the answer should come from the first-class roster/instance detail with its hot/cold state, and an id built from a chat-root suffix must never be offered as an instance · fork / harness-runtime-model skill guidance + `session_search` · evidence: QA home `profiles/base/logs/agent.log` 07:20:53–07:21:13 (2026-10-15, chat `persona_chat_personainst_profile_base_c79130b80c0e`, tool_turns=9); launcher capture `b4-p2-qa-reuse_20261015072114768.png` · launcher row: mission-control-queue "P2 — Investigate Agent Console response/workflow acceptance" · guidance + harness_query schema steer landed bd2ddc962a7 (session_search is history not state, no id cut from a chat root, fresh instance per QA task) · BLOCKED 2026-10-18: launcher — `MC-P2-CONSOLE-WORKFLOW` (itself BLOCKED owner sitting) · mission-control-queue "P2 — Investigate Agent Console response/workflow acceptance" re-runs the prompt on a Base chat against a live serve

### Filed on arrival — 2026-10-15 (lane w1015h-rt-h)

### Filed on arrival — 2026-10-15 (audit lane a1015-hrt)


### Filed on arrival — 2026-10-15 (lane w1015b-rt-h)


### Filed on arrival — 2026-10-14 (Console execution controls)





### Filed on arrival — 2026-10-12 (composer thinking meter)


### Filed on arrival — 2026-10-11 (lane h-s17, one-action-layer S17)

- **`RT-R10-ENTRY-ID-GATE` — The R10 entry-id gate (landing from lane h-s17, `tests/tooling/`) sees only the dotted spelling `launcher.<area>.<verb>`; the Launcher's tool-name spelling of the same id (`launcher_<area>_<verb>`, from `appFunctionToolName`) walks through.** Live instance: an incident comment in `tools/tool_search_downstream.py` names `launcher_generated_list`. A naive `launcher_\w+` pattern would flag fork module names (`launcher_app_functions`, `launcher_client_requests`), so the answer is a typed name rule (tool names derived from the listed entry only, or a shared name-shape the gate can enumerate), not a wider regex. Plan: `EterniaLauncher/docs/embedded_hermes/subsystems/ONE_ACTION_LAYER_2026-10-10.md` R10. · fork · no in-tree enumeration of Launcher tool names exists (the 11 `launcher_<a>_<b>` tokens in fork source are module, ContextVar and dict-key names) · NEEDS PLAN 2026-10-18: the vendored `launcher.app_functions.list` fixture the gate enumerates from — where it lives, who refreshes it from the Launcher, and how drift reds (tree unchanged: `AppFunctionEntry.parse` takes each tool name from the Launcher's `name`; hermes derives none)

### Verified Console history PR #7 follow-up — 2026-10-11





### Filed on arrival — 2026-10-10 (D2.07 redesign, filed by the orchestrator)


### Filed on arrival — 2026-10-10 (guard fix, build batch 2 C1–C4, filed by the orchestrator)

- **`RT-BOARD-CARD-FOLD-RUNTIME` — board_card fold: the `runtime.board.*` twins ack but publish no fold; a fold needs its producer inside `board_lock` (board-surface-rpc-lane.md rule 3)** · fork / board · `agent_runtime/serve_rpc/board.py` (build-1011-C4) · plan `docs/agent-runtime-harness/planned/board-card-fold-2026-10-15.md` approved by owner 2026-10-15 · BLOCKED 2026-10-16: owner sitting — S0 live end-to-end timing (ack → full core → Launcher repaint) on a running serve + Launcher, Windows box; S1–S4 gate on its number

### Filed on arrival — 2026-10-10 (build batch 1, build-1011-B1..B5, filed by the orchestrator)


### Filed on arrival — 2026-10-10 (Fable design sweep D1–D3, filed by the orchestrator)

- **`RT-PROVIDER-REQUEST-START` — Provider request-start evidence is recorded at agent-ready rather than transport dispatch.** `hermes_cli/harness_parts/persona/chat_turn_commit/run.py::_agent_ready_for_steer` sets `provider_request_started` before conversation prompt assembly and transport; generic failures in that gap still lack proof of whether a request left Hermes. Bind dispatch evidence to the actual transport boundary while preserving uncertainty for ambiguous executions; sol-prov separately fixes positively identified local provider refusals. · fork / chat outcome evidence · found 2026-10-14 sol-prov · transport-boundary evidence exists (`provider_request_dispatched` from the `conversation_request_sent` marker, d382d9ee645; the emitter's first byte, 8764e5edb4d); reading its absence as "not sent" first needs proof that it fires on every provider path (non-stream/argv lanes, every transport) · measured 2026-10-16 r-turnrec: it does NOT — `request_sent` is hooked on the Anthropic checkout, the Codex stream open and (r-turnrec) the OpenAI-SDK request-client checkout (chat completions, stream and non-stream); Bedrock (boto3) and the Codex app-server (a subprocess) carry no hook, so absence stays ambiguous there · BLOCKED 2026-10-16: owner decision — may a generic failure on a HOOKED transport with no `request_sent` settle `chat_turn_not_submitted` (retry the same id), given a fallback client without the hook could have sent? · Recommend: yes, keyed on a per-attempt "hooked" fact recorded by `install_transport_phase_trace`, never on the absence alone
- **`RT-REALM-DOCUMENT-FAMILY` — Two whole-document realm-sync appliers are one module twice (`level_sync.py`, `map_sync.py`); a third family would be a third copy — class answer `realm_sync/document_family.py`** · fork / realm sync · design-sweep-d2 § D2.12 · the level/map MOVE onto `realm_sync/document_family.py` is a dedicated MOVE lane · READY 2026-10-18: the launcher bind it waited on (`OFFICE-PREFAB-STORE-BIND`) is built, launcher `97300ad929`; only that row's QA step 5 remains · **TAKEN 2026-10-18 w2-realm**

### Filed on arrival — 2026-10-10 (fork-fixable sweep lane-1011, filed by the orchestrator)


### Filed on arrival — 2026-10-10 (queue sweep lane-1010, filed by the orchestrator)


### Filed on arrival — 2026-10-10 (release merge v0.21.6 reds)


### Filed on arrival — 2026-10-09 (owner report: "this chat I cannot delete")

### Filed on arrival — 2026-10-09 (owner report: Agent Console silent after the toolvis 1b landing)

### Filed on arrival — 2026-10-08 (launcher lane opus-qa-hygiene)

### Filed on arrival — 2026-10-08 (gateway restart after a live-checkout fast-forward)
- **`RT-GATEWAY-START-MANAGED-PYTHON` — `hermes --profile alice gateway start` raises `ManagedPythonUnavailable` ("no Hermes virtualenv found") even when run by the managed venv's own interpreter (the managed venv's `Scripts/python.exe -m hermes_cli.main`), while `hermes_cli.gateway._detect_venv_dir()` in that same interpreter returns the venv; `gateway restart` drained the gateway and then could not bring it back, so the operator is left with no gateway. Cause unproven — read the `gateway_windows.start` → `_spawn_detached` → `_launcher_settings` path for a re-exec or an env scrub before `resolve_managed_python`. Worked around with a detached `gateway run`.** · fork / gateway service (Windows) · `hermes_cli/gateway_windows.py::_launcher_settings`, `hermes_cli/gateway_downstream.py::resolve_managed_python` · evidence: 2026-10-08 ~21:55 restart, alice `gateway.log` (stopped 21:54:58, manual run up 21:58:16). Also seen: the shell's PATH `hermes` resolved to a leftover test shim `/tmp/rb7-identity-flip-559b6bbd/hermes/bin/hermes` · read 2026-10-15: resolve_managed_python sees only sys.prefix, VIRTUAL_ENV and <checkout>/.venv|venv, and the launcher venv sits outside the checkout, so any interpreter whose sys.prefix is not that venv raises · BLOCKED 2026-10-16: owner sitting — the failing traceback from a live `gateway start` on the Windows box

### Filed on arrival — 2026-10-08 (owner ask: capability vs. cost-trim quietness, Neko QA-build turn)

### Filed on arrival — 2026-10-08 (warm send-prep integration review, `196ec6159d`)
- **`RT-FIRST-TURN-BOOT-LATENCY` — The first turn after boot is 770 ms and the first after 105 s idle is 441 ms, against a warm 259.5 ms, with the actor prewarmed and reused; re-take each (n=1) and attribute by phase against the warm table** · runtime / turn latency · evidence: [Integrated receipts](../../docs/agent-runtime-harness/planned/warm-prep-integration-2026-10-08.md) · BLOCKED 2026-10-16: owner sitting — the n=1 re-takes on the owner's live serve (Windows box)
- **`RT-WARM-MEDIAN-LIVE-PROOF` — OWED live proof: the 259.5 ms warm median is a reference-client number on a fresh history at `a43466214c`; re-take warm/cold/idle on the post-relay head through the Launcher route (capability bridge, `[MissionChatTiming]` spans joined) and on a real long history (H8)** · runtime + launcher / live proof · evidence: [Integrated receipts](../../docs/agent-runtime-harness/planned/warm-prep-integration-2026-10-08.md) · covers send-prep H8 (history cloning, sanitization and token estimation on real-sized histories) · BLOCKED 2026-10-16: owner sitting — warm/cold/idle turns through the Launcher route on a real long history (Windows box)
- **`RT-SEND-PREP-H2-H6` — Send-prep H2 + H6 UNRESOLVED: skill preload (65–95 ms historically on Dev) and package stamps/preload checks did not reproduce on the fresh Neko route; re-measure on a skill-heavy persona using the existing `context_skill_preload_ms` receipts before changing either** · runtime / measured send-prep · `agent_runtime/skill_resolution.py`, `skills_context.py` · evidence: [Integrated receipts](../../docs/agent-runtime-harness/planned/warm-prep-integration-2026-10-08.md) · H2 reproduces on Dev (`context_skill_preload_ms` median 73; the cost sits in upstream `agent/skill_commands.py::build_preloaded_skills_prompt`/`skill_view`); H6 2–5 ms, below the bar (`docs/agent-runtime-harness/planned/warm-prep-integration-2026-10-08.md` § Attribution pass; design-sweep-d1 § D1.10) · RULED 2026-10-10 owner: WAIT on the upstream frontmatter-in-result door (no six-input memo) · BLOCKED 2026-10-16: upstream — the frontmatter-in-result door (`docs/agent-runtime-harness/planned/skill-catalog-doors-2026-10-15.md`)
- **`RT-SEND-PREP-H7-UNRESOLVED` — Send-prep H7 UNRESOLVED: request build is 47–50 ms per warm turn and is broader than the web-search lookup (separate row); split it with the existing `profile_conversation_request_*_ms` parts and name what kwargs / tool-JSON work remains, keeping the final wire-tool receipt** · runtime / measured send-prep · `agent/transports/codex.py::ResponsesApiTransport.build_kwargs`, `capture_final_request_tools` · evidence: [Integrated receipts](../../docs/agent-runtime-harness/planned/warm-prep-integration-2026-10-08.md) · split on Neko n=8: request build 48 = kwargs 41 + middleware 4 + preflight 1; kwargs is upstream `ResponsesApiTransport.build_kwargs`, its fixture-confirmed share is the web-search selection (`docs/agent-runtime-harness/planned/warm-prep-integration-2026-10-08.md` § Attribution pass; design-sweep-d1 § D1.11) · RULED 2026-10-15 owner: wait for the upstream web-search fix, no short cache · BLOCKED 2026-10-16: upstream — `RT-REQUEST-BUILT-RESOLVES-WEB`, the active-search-provider fix (Seams row "request_built resolves every web-search provider's availability")

### Filed on arrival — 2026-10-08 (GenUI comparison turn audit, Amelia turn `agent-chat-send-db7a2d34-731b-4cc8-bc0b-d00b7394f753`)

- **`RT-ALWAYS-HARNESS-SKILLS-PAID` — The always-on harness skills are paid per turn through `skill_view` instead of once in the cached prefix: Amelia turn `agent-chat-send-db7a2d34` (2026-10-08) read `harness-dev-delivery` (13.7 KB) and `harness-runtime-model` (18 KB, frontmatter `load_policy: required_preload`) by tool, and the relay receipt shows `required_preload_skills: []` — `required_preload_skill_ids` filters the persona's OWN assigned identifiers by surface, and nothing is assigned, so the mechanism never fires. Owner ruling owed: which skills each harness persona preloads, then assign them (persona config, not code) and compress their bodies to short operational rules per the 2026-10-08 plan; a preloaded skill `skill_view` re-reads should answer "already in your prompt" cheaply.** · fork / `agent_runtime/mission_chat_turn_context.py::_required_preload_skills`, `agent_runtime/skill_resolution.required_preload_skill_ids`, persona skill assignment · filed by lane host-guidance 2026-10-08 · RULED 2026-10-10 owner: skills load on demand by default; each persona preloads at most its top one or two · RULED 2026-10-15 owner: Launcher Dev and Backend Dev preload the delivery contract; Neko and Base preload the runtime model; everything else loads on demand · the preload half landed 6d7938ce1ab; the "preloaded skill_view re-read answers cheaply" half is upstream `tools/skills_tool.py` · BLOCKED 2026-10-18: upstream — issue text: "`tools/skills_tool.skill_view` re-reads and returns a skill body the system prompt already carries; let the preloaded-skill set answer `skill_view` with a one-line 'already in your prompt'" · the fork does not own `skill_view`'s caller (the model calls the tool); preload half on main 6d7938ce1ab
- 2026-10-08 evidence for the GenUI selection row below: with the eager pair delivered (runtime `94043a1a42`, listing `26 core/visible tools kept, 18 deferred` at 13:23:09), the first-response path still did not call `launcher_generated_list` directly — the turn loaded five skills (`launcher-generated-ui`, `harness-dev-delivery`, `harness-continuity`, `harness-runtime-model`, one not found; ~44 KB of skill text), searched, described, queried the roster, took the wrong door, then relayed to a peer and burned the rest of the 240 s on the deadlock row above. The profile-local skill is a second copy of the tool contract (it says "discover with `launcher_generated_list`" without saying it is direct); F2 of the launcher audit stands.


### Filed on arrival — 2026-10-07 (GenUI selection audit)




- **`RT-VERIFY-IMPROVE-FIRST-RESPONSE` — Verify and improve first-response selection of existing Launcher generated-content tools for ordinary comparison requests.** · fork / `tools/tool_search_downstream.py::never_defer_tool_names`, `agent_runtime/launcher_app_functions.py` · observed Amelia turn `agent-chat-send-1f241d5d-e572-488c-987c-c75b55155963` (2026-10-07 23:27:12Z) loaded `hermes-agent` and returned Markdown; the correction turn searched successfully for all five generated tools, and `agent-chat-send-19bd6f54-a744-427c-9e5f-aaa82eb30d44` successfully listed/created native Composition/Text. Its model-input receipt (`ctx_bc3da2d48efa6016`, `final_model_input.tool_schema.final_model_tools`) offers 27 direct tools and keeps generated tools behind discovery; the quoted workflow resolves as profile-local `launcher-generated-ui`, with no required preload. This demonstrates a selection failure, not a missing bridge or a proven sole cause. Evaluate direct exposure of existing discovery/create tools and shared capability guidance without duplicating the Launcher catalog/dispatcher, granting tools to unlinked sessions, changing permissions, or mutating an active conversation's cached prefix. Prove ordinary-language selection across agents; retain exact refusal handling and measure prompt cost. Launcher owner: `EterniaLauncher/lib/core/services/hermes/runtime/data/capabilities/harness_generated_capabilities.dart`. · delivery landed 2026-10-08 (host-owned opt-in for list/create; [Qualification](../../docs/downstream/genui-discovery-qualification-2026-10-08.md)) · live 2026-10-15 (QA serve 7e24ded80e, Base): still fails — plain Markdown, tool_turns=0, with all five generated tools declared alwaysLoaded by the Launcher, so the miss is the model choosing Markdown with the tools in view · NEEDS PLAN 2026-10-18: the A/B eval's prompt set and pass bar on the owner's QA serve; the comparison WHEN line lands in the Launcher's guidance first — [proposal §1](../../docs/agent-runtime-harness/planned/agent-behaviour-proposals-2026-10-18.md)

### Filed on arrival — 2026-10-07 (native turn anchor carrier)


### Filed on arrival — 2026-10-07 (latency source recheck)



### Filed on arrival — 2026-10-06 (lane h-slim-prompt)

- **`RT-AUTH-JSON-TRANSIENT-READ` — `base/auth.json` read failed at a turn's start (`hermes_cli.auth: could not read ...profiles\base\auth.json, leaving the store on disk untouched`, 12:07:05.613) and the credential pool then reported `no available entries (all exhausted or empty)` (12:07:05.269); the launcher showed "openai-codex: this credential needs attention" while codex turns succeeded — a transient read (lock/partial write?) surfaces as a credential fault** · runtime / provider credentials · evidence: agent.log 2026-10-07 12:07:05 + launcher banner screenshot · lane: find the reader racing the writer, make the read atomic/retried, and never raise needs-attention on one failed read · 2026-10-07/2026-10-14: a synthetic auth-reader failure settles typed `provider_unavailable` with disk unchanged; the historical reader/writer race and the needs-attention mapping remain unproved (`docs/agent-runtime-harness/planned/runtime-evidence-wave4-2026-10-07.md`) · RULED 2026-10-15 owner: book a weekly operator sitting on the Windows box and run this check there · BLOCKED 2026-10-16: owner sitting — the weekly Windows-box sitting
- **`RT-PREWARM-HOLDS-WORKDIR-LOCK` — Prewarm still holds _WORKDIR_LOCK through single steps it cannot interrupt (live 20:23:47: system_prompt_build_ms=7855, construct_ms=5318); a turn arriving mid-step waits that step** · runtime / turn latency · evidence: agent.log 2026-10-06 20:23:47 prewarm_first_turn line · lane: move system-prompt build and construction off the lock, or split them into yieldable steps · designed in `docs/agent-runtime-harness/planned/design-sweep-d1-2026-10-10.md` § D1.04 (investigation; the measurement protocol is in the plan) · BLOCKED 2026-10-16: owner sitting — the D1.04 live measurement on the owner's serve (Windows box)
- **`RT-ARGV-STREAM-READERS-LINGER` — The serve keeps `harness stream` argv readers (`caller=cli`) attached long after the launcher settled on its hub lane: four `stream_attach op=harness_stream purpose=cli_stream` at 19:01:43.368 (beside the hub's conn-1 subscribe), two still framing every turn of one chat at 19:03:51 (`turn_section … source=reused caller=cli` x2 per section) and LEADING full `snapshot_build reason=demote caller=cli` cores (1.4–2.2 s, 19:02:14, 19:03:14, 19:03:16, 19:04:11) the hub would otherwise not pay; the launcher holds one hub and zero argv streams by design (`EterniaLauncher/lib/…/mission_stream_lane_lifecycle.dart` `resolveOnGreeting` cancels the argv lane), so either the cancel never reaches the serve's argv stream or the lane was opened after the hub — find which, end the reader with its client** · fork / `hermes_cli/harness_parts/runtime_commands.py::_cmd_stream` + serve argv lanes · evidence: `profiles/base/logs/agent.log` 2026-10-06 19:01:43–19:04:11 (serve 274eb9bb6c, pid 14988), launcher diag `[MissionStream] lane=argv reason=serve_absent` x2 23:00:48Z then `lane=hub` 23:01:42Z; lane h-prep-contention commit body · LIVE 2026-10-15 (QA home): REPRODUCED — four `harness_stream purpose=cli_stream` attaches opened AFTER the hub with no detach, still framing turns with `caller=cli`; no argv process alive, so the readers are serve-side; b931a2de996 names request/connection/max_frames on the attach line and adds a `stream_detach` line · RULED 2026-10-15 owner: book a weekly operator sitting on the Windows box and run this check there · BLOCKED 2026-10-16: owner sitting — one more sighting under the new lines at the weekly Windows-box sitting, naming the connection that never cancelled

### Filed on arrival — 2026-10-06 (lane h-pool-starve)

- **`RT-ATTRIBUTE-RECORDED-FIRST-TURN` — Attribute the recorded first-turn stall before moving post-send work.** · runtime / turn latency · evidence: existing 375 ms stall receipt; `transport_phase_trace.py::phase_trace_for`, `title_upgrade_defer.py`, `skill_root_freshness.py::revalidate_served_roots` · **Action:** after `h-idle-turn`, take stack samples and controlled persistence/title/refresh ablations against the same fast response. Move only work demonstrated to delay response consumption, using existing turn-window/finalization mechanisms. **Done when:** first text improves without worse streaming; persistence remains exactly once and completes before actor reuse; retry, cancellation, no-request and failure paths pass; title fallback survives. Coordinate refresh behavior with `h-idle-turn`, not a competing scheduler. · **No assumed 375 ms saving.** · 2026-10-07: no historical 375 ms attribution; stack/refresh/persistence sample missing (`docs/agent-runtime-harness/planned/runtime-evidence-wave4-2026-10-07.md`) · RULED 2026-10-15 owner: book a weekly operator sitting on the Windows box and run this check there · BLOCKED 2026-10-16: owner sitting — stack samples and ablations at the weekly Windows-box sitting
- **`RT-RESOLVE-TURN-TWO-CACHE` — Resolve the turn-two cache miss from final dispatched requests, not post-turn `agent.tools`.** · runtime / prompt cache · **Prerequisite:** the existing `h-cache-hit` final-wire-tools capture row and tool-pin ownership finding. **Action:** compare turns 1–3’s actual prefix, ordered tools, model/effort, route, cache scope, and session pin; repair only demonstrated unintended drift. **Done when:** deterministic request/pin consistency tests pass and matched live runs report input/cached tokens plus first-text distributions. Distinguish prefix drift from provider-side cache availability. Record hashes/counts, not sensitive prompt bodies or credentials; do not lower permissions, required preloads, or reasoning to meet the target. · 2026-10-07: the R034 final dispatched wire/tools capture is outstanding; no authenticated cache-token distribution (`docs/agent-runtime-harness/planned/runtime-evidence-wave4-2026-10-07.md`) · RULED 2026-10-15 owner: book a weekly operator sitting on the Windows box and run this check there · BLOCKED 2026-10-16: owner sitting — matched live runs at the weekly Windows-box sitting

### Filed on arrival — 2026-10-06 (lane h-send-window)


### Filed on arrival — 2026-10-06 (lane h-turn1-conn)


### Filed on arrival — 2026-10-06 (lane h-turn1-again)


### Filed on arrival — 2026-10-06 (lane h-model-pick)


### Filed on arrival — 2026-10-06 (lane h-newchat-t1)


### Filed on arrival — 2026-10-06 (lane h-cache-hit)


### Filed on arrival — 2026-10-06 (lane h-conn-pool)

- **`RT-TURN1-WARM-CONNECTION` — Re-read turn 1 on the next prewarmed Neko chat after h-conn-pool lands: the pre-connect now warms the turn's own request client and the default config already shares one pool (offline + real-edge probe: turn 0 rides the HEAD's connection), so a turn-1 `tls_done` there means something else took or killed the warm connection between prewarm and turn — read `tls_done`, `client_built→request_sent` and `prewarm_first_turn_warmup_ms`** · fork / chat turn · evidence: lane h-conn-pool `3b0cbc20ab` body · LIVE 2026-10-15 (QA serve 7e24ded80e): every turn's api:1 is `conn=new` while api:2+ reuse — the 20 s `keepalive_expiry` reap (`agent/process_bootstrap.py`) that `agent_runtime/idle_turn_keeper.py` prevents, and the keeper does not arm with resident chats off (row "A serve with resident chats off…", RULED 2026-10-16) · BLOCKED 2026-10-16: owner sitting — turn-1 stamps on a prewarmed Neko chat after the keeper change lands (Windows box)

### Filed on arrival — 2026-10-06 (lane h-readiness)


### Filed on arrival — 2026-10-06 (lane h-snapshot-offproc)


### Filed on arrival — 2026-10-05 (lane h-prompt-design; h-turn1-c)

- **`RT-LEAN-OPERATIVE-RULES` — With `lean_operative_rules` on, the threading and `clarify_token` rules reach the agent only through `agent_chat_send`'s describe doc, and an eager tool is rarely described; the R4 A/B must check one teammate clarify answer goes back on its `clarify_token`, or the bullets move into `harness-mission-lead` (operator-home skill)** · fork / chat lane · evidence: lane h-prompt-surface `ba499069be` · lane: R4 A/B · BLOCKED 2026-10-16: owner sitting — the R4 A/B (ten live turns, flag on) on the owner's serve; the clarify-token check rides it

### Filed on arrival — 2026-10-05 (launcher lane docs-dev, filed by the orchestrator)


### Filed on arrival — 2026-10-05 (lane h-turn1-c1-design)


### Filed on arrival — 2026-10-05 (launcher lane console-1a, filed by the orchestrator)


### Filed on arrival — 2026-10-05 (owner live turns, "turns still feel slow")




- **`RT-REMOVE-H-TURN1-A5` — Remove the h-turn1 A5 stamps from upstream `agent/turn_api_request.py` (8 lines marked `# fork seam: h-turn1 A5`) once the first-turn `build_api_request` cost is fixed — owner kept them 2026-10-05 as a TEMPORARY diagnostic against the 2026-09-29 DOORS-A ruling (`bfee7eb896`); the file returns to upstream bytes and the footprint fixture drops by one** · seam / `agent/turn_api_request.py` · evidence: `lane/h-turn1-tail` `4b49ff114b` · the cost row was folded into this one at 11dedd066f6; the 8 stamp lines are still in `agent/turn_api_request.py` · BLOCKED 2026-10-16: owner sitting — a live first-turn read of the A5 stamps on the owner's serve

- **`RT-CHAT-TURN-22K-TOKENS` — Every chat turn ships ~22k input tokens: Neko "hi" read `in=21957` (tool_search tier 1: 28 core/visible tools kept, 51 deferred, deferred listing ~20,232 tokens); the provider's send→first-text leg is 1.4–2.2 s on a 12-token reply. Measure what the 22k is made of (system prompt, tool schemas, deferred listing, skills) and what a smaller first-turn surface would cost the agent** · fork / prompt surface · evidence: neko `agent.log` 2026-10-05 19:16:28 `API call #1 … in=21957`; plan `plan/h-prompt-design` `0d71896c74` (R1–R5 taken 2026-10-05; owner amends R1: only the five `browser_vault_*` tools are deferred) · landed 2026-10-06 hermes `f779903ba7` (S0–S3, S6, S4 behind `agent_runtime.mission_chat.lean_operative_rules`) · BLOCKED 2026-10-16: owner sitting — the next live first turn's S0 per-part receipt, `cache=` on a second chat, and the R4 A/B (10 turns, flag on)





- **`RT-QUEUE-COMMIT-SERVE-RESTART` — A queue-only commit on the primary checkout restarts the live serve and stalls the Launcher ~27 s: each of three docs-only commits (`fb5a186264`, `0ed627cea0`, `4adeb0f116`) was followed by a drain whose old serve never proved an exit inside 20 s (`serve_drain proven=no polls=13–14 waited_ms=20503/20848`, pids 28592, 28456), opens deferred behind it (`serve_spawn_deferred reason=drain_in_flight` up to 19,844 ms), an open answered at `+26817 ms`, then a 15.4 s first snapshot build; the code identity should ignore commits that touch no shipped code, and the drain should end the old serve inside its budget** · fork / serve lifecycle (the restart door is the Launcher's `MissionServe`; file its half in `mission-control-queue.md` once this side says what the identity covers) · evidence: base `agent.log` 14:54:08.535 `home maintenance: code changed to 4adeb0f116d1`; `%TEMP%\eternia_launcher_diag.log` 18:48:10 / 18:54:00 / 18:54:15 `MissionServe`/`MissionOpenChat` lines · **LANDED 2026-10-05 hermes `c87f8ed59e` + launcher `0d377ec6b3` (D1–D4); OWED live proof: a vault-only commit on the primary draws no `[MissionServe] drain`, and the next real restart logs `serve_drain proven=yes`.** · BLOCKED 2026-10-16: owner sitting — on the owner's primary checkout, a vault-only commit draws no `[MissionServe] drain` and the next real restart logs `serve_drain proven=yes`


### Filed on arrival — 2026-10-05 (owner screenshot, "screenshot posts" 13:05)


### Filed on arrival — 2026-10-05 (lane hb-c)


### Filed on arrival — 2026-10-04 (launcher lane console-boundaries, filed by the orchestrator)


### Filed on arrival — 2026-10-04 (owner design: builds as first-class background work)



### Filed on arrival — 2026-10-03 (lane h-wakecap)


### Filed on arrival — 2026-10-03 (resident identity audit)


### Filed on arrival — 2026-10-03 (lane h-fence)


### Filed on arrival — 2026-10-03 (launcher lane fx-mc2, filed by the orchestrator)

- **`RT-HARNESS-SERVE-COLD-BOOT` — `harness serve` cold boot dominates Mission Control's first open: total_ms 21592, interpreter_ms 15203 (interpreter_boot 5196, main_import 4016, dispatch 5991) on a disk-cold QA seed, 2026-10-03 — profile and cut the import/dispatch path** · `hermes_cli/harness_parts/serve/boot.py` · launcher fx-mc2 · designed in `docs/agent-runtime-harness/planned/design-sweep-d1-2026-10-10.md` § D1.06 (investigation) · BLOCKED 2026-10-16: owner sitting — the D1.06 protocol on a disk-cold QA seed on the owner's machine

### Filed on arrival — 2026-10-02 (launcher lane mc-a, filed by the orchestrator)


### Filed on arrival — 2026-10-02 (launcher lane mc-pidx, filed by the orchestrator)


### Filed on arrival — 2026-10-02 (launcher lane w12-qa, filed by the orchestrator)


### Owner asks — 2026-10-02 (long tool calls)

- **`RT-LONG-TOOL-CALLS-BACKGROUND` — DESIGN — long tool calls move to the background (owner ask 2026-10-02: "what would be good agent UX"). Proposed: a call that passes a threshold (~30–60 s, or a tool that declares itself long-running) is promoted to running_work / Background Work; the agent gets an immediate "running in background" result with a handle and may keep talking; the operator may keep chatting; on completion the final result is delivered to the agent as a new event that wakes the turn; running cards offer Send to background and Cancel. Write the design (turn/await semantics, how the result re-enters the conversation, upstream vs fork seams, what the console renders) for the owner to approve before any build** · `fork / runtime` · launcher Background Work panel · RULED 2026-10-10 owner: parked: the design is approved before any build · Recommend: approve the design (promote past a declared `long_running` or 45 s to a synthetic `running_in_background` result, re-enter as a `tool_call_finished` fork completion event, Send to background / Cancel on the running card) — [proposal §2](../../docs/agent-runtime-harness/planned/agent-behaviour-proposals-2026-10-18.md) · RULED 2026-10-18: owner — the written design is approved (promote past a declared `long_running` or 45 s; Send to background / Cancel on the running card) · READY 2026-10-18 · **TAKEN 2026-10-18 w2-turn**

### Filed on arrival — 2026-10-02 (lane w10-hr, filed by the orchestrator)


### Filed on arrival — 2026-10-02 (owner screenshot: QA turn ended silent; filed by the orchestrator)


### Filed on arrival — 2026-10-02 (launcher lane w10-pkg, bundled Hermes on macOS/Linux; moved here by the orchestrator)


### Filed on arrival — 2026-10-02 (lane w10-s7h, Stage 7 hermes half)


### Owner asks — 2026-10-02 (agent chat is ONE surface; filed by the launcher orchestrator)

- The launcher half of the same ruling (the Agent Console becomes the one chat widget, rendered with Intelligence's materials; `EterniaLauncher/docs/companion/planned/AGENT_CHAT_UNIFICATION_AUDIT_2026-10-02.md`) changes NO hermes method: `runtime.chat.*` and `perform_chat_turn` are the surviving chat lane; the `tui_gateway` worker is the lane that goes. Work on the worker's lifecycle beyond keeping it alive until the cutover is upstream work (the cold-start hello carry under Upstream-owned), not cutover work.

### Filed on arrival — 2026-10-02 (orchestrator, live MCP check)


### Filed on arrival — 2026-10-02 (launcher lane w5-mc, filed by the orchestrator)


### Owner asks — 2026-10-01 (instance conversations)

- **`RT-INSTANCE-CONVERSATION-CUTOVER` — Instance-conversation cutover remainder:** qualify rich input/activity, recovery and live latency before retiring the profile worker; identity/account/directory/inspection foundation lands separately. · `fork / runtime` · [Plan](../../docs/agent-runtime-harness/planned/instance-conversations-2026-10-01.md#foundation-landing-boundary-october-2) · designed in `docs/agent-runtime-harness/planned/design-sweep-d2-2026-10-10.md` § D2.08 (the instance-conversations plan owns it) · BLOCKED 2026-10-16: owner sitting — the qualification's live latency half on the owner's serve

### Owner asks — 2026-10-01 (Eternia Lens in hermes)

- **`RT-ETERNIA-LENS-L2-L4` — Eternia Lens L2–L4 (exit door, push door, pull door): L0 + L1 are built (branch `q/r-realm-lens`, lane r-realm-lens 2026-10-16); next is L2 — `trigger`, `artifacts`, `tool` opening block, daily cap, pause, receipts, `runtime.lens.receipt`** · `fork / runtime` · plan [eternia-lens-in-hermes.md](../../docs/agent-runtime-harness/planned/eternia-lens-in-hermes.md) §5 and the cut `docs/agent-runtime-harness/planned/eternia-lens-program-cut-2026-10-15.md` (one lane per stage, sequential) · launcher half: `EterniaLauncher/Launcher_Brain/20 — Active Initiatives/mission-control-queue.md` (the L1 fold row) · RULED 2026-10-02 owner (plan §6, all four) · NEEDS PLAN 2026-10-18: L2 forge target and shape — `persona_id: null` has no hermes-side "selected persona", which thread, the `requested_by` provenance prefix, artifacts via MEDIA declarations, W9 per-turn tool admission, notify semantics, the forge worker — plan §5a (L0 remainder landed on `q/r-lens`)


### Filed on arrival — 2026-10-01 (lane w3-turn)


### Filed on arrival — 2026-10-01 (launcher lane mc-a, filed by the orchestrator)


### Filed on arrival — 2026-10-01 (lane hq-b)




### Filed on arrival — 2026-09-30 (moved from the launcher spatial queue, owner rulings)

- **`RT-REALM-SYNCED-LEVEL-REVERT` — A realm-synced LEVEL has no revert arm, so `realm sync status` reports it and the operator cannot act on it** · `hermes-agent` · raised 2026-09-10 by lane H while landing the `level` family, and deliberately scoped out with the reason measured rather than judged. `realm_revert` subscripts `_PROCESS_ORDER[row.family]` directly and dispatches on family for the upstream lookup, the baseline and the store door, so a `store_drift` family added without a revert arm hands `revert --all` a `KeyError` — which is the reason `_flow_graph_status_row`'s own docstring gives for why the CANVAS was not a drift family until its revert arm landed. So the level family ships with a top-level `levels` status row (`publishable`/`unpublished`/`held`/`refused`) and NO drift rows, pinned by `test_the_level_family_is_not_a_store_drift_family` so a later lane has to make the decision rather than inherit it. The work is the arm: a `DRIFT_FAMILY_LEVEL`, a `_PROCESS_ORDER` entry, and the three dispatch sites in `realm_revert.py` · hermes `agent_runtime/realm_sync.py` (`_level_status_row`), `agent_runtime/realm_revert.py`, `agent_runtime/level_sync.py` · moved from the launcher spatial queue 2026-09-30 by owner ruling (`EterniaLauncher/docs/spatial/subsystems/SPATIAL_QUEUE_RULINGS_2026-09-30.md` §C) · RULED 2026-10-10 owner: fold the `levels` status row into `store_drift` (one count) · plan `docs/agent-runtime-harness/planned/realm-level-revert-arm-2026-10-15.md` approved 2026-10-15; S1 family table + S2 level drift rows/arm landed with `build/h4-seeds` (28593ecc42d) · BLOCKED 2026-10-18: owner sitting — the live proof (edit a level, status, revert) on the owner's machine; S3 landed in the launcher (`897e70756a`, its row closed by `15b6c4d2b4`); S4 deletes the old `levels` key one release after S3
- **`RT-REALM-SYNC-REVERT-TAKES` — Realm sync revert takes a very long time (owner report 2026-09-30): measure where a revert spends its time — per-artifact git fetch/checkout, serial HTTP round-trips, a full re-sync after the revert — and cut it; a revert should feel instant next to the sync that produced it** · `hermes-agent` · `agent_runtime/realm_revert.py` · the launcher surfaces it through Mission Control's realm sync controls; no timing has been taken yet · measured 2026-10-02: the argv call paid 5.7–9.2 s of CLI cold start; `runtime.realm.sync.revert` is on the method lane (h-twins) and the launcher binds it method-first (`lib/features/mission_control/sync/realm_sync_method_lane.dart`) · BLOCKED 2026-10-16: owner sitting — time `revert_realm_sync` in-serve on a real realm with the operator's sign-in
- **`RT-USER-PREFABS-TRAVEL-RUNTIME` — User prefabs do not travel: `runtime.prefab.*` (`agent_runtime/prefab_store.py`, store/prefabs/<profile>/) is install-local; add the realm-sync family beside `map_sync` (publish scan, pull applier adopt/keep/HOLD, baseline, status counts) so a profile's shelf follows it across machines** · `hermes-agent` · store + verbs landed by w5-rt 2026-10-02; the launcher binds its `UserPrefabStore` to the verbs first (launcher row) · designed in `docs/agent-runtime-harness/planned/design-sweep-d2-2026-10-10.md` § D2.12 (`realm_sync/document_family.py`, level/map MOVE, prefab = one descriptor) · READY 2026-10-18: the launcher bind (`OFFICE-PREFAB-STORE-BIND`) is built, launcher `97300ad929` (`HermesUserPrefabStore` bound in `spatialAppOverrides()`); only that row's QA step 5 remains · **TAKEN 2026-10-18 w2-realm**

### Filed on arrival — 2026-09-29 (lane h10b-triage)


### Embedded (bundled) Hermes — 2026-09-28 (filed by the launcher orchestrator)

Plan and rulings: `EterniaLauncher/docs/embedded_hermes/planned/IMPLEMENTATION_2026-09-28.md` (stages named per row) and `ARCHITECTURE_2026-09-28.md` §4. Rule: one Python implementation, universal — enable existing Hermes code, never reimplement; bundle only what is needed.

- **`RT-MESSAGING-PLATFORMS-TELEGRAM` — Messaging platforms (Telegram, Discord, …) as fork work for the headless toolset (full Hermes as a service); off in bundled profiles.** · spec ruling 8. · the off-in-bundled half is in the tree (bundled-desktop.yaml / bundled-phone.yaml deny discord tools and set `gateway.platform_adapters: false`) · RULED 2026-10-16: owner 2026-09-29 "park until Hermes-as-a-service is wanted"; 2026-10-10 "parked stays parked" · NEEDS PLAN 2026-10-18: under ADR 0015 this is the fork's own headless persona gateway, not upstream's adapters — the plan decides: which platforms first; whether it wraps upstream `gateway/platforms/*` (unused per 0015, so the fork owns their tests again) or ships its own adapters; how an inbound platform identity binds to a persona instance + chat session (the runtime.chat lane, never a second session store); where platform credentials live (Hermes-owned auth store, per-profile); the process model (headless `harness serve` with no Launcher) and how approvals reach an operator off-desktop; which bundle profile turns it on (bundled ones stay off)
- **`RT-MACOS-LINUX-BUNDLED-DESKTOP` — macOS / Linux bundled desktop ships no OS secure store: `keyring` (Keychain / Secret Service) is not in the bundled-desktop packaging, so `auth.os_secure_store: true` refuses to start there — add it to those targets' packaging when they exist** · `fork` · evidence: `agent_runtime/host_store/desktop.py::admitted_keyring_backend` · filed 2026-09-28 (lane w5-hdpapi) · `keyring` is in neither pyproject.toml nor uv.lock; add it as an optional extra + networked `uv lock` + bundled-desktop.yaml darwin/linux extras in the change that first builds those targets · RULED 2026-10-16: owner — "add keyring when mac/linux builds exist, not now"; prove it at the Mac sitting · DEFERRED 2026-10-18: `bundled-desktop.yaml` declares no darwin/linux target yet, so there is no packaging to add it to; the change that adds the first such target adds `keyring` (optional extra + networked `uv lock` + that target's extras) and proves `admitted_keyring_backend` at the Mac sitting — owner 2026-10-16

### Filed on arrival — 2026-09-29 (lane h11-mcp)


### Filed on arrival — 2026-09-29 (lane h9-bundle)


### Filed on arrival — 2026-09-30 (lane s2-plan — phone gate → zero, one row per lane; work them in the plan's order)

### Filed on arrival — 2026-09-28 (lane p2-hphone)

### Filed on arrival — 2026-09-28 (lane p1-hsplit)

### Filed on arrival — 2026-09-28 (lane w4-hd4)

### Filed on arrival — 2026-09-29 (upstream merge `merge/upstream-2026-09-29`, filed by the orchestrator)

### Filed on arrival — 2026-09-29 (lane h7-phone)

### Filed on arrival — 2026-09-29 (lane w6-hwort)
- **`RT-PIPER-FIRST-AUDIO-LATENCY` — Piper first audio is ~2 s on a sentence with a name the phonemizer dictionary lacks ("…Mira hasn't joined yet") vs 0.2–0.5 s otherwise — profile the out-of-dictionary path (the model runs per word) and cache or batch it.** · `agent_runtime/speech_phonemize.py`; listening manifest (lane h8-voice, 2026-09-29) · code read: `OpenPhonemizer._predict` is one ORT forward per OOD word, so the likely cost is the first forward on a fresh input shape; owner 2026-09-29: profile once the voice pack is on the box, a warm-up forward at load is the likely cheap fix · BLOCKED 2026-10-16: owner sitting — profile first vs second OOD word with the Piper speech pack + `openphonemizer-en_us.onnx` installed (Windows box)

### Filed on arrival — 2026-09-28 (lane w4-hfix2)

### Filed on arrival — 2026-09-28 (lane w1-hclean, filed by the launcher orchestrator)


### Native conversation lifecycle audit — 2026-09-26



### Filed on arrival — 2026-09-26 (lane PF-1, filed by the orchestrator)


### Filed on arrival — 2026-09-26 (lane PF-3, filed by the orchestrator)


### Filed on arrival — 2026-09-26 (the wedged live serve, owner screenshot 15:05; filed by the orchestrator)


### Filed on arrival — 2026-09-26 (lane CI-RESTORE, filed by the orchestrator)

### Filed on arrival — 2026-09-26 (post-landing gate, filed by the orchestrator)


### Filed on arrival — 2026-09-26 (owner ruling: ACP is not used)

### Filed on arrival — 2026-09-26 (lane L5, filed by the orchestrator)


### Filed on arrival — 2026-09-26 (lane L4, filed by the orchestrator)


### Filed on arrival — 2026-09-26 (launcher lane LLAMA-SWITCH, filed by the orchestrator)


### Filed on arrival — 2026-09-25 (launcher lane REALM-HISTORY, filed by the orchestrator)

The launcher's realm History sheet landed at `EterniaLauncher` `4f77ddfc8`; its Remote tab renders UNSUPPORTED and restore-to-version records a refused row until H1 and H3 exist. Evidence for all four: `EterniaLauncher/docs/mission_control/subsystems/realm-history-and-publish-policy-design-sheet.md` §3.


### Filed on arrival — 2026-09-25 (program-end suite, filed by the orchestrator)


### Filed on arrival — 2026-09-25 (lane LAYERS-DESIGN, filed by the orchestrator)


### Filed on arrival — 2026-09-25 (lane LLAMA-ALIAS)


### Filed on arrival — 2026-09-25 (lane W3-D)



### Filed on arrival — 2026-09-25 (lane W3-C)

### Filed on arrival — 2026-09-25 (lane B4)

### Filed on arrival — 2026-09-25 (lane 2B-A)

### Filed on arrival — 2026-09-24 (lane LLAMA-H)


### Filed on arrival — 2026-09-24 (lane MOVE-A)

- **`RT-RETIRE-LEGACY-TOP-LEVEL` — Retire the legacy top-level `remote_gateway.*` / `charsheet.*` read once the launcher writes `plugins.entries.eternia-harness.settings.remote_gateway_listen` / `remote_gateway_port`: empty `LEGACY_KEYS` and delete-and-report the old blocks at one chokepoint** · fork / config · `agent_runtime/harness_settings.py::LEGACY_KEYS` · blocked on the launcher row "Harness config keys move under the plugin manifest" (`mission-control-queue.md`) · filed by lane h-doors 2026-10-03 · launcher writes the new path since 290449df44 (lane mc-doors); retire only once the owner's installed launcher is at or after that commit, or an older launcher's LAN toggle silently stops working · RULED 2026-10-15 owner (decision sheet w1015i #4): check the BUILD line; if it is that build or newer, say go · BLOCKED 2026-10-16: owner sitting — read the installed launcher's BUILD line against 290449df44

### Filed on arrival — 2026-09-24 (seam lane S2)

### Filed on arrival — 2026-09-24 (lanes UPREV, DISP-M)

### Filed on arrival — 2026-09-24 (seam lane S5)

### Filed on arrival — 2026-09-24 (seam lane S4)

### Owner asks — 2026-09-22, filed on arrival


### Contract questions the launcher is waiting on (filed 2026-09-20/21, routed by the 2026-09-22 verdict sheet)



### Owner design changes — 2026-09-18 (the generic-desk landing, hermes `f1268bd017`)

- **`RT-GENERIC-DESK-WRITE-PAYS` — A generic desk write still pays ONE `scan_actors`** · `hermes` · a desk actor names no `persona_instance_id`, so it is a CLASS-KEYED payload and `_guard_class_keyed_write` scans the directory; the retired fence took two scans to one, not to zero — the generic-desk plan's cost claim was half right. Decide with launcher slice 2 whether desk writes should leave the class-key fence · `test_office_store.py::test_a_generic_desk_write_pays_the_CLASS_KEY_scan_and_only_that_one`. · NEEDS PLAN 2026-10-16: whether desk writes leave the class-key fence, decided with launcher slice 2

### Discussion Tables (hermes half) — from the 2026-09-17 reviews of `codex/discussion-tables-*`

- **`RT-DISCUSSION-RETENTION-PIN-LEAK` — Discussion Tables (hermes half): a retention pin leaks on a crash between `_retain` and `disband_room`** · `hermes` · `agent_runtime/discussions/service.py:316-318`; a pin on a still-live room is reclaimable by no lane (age/tombstone exempt pins, the byte lane selects `disbanded_at IS NOT NULL`) and `unpin_room_history` has no production caller that could clear it. Strictly narrower than the per-run leak the fix retired. Reviewer plant B, 2026-09-17 review of `codex/discussion-tables-fix` @ `20b148694e` (verdict LAND). · the pin owner is ruled on the `run.end` row below (hermes clears leftover pins at start-up) · READY 2026-10-16 · **TAKEN 2026-10-18 w2-agent**
- **`RT-DISCUSSION-TYPED-REFUSAL` — Discussion Tables (hermes half): D3 closes the typed-refusal lane by subclass, leaving three families on the raw-text boundary** · `hermes` · `agent_runtime/discussions/rpc.py:90-105`: `DiscussionPolicyError` (the base), the `DriverStateError` family (`gateway/hosted_room_driver.py:104-111`) and checkpoint `RuntimeError`s (`gateway/hosted_room_policy_checkpoint.py:183,291,298`) still reach `serve_rpc` as `handler_failed` with `f\"handler error: {exc}\"`. Latent — not live-reachable today. Same review @ `20b148694e`. · the policy base and `DriverStateError` family are typed in d151314bcfe; the checkpoint's three plain `RuntimeError`s are raised by upstream `gateway/hosted_room_policy_checkpoint.py`, so typing them is an upstream door (a typed subclass) · DEFERRED 2026-10-16: owner — prepared PR branches stay idle while upstream is not taking the owner's PRs
- **`RT-DISCUSSION-RUN-END-DISBAND` — Discussion Tables (hermes half): `run.end` still refuses on a non-`RoomNotFound` disband failure** (e.g. `AuthorityConflictError`) — decide whether a terminal run may release its claims with the room undisbanded · `hermes` · `agent_runtime/discussions/service.py::_finalize_room`; residual named by the 2026-09-17 D2 fix lane on `codex/discussion-tables-fix` @ `20b148694e`, deliberately not widened there. · RULED 2026-10-15 owner: hermes clears leftover pins at start-up; an ended run may release its seats and leave the room marked for that same clean-up · READY 2026-10-16 · **TAKEN 2026-10-18 w2-agent**

### The ghost agent — filed 2026-09-11 from the office removal-lane fix

- **`RT-AGENT-CREATE-REFUSES-UNMARKED` — `agent.create` refuses an unmarked placement id; the office write lane accepts one, and that pair is how the ghost was minted** · `hermes` · `perform_agent_create` answers `placement_id_not_discriminable` ("supply the `<persona-token>_agent_<hex8>` shape"), but `PersonaInstanceStore.add_instance` takes any token and `OfficeStore.upsert_actor` will place the result, so `persona instance create` + a scene save produces an instance-backed actor with no marker — `personainst_chara_a2_7b31d0e4`, the 09-11 ghost. Either the second route should mint marked ids or the create door's refusal is protecting a discriminator nothing else relies on any more. Needs a ruling, not a patch; the launcher no longer depends on the marker for its archive lane. · `agent_runtime/agent_create/`, `agent_runtime/persona_assignments.py` `add_instance`; the pin that the refusal still exists is `test_the_placement_verb_really_does_refuse_this_id_shape` in `tests/agent_runtime/test_persona_instance_unplaced.py`. · RULED 2026-10-15 owner: mark ids everywhere, so there is one id shape and one rule · READY 2026-10-16 · **TAKEN 2026-10-18 w2-office**

### Runtime observability — filed 2026-09-06 from the post-rebuild field run

- **`RT-MAC-OPEN-CHAT-BUDGET` — The Mac did not answer `runtime.persona.instance.open_chat` inside the budget three times while its snapshot stream flowed, and its Neko instance reads `status=running` with no visible activity, which is exactly the cockpit's occupied-chat dialog condition** · `hermes` (Mac read) + `launcher` · 2026-09-07 16:26:51 / 16:27:06 / 16:27:39Z `open_chat lane=method install=912c69ce… outcome=unknown reason=call_timeout retry=same_key`; `fold_applied persona_instance x1` from the Mac 5 s and 24 s after the first two. Needs the Mac's `agent.log` for 16:26:40–16:27:40Z and the instance row's `status`; the launcher's open-chat receipt should name WHICH budget expired (the connector's default or the lane client's 30 s). · `restart-drain-fence.md` §3 names it · BLOCKED 2026-10-16: owner sitting — the Mac's `agent.log` for 16:26:40–16:27:40Z and its instance row's `status` (Mac)
- **`RT-LOCAL-CHAT-PREP-COST` — The local chat prep cost is now a measured baseline** · `hermes` · `turn_context_ms` 620 / 829 / 1,233 / 4,730 with `builds_overlapped` 1 / 0 / 2 / 3 on four idle local turns (2026-09-06 15:29–15:30Z), the provider itself 0.9–1.5 s — `planned/chat-turn-prep-cost.md` (hermes canon) is re-armable as a stage against these numbers. · plan `docs/agent-runtime-harness/planned/chat-turn-prep-cost.md` (rulings CP-1..CP-9, Stages 6–10): Stage 6 landed hermes `a319021acc` (pre-rewrite) / launcher `a4b8e390c`; CP-9's PC read taken and Stage 7 landed hermes `483bcf6fab` (pre-rewrite) (write_ahead p50 844 ms; skill work 74–89 % of it, so Stage 8 is billed on live turns); no `codex/prep-cost-stage8-one-walk` branch exists — re-verify Stage 8's state before claiming; owed: CP-9's Mac half, Stage 7's ten-turn number, the launcher `ready.json` re-capture · BLOCKED 2026-10-16: owner sitting — CP-9's Mac read (the Mac pulls and re-reads) and live operator turns for Stage 8

### Snapshot build latency on Windows — filed 2026-09-08

- **`RT-LIVE-SERVE-AGENTS-READINESS` — The live serve's `agents_readiness` walk costs 5-10x the same walk in a quiet process, and nothing explains the difference** · `hermes` · `snapshot_agents_readiness walk_ms=` reads 651-1595 ms across 664 samples in the operator's `agent.log`, against 126-155 ms for the identical five-persona walk measured read-only against the same live store from an isolated process; the 2026-08-22 note in the walk itself records 146 ms and matches the quiet figure, so the algorithm is not what moved — the serve process is · `docs/agent-runtime-harness/planned/windows-path-syscall-cost-2026-09-08.md` "What the measurement did NOT explain" item 1 · found while profiling the build for the memo landed at hermes `6d79b6d724` (pre-rewrite). · BLOCKED 2026-10-16: owner sitting — a live-serve investigation on the owner's box
- **`RT-CORE-CACHE-WRITES-BUILD` — The core cache writes on every build and has never once been served on this install** · `hermes` · 2,094 `snapshot_core_cache_write` lines against ZERO `core_source=cache` serves in one `agent.log`; the same code DOES serve on a quiescent copy of the same store (226-241 ms against a 1.0-2.2 s cold build), so convergence is the whole blocker — and "just stop writing" is dead as a remedy because disabling the write-back entirely bought 4 ms · `docs/agent-runtime-harness/planned/core-cache-input-closure.md` 2026-09-08 addendum, which is the field half of its own IC-4 "measure first" gate · the per-family reader audit that plan demands is still owed. · BLOCKED 2026-10-16: owner sitting — the IC-4 per-family reader audit measured against the live store

- **`RT-FULL-PERSONAASSIGNMENTSTORE` — Full `PersonaAssignmentStore` retirement is gated on a residual-row census that came back NONZERO (81, unchanged at the 2026-09-04 re-census)** · `hermes` · blocked on an OPERATOR settle of the 15 non-terminal rows, not on implementation; the launcher half is closed (§AX2 / Z1, `EterniaLauncher` `bf33487b2`). Routed out of the launcher Mission Control queue 2026-09-22 (wave 8, lane docs-2) per `EterniaLauncher` `9de7b2bfd`. · BLOCKED 2026-10-16: owner sitting — settle the 15 non-terminal rows in the owner's live store

### Harness CLI and the doctor — 2026-08-30 / 2026-09-02 hand-backs, 2026-09-12 skill sync

- **`RT-ROOT-CONFIG-MISPLACEMENT-CURE` — `root_config_misplacement` has a cure and a denominator; the 9-vs-2 comparison needs re-reading** · `hermes` · the finding half landed 2026-09-04 (w12/m5, hermes `42d54af562` (pre-rewrite)): `remediation` (present even when `ok`) and `scope` (`profiles_examined` / `root_only_key_patterns`) from the rows' own walk; doctor `schema_version` 9. A row is (profile × concrete key) and two of four patterns are per-persona, so 9 vs 2 across two machines compares inventories. What remains is operator-only: re-read the two stores against `scope` and fix the genuinely inert rows by hand — there is deliberately no automated repair, because rewriting an operator's `config.yaml` is not a write the doctor takes. · BLOCKED 2026-10-16: owner sitting — re-read both machines' stores against `scope` and hand-fix the inert `config.yaml` rows (Windows box and Mac)



### Filed on arrival — 2026-09-25 (lane R4)



### Filed on arrival — 2026-09-25 (lane S2B)

### Filed on arrival — 2026-09-25 (lane S2A)

### Filed on arrival — 2026-09-25 (lane 2B-C)


### Filed on arrival — 2026-09-25 (lane B2)


### Filed on arrival — 2026-09-25 (lane B3)


### Filed on arrival — 2026-09-25 (lane B4, filed by the orchestrator)


### Filed on arrival — 2026-10-17 (lane r-perf)


### Filed on arrival — 2026-10-17 (q-version)


### Filed on arrival — 2026-10-17 (harvest of rows committed on branches, never landed)

- **`RT-AUTONOMY-APPLY-WITH-REVIEW` — `AutonomyLevel.APPLY_WITH_REVIEW` is read by nothing but `snapshot/summaries.py` and `config/persona_records.py`; persona autonomy is a label, not a workflow** · fork / personas · audit §2 · lane: make it the switch that requires a review before a Work card completes (with the review-door row), or delete the member with a tombstone. · carried from origin/ccr-cc6cbc42-w6ahvk db13f82 (2026-10-17 harvest) · Recommend: delete the member with a tombstone (its one reader, `coordinator_permissions.scope_for_persona`, already treats it as `autonomous`), read a stored value as `autonomous`, and type the field with the enum (`review` = `propose_only` alias) — [proposal §3](../../docs/agent-runtime-harness/planned/agent-behaviour-proposals-2026-10-18.md) · RULED 2026-10-18: owner — delete it with a tombstone; type the field with the enum, `review` an alias of `propose_only` · READY 2026-10-18 · **TAKEN 2026-10-18 w2-agent**
- **`RT-VERIFY-ON-STOP-OFF` — `agent.verify_on_stop` is off (upstream default `False`); `auto` resolves ON for any non-messaging surface, which a harness persona turn is (`agent/verification_stop.py::verify_on_stop_enabled`), so the flip is one profile config line — the nudge cost on persona turns is unmeasured** · fork / profiles · audit §2 · lane: measure on five dev-persona turns, then owner rules per persona profile. · carried from origin/ccr-cc6cbc42-w6ahvk db13f82 (2026-10-17 harvest) · Recommend: `true` only in repo-slot (dev) persona profiles, after five editing turns ON vs OFF on the QA serve measure extra calls/tokens/wall time — [proposal §4](../../docs/agent-runtime-harness/planned/agent-behaviour-proposals-2026-10-18.md) · RULED 2026-10-18: owner — on only for dev personas bound to a repo slot, after five editing turns ON vs OFF · BLOCKED 2026-10-18: owner sitting — five editing turns ON vs OFF on the QA serve
- **`RT-DELEGATE-VS-CHAT-VS-WORK` — Nothing on the lane states when to `delegate_task` (bounded side job), `agent_chat_send` (persistent teammate) or submit Work (durable, hand-off, survives restart); upstream's own "Kanban vs. `delegate_task`" table is the rule** · fork / prompt surface · audit §7 · lane: one paragraph in the plugin's `eternia-harness.tool-guidance` section, token cost measured the way `h-prompt-brief` measured descriptions. · carried from origin/ccr-cc6cbc42-w6ahvk db13f82 (2026-10-17 harvest) · NEEDS PLAN 2026-10-18: the guidance constant, a two-tool gate in `_TOOL_GUIDANCE`, and its receipt-measured token cost (draft line ~75 tokens; the Work clause waits on the `kanban` toolset being admitted) — [proposal §5](../../docs/agent-runtime-harness/planned/agent-behaviour-proposals-2026-10-18.md)
- **`RT-GOAL-ENGINE-DOOR` — No door to upstream's goal engine on the persona chat lane: `hermes_cli/goals.py` (per-session judge, continuation, turn budget, completion contracts, quality gates, park on a background process, pause/resume, persisted in SessionDB) is reachable only as the `/goal` slash command in CLI/TUI/gateway; the runtime has no `runtime.chat.goal.*` method and the console no action, so a persona chat cannot "keep going until it is done". The fork's `goal_id` / `current_chat_goal` are a label and a display string, not a loop** · fork / chat RPC · evidence: `docs/agent-runtime-harness/planned/upstream-capability-audit-2026-10-12.md` §1–§2; `agent_runtime/state_patches/persona_instance.py` (`current_chat_goal`) · lane: DESIGN — set / status / pause / clear over the RPC lane keyed by the persona chat root, continuation turns forged through the mission-chat door the delivery drain uses; everyday surface: none (the persona keeps going), developer mode: a status line. OWNER RULES. · carried from origin/ccr-cc6cbc42-w6ahvk cb32d71 (2026-10-17 harvest) · Recommend: build `runtime.chat.goal.set|status|pause|resume|clear` over `GoalManager`, the serve forging continuations through the mission-chat door, after Work carries `goal_mode` — [proposal §6](../../docs/agent-runtime-harness/planned/agent-behaviour-proposals-2026-10-18.md) · RULED 2026-10-18: owner — build `runtime.chat.goal.*` over `GoalManager` once Work carries `goal_mode` · BLOCKED 2026-10-18: another lane — `RT-WORK-W3-ENGINE`

## Seams

### Filed on arrival — 2026-10-16 (lane r-realm-lens, branch `q/r-realm-lens`)

- **`RT-LENS-CREDENTIAL-PREVIEW` — Lens source credentials live in the credential pool's `lens` slice, and upstream's dashboard `GET /api/credentials/pool` (`hermes_cli/web_routers/ops.py::list_credential_pool`) lists that slice with a `redact_key` token preview — the Lens ruling is write-only (set / not set / rotated, never any part of the value); wants a caller-side door (hide a slice by source `manual:lens`) or an upstream issue, never an edit** · seam / credential pool · `agent_runtime/lens/credentials.py` · READY 2026-10-18 · RULED 2026-10-18: a fork-owned 0600 file under `HERMES_HOME/lens/` behind the unchanged `lens.credentials` API (amends launcher plan S2), plus an upstream issue for a listing-hidden pool flag (owner) · **TAKEN 2026-10-18 w2-lens**
### Filed on arrival — 2026-10-16 (lane r-turnrec)




### Filed on arrival — 2026-10-15 (door PR lanes doors-a, doors-b)

- **`RT-J2-HOSTED-ROOM-LIMITS` — J2 hosted-room limits: at the NEXT release merge (the tag carrying upstream `676238c81b8`), slices A2 (`_conclude` on `_bounded_task_delta` + always-frozen `input_context`) and A3 (per-instance checkpoint transcript bound); the fork's `member_id=` hunk on `tui_gateway/hosted_room_driver.py::submit` retires free; the J2a/J2b/B0 upstream PR prep waits (PR branches idle)** · seams · `docs/agent-runtime-harness/planned/hosted-room-j2-limits-2026-10-16.md` (q-j2 `ab0eb8a6d89`, recommendations taken) · BLOCKED 2026-10-16: upstream — the release tag carrying upstream `676238c81b8`
- **`RT-DOORS-SHEET-C-PART-B` — Doors sheet §C part B (gh/Qwen `adopt_external_logins` bug fix) has no prepared branch; part A shipped as `feat/secret-file-store` (634f2ab083)** · seams · doors-a lane report 2026-10-15; sheet on `h-doors-2` §C · build a branch from upstream/main with a body in `pr-bodies` · RULED 2026-10-16: owner — "pr branches should remain idle" while upstream is not taking the owner's PRs · DEFERRED 2026-10-18: build the part B branch from the then-current upstream release when upstream takes the owner's PRs again — owner 2026-10-16 deferral




- **`RT-QUALIFY-HELD-CHECKPOINT` — Qualify the held checkpoint upstream candidates against native user value and maintainer demand.** Native write extraction and reviewed consumers are complete in Console history PR #7, with separate behavior-preserving extraction `71ba58a781`. Before any submission, check open issues/discussions and overlapping PRs and apply the evidence/value bar in the footprint ledger; product neutrality alone is insufficient. Busy/wait is a separate candidate. Retention pins accompany qualified resumable restore or remain held. No upstream submission is authorized by this row. · seam / checkpoints · `docs/agent-runtime-harness/planned/upstream-footprint-ledger.md`, `docs/agent-runtime-harness/planned/console-history-followup-verification-2026-10-11.md` · RULED 2026-10-15 owner: no, not yet; there is no sign upstream wants them · DEFERRED 2026-10-18: hold until an upstream issue or maintainer asks for checkpoint restore — owner 2026-10-15 "no sign upstream wants them"


### Filed on arrival — 2026-10-10 (guard fix, build batch 2 C1–C4, filed by the orchestrator)

- **`RT-CONTEXT-MANIFEST-SHADOWED` — The /context manifest says "shadowed" for files the fork's prompt actually loads: `agent/context_file_sources.list_context_file_sources` marks lower-priority kinds `shadowed`, but the fork's `build_context_files_prompt` loads every kind** · seam / prompt context · design-sweep-d1 § D1.12 S2 (build-1011-C2) · the fix is a non-additive hunk in upstream `agent/context_file_sources.py` (drop the winner rule) to match the fork's load-every-kind builder carry · Recommend: rule a one-file footprint raise for an additive one-line carry in `list_context_file_sources` (`winner = None` at the top of its loop, so every present kind reports loaded like the fork's builder); `agent/context_file_sources.py` is at upstream bytes and every reader is upstream (`/context` in CLI, gateway, TUI), so no fork-only door exists and the footprint gate refuses the edit without an `owner_ruling` · RULED 2026-10-18: owner — a one-line additive carry in `agent/context_file_sources.py` (`winner = None` at the loop top) is ruled; raise the footprint for it · READY 2026-10-18 · **TAKEN 2026-10-18 w2-agent**

### Filed on arrival — 2026-10-10 (fork-fixable sweep lane-1011, filed by the orchestrator)


### Filed on arrival — 2026-10-10 (queue sweep lane-1010, filed by the orchestrator)


### Filed on arrival — 2026-10-10 (release merge v0.21.6 reds)



### Filed on arrival — 2026-10-08 (warm send-prep integration review, `196ec6159d`)

### Filed on arrival — 2026-10-08 (native connection ownership cleanup)

### Filed on arrival — 2026-10-06 (upstream sync planning; AFTER the next release merge)


- **`RT-REQUEST-BUILT-RESOLVES-WEB` — request_built resolves every web-search provider's availability on every request (`agent/transports/codex.py::_alias_wire_tools` → `_openai_prefers_native_web_search` → `agent/web_search_registry.get_active_search_provider`: credential-pool loads, auth-file reads, nous account lookups; 85–105 ms live, ~100 ms on the fixture)** · runtime / turn latency · evidence: h-warm-phases commit 01b1a9a0f8 body · measured 2026-10-08 (`docs/agent-runtime-harness/planned/warm-send-prep-measurements-2026-10-08.md`); every fix site is upstream (`agent/transports/codex.py`, `agent/web_search_registry.py`) · RULED 2026-10-15 owner: wait for the upstream fix; no short cache (a stale cache can send the wrong search tool) · BLOCKED 2026-10-16: upstream — the active-search-provider fix in `agent/web_search_registry.py`
- **`RT-NATIVE-CONVERSATION-RECOVERY` — Native conversation recovery lives inside ~15 upstream `tui_gateway/` files and is the top repeat merge conflict (`session_workdir`, `session_lifecycle`, `methods_session`, `event_replay`, `rpc_dispatch`, `server_requests`, `contracts/sessions` conflicted in the 2026-09-29 merge and/or the 2026-10-06 dry run): move the logic into fork modules, leave one-line call sites. Start only after the next release merge lands** · `seams / tui_gateway` · ledger `carry` rows "native conversation recovery"; `Merging upstream.md` · designed in `docs/agent-runtime-harness/planned/design-sweep-d2-2026-10-10.md` § D2.09 (two MOVE clusters + four door-PR rows) · BLOCKED 2026-10-18: upstream — the next upstream release tag after v0.22.2 (merged `785b27aa10`, 2026-10-15), then its release merge (`Merging upstream.md`)
- **`RT-FOUR-UPSTREAM-DOOR-PRS` — Four upstream door PRs would retire 23 fork-edited upstream files (optional-module 6, SDK fallback 3, secret-file store 7+2, provider access 5): the design is on branch `h-doors` (`d3d91edc7f`, its upstream-doors plan, not on main). Owner go needed before the Opus build lanes; land the plan with the first lane; open no upstream PR without the owner's OK** · `seams / upstream doors` · `h-doors` · RULED 2026-10-10 owner: go: the four door-PR Opus build lanes on `h-doors`, and open the four upstream PRs · part A shipped as `feat/secret-file-store` (634f2ab083) · RULED 2026-10-16: owner — "pr branches should remain idle" while upstream is not taking the owner's PRs · DEFERRED 2026-10-18: build the three remaining door branches (optional-module, SDK fallback, provider access) on `h-doors` when upstream takes the owner's PRs again — owner 2026-10-16 deferral
- **`RT-DOOR-PR-LANDS-UPSTREAM` — When a door PR lands upstream and reaches a release: delete the fork hunks it retires, file by file, per the plan's "fork deletion" section, and lower `tests/fixtures/upstream_footprint.json`** · `seams / upstream doors` · `upstream-doors-2026-10-06.md` · BLOCKED 2026-10-16: upstream — a release carrying one of the four door PRs

### Filed on arrival — 2026-10-06 (lane h-prereq-window)


### Filed on arrival — 2026-10-06 (lane h-model-pick)


### Filed on arrival — 2026-10-06 (lane h-conn-pool)


### Filed on arrival — 2026-10-06 (lane h-readiness)


### Filed on arrival — 2026-10-05 (lane h-prompt-tools)


### Filed on arrival — 2026-10-04 (lane hb-a)


### Filed on arrival — 2026-10-03 (lane h-mcpwake)


### Filed on arrival — 2026-10-02 (instance-conversations)


### Filed on arrival — 2026-10-01 (lane w3-turn)

- **`RT-RETIRE-COMPUTE-HOST-COLD` — Retire the compute-host cold-start carry: `tui_gateway/host_supervisor.py` waits a fixed 10 s for the child's hello while the child imports `tui_gateway.server` first (5.6–6.2 s idle, 10.8–28.5 s loaded); the fork added `_HELLO_COLD_START_GRACE_SECS` (additions only). Upstream PR: a configurable hello budget, or the hello sent before the heavy import** · `upstream / tui_gateway` · ledger row `tui_gateway/host_supervisor.py` (cold-start hello grace, 2026-10-01) · RULED 2026-10-10 owner: yes: open one upstream PR for a configurable compute-host hello budget (default 10 s) · draft: local branch `up/compute-host-hello-budget` (fd282272f8e, `dashboard.compute_host_hello_timeout_secs`, red recorded) · BLOCKED 2026-10-18: upstream — issue text: "`host_supervisor` waits a fixed 10 s for the compute-host hello while the child imports `tui_gateway.server` first (5.6–28.5 s measured); make the budget `dashboard.compute_host_hello_timeout_secs`, default 10" · draft `up/compute-host-hello-budget` (fd282272f8e) · fork carry `_HELLO_COLD_START_GRACE_SECS` stays

### Filed on arrival — 2026-09-29 (lane fix-cron-openai)


### Embedded (bundled) Hermes — 2026-09-28 (filed by the launcher orchestrator)


### Filed on arrival — 2026-09-29 (lane h9-bundle)


### Filed on arrival — 2026-09-26 (lane FIX-TRIAGE, filed by the orchestrator)

### Filed on arrival — 2026-09-26 (lane PF-1, seams; filed by the orchestrator)


### Filed on arrival — 2026-09-26 (lane AUTH-PR, filed by the orchestrator)


### Filed on arrival — 2026-09-26 (owner ask: the fix-shaped footprint)


### Filed on arrival — 2026-09-26 (owner ask: what else moves to the plugin side without a PR)

### Filed on arrival — 2026-09-26 (orchestrator, the sync-friction read)


### Filed on arrival — 2026-09-26 (orchestrator, the footprint read)


### Filed on arrival — 2026-09-25 (lane MERGE, filed by the orchestrator)


### Filed on arrival — 2026-09-25 (orchestrator, the `[up-fp]` raise)


### Filed on arrival — 2026-09-25 (lane 2B-B)


### Filed on arrival — 2026-09-24 (seam lane S2)

- **`RT-NINE-STAGE-2-ROWS` — Nine Stage 2 rows the ledger said the surface "has" wait on five widening PRs nobody owns, and none is on §Stage 3's P-list** · `seams / upstream` · `register_command` with gateway context + `busy_policy` (`/queue-status`, 4 rows); a terminal command-guard hook consulted by `_check_all_guards` with a typed result (the envelope gate); a per-call usage ledger in the turn result (`usage_ledger`, 3 rows); a tool-schema transform hook (wire briefs); a register-toolset PR (bundle membership, `harness_core`). Each needs a P-number, an owner and a fallback in `docs/agent-runtime-harness/planned/harness-plugin-and-upstream-seams.md` §Stage 3 · evidence: `docs/agent-runtime-harness/planned/upstream-footprint-ledger.md` rows marked "DESIGN (lane S2)" / "waits on" · filed by lane S2 2026-09-24 · the tool-schema transform ask is REFUTED (upstream `llm_request` middleware rewrites `api_kwargs.tools`) · RULED 2026-10-10 owner: fork-side `/queue-status` through `pre_gateway_dispatch`, no re-cut — in the tree (98b4553ef03, `agent_runtime/gateway_queue_status.py`) · BLOCKED 2026-10-16: upstream — merges of #123977 command_guard, #123978 per-call cost + Codex parity, #123979 register_toolset

### Filed on arrival — 2026-09-24 (disposition wave, lane DISP-C)

### Filed on arrival — 2026-09-23 (seam lane S45, Stage 4/5/6 inventories)

- **`RT-UPSTREAM-TEST-INPLACE-EDITS` — 177 of the 252 upstream test files the fork edits hold in-place edits, not fork tests. Stage 5's MOVE lanes cannot retire them, and its `[up-fp] files −242` target is not reachable (MOVE ceiling 28)** · `seams / tests` · these need a disposition pass (a batched portability/hermeticity PR upstream, or carry with a reason) before Stage 5's gate means anything. Evidence: the same note §1.1–§1.3 · filed by lane S45 2026-09-23 · RULED 2026-09-23 owner: upstream, separate PRs per fix class; never carried · RULED 2026-10-10 owner: no re-file; drop each carry upstream now covers, keep the rest with a ledger reason, re-count at the next release merge · BLOCKED 2026-10-18: upstream — the next upstream release tag after v0.22.2 (merged `785b27aa10`, 2026-10-15), then its release merge (`Merging upstream.md`)

### Standing

- **`RT-DISCUSSION-PIN-BYTE-BUDGET` — Discussion Tables (hermes half): pin exempts rooms from the gateway byte budget while its own comment says it does not, and no test touches any new gateway symbol** (`pin_room_history`, `max_active_events`, `DiscussionLimits`, `request_reconciliation`, `stop_unresolved`) · `hermes` · `gateway/hosted_rooms.py:556-577`; degrades stock Group Chat retention, not only discussions. Same review @ `f4abe884a9`. · `d33dff5bbd` covered the three symbols · BLOCKED 2026-10-16: owner decision — should a pinned room count against the gateway byte budget (fix the code to its comment) or stay exempt (fix the comment)? · Recommend: count it, so a pin cannot degrade stock Group Chat retention, then an upstream door PR
- **`RT-SPARK-PRO-USAGE-BUCKET` — Spark has a Pro usage bucket but Hermes's ChatGPT-account Codex route rejects it** · observed 2026-09-16: the live model catalog omitted Spark, the same account's usage response named the separate `codex_bengalfox` bucket, and a minimal `gpt-5.3-codex-spark` request returned HTTP 400 "not supported when using Codex with a ChatGPT account." The picker now shows it disabled. Investigate a supported runtime route before enabling it · `EterniaLauncher/docs/mission_control/subsystems/model-picker-account-catalog-contract-20260916.md`, `hermes_cli/codex_models.py`. · BLOCKED 2026-10-16: owner sitting — probe a supported Spark route with a live ChatGPT Pro account



## Upstream-owned

### Filed on arrival — 2026-10-18 (lane r-state, branch `q/r-state`)


### Filed on arrival — 2026-10-17 (harvest)

- **`RT-ONBOARDING-PATH-IMPORT` — Repair the upstream onboarding import that blocks native gateway startup.** Clean `b9e7e77cc7` reproduces `NameError: Path` at `tui_gateway/methods_onboarding.py:71` before handler binding; existing worker/compute tests and all six subagent process round trips fail before routing. Evidence: `docs/downstream/agent-console-subagents-settings-2026-10-16.md` § Qualification. Keep the native footprint ruling explicit; Step 6 does not silently absorb a fifth seam. · upstream / gateway · UNCLAIMED · carried from origin/codex/subagent-settings-hermes 698e0da (2026-10-17 harvest) · READY 2026-10-18: re-read 2026-10-18 on `4f5e793ca1`, `import tui_gateway.methods_onboarding` still raises `NameError: Path` (the fork-edited file lacks upstream's `from pathlib import Path`) · **TAKEN 2026-10-18 w2-seams**

### Filed on arrival — 2026-10-17 (lane r-perf)

- **`RT-CHECKPOINT-PM-ENSURE` — `tools/checkpoint_manager._run_git` calls `pm.client.ensure` per git call (a store-root walk each time): ~20% of `test_operator_redo` profiled** · upstream / checkpoints · [[r-perf-2026-10-17]] · upstream issue or a caller-side memo · BLOCKED 2026-10-18: upstream — issue text: "`pm.client.ensure('git')` costs ~31 ms a call on Windows, and `tools/checkpoint_manager._git_env` (via `hermes_cli._subprocess_compat.selected_git_env`) pays it once per git spawn (1,954 calls = 31.9 s of `test_operator_redo`'s 150 s alone). cProfile: 82% is `pm.environments.store_root` <- `pm.paths.store_root` / `install_stamp_path` / `repo_root`, ~118 `Path.resolve` per call. `repo_root()` and `lockfile_path()` resolve `__file__` on every call: caching those two takes a call to 18 ms; caching `store_root(root)` per (root, `HERMES_RUNTIME_DIR`) to 3.7 ms." A memo above `pm.ensure` is ruled out by upstream's own contract (`tests/tools/test_git_consumer_environment.py`: "A changed PM selection must affect this same process"), and `pm/paths.py` is not in the footprint — q-pm 2026-10-18
- **`RT-SQLITE-JOURNAL-MODE-RERESOLVE` — Every SQLite open re-resolves the journal mode (config read + header probe + the 3.50.4 DELETE path in `hermes_state_wal.apply_wal_with_fallback`): ~10k opens in `test_discussion_runtime`, whose driver `stop` then waits ~12 s per test** · upstream / state · [[r-perf-2026-10-17]] · upstream issue (resolve once per process per path) · BLOCKED 2026-10-18: upstream — re-measured 2026-10-18 (Windows, SQLite 3.50.4): `apply_wal_with_fallback` 2.52 ms/open on a home with no `config.yaml`, 0.37 ms with one (bare connect 0.11–0.14); `resolve_journal_mode` 2.02 ms vs 0.13 ms — the cost is `hermes_cli/config.py::_load_config_impl` caching nothing when neither config file exists (`cache_sig` None: deepcopy `DEFAULT_CONFIG` + env expansion per call), not the header probe; `test_discussion_runtime` 72.5 s → 41.2 s with a `config.yaml` in its homes · issue text: "`load_config` / `load_config_readonly` rebuild the defaults on every call when no config file exists; memoise the defaults under a missing-file signature" · the per-open caller is upstream `apply_wal_with_fallback`, so no fork memo


### Filed on arrival — 2026-10-10 (fast gate FG1, filed by the orchestrator)


### Filed on arrival — 2026-10-10 (guard fix, build batch 2 C1–C4, filed by the orchestrator)

- **`RT-SSH-PROFILE-REMOTE-CWD` — An ssh profile's REMOTE cwd is shape-checked with the host's `os.path.isabs`: `tui_gateway/session_workdir.py::_is_remote_cwd_shape`; on Windows under Python ≥ 3.13 `ntpath.isabs("/home/kali")` is False, so `_completion_cwd` drops a named ssh profile's remote cwd to "~" and `_workspace_cwd` refuses it (`session.workspace.move` → 4017)** · upstream / tui_gateway · 4 tests red on pure tag v0.21.6 `818c13be1d`, marked `_up_red_when` (fix/1011-guard-and-tui-reds `462337b735`) · upstream issue (the remote shape wants `posixpath.isabs`) · the four tests are already `_up_red_when`-marked · RULED 2026-10-15 owner (decision sheet w1015i #2): yes — post them together in one sitting · BLOCKED 2026-10-16: owner sitting — post the upstream issue (the remote shape wants `posixpath.isabs`) at the upstream posting sitting

### Filed on arrival — 2026-10-10 (build batch 1, build-1011-B1..B5, filed by the orchestrator)

- **`RT-SKILL-CATALOG-FRONTMATTER` — Upstream `tools/skills_tool._skill_catalog` parses every SKILL.md frontmatter itself, and the kanban environment gate costs 3 ms per tagged skill uncached plus a 1.3 s first-call import** · upstream / skill catalog · build-1011-B2 `9dc0b2ad19` (60/60 parses in a primed cold child) · plan `docs/agent-runtime-harness/planned/skill-catalog-doors-2026-10-15.md` approved by owner 2026-10-15 · BLOCKED 2026-10-18: upstream — issue text: "`_skill_catalog` parses each SKILL.md frontmatter itself and runs the kanban environment gate per tagged skill uncached; accept parsed frontmatter from the caller and memoise the gate per process" · plan `docs/agent-runtime-harness/planned/skill-catalog-doors-2026-10-15.md` · its only caller is upstream

### Filed on arrival — 2026-10-10 (Fable design sweep D1–D3, filed by the orchestrator)

- **`RT-PREFLIGHT-DB-WRITABILITY` — `preflight_db_writability` reads `os.access` on a sidecar it listed a moment earlier; a WAL unlinked in between reports as read-only** · upstream / state repair · design-sweep-d3 § D3.02 · fork carry built by build-1011-B5; upstream PR owed · the fork carry is built (build-1011-B5); the upstream PR remains · BLOCKED 2026-10-18: upstream — issue text: "`preflight_db_writability` lists the -wal/-shm sidecars, then `os.access`es each; one unlinked in between reports the store read-only; re-check existence and skip a vanished sidecar" · fork carry build-1011-B5 stays

### Filed on arrival — 2026-10-10 (fork-fixable sweep lane-1011, filed by the orchestrator)

- **`RT-CONFTEST-DB-PATH-PIN` — `tests/conftest.py` step 3b pins `hermes_state.DEFAULT_DB_PATH` only when `hermes_state` is already imported, so an argless `SessionDB()` is import-order dependent; the fork unpins by node id (`tests/_downstream/state_db_scope.py`)** · upstream / suite · `ddf83ac62a` (M4.06) · lane: upstream issue (order-independent pin) · the fork side is done (`tests/_downstream/state_db_scope.py` unpins by node id) · RULED 2026-10-15 owner (decision sheet w1015i #2): yes — post them together in one sitting · BLOCKED 2026-10-16: owner sitting — post the upstream issue (order-independent pin) at the upstream posting sitting

### Filed on arrival — 2026-10-10 (queue sweep lane-1010, filed by the orchestrator)


### Filed on arrival — 2026-10-08 (lane opus-w1-hermes, moved from fork-hygiene)


### Filed on arrival — 2026-10-06 (lane h-suite-tail-b)

- **`RT-DASHBOARD-AUTH-SCRYPT-IMPORT` — `plugins/dashboard_auth/basic` computes a scrypt `_DUMMY_HASH` at import time (~0.2 s), paid again on every plugin re-import (80–122 scrypt calls per test file in the profiles)** · upstream-owned · evidence: lane h-suite-tail-b profiles · an upstream issue or a caller-side memo, never an edit · no caller-side memo reaches a module-level import-time computation without editing the module · RULED 2026-10-15 owner (decision sheet w1015i #2): yes — post them together in one sitting · BLOCKED 2026-10-16: owner sitting — post the upstream issue at the upstream posting sitting

### Filed on arrival — 2026-10-05 (lane h-defer, name-set sweep)


### Filed on arrival — 2026-10-02 (lane w5-fh, filed by the orchestrator)


### Filed on arrival — 2026-10-01 (instance conversations)


### Filed on arrival — 2026-10-01 (lane rw-h)


### Filed on arrival — 2026-09-29 (lane h11-code)


### Filed on arrival — 2026-09-29 (lane h10-rtseam, filed by the orchestrator)


### Embedded (bundled) Hermes — 2026-09-28 (filed by the launcher orchestrator)

- **`RT-OFFER-SDK-FREE-HTTPX` — Offer the SDK-free httpx client (re-homed `turn_runner`) upstream as a transport "client" door, after the fork polish.** · architecture §4; ask the owner before opening the PR. · RULED 2026-10-10 owner: yes: offer the transport client door upstream · RULED 2026-10-16: owner — "pr branches should remain idle" while upstream is not taking the owner's PRs · DEFERRED 2026-10-18: offer it after the fork polish closes and upstream takes the owner's PRs again — owner 2026-09-29 + 2026-10-16

### Filed on arrival — 2026-09-29 (lane fix-node-deps, filed by the orchestrator)

- **`RT-NODE-DEPS-LAUNCH-TIME` — node-deps: launch-time `npm ci` on Windows fails EPERM when a loaded native binding under `node_modules` is held open (the retry covers ENOTEMPTY only), and the npm error goes to stderr only, so "source-update completion failed" loses the real cause** · `upstream` · `scripts/build/node-deps.mjs` `runNpmCi`, `hermes_cli/source_build.py` `run_source_script` · reproduced 2026-09-29 in a worktree (lightningcss `.node` held by a second node process); the live checkout self-healed at the 12:03 pm sync · filed 2026-09-29 · `runNpmCi` (`scripts/build/node-deps.mjs:67`) retries only on ENOTEMPTY; upstream already skips `npm ci` on an unchanged lockfile via the `--reuse` receipt; the local draft `up/node-deps-reuse-installed-superset` ebd22f05fa covers only the workspace-union trigger · RULED 2026-09-29 owner: HOLD that branch until the EPERM's trigger (workspace selection / node-npm version / `npm_config_*` env) is proven · RULED 2026-10-15 owner: book a weekly operator sitting on the Windows box and run this check there · BLOCKED 2026-10-16: owner sitting — reproduce the held-handle EPERM at the weekly Windows-box sitting and name its trigger

### Filed on arrival — 2026-09-29 (PR #125262 review follow-up, filed by the orchestrator)


### Filed on arrival — 2026-09-27 (lane PR-REPLIES, filed by the orchestrator)


### Filed on arrival — 2026-09-26 (lane HELD-TESTS, filed by the orchestrator)



### Filed on arrival — 2026-09-26 (lane FIX-TRIAGE, filed by the orchestrator)

- **`RT-HERMES-STATE-SCHEMA-STALE` — `hermes_state_schema.py`'s stale-FTS rebuild never recovers on SQLite 3.45.3 (Windows CPython 3.12.5): `DROP TABLE IF EXISTS messages_fts` from a fresh connection raises `vtable constructor failed: messages_fts` when the FTS5 data is corrupt, so FTS stays detached for good** · `upstream` · reproduced on a bare FTS5 table; the four `test_fts_runtime_rebuild.py` reds are `_up_red` rows in `tests/_downstream/id_markers/upstream_reds.py` (lane TRIAGE); sibling of the `state_db_has_structural_damage` row below · PR candidate: on that raise, drop the FTS5 shadow tables under `PRAGMA writable_schema` and recreate · filed 2026-09-26 (lane TRIAGE) · RULED 2026-10-10 owner: wait for upstream; keep the `_up_red_when(sqlite<3.46)` markers; no VACUUM INTO draft · BLOCKED 2026-10-16: upstream — a stale-FTS rebuild that recovers on SQLite < 3.46

- **`RT-SKILL-UTILS-STAT-CALLS` — `agent/skill_utils` spends 480 `realpath` + 698 `os.stat` calls per snapshot build** · `hermes` · `_resolved_path` (three call sites under `resolve_skills`) and `is_skill_support_path` (under `_skill_root_registry`); on Windows each `realpath` is an `nt._getfinalpathname` handle open at ~71 us, so this is the second-largest path-syscall term after the one just retired. Upstream-owned file — the fork's leave-upstream-alone rule means the fix is a caller-side memo or a resolver seam, not an edit there · `docs/agent-runtime-harness/planned/windows-path-syscall-cost-2026-09-08.md` item 3. · `_resolved_path` is fork-owned (`agent_runtime/skill_resolution.py`) and `is_skill_support_path` runs only on a registry rebuild since h-chatperf/CP-5 cached the registries; re-measure on a current snapshot build before memoizing · READY 2026-10-16 · **TAKEN 2026-10-18 w2-office**
- **`RT-HOSTED-ROOMS-CANNOT-MOVE` — `gateway/hosted_room_discussion.py` (85/33) and `gateway/hosted_rooms.py` (72/4) cannot move into fork modules: their bodies call 6+ upstream privates; retire via the Group Chat host-surface widening PR, not a move** · seams · evidence: `docs/agent-runtime-harness/planned/footprint-drop-2026-09-27.md` Outcome · filed 2026-09-27 · fork diff +143/−37 and +72/−4; the bodies call upstream privates, so a fork module would import six-plus `_names` · RULED 2026-10-16: owner 2026-09-29 "park until group-chat work resumes"; 2026-10-10 "parked stays parked" · DEFERRED 2026-10-18: leave both as seams until group-chat work resumes, then retire them through the Group Chat host-surface widening upstream PR (a move would import six-plus upstream `_names`); re-measured vs merge-base `d923a5eb48`: +106/−44 and +21/−4 — `docs/agent-runtime-harness/planned/footprint-drop-2026-09-27.md` Outcome

- **`RT-PROCESS-STARTUP-UPSTREAM-WORK` — Every `hermes` process pays upstream start-up work no read-only verb uses: importing `hermes_cli.config` runs provider discovery (`_inject_profile_env_vars` → `providers.list_providers`, ~1.6 s, 38 plugin dirs, 27 YAML loads) and `plugins/model-providers/fireworks` calls `get_version_info()` at import (5+ `git` subprocesses for a User-Agent); `main()` then runs `_warn_pending_fleet_restart_on_startup` (`git` via `get_code_identity`, ~0.8-1.7 s). Fork-side cut so far: the land/q4 version-info cache (boot 6 → 4.2 s); a test-child shortcut is rowed in fork-hygiene-queue. Upstream PR candidates: lazy OPTIONAL_ENV_VARS injection, a lazy User-Agent** · `upstream` · evidence: the HQ3 commit message on lane/hq-b (`perf(cli): …`, profiles 2026-10-01) · PR candidates (w3-perf 2026-10-01): (a) defer `_inject_profile_env_vars`' provider discovery — `OPTIONAL_ENV_VARS`, `CORE_DECLARED_ENV_NAMES` and the platform-manifest precedence together behind one accessor; (b) build the fireworks User-Agent on first request — drafted as local branch `up/fireworks-lazy-user-agent` (57735398159, red recorded); (c) ask git only when the fleet receipt is unfinished or stale · RULED 2026-10-15 owner: approved: open upstream PRs (a) and (b) · BLOCKED 2026-10-18: upstream — re-measured 2026-10-18: `import hermes_cli.config` 1.6–3.1 s under a concurrent test run, module body 0.59 s self (`-X importtime`) · re-measured 2026-10-18 lane h5-boot (test venv, warm bytecode, sandbox home; cProfile to the serve's `ready` frame): `hermes_cli.config` 0.70–1.04 s of which `_inject_platform_plugin_env_vars` 0.42–0.62 s (23 platform manifests parsed again, then re-parsed by the manifest scan) and `_inject_profile_env_vars` 0.16 s; `main()` startup work `_recover_update_debts_on_startup` 0.25–0.44 s and `_warn_pending_fleet_restart_on_startup` 0.24–0.40 s; `hermes_cli/main.py` module-scope command imports a read-only verb never runs — `hermes_cli.backup` (→ `hermes_state_dbfile` → `agent.context_compressor`) 0.22–0.99 s, `model_setup_flows_local` (asyncio) 0.14–0.20 s, `secrets_cli` (rich) 0.10–0.18 s, `update_cmd` 0.2 s, `kanban` 0.23 s, `pm.install` 0.07–0.10 s; upstream share of a `harness --json status` import self-time 0.91 s vs fork 0.50 s · PR candidate (d): `main.py`'s command-module imports move into their `cmd_*` handlers · issue texts (a)–(d) above; (b) drafted `up/fireworks-lazy-user-agent` (57735398159) · every caller is upstream import-time or `main()`, so no fork memo

### Filed on arrival — 2026-10-03 (launcher orchestrator, owner verdicts)
- **`RT-SEED-DOOR-FIT-PARTIAL` — Seed the door-fit PARTIAL keys (`mcp_servers.<s>.env`, `credential_pool_strategies`, `skills.create_dir`/`external_dirs`/`disabled`, `toolsets:`, `approvals.deny`, `HERMES_MANAGED_DIR`) on persona create — owner ruled 2026-10-03 that HERMES seeds them, not the launcher; the values in `docs/agent-runtime-harness/planned/door-fit-2026-09-27.md` § CARRY-DELETE still need owner picks** · fork / persona create · **RULED 2026-10-10 owner:** orchestrator drafts default seed values from door-fit-2026-09-27.md for the owner to approve · plan `docs/agent-runtime-harness/planned/persona-create-seed-values-2026-10-15.md` approved by owner 2026-10-15 · lines 1-2 seeded at mint + startup sweep (`43378428534`, landed with `build/h4-seeds` 28593ecc42d); line 4 seeds with the S3 commit deleting the shared-root search-tier carry; line 5 needs a placement→incompatible-skill computation; line 6 names an unregistered `eternia-persona` toolset and would flip every persona to `profile_config`; line 8 has no glob form of the class+grant envelope (plan § Build status) · BLOCKED 2026-10-16: owner decision — line 3 (`skills.create_dir` = shared root) lets skill_manage write straight into the published root past the hash-guarded promotion door; seed it? · Recommend: no, keep creates profile-local and promote

### Filed on arrival — 2026-10-03 (lane h-twins)

### Filed on arrival — 2026-10-03 (launcher lane rpc-census, filed by the orchestrator)

### Filed on arrival — 2026-10-03 (cold first-chat diagnosis, filed by the launcher orchestrator)

### Filed on arrival — 2026-10-03 (lane h-chatperf)
- **`RT-NATIVE-HISTORY-REREAD` — Native history is re-read from SessionDB and re-filtered against the turn ledger on every turn though the resident actor holds the same lineage; now measured as `context_native_history_ms`** · fork / `hermes_cli/harness_parts/persona/chat_turn_commit/run.py::_build_context` · decide whether a reused actor whose `native_revision` is unchanged may hand its own messages to the turn (SessionDB stays the authority, the revision is the guard) · evidence: turn `15c73e0c` had 168 ms of `context_built` unattributed (1035 − preload 858 − hud 7 − signature 2) · RULED 2026-10-10 owner: yes: a reused actor with an unchanged `native_revision` hands its messages to the turn; SessionDB stays the authority, the revision the guard · plan `docs/agent-runtime-harness/planned/sessiondb-lineage-stamp-2026-10-15.md` approved by owner 2026-10-15; S1–S3 built on `build/h1-lineage` (the turn hand-off is S3, 52.6 → 6.4 ms on an 800-message lineage); S4, the upstream door draft, waits on the orchestrator sequencing it with Phase B wave 2 · S1–S3 landed (fc3350d3044; `build/h1-lineage` has no unlanded patch) · BLOCKED 2026-10-18: upstream — S1–S3 on main (fc3350d3044; 52.6 → 6.4 ms on an 800-message lineage); S4 issue text: "SessionDB has no public lineage revision; expose a per-session message revision readable without reading the lineage" · plan `docs/agent-runtime-harness/planned/sessiondb-lineage-stamp-2026-10-15.md` § S4

## Filed on arrival — 2026-10-09 (owner: a built-in way to message a persona through the running serve)

## Filed on arrival — 2026-10-09 (perf programme close-out sweep)

- **`RT-SEND-PREP-FIXES-LIVE-PROOF` — OWNER live proof owed for the 2026-10-09 send-prep fixes: on a rebuilt serve, ~8 warm Neko/Dev turns (one Dev chat of 20+ rows) and read `turn-timing`: (a) tool-form one owner (`settle_turn_tool_form`, plan `docs/agent-runtime-harness/planned/tool-form-one-owner-2026-10-08.md`) — `mcp_refresh_ms`≈0 and `tool_form_receipt source=unchanged publishes=0 pin_written=0` on warm turns, warm median vs 259.5 ms; (b) the native-revision double read (`f7c61ff2ac`) — matched before/after on the 20+ row chat; (c) the 400 ms warm `send_prep_total` budget holds. All three are fixture-proved only** · fork / send-prep · evidence: tool-form S0–S4, opus-w1-sendprep report · lane: operator live turns (an agent can send them with `hermes harness mission-chat message`, which now runs in the live serve) · BLOCKED 2026-10-16: owner sitting — ~8 warm Neko/Dev turns on a rebuilt serve, read off `turn-timing`

## Filed on arrival — 2026-10-09 (GenUI wire receipts)



## Filed on arrival — 2026-10-09 (Console history authority audit)

## Filed on arrival — 2026-10-09 (launcher transcript capability audit; the launcher halves are in `eternia_launcher/Launcher_Brain/20 — Active Initiatives/mission-control-queue.md` under the same-dated heading)
- **`RT-TURN-LEFT-BEHIND-RECORD` — No turn-level record says what a turn left behind — tests run and their verdict, commits made, whether they were pushed; `commit` appears only in realm sync and the build stamp.** fork / the turn record, `agent/tool_executor.py` · Derive a typed turn-outcome record from the turn's own tool results (terminal commands matching test/commit/push shapes, their exit codes, file tools' paths) and project it on the turn; a client renders it in its fold summary. Decide first whether derivation belongs to a plugin hook or the executor. Starting point, verified 2026-10-14: upstream `agent/turn_summary.py::TurnSummaryCollector` already tallies a turn from `tool.completed` events ("edited 2 files +18 -3 · read 4 files · ran 3 commands"), but it is CLI display only (`hermes_cli/cli_status_bar_mixin.py`), skips failed calls, and no serve RPC verb or `api_server` endpoint carries it; `TurnReceipt` (execution state) and the settle `TurnOutcome` (accepted/refused) are not this record either. · RULED 2026-10-10 owner: derive the turn outcome in a plugin hook, not the upstream executor · NEEDS PLAN 2026-10-18: proposed shape — the eternia-harness plugin registers `post_tool_call` and folds each turn's terminal/file results into one typed `TurnOutcome` {tests: [{command, exit_code, verdict: passed|failed|unknown}], commits: [{sha, pushed: bool|null}], files: [{path, op}]} keyed by `turn_id` (classifier: a table of command shapes, never an if-ladder), persisted on the turn's `mission_chat_turns` row at settle and read by `runtime.operator.conversation.read`; never a parity-envelope key. Owed before exec: the launcher fold-summary row that consumes it (none filed) and the owner's still-standing 2026-10-15 deferral

## Filed on arrival — 2026-10-09 (lane h-hud-receipt)


## Filed on arrival — 2026-10-10 (lane h-settle-push)


## Filed on arrival — 2026-10-10 (lane h-busy-queue)



## Filed on arrival — 2026-10-10 (launcher lane q-turn)


## Filed on arrival — 2026-10-12 (launcher lane q-mc)




## Filed on arrival — 2026-10-15 (Claude sol-prov landing)


## Filed on arrival — 2026-10-15 (launcher QA provider check)


## Filed on arrival — 2026-10-15 (lane w1015-prov-l)


## Filed on arrival — 2026-10-15 (launcher lane console-scroll-2)


## Filed on arrival — 2026-10-15 (launcher lane w1015-misc-l)


## Filed on arrival — 2026-10-15 (owner rulings: hermes builds first for the Agent Console)

- **`RT-EMIT-RUNNING-WORK-CHAT` — Emit running_work and chat mints on the patch lane** — the launcher row "running_work and chat mints on the patch lane" waits on the hermes emitter. OWNER RULING 2026-10-15: on hermes' next wave · fork / serve patch lane · the chat half shipped: a chat turn's running_work row and a new chat's open ride the `persona_chat_turn` / `persona_chat_open` frames (a317870c7f); left is non-chat running_work (build and terminal rows), whose terminal writer is upstream `tools/process_registry.py` · RULED 2026-10-16 owner: no — no read-time projection writes `state.patched` for build/terminal running_work rows; they stay on the full-core lane until hermes owns a fork chokepoint that writes them (reverses the 2026-10-15 yes) · NEEDS PLAN 2026-10-18: no fork chokepoint exists to hang a keyed `state.patched` off — terminal rows are written only by upstream `tools/process_registry.py` (no spawn/exit listener) and announced builds by the job's own external writer (`builds.registry` records). Proposed: an additive upstream seam `ProcessRegistry` spawn/exit listener (a held PR row in `docs/agent-runtime-harness/planned/upstream-footprint-ledger.md`), a fork listener that writes the keyed running_work patch, and announced builds left on the full-core lane

## Filed on arrival — 2026-10-15 (lane w1015b-con-x)


## Filed on arrival — 2026-10-15 (owner: provider SDKs on first setup)



## Filed on arrival — 2026-10-15 (lane e-triage: blockers with no row)


## Filed on arrival — 2026-10-15 (launcher lane w1015e-mc-l)

## Filed on arrival — 2026-10-15 (lane w1015i-packs)

## Filed on arrival — 2026-10-15 (lane w1015j-hermes)


## Filed on arrival — 2026-10-15 (backend build wave A, realms)

- **`RT-MAP-BACKEND-409-REALMS` — Map backend `409 realms.git_host_binding_lost` like `realms.git_host_unbound` (stop retrying), not to `sync_remote_unreachable`** · `hermes` · the backend's realm sync used to answer a permanent 503 when the GitHub App binding vanished mid-sync; since backend `0543d8b6` (REALM-SYNC-PERMANENT-503-1) it is a typed 409 that will not heal on retry · backend `docs/architecture/contracts/nexus/FRONTEND_STAGES.md` realms errors. · READY 2026-10-16 · **TAKEN 2026-10-18 w2-realm**



## Filed on arrival — 2026-10-16 (backend build wave B, realms)

- **`REALM-REVOKED-CLIENT` — on backend `realm.revoked` (`personal:`, durable) mark the realm credential expired, stop its sync loop, keep local data; on reason `git_host_unbound` also surface host state** · `hermes` · backend `docs/architecture/02-realms-nexus.md` §4, EVENT_CATALOG `realm.revoked` (backend lane b-commerce, wave B) · `docs/agent-runtime-harness/03-transport-and-wire.md`. · READY 2026-10-16 · **TAKEN 2026-10-18 w2-realm**
- **`REALM-LOCAL-CRED-SOURCE` — local realms take their credential from the launcher via backend `POST /api/me/realms/local:<id>/sync/credential` (frozen credential JSON, `realm_id=local:<id>`); keep the local allow stub** · `hermes` · backend 02 §4c · `docs/agent-runtime-harness/01-system-architecture.md` § Realm sync. · READY 2026-10-16 · **TAKEN 2026-10-18 w2-realm**
- **`REALM-COURSE-SUBJECT` — map `realm_id = course:<id>` in `RealmSyncCredential` (education git courses now mint clone credentials through backend `POST /api/education/git-courses/{id}/clone-credential`)** · `hermes` · backend lane b-edu, wave B 2026-10-16, `docs/architecture/planned/education-git-course-lane.md` Stage 5. · READY 2026-10-16 · **TAKEN 2026-10-18 w2-realm**


- **`RT-OPERATOR-CHAT-SEND-PERSONA` — The operator chat send (`persona.chat.send` / the chat turn) accepts text only, so a pasted image never reaches a vision model: accept bounded image content parts (PNG/JPEG; the launcher converts BMP/clipboard formats), pass them to the provider as image parts for a vision-capable model, and refuse with a typed error for a model without vision** · seam / operator chat send · launcher `mission-control-queue.md` "A pasted image never reaches the model" (launcher half: `lib/features/agent_console/panel/agent_console_pasted_image_policy.dart` `messageWithPastedImages` sends a text manifest only) · owner sitting 2026-10-15 · READY 2026-10-18: the launcher half `MC-PASTED-IMAGE` (`mission-control-queue.md`) is BLOCKED hermes on this row, so hermes moves first and the launcher mirrors this param. Proposed shape: `images: [{media_type: image/png|image/jpeg, data_b64}]` on the send (≤4 parts, ≤5 MiB decoded each, magic-byte check, typed refusals `image_invalid` / `image_too_large` / `vision_unsupported`); bytes stored content-addressed under the store root beside the session and named on the pre-persisted operator row (so a reused row on retry keeps them and `runtime.media.get` serves the bubble); `AgentRunRequest` gains `user_image_paths` passed to upstream `build_native_content_parts`; `vision_unsupported` when `decide_image_input_mode` answers `text` · **TAKEN 2026-10-18 w2-turn**

### Filed on arrival — 2026-10-16 (launcher lane w1016c-mc)

- **`RT-MISSION-CHAT-MESSAGE-TAKES` — `mission.chat.message` takes reviewed files and publishes their limits** — the launcher Agent Console composer can attach files only once the chat send carries `prompt.files`-style reviewed files and the console can read their count/size/type limits; today the console sends text-only `mission.chat.message`, so its Attach button would do nothing · fork / serve chat send · launcher row: Agent Console Attach file in `EterniaLauncher/Launcher_Brain/20 — Active Initiatives/mission-control-queue.md` (BLOCKED hermes), plan `EterniaLauncher/docs/mission_control/planned/CONSOLE_ATTACH_FILE_2026-10-16.md` · NEEDS PLAN 2026-10-16: the send shape for reviewed files, where the limits are published (ready/hello_ok like `rpc.limits.operator_text`), and the review/redaction path

### Filed at the launcher w1016 wrap-up — 2026-10-16

- **`RT-ETERNIA-SKILLS-LENDS-SKILLS` — `eternia.skills.*` lends skills to a Work task or worker** — the calls take only the parent session (no `child_ref`), so a worker cannot be given skills; the launcher's skills-expansion row (owner ruling 2026-10-16: the Work/worker journey first) waits on this · fork / skills seam · launcher row: skills expansion in `EterniaLauncher/Launcher_Brain/20 — Active Initiatives/companion-queue.md` · RULED 2026-10-18: owner — lending is a write verb · BLOCKED 2026-10-18: another lane — `RT-WORK-W2-WRITER` gives a Work task its persona owner
- **`RT-RUNTIME-LENS-PREVIEW-RETURNS` — `runtime.lens.preview` returns the raw source read and never applies `typed_reading`, so a preview shows a value the poller would store as a `type_mismatch`/`implausible` gap (L0 remainder, hermes `q/r-lens` 285cef8e99)** · fork / lens · lane r-lens report 2026-10-18 · READY 2026-10-18 · **TAKEN 2026-10-18 w2-lens**

### Filed on arrival — 2026-10-18 (lane q-reds, branch `q/q-reds`)
- **`RT-WINDOWS-SOURCE-HERMES-UPDATE` — On Windows a source `hermes update`'s `--prepared` completion child refuses its own bootstrap's checkout lease ("its owner exited but a process it started still holds the checkout"), so the tail is always owed** · upstream-owned (`hermes_cli/update_completion.py::_prepare`, `hermes_cli/source_completion.py::complete_source_checkout`) · red on pure tag v0.22.2 `d923a5eb48`: 5 of the 9 `tests/hermes_cli/test_update_completion_process.py` reds now xfailed in `tests/_downstream/id_markers/upstream_reds_v0222.py` (`_COMPLETION_ROWS`) · upstream issue; the strict xfail retires on its fix · READY 2026-10-18 · **TAKEN 2026-10-18 w2-reds**

### Filed on arrival — 2026-10-18 (lane q-stale, branch `q/q-stale`)
### Filed on arrival — 2026-10-18 (lane q-stale, branch `q/q-stale`)
- **`RT-15-FORK-HUNKS-SIT` — 15 fork hunks sit inside upstream functions v0.22.2 rewrote since v0.21.7 (`agent/agent_init.py::init_agent`, `tools/tool_search.py` ×3, `tools/connectors/search.py` ×3, `tui_gateway/*` ×5, `runtime_provider_custom`, `pm/environment`, `tools/environments/local`): re-read each against the new body — still needed, still placed right, or now a hook** · seam / upstream-merge · `Harness_Brain/20 — Active Initiatives/stale-fork-test-sweep-2026-10-18.md`; `python scripts/upstream_retirement_scan.py --arm hunks` · READY 2026-10-18 · **TAKEN 2026-10-18 w2-seams**

- **`RT-LENS-W5-TOTAL-COST` — Lens W5 total-cost value (price + shipping + estimated tax, dated exchange-rate feed), the W2(c) median/deviation outlier guard for fast feeds, and W7 adaptive cadence (tighten as a deadline nears, a confirming read before the turn) are not built; L0 remainder shipped money-with-currency, instants, plausible range, confirm_reads and the four §6a rules** · fork / lens · plan `eternia-lens-in-hermes.md` §6b W2 W5 W7; `agent_runtime/lens/feed.py`, `rules.py`, `poller.py` · READY 2026-10-18 · **TAKEN 2026-10-18 w2-lens**

- **`RT-CHARSHEET-JSON-VERBS-STATE` — Charsheet JSON verbs state no root: 18 `_cmd_characters_*` verbs answer an empty library from a wrong home with `ok: true`; attaching resolution is a `charsheet_payload_contract.json` + launcher-mirror change** · fork / json-root · `tests/hermes_cli/test_harness_json_root_observability.py` LEDGER (`_CHARSHEET_REASON`), build-1011-C4; the 6 workspace-slot verbs landed (lane r-wire 2026-10-18, `_emit_workspace_slot_verb`) · the charsheet verbs answer from HERMES_HOME (`characters_dir`), not the store root · READY 2026-10-18: the launcher mirror `MC-CHARSHEET-HOME` is filed (READY) and mirrors the re-vendored contract, so hermes moves first — proposed shape: one top-level `home: {hermes_home, characters_dir, source}` block on every charsheet envelope (not the store-root `resolution`, which names the wrong root for this family), added to the contract's envelope key set, regenerated by `scripts/dump_payload_contract.py` and landed paired with the launcher mirror · **TAKEN 2026-10-18 w2-seams**
- **`RT-WHETHER-UPSTREAM-POST-TURN` — Whether upstream's post-turn `agent/background_review.py` fork runs on persona turns is unmeasured: `turn_finalizer` spawns it when `_should_review_memory` or `_should_review_skills` (10 tool iterations and `skill_manage` on the lane) holds, and no fork site passes `skip_background_review`** · fork / memory · prep-cost class; the read half landed as `runtime.operator.conversation.memory` (lane r-wire, 2026-10-18) · lane: count review spawns over ten live persona turns from a receipt, then rule `skip_background_review` per persona · BLOCKED 2026-10-18: owner sitting — ten live persona turns on the owner's serve

### Filed on arrival — 2026-10-18 (lane r-product, branch `q/r-product`)
- **`RT-BUNDLE-PROFILE-GATE-PROFILE` — `scripts/bundle_profile_gate.py --profile bundled-phone` is REFUSED at tip (36 findings) although the runtime phone turn is clean: `tools.connectors.gateway.wire` is still statically reached (pinned) through `tools/connectors/gateway/files.py`'s module-scope import; shipped `fastapi` (reached via `hermes_cli.model_setup_flows_local`) requires omitted pydantic/pydantic-core; `openai` unguarded in `agent_runtime.first_turn_warmup`; `psutil` unguarded in `chat_turn_reservations`, `builds.detect`, `conversations.process_evidence`; 31 `subprocess_call` sites** · fork-owned (`agent_runtime/bundle_profiles/bundled-phone.yaml`, the named modules) · evidence: gate run at `0608addbe4` (lane r-product); `tests/agent/transports/test_sdk_free_phone_imports.py` + `test_embedded_phone_session.py` 7 passed on the same tip · lane: phone-closure · READY 2026-10-18 · **TAKEN 2026-10-18 w2-phone**

### Filed on arrival — 2026-10-18 (lane h2-sleep)
- **`RT-ROOM-LEASE-LAPSES-MID-CYCLE` — The hosted-room driver renews its room lease only between room cycles (`tui_gateway/hosted_room_driver.py::_ensure_lease` / `_renew_lease_if_needed`), so a cycle that blocks longer than the lease TTL loses the lease mid-turn and the turn never settles; and a successor serve adopts a room whose owner left a task running only once the old lease expires (up to 30 s of restart recovery, the fork's `DiscussionService` default)** · upstream / discussions room driver · lane h2-sleep 2026-10-18: at a 5 s test TTL a real-native room cycle ran 6.5 s and `test_real_group_compare_discuss_target_and_reopen` red; the fork now sets the TTL through `DiscussionService(lease_ttl=)` (8bcbe70242) · BLOCKED 2026-10-18: upstream — issue text: "`HostedRoomRuntime` renews a room lease only between cycles; renew from a heartbeat while an attempt executes, and let a successor with the same gateway identity adopt a lease whose `process_generation` is provably dead instead of waiting out the TTL"

### Filed on arrival — 2026-10-18 (lane h3-plugins, branch `q/h3-plugins`)
- **`RT-BASIC-AUTH-IMPORT-SCRYPT` — `plugins/dashboard_auth/basic/__init__.py` runs scrypt (n=2^14) at import for `_DUMMY_HASH`: ~0.25 s CPU each time the bundled plugin is imported, at every boot that loads plugins and at every test discovery (252 s of the 478 s plugin-phase CPU over the top 15 suite files)** · upstream / dashboard auth · evidence: lane h3-plugins report, commit `0c4104f40a` body (bucket profile: 1,002 imports, 252.1 s in `hashlib.scrypt`) · fix: an upstream PR computing the dummy hash lazily on the first unknown-username login (the fork may not edit the file) · READY 2026-10-18 · **TAKEN 2026-10-18 w2-seams**

### Filed on arrival — 2026-10-18 (lane h4-hotpath, branch `q/h4-hotpath`)
- **`RT-I18N-BUNDLED-PER-HOME` — `agent/i18n.py::_load_catalog` re-parses the bundled locale YAML once per `(HERMES_HOME, lang)`: 23.8% of 3,668 profiled seconds over 12 files (68% of `test_goal_dispatch`)** · upstream / i18n · [[r-perf-2026-10-17]] § h4-hotpath · BLOCKED 2026-10-18: upstream — issue text: "`_load_catalog` caches the merged catalog per `(home, lang)`, and on a miss `_load_bundled` re-parses `locales/<lang>.yaml` (260–330 KB; ~0.65 s with pure-Python ruamel 0.18.16, which 3.14 installs without the C loader). The bundled layer does not depend on the home, so every new profile home — each profile of a multiplexed gateway, each profile `gateway migrate` plans for, each test home — pays the full parse again. Cache `_load_bundled(lang)` by the file's `(path, mtime_ns, size)` and merge the home's overlay/pack layers over a copy; `reset_language_cache` clears it."
- **`RT-CONFIG-NOFILE-REBUILD` — `hermes_cli/config.py::_load_config_impl` caches nothing when the home has no `config.yaml`, so every read rebuilds the defaults (~2 ms; 61,049 rebuilds, 14.6% of 3,668 profiled seconds, all 23 files)** · upstream / config · [[r-perf-2026-10-17]] § h4-hotpath; the class behind `RT-SQLITE-JOURNAL-MODE-RERESOLVE` · BLOCKED 2026-10-18: upstream — issue text: "`_load_config_cache_sig` returns `cache_sig=None` when neither the user nor the managed `config.yaml` exists, and `_load_config_impl` then skips `_LOAD_CONFIG_CACHE`, so each `load_config`/`load_config_readonly` deep-copies `DEFAULT_CONFIG`, canonicalizes and expands it again (2.1 ms vs 0.11 ms with a file, Windows). Readers that run per item multiply it: `plugins_loader._resolve_plugin_load_timeout` reads config once per plugin load (16,022 calls in 12 test files), `hermes_state_wal.resolve_journal_mode` once per SQLite open. Cache the absent state under a sentinel signature (`(0, 0, 0, 0)` for the missing user file, as the managed half already does); creating the file changes the signature, so the next read sees it."
- **`RT-AUX-KEY-CHAIN-LOAD-CONFIG` — `agent/auxiliary_client._resolve_api_key_provider` walks ~48 providers per auto resolution, each paying `hermes_cli/auth._model_level_key_env` → `load_config()` (a full deepcopy) plus a pool load: 34 resolutions → 1,530 `load_config`, 1,648 pool loads, 40% of `test_compression_rotation_state`** · upstream / auxiliary client · [[r-perf-2026-10-17]] § h4-hotpath · BLOCKED 2026-10-18: upstream — issue text: "When no auxiliary key is configured, `_try_discovery_chain` → `_resolve_api_key_provider` tries every API-key provider; per provider `resolve_api_key_provider_credentials` → `_resolve_api_key_provider_secret` → `_model_level_key_env` calls `load_config()` (a deepcopy of the whole merged config) only to read `model.provider`/`model.key_env`, and `_select_pool_entry` → `_load_pool_with_credentials` loads the pool. Read the `model` block once per resolution (or use `load_config_readonly()` — the value is only read) and skip providers with no pool and no env key before loading their pool. Each compression's auxiliary resolution pays the whole walk."

## Filed on arrival — 2026-10-18 (lane h5-boot)
- **`RT-HARNESS-ARGV-MANIFEST-SCAN` — Every `hermes harness …` process (each CLI call, each serve boot, each test child) parses all 57 plugin manifests to find the one `cli_commands: harness` row: `harness` is not in `_BUILTIN_SUBCOMMANDS`, so `attach_declared_cli_command` runs the full `collect_directory_manifests` scan (~130–150 ms prod venv with ruamel's CParser, ~270 ms test venv, 0.6–0.9 s under cProfile)** · fork-owned · `hermes_cli/plugins_manifest_cli_commands.py::discover_declared_cli_commands` · measured lane h5-boot 2026-10-18 (in-process timer + cProfile to `ready`) · options: a manifest-fingerprint cache in `HERMES_HOME` (over-approximated stat walk; re-parse only the declaring manifest; gate live), a text prefilter that keeps winner and gate semantics, or `harness` as a built-in verb (drops the plugin-disable gate for it) · NEEDS PLAN 2026-10-18: which option keeps the seam's precedence and enable gate identical without duplicating upstream's directory walk
- **`RT-TEST-VENV-PURE-YAML` — The test venv (`~/.venvs/hermes-test`, CPython 3.14) has no `ruamel.yaml.clib`, so every YAML load in tests and test-spawned hermes children runs ruamel's pure-Python parser (57 manifest loads 270–290 ms vs 92–130 ms in the 3.12 runtime venv); and a session that exports `PYTHONDONTWRITEBYTECODE=1` (this lane's shell did) makes each child compile ~535 modules (`compile` 1.39 s of a 4.6 s `harness --help`)** · fork hygiene (test env) · measured lane h5-boot 2026-10-18 · install a cp314 `ruamel.yaml.clib` wheel when one exists, and have the test runner drop `PYTHONDONTWRITEBYTECODE` for children or say why not · READY 2026-10-18 · **TAKEN 2026-10-18 w2-speed-b**
- **`RT-FLEET-CHECKOUT-ANCESTRY-RED` — `tests/hermes_cli/test_update_fleet_checkout_build_stamp.py::test_git_checkout_still_walks_ancestry` is red on `origin/main` 3fd8545759 (alone, test venv): it patches `chk.subprocess.run`, but upstream `ea665a911d` moved `checkout_contains` onto `hermes_cli.update_custody.run_git`, so the stub never answers and the probe fails closed (`assert False is True`)** · upstream-owned (code and test both upstream) · `hermes_cli/update_cmd_fleet_checkout.py::checkout_contains` · found lane h5-boot 2026-10-18 · an `_up_red` marker in `tests/_downstream/id_markers/upstream_reds.py` plus the upstream issue text "test stubs subprocess.run after the custody move" · READY 2026-10-18 · **TAKEN 2026-10-18 w2-reds**

## Filed on arrival — 2026-10-18 (land h1018)


## Filed on arrival — 2026-10-18 (owner sitting: Work on todo boards)

- **`RT-WORK-W1-STORE` — Work W1: the todo-board store — slot-driven board over each bound repo's `type: queue` notes, the grammar's optional `assignee: persona:<id>` segment (ADR 0011 + launcher ADR 0025), engine IDs `WORK-<6>`, and the auto-created default brain (`<store_root>/work/<workspace>/brain/`, `git init`, `Work_Brain/TODO.md` + `work-queue.md`) bound as slot `brain`** · fork / Work · `docs/agent-runtime-harness/planned/work-on-markdown-2026-10-18.md` §2–§4 · RULED 2026-10-18: owner — Work = the workspace's todo board (the brain queue notes of every repo folder the workspace binds), worked by persona instances, written through hermes's own worktree with replay-by-ID; reads from the tip via `runtime.work.list`; done = row deleted; assignee `persona:<instance>` or `persona:<persona_id>`; claim-only first; default brain local-only until `slots.declare`; hermes's own per-machine commit identity; agent `work.*` tools = engine only first; kanban retirement as W5 · READY 2026-10-18
- **`RT-WORK-W2-WRITER` — Work W2: hermes the one writer per machine in its own worktree `work/<machine_id>` (fetch → reset to tip → op by ID with tip-checked refusals → one commit → fast-forward push → replay on a lost race; never merge/pull/stash), `runtime.work.*` keyed by persona instance (replaces `agent_runtime/work/native.py::scopes`' upstream-profile owners and `context.py::_operator`'s persona refusal), `scripts/work_row.py` for sessions** · fork / Work · `docs/agent-runtime-harness/planned/work-on-markdown-2026-10-18.md` §5 · BLOCKED 2026-10-18: another lane — `RT-WORK-W1-STORE` lands the store first
- **`RT-WORK-W3-ENGINE` — Work W3: the worker engine (`agent_runtime/work_store/engine.py`) — claim `TAKEN … persona:<instance_id>` → hand-off as that instance's chat turn → write back by ID (done = delete, question = BLOCKED owner decision, stop = claim released); built behind an executor interface so batch lanes and upstream engines plug in later (`RT-DISPATCH-B5-LANE-EXECUTOR`)** · fork / Work · `docs/agent-runtime-harness/planned/work-on-markdown-2026-10-18.md` §3 · BLOCKED 2026-10-18: another lane — `RT-WORK-W2-WRITER`
- **`RT-WORK-W5-KANBAN-RETIRE` — Work W5: retire the fork's kanban code — `agent_runtime/work/native.py`'s kanban imports, `hermes_cli/kanban_blocked_pm.py`, `kanban_blocked_pm_tick.py`, `kanban_crash_evidence.py`, the eternia-harness plugin's two kanban hooks and their five tests; `test_no_kanban_dependency` back to the blanket prohibition; ADR 0015's "kanban unused" then holds for fork code and the kanban skip rows stay right** · fork / Work · `docs/agent-runtime-harness/planned/work-on-markdown-2026-10-18.md` §6 · BLOCKED 2026-10-18: another lane — `RT-WORK-W2-WRITER`

## Filed on arrival — 2026-10-18 (design: dispatcher and libraries)

- **`RT-DISPATCH-B1-CONTRACTS` — the three library contracts: `work_store/{reasons,source,executor,scheduler}.py`, `ManualScheduler`, fakes; one `Reason` enum for every Work refusal** · fork / Work · `docs/agent-runtime-harness/planned/dispatcher-and-libraries-2026-10-18.md` §2, §6 · BLOCKED 2026-10-18: another lane — `RT-WORK-W2-WRITER` lands the writer the SOURCE wraps
- **`RT-DISPATCH-B2-BATCH` — the batch dispatcher: `agent_runtime/batch/{planner,machine,manifest,rpc}.py`, thick lanes by `Domain(slot, note, heading)`, the state table, manifest notes under `50 — Agent Handoffs/batches/`, `runtime.batch.plan|start|status|stop|land|approve`, manual by default** · fork / Work · `docs/agent-runtime-harness/planned/dispatcher-and-libraries-2026-10-18.md` §3 · RULED 2026-10-18: owner — the batch manifest lives in the workspace's default brain; a lane whose rows name no assignee gets a persona by roster role match, and the operator is asked when none matches; `batch_automation` is `off | plan | start`, default `off`, and land/approve are never automated; stop waits for the running turn to end; a lane's size is budgeted by how big its rows are (estimated effort/files touched), not a fixed row count — 65 rows is only a ceiling · BLOCKED 2026-10-18: another lane — `RT-DISPATCH-B1-CONTRACTS`
- **`RT-DISPATCH-B3-PERSONA-EXECUTOR` — W3's engine as `PersonaTurnExecutor` behind the `Executor` contract, plus `runtime.chat.goal.set|status|pause|resume|clear` over `GoalManager` and the after-turn continuation hook (`RT-GOAL-ENGINE-DOOR` lands here)** · fork / Work, chat RPC · `docs/agent-runtime-harness/planned/dispatcher-and-libraries-2026-10-18.md` §2.2, §5 · RULED 2026-10-18: owner — goal gates built from the brief's test commands, on by default for `UNTIL_DONE` · BLOCKED 2026-10-18: another lane — `RT-WORK-W3-ENGINE`
- **`RT-DISPATCH-B4-SCHEDULER` — the fork's `ServeTickScheduler`: one 60 s serve tick, `store/schedules/<key>.json`, triggers `MANUAL|AT|EVERY|CRON|WHEN_IDLE`, `scheduler.max_parallel` default 4, the `schedule_manage` tool, `runtime.schedule.arm|disarm|list`, `Trigger.from_cron_job`; closes `RT-D1/D3/D5/D6` as moot and leaves cron on ADR 0015's list** · fork / scheduling · `docs/agent-runtime-harness/planned/dispatcher-and-libraries-2026-10-18.md` §2.3, §4 · RULED 2026-10-18: owner — scrap upstream cron for the fork's own scheduler (`598bedea` stays on its branch as evidence; `Trigger.from_cron_job` is the one compatibility door); the desktop runtime's scheduler is the official one; on mobile a schedule rides the OS scheduler (the Launcher's `OsReminderScheduler`; iOS limits background work), with an OS-independent mobile path a later goal (`MC-MOBILE-SCHEDULES-OS`) · BLOCKED 2026-10-18: another lane — `RT-DISPATCH-B1-CONTRACTS`
- **`RT-DISPATCH-B5-LANE-EXECUTOR` — `BatchLaneExecutor`: worktree beside the clone via `run_git`, brief file from the skeleton (≤ 40 lines), per-run workdir override, the landing lane, push to `main` only behind `approve`** · fork / Work · `docs/agent-runtime-harness/planned/dispatcher-and-libraries-2026-10-18.md` §2.2, §3.2 · BLOCKED 2026-10-18: another lane — `RT-DISPATCH-B2-BATCH`
- **`RT-SCHEDULE-TURN-RUNNING-WORK` — a scheduled fire reports as a `running_work` row of kind `scheduled_turn` (the Launcher renders unknown kinds with the raw wire word; no launcher change until it wants a label)** · fork / snapshot · `docs/agent-runtime-harness/planned/dispatcher-and-libraries-2026-10-18.md` §4 · RULED 2026-10-18: owner — a scheduled fire is a new `running_work` kind `scheduled_turn`, not `cron_job` · BLOCKED 2026-10-18: another lane — `RT-DISPATCH-B4-SCHEDULER`
