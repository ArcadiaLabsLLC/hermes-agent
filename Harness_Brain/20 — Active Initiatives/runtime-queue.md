---
type: queue
program: mission-control
status: open
tags: [queue, program/mission-control, runtime]
---

# Runtime — the hermes half of the Mission Control queue



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

### Filed on arrival — 2026-10-21 (lane w1021j-bundle, branch `w1021j/bundle`)

- **`RT-BUNDLED-PHONE-POOL` — the packager's pool installs the whole uv export for a phone target, so `--profile bundled-phone` never reaches verify** · fork / `scripts/bundle_profile_package.py::install_pool` / `export_requirements` · evidence: commit `83bf715c9d` body (omitted_distributions not dropped; psutil git pin unhashable; no phone wheels for cryptography, firecrawl-anydoc, httptools, jiter, markupsafe, pillow, watchfiles, resvg-py) · NEEDS PLAN 2026-10-21: a phone-scoped pool (closure-first, or an omitted-filtered export) · **TAKEN 2026-10-22 w1022a-plan**

### Filed on arrival — 2026-10-21 (land w1021i)

- **`RT-SEED-LINES-6-8-STRIKE` — door-fit seed lines 6 (`toolsets:` names an unregistered `eternia-persona` toolset) and 8 (`approvals.deny`: `hard_floor_command_classes()` is empty after R-2, so a static deny refuses what a grant allows) cannot be seeded as written** · fork / persona seed · plan `docs/agent-runtime-harness/planned/persona-create-seed-values-2026-10-15.md` § Amendment 2026-10-21 · BLOCKED 2026-10-21: owner decision — strike lines 6 and 8, or seed `toolsets: [harness_core]` and only ungranted classes re-seeded on every grant change? · Recommend: strike both
- **`RT-COURSE-AUTHORING-RULINGS` — course authoring stage C3 needs two owner answers: who hands the persona the course credential during a turn, and whether the course installation token may open a PR (the App has contents+metadata only)** · fork / course authoring · plan `docs/agent-runtime-harness/planned/realm-course-subject-authoring-2026-10-21.md` · BLOCKED 2026-10-21: owner decision — Launcher brokers the credential inline, or hermes calls the backend; and add `pull_requests: write` to eternia-server-realms? · Recommend: Launcher inline (hermes holds no player bearer); yes, add the permission, with C3 behind `pull_request_not_permitted` until it lands

### Filed on arrival — 2026-10-21 (lane w1021h-rpc, branch `w1021h/rpc`)

- **`RT-PROVIDER-AUTH-MODE-CONFIGURE` — no RPC verb writes model.auth_mode: the only provider-configure door is argv `harness auth set-key` (stdin secret), and entra_id has no secret** · fork / provider configure · launcher MC-AZURE-IDENTITY-PACK · evidence `14773aad1c` (branch `w1021h/rpc`) · BLOCKED 2026-10-21: owner decision — which profile a mode write targets, and does it also select model.provider? · Recommend: runtime.provider.configure {provider, auth_mode, base_url?} on the bound provider home

### Filed on arrival — 2026-10-21 (lane w1021h-cli, branch `w1021h/cli`)

- **`RT-RESOLUTION-HOME-DELEGATE-AFTER-MERGE` — after the v0.22.3 merge, `agent_runtime/resolution.py::_platform_default_hermes_home` calls upstream's env-pure `hermes_constants._platform_default_hermes_home(environ, user_home)` instead of restating it** · fork / `agent_runtime/resolution.py` · evidence `c1e905df98` (branch `w1021h/cli`) · BLOCKED 2026-10-21: upstream — v0.22.3's release merge into main (owner holds it on `integration/upstream-daily`)
- **`RT-SEED-LINE4-UNBOUND-HOMES` — seeding `skills.external_dirs` (line 4) and deleting the shared-root carry in `agent/skill_utils.py` would drop the shared skills root from every home the persona sweep never seeds (root/head home, unbound profiles)** · fork / persona seed · plan `docs/agent-runtime-harness/planned/persona-create-seed-values-2026-10-15.md` § Build status · BLOCKED 2026-10-21: owner decision — seed every skill-reading home, or keep the carry for unbound homes? · Recommend: keep the carry for unbound homes

### Filed on arrival — 2026-10-21 (launcher lane w1021f-qa-isolation)


### Filed on arrival — 2026-10-21 (launcher lane w1021e-mc-windows)


### Filed on arrival — 2026-10-21 (launcher landing land-w1021c)


### Filed on arrival — 2026-10-21 (launcher plan lane w1021c-plan-mc)


### Filed on arrival — 2026-10-20 (launcher landing land-w1020u review)


### Filed on arrival — 2026-10-20 (launcher lane w1020t-mc-slots)


### Filed on arrival — 2026-10-20 (launcher lane w1020r-mc-office)


### Filed on arrival — 2026-10-20 (launcher lane w1020r-mc)


### Filed on arrival — 2026-10-20 (launcher lane w1020r-dist)


### Filed on arrival — 2026-10-18 (land w6)

### Filed on arrival — 2026-10-18 (lane w6-misc, branch `w6/misc`)

### Filed on arrival — 2026-10-18 (land w5)


### Filed on arrival — 2026-10-18 (land w4)


### Filed on arrival — 2026-10-18 (lane w4-fold, branch `w4/fold`)


### Filed on arrival — 2026-10-18 (landing land-w2)

### Filed on arrival — 2026-10-16 (lane r-realm-lens, branch `q/r-realm-lens`)

- **`RT-LENS-L1-LIVE-PROOF` — Lens L1 has no live proof: a real HTTP feed polled by a running serve, an Episode raised, and the stored evidence row read back redacted** · fork / runtime · r-realm-lens `13cf04f76fa` (no serve started) · BLOCKED 2026-10-16: owner sitting — live: needs an operator serve with `plugins/eternia-lens` shipped

### Filed on arrival — 2026-10-16 (build lane h-bundle-speed, branch `build/h-bundle-speed`)


### Filed on arrival — 2026-10-16 (build lane h3-runser, branch `build/h3-runser`)

- **`RT-POSIX-TURNS-SERIALIZE-BEHIND` — POSIX turns still serialize behind one process lock: the fork writes `HOME` per profile turn because upstream's in-process `expanduser`/`Path.home()` readers have no context hook** · upstream door (run-serialization decision 3) · `agent_runtime/profile_context.py::persona_profile_context` (the `HOME` write and its pinned-readers comment) · draft the one upstream door for a context-aware home hook (`~` in `skills.external_dirs`, the `~/.codex` / `~/.qwen` credential files); once it lands, delete `_PROCESS_HOME_LOCK` on the h3-runser branch and POSIX gets per-root turns like Windows · BLOCKED 2026-10-18: upstream — issue text: "`os.path.expanduser`/`Path.home()` readers (`~` in `skills.external_dirs`, the `~/.codex` / `~/.qwen` credential files) take no home hook, so an embedder serving several profiles in one process must write `HOME` and serialise turns; add one context-aware home resolver those readers call" · no fork-owned caller to memo (the readers are upstream)
- **`RT-SETTLE-PUSH-LIVE-PROOF` — CLI route S4's push half is unproven live: a re-armed settle was due but no listener was attached, so no delivery was observed** · fork / RPC lane · `hermes_cli/harness_parts/serve/settle_push.py::SettlePush._push_due_settles` · with a launcher (or a `harness stream` client) attached, re-arm an undelivered settle from a shell and record the pushed frame and the ack · BLOCKED 2026-10-16: owner sitting — live serve; needs a running serve with a launcher or `harness stream` listener attached (r-turnrec may not start one)

### Filed on arrival — 2026-10-16 (build lane h1-lineage)


### Filed on arrival — 2026-10-16 (build lane h4-seeds)

### Filed on arrival — 2026-10-16 (release merge v0.22.2, daily branch at upstream acc3cada0da)




### Filed on arrival — 2026-10-15 (launcher lane w1015i-mc)


### Filed on arrival — 2026-10-15 (orchestrator: QA bundle build under load)


### Filed on arrival — 2026-10-15 (owner sitting: first real QA bundle build)


### Filed on arrival — 2026-10-15 (owner sitting: send-prep live proof)




- **`RT-CONNECTIONS-TRACE-MISSING` — Connections: trace the missing browser sign-in `done` event for the isolated QA profile.** Owner report/review 2026-10-14: ChatGPT or Codex Subscription web sign-in completed, but the login-stream `done` event did not reach the Launcher and the pane remained pending; the selected isolated profile subsequently had a credential entry and canonical `logged_in=true`. Root cause is unproven: no historical completion frame was captured. Start at producer `hermes_cli/provider_browser_login.py::run_browser_login` (`send` of `done`), trace `agent_runtime/provider_signin.py` and the consumer `EterniaLauncher/lib/shared/provider_connections/provider_connection_state.dart::ProviderSetupController` under the same profile; capture redacted lifecycle/transport evidence and pin reliable terminal delivery. The Launcher projection reconciliation on `fix/sol-connect-20261014` is a safety net, not the root-cause fix. Preserve the QA binding; never capture credentials or account identifiers. · fork / launcher seam · found 2026-10-14 sol-connect review · code read 2026-10-15: run_browser_login sends done only after _save_codex_tokens returns, ProviderSignIns._pump folds it only while the session is ACTIVE, and the registry lives in one serve process, so a serve restart between the credential write and the next poll answers login_not_found to a pane still pending · BLOCKED 2026-10-16: owner sitting — one live ChatGPT/Codex browser sign-in on the isolated QA profile (Windows box), capturing the poll replies and the serve pid

### Filed on arrival — 2026-10-15 (lane w1015h-prov)


### Filed on arrival — 2026-10-15 (launcher lane w1015h-misc-l)


### Filed on arrival — 2026-10-15 (launcher lane w1015h-mc-l)


### Filed on arrival — 2026-10-15 (lane w1015h-comp-l)


### Filed on arrival — 2026-10-15 (lane live-qa)

- **`RT-QA-REUSE-PHANTOM-INSTANCE` — Asked "is there an existing QA session I can reuse to take a Launcher screenshot?", Base answered "Yes" and named instance `personainst_qa_cf20b758ee50`, which is not on the roster (the roster has `personainst_qa`), from four `session_search` calls and no roster/state receipt, and offered reuse instead of a fresh QA instance per task** — the F4/F5 failure of `EterniaLauncher/docs/mission_control/SIX_SCREENSHOT_FINDINGS_2026-10-01.md` reproduced after HQ1/HQ2; the answer should come from the first-class roster/instance detail with its hot/cold state, and an id built from a chat-root suffix must never be offered as an instance · fork / harness-runtime-model skill guidance + `session_search` · evidence: QA home `profiles/base/logs/agent.log` 07:20:53–07:21:13 (2026-10-15, chat `persona_chat_personainst_profile_base_c79130b80c0e`, tool_turns=9); launcher capture `b4-p2-qa-reuse_20261015072114768.png` · launcher row: mission-control-queue "P2 — Investigate Agent Console response/workflow acceptance" · guidance + harness_query schema steer landed bd2ddc962a7 (session_search is history not state, no id cut from a chat root, fresh instance per QA task) · BLOCKED 2026-10-21: launcher — `MC-P2-CONSOLE-WORKFLOW` (itself BLOCKED 2026-10-20 on an owner sitting: re-ask F2–F5 on the owner's Hermes with a provider) · mission-control-queue "P2 — Investigate Agent Console response/workflow acceptance" re-runs the prompt on a Base chat against a live serve

### Filed on arrival — 2026-10-15 (lane w1015h-rt-h)

### Filed on arrival — 2026-10-15 (audit lane a1015-hrt)


### Filed on arrival — 2026-10-15 (lane w1015b-rt-h)


### Filed on arrival — 2026-10-14 (Console execution controls)





### Filed on arrival — 2026-10-12 (composer thinking meter)


### Filed on arrival — 2026-10-11 (lane h-s17, one-action-layer S17)


### Verified Console history PR #7 follow-up — 2026-10-11





### Filed on arrival — 2026-10-10 (D2.07 redesign, filed by the orchestrator)


### Filed on arrival — 2026-10-10 (guard fix, build batch 2 C1–C4, filed by the orchestrator)

- **`RT-BOARD-CARD-FOLD-RUNTIME` — board_card fold: the `runtime.board.*` twins ack but publish no fold; a fold needs its producer inside `board_lock` (board-surface-rpc-lane.md rule 3)** · fork / board · `agent_runtime/serve_rpc/board.py` (build-1011-C4) · plan `docs/agent-runtime-harness/planned/board-card-fold-2026-10-15.md` approved by owner 2026-10-15 · BLOCKED 2026-10-16: owner sitting — S0 live end-to-end timing (ack → full core → Launcher repaint) on a running serve + Launcher, Windows box; S1–S4 gate on its number

### Filed on arrival — 2026-10-10 (build batch 1, build-1011-B1..B5, filed by the orchestrator)


### Filed on arrival — 2026-10-10 (Fable design sweep D1–D3, filed by the orchestrator)


### Filed on arrival — 2026-10-10 (fork-fixable sweep lane-1011, filed by the orchestrator)


### Filed on arrival — 2026-10-10 (queue sweep lane-1010, filed by the orchestrator)


### Filed on arrival — 2026-10-10 (release merge v0.21.6 reds)


### Filed on arrival — 2026-10-09 (owner report: "this chat I cannot delete")

### Filed on arrival — 2026-10-09 (owner report: Agent Console silent after the toolvis 1b landing)

### Filed on arrival — 2026-10-08 (launcher lane opus-qa-hygiene)

### Filed on arrival — 2026-10-08 (gateway restart after a live-checkout fast-forward)
- **`RT-GATEWAY-START-MANAGED-PYTHON` — `hermes --profile alice gateway start` raises `ManagedPythonUnavailable` ("no Hermes virtualenv found") even when run by the managed venv's own interpreter (the managed venv's `Scripts/python.exe -m hermes_cli.main`), while `hermes_cli.gateway._detect_venv_dir()` in that same interpreter returns the venv; `gateway restart` drained the gateway and then could not bring it back, so the operator is left with no gateway. Cause unproven — read the `gateway_windows.start` → `_spawn_detached` → `_launcher_settings` path for a re-exec or an env scrub before `resolve_managed_python`. Worked around with a detached `gateway run`.** · fork / gateway service (Windows) · `hermes_cli/gateway_windows.py::_launcher_settings`, `hermes_cli/gateway_downstream.py::resolve_managed_python` · evidence: 2026-10-08 ~21:55 restart, alice `gateway.log` (stopped 21:54:58, manual run up 21:58:16). Also seen: the shell's PATH `hermes` resolved to a leftover test shim under the temp dir (`rb7-identity-flip-559b6bbd/hermes/bin/hermes`) · read 2026-10-15: resolve_managed_python sees only sys.prefix, VIRTUAL_ENV and <checkout>/.venv|venv, and the launcher venv sits outside the checkout, so any interpreter whose sys.prefix is not that venv raises · BLOCKED 2026-10-16: owner sitting — the failing traceback from a live `gateway start` on the Windows box

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




- **`RT-VERIFY-IMPROVE-FIRST-RESPONSE` — Verify and improve first-response selection of the Launcher generated-content tools for ordinary comparison requests; the A/B eval is built (`evals/genui_first_response_ab.py`, b05ccafe29)** · fork / tool selection · plan `docs/agent-runtime-harness/planned/p10-agent-2026-10-19.md` §3 · RULED 2026-10-19: owner — arms switched by QA build · BLOCKED 2026-10-21: owner sitting — the QA sitting runs arm A and arm B (arm-B wording landed launcher `469e500730`; driver + report landed `239beb4b7e`, `92f8967e43`) (`docs/agent-runtime-harness/planned/live-proof-sitting-2026-10-18.md` § Wave 10)

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

- **`RT-ETERNIA-LENS-L2-L4` — Eternia Lens L2–L4 (exit door, push door, pull door) are built and on main (b05ccafe29); each owes one live proof on the owner's serve** · fork / runtime · plan `docs/agent-runtime-harness/planned/p10-agent-2026-10-19.md` §5 · RULED 2026-10-19: owner — persona_id required at seal for investigate; L3's listener in-serve · BLOCKED 2026-10-19: owner sitting — the L2 forged turn, the L3 signed curl and the L4 `lens_read` turn, steps in `docs/agent-runtime-harness/planned/live-proof-sitting-2026-10-18.md` § Wave 10


### Filed on arrival — 2026-10-01 (lane w3-turn)


### Filed on arrival — 2026-10-01 (launcher lane mc-a, filed by the orchestrator)


### Filed on arrival — 2026-10-01 (lane hq-b)




### Filed on arrival — 2026-09-30 (moved from the launcher spatial queue, owner rulings)

- **`RT-REALM-SYNCED-LEVEL-REVERT` — A realm-synced LEVEL has no revert arm, so `realm sync status` reports it and the operator cannot act on it** · `hermes-agent` · raised 2026-09-10 by lane H while landing the `level` family, and deliberately scoped out with the reason measured rather than judged. `realm_revert` subscripts `_PROCESS_ORDER[row.family]` directly and dispatches on family for the upstream lookup, the baseline and the store door, so a `store_drift` family added without a revert arm hands `revert --all` a `KeyError` — which is the reason `_flow_graph_status_row`'s own docstring gives for why the CANVAS was not a drift family until its revert arm landed. So the level family ships with a top-level `levels` status row (`publishable`/`unpublished`/`held`/`refused`) and NO drift rows, pinned by `test_the_level_family_is_not_a_store_drift_family` so a later lane has to make the decision rather than inherit it. The work is the arm: a `DRIFT_FAMILY_LEVEL`, a `_PROCESS_ORDER` entry, and the three dispatch sites in `realm_revert.py` · hermes `agent_runtime/realm_sync/status.py` (`_level_status_row`), `agent_runtime/realm_revert.py`, `agent_runtime/level_sync.py` · moved from the launcher spatial queue 2026-09-30 by owner ruling (`EterniaLauncher/docs/spatial/subsystems/SPATIAL_QUEUE_RULINGS_2026-09-30.md` §C) · RULED 2026-10-10 owner: fold the `levels` status row into `store_drift` (one count) · plan `docs/agent-runtime-harness/planned/realm-level-revert-arm-2026-10-15.md` approved 2026-10-15; S1 family table + S2 level drift rows/arm landed with `build/h4-seeds` (28593ecc42d) · BLOCKED 2026-10-18: owner sitting — the live proof (edit a level, status, revert) on the owner's machine; S3 landed in the launcher (`897e70756a`, its row closed by `15b6c4d2b4`); S4 deletes the old `levels` key one release after S3
- **`RT-REALM-SYNC-REVERT-TAKES` — Realm sync revert takes a very long time (owner report 2026-09-30): measure where a revert spends its time — per-artifact git fetch/checkout, serial HTTP round-trips, a full re-sync after the revert — and cut it; a revert should feel instant next to the sync that produced it** · `hermes-agent` · `agent_runtime/realm_revert.py` · the launcher surfaces it through Mission Control's realm sync controls; no timing has been taken yet · measured 2026-10-02: the argv call paid 5.7–9.2 s of CLI cold start; `runtime.realm.sync.revert` is on the method lane (h-twins) and the launcher binds it method-first (`lib/features/mission_control/sync/realm_sync_method_lane.dart`) · BLOCKED 2026-10-16: owner sitting — time `revert_realm_sync` in-serve on a real realm with the operator's sign-in

### Filed on arrival — 2026-09-29 (lane h10b-triage)


### Embedded (bundled) Hermes — 2026-09-28 (filed by the launcher orchestrator)

Plan and rulings: `EterniaLauncher/docs/embedded_hermes/planned/IMPLEMENTATION_2026-09-28.md` (stages named per row) and `ARCHITECTURE_2026-09-28.md` §4. Rule: one Python implementation, universal — enable existing Hermes code, never reimplement; bundle only what is needed.

- **`RT-MESSAGING-PLATFORMS-TELEGRAM` — Telegram for the headless persona runtime: stores and `runtime.messaging.*` verbs, the Bot API transport, the inbound bridge, approval cards and the serve lane with OS-scheduler service templates are on main (b05ccafe29), off by default and off in every bundled profile** · fork / messaging · plan `docs/agent-runtime-harness/planned/p10-messaging-2026-10-19.md` · RULED 2026-10-19: owner — Telegram only in v1, fork-owned transport over raw httpx, one persona instance per chat, the token in the serve head home, approval cards for every bound root, the installer and a headless bundle profile wait for M7 after one live week · BLOCKED 2026-10-19: owner sitting — the bot-token sitting (bind, turn, redelivery, approval once + timeout, `--service` from Task Scheduler, drain, launcher attach), steps in `docs/agent-runtime-harness/planned/live-proof-sitting-2026-10-18.md` § Wave 10
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


### Discussion Tables (hermes half) — from the 2026-09-17 reviews of `codex/discussion-tables-*`

- **`RT-DISCUSSION-TYPED-REFUSAL` — Discussion Tables (hermes half): D3 closes the typed-refusal lane by subclass, leaving three families on the raw-text boundary** · `hermes` · `agent_runtime/discussions/rpc.py:90-105`: `DiscussionPolicyError` (the base), the `DriverStateError` family (`gateway/hosted_room_driver.py:104-111`) and checkpoint `RuntimeError`s (`gateway/hosted_room_policy_checkpoint.py:183,291,298`) still reach `serve_rpc` as `handler_failed` with `f\"handler error: {exc}\"`. Latent — not live-reachable today. Same review @ `20b148694e`. · the policy base and `DriverStateError` family are typed in d151314bcfe; the checkpoint's three plain `RuntimeError`s are raised by upstream `gateway/hosted_room_policy_checkpoint.py`, so typing them is an upstream door (a typed subclass) · DEFERRED 2026-10-16: owner — prepared PR branches stay idle while upstream is not taking the owner's PRs

### The ghost agent — filed 2026-09-11 from the office removal-lane fix


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


## Seams

### Filed on arrival — 2026-10-22 (upstream PR audit, lanes up-audit-a/b/c/open)

- **`RT-LEDGER-SKILL-SEARCH-PR-132423` — the footprint ledger's `tools/skills_tool.py` row omits #132423 (OPEN, continues closed #37552), the upstream candidate that would retire the plugin's `skill_search` register_tool** · seam / `docs/agent-runtime-harness/planned/upstream-footprint-ledger.md` · evidence `gh pr view 132423` (OPEN), `plugins/eternia-harness/__init__.py::_handle_skill_search` · READY 2026-10-22 · **TAKEN 2026-10-22 w1022a-upstream**

### Filed on arrival — 2026-10-21 (lane w1021h-daily, `integration/upstream-daily` `4ce03587da`)

- **`RT-UPSTREAM-DOORS-SKILLS-PUBLISHED` — upstream published find_all_skills/sort_skills/locate_skill/skill_lookup_path_error/skill_search_dirs (ruling-Q7 widening done); retire the held widening ledger row and carry the daily `3e885680e5`/`df1c808a27` at the v0.22.3 release merge** · seam / `agent_runtime/_upstream_doors.py` · evidence `3e885680e5` (`integration/upstream-daily`) · BLOCKED 2026-10-21: upstream — v0.22.3's release merge into main (owner holds it on `integration/upstream-daily`)

### Filed on arrival — 2026-10-21 (lane w1021h-rpc, branch `w1021h/rpc`)

- **`RT-WORKER-BOOT-PYDANTIC-CONTRACTS` — a desktop gateway/worker pays 1.1 s importing tui_gateway.contracts whatever imports it first: four fork worker modules declare_contracts() at register and rpc_dispatch validates every request through the pydantic registry, so a lazy methods_connectors_account saves 0 under the default tui_gateway.pydantic_contracts: true** · seam / turn latency · evidence: w1021h-rpc `-X importtime` (lazy account stub: contracts still 1.07 s via worker_subagents.install) · BLOCKED 2026-10-21: owner decision — workers validate with the generated catalog (the phone's shape validator), or keep pydantic and defer declarations to the first registry read? · Recommend: catalog in workers, pydantic kept in the suite

### Filed on arrival — 2026-10-16 (lane r-realm-lens, branch `q/r-realm-lens`)

### Filed on arrival — 2026-10-16 (lane r-turnrec)




### Filed on arrival — 2026-10-15 (door PR lanes doors-a, doors-b)

- **`RT-J2-HOSTED-ROOM-LIMITS` — J2 hosted-room limits: at the NEXT release merge (the tag carrying upstream `676238c81b8`), slices A2 (`_conclude` on `_bounded_task_delta` + always-frozen `input_context`) and A3 (per-instance checkpoint transcript bound); the fork's `member_id=` hunk on `tui_gateway/hosted_room_driver.py::submit` retires free; the J2a/J2b/B0 upstream PR prep waits (PR branches idle)** · seams · `docs/agent-runtime-harness/planned/hosted-room-j2-limits-2026-10-16.md` (q-j2 `ab0eb8a6d89`, recommendations taken) · BLOCKED 2026-10-21: upstream — v0.22.3 (released 2026-10-21, carries it) awaits its release merge into main; the owner holds it on `integration/upstream-daily` (`4ce03587da`)
- **`RT-DOORS-SHEET-C-PART-B` — Doors sheet §C part B (gh/Qwen `adopt_external_logins` bug fix) has no prepared branch; part A shipped as `feat/secret-file-store` (634f2ab083)** · seams · doors-a lane report 2026-10-15; sheet on `h-doors-2` §C · build a branch from upstream/main with a body in `pr-bodies` · RULED 2026-10-16: owner — "pr branches should remain idle" while upstream is not taking the owner's PRs · DEFERRED 2026-10-18: build the part B branch from the then-current upstream release when upstream takes the owner's PRs again — owner 2026-10-16 deferral




- **`RT-QUALIFY-HELD-CHECKPOINT` — Qualify the held checkpoint upstream candidates against native user value and maintainer demand.** Native write extraction and reviewed consumers are complete in Console history PR #7, with separate behavior-preserving extraction `71ba58a781`. Before any submission, check open issues/discussions and overlapping PRs and apply the evidence/value bar in the footprint ledger; product neutrality alone is insufficient. Busy/wait is a separate candidate. Retention pins accompany qualified resumable restore or remain held. No upstream submission is authorized by this row. · seam / checkpoints · `docs/agent-runtime-harness/planned/upstream-footprint-ledger.md`, `docs/agent-runtime-harness/planned/console-history-followup-verification-2026-10-11.md` · RULED 2026-10-15 owner: no, not yet; there is no sign upstream wants them · DEFERRED 2026-10-18: hold until an upstream issue or maintainer asks for checkpoint restore — owner 2026-10-15 "no sign upstream wants them"


### Filed on arrival — 2026-10-10 (guard fix, build batch 2 C1–C4, filed by the orchestrator)


### Filed on arrival — 2026-10-10 (fork-fixable sweep lane-1011, filed by the orchestrator)


### Filed on arrival — 2026-10-10 (queue sweep lane-1010, filed by the orchestrator)


### Filed on arrival — 2026-10-10 (release merge v0.21.6 reds)



### Filed on arrival — 2026-10-08 (warm send-prep integration review, `196ec6159d`)

### Filed on arrival — 2026-10-08 (native connection ownership cleanup)

### Filed on arrival — 2026-10-06 (upstream sync planning; AFTER the next release merge)


- **`RT-REQUEST-BUILT-RESOLVES-WEB` — request_built resolves every web-search provider's availability on every request (`agent/transports/codex.py::_alias_wire_tools` → `_openai_prefers_native_web_search` → `agent/web_search_registry.get_active_search_provider`: credential-pool loads, auth-file reads, nous account lookups; 85–105 ms live, ~100 ms on the fixture)** · runtime / turn latency · evidence: h-warm-phases commit 01b1a9a0f8 body · measured 2026-10-08 (`docs/agent-runtime-harness/planned/warm-send-prep-measurements-2026-10-08.md`); every fix site is upstream (`agent/transports/codex.py`, `agent/web_search_registry.py`) · RULED 2026-10-15 owner: wait for the upstream fix; no short cache (a stale cache can send the wrong search tool) · BLOCKED 2026-10-16: upstream — the active-search-provider fix in `agent/web_search_registry.py`
- **`RT-NATIVE-CONVERSATION-RECOVERY` — Native conversation recovery lives inside ~15 upstream `tui_gateway/` files and is the top repeat merge conflict (`session_workdir`, `session_lifecycle`, `methods_session`, `event_replay`, `rpc_dispatch`, `server_requests`, `contracts/sessions` conflicted in the 2026-09-29 merge and/or the 2026-10-06 dry run): move the logic into fork modules, leave one-line call sites. Start only after the next release merge lands** · `seams / tui_gateway` · ledger `carry` rows "native conversation recovery"; `Merging upstream.md` · designed in `docs/agent-runtime-harness/planned/design-sweep-d2-2026-10-10.md` § D2.09 (two MOVE clusters + four door-PR rows) · BLOCKED 2026-10-21: upstream — v0.22.3 (released 2026-10-21, carries it) awaits its release merge into main; the owner holds it on `integration/upstream-daily` (`4ce03587da`)
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

- **`RT-UPSTREAM-TEST-INPLACE-EDITS` — 177 of the 252 upstream test files the fork edits hold in-place edits, not fork tests. Stage 5's MOVE lanes cannot retire them, and its `[up-fp] files −242` target is not reachable (MOVE ceiling 28)** · `seams / tests` · these need a disposition pass (a batched portability/hermeticity PR upstream, or carry with a reason) before Stage 5's gate means anything. Evidence: the same note §1.1–§1.3 · filed by lane S45 2026-09-23 · RULED 2026-09-23 owner: upstream, separate PRs per fix class; never carried · RULED 2026-10-10 owner: no re-file; drop each carry upstream now covers, keep the rest with a ledger reason, re-count at the next release merge · BLOCKED 2026-10-21: upstream — v0.22.3 (released 2026-10-21, carries it) awaits its release merge into main; the owner holds it on `integration/upstream-daily` (`4ce03587da`)

### Standing

- **`RT-SPARK-PRO-USAGE-BUCKET` — Spark has a Pro usage bucket but Hermes's ChatGPT-account Codex route rejects it** · observed 2026-09-16: the live model catalog omitted Spark, the same account's usage response named the separate `codex_bengalfox` bucket, and a minimal `gpt-5.3-codex-spark` request returned HTTP 400 "not supported when using Codex with a ChatGPT account." The picker now shows it disabled. Investigate a supported runtime route before enabling it · `EterniaLauncher/docs/mission_control/subsystems/model-picker-account-catalog-contract-20260916.md`, `hermes_cli/codex_models.py`. · BLOCKED 2026-10-16: owner sitting — probe a supported Spark route with a live ChatGPT Pro account



## Upstream-owned

### Filed on arrival — 2026-10-21 (land w1021j)

- **`RT-PICKER-AUTH-DIRECT-READS` — a picker open still reads auth.json 235× after the pool snapshot: `model_switch_providers._auth_store_has_provider` (93) and `_raw_pool_usable` (23) read the store per row** · upstream-owned / `hermes_cli.model_switch_providers` · evidence `0c619a8b70` (w1021j/chat P3) · READY 2026-10-21: a per-build auth-store memo on `_PickerBuild` beside `pool_snapshot` (fork caller side; extend the idle `up/picker-pool-snapshot`), then lower `PICKER_AUTH_READS_BAR` · **TAKEN 2026-10-22 w1022a-upstream**

### Filed on arrival — 2026-10-21 (lane w1021j-tooling, branch `w1021j/tooling`)

- **`UP-E2E-UPGRADE-PWD-IMPORT` — `tests/e2e/core/upgrade/_helpers.py` does `import pwd` at module scope, so all 36 upgrade e2e files cannot collect on Windows (pure tag v0.22.2 too); the fork skips them by 36 skip-list rows** · upstream tests · evidence: `b5d761fdfa` (branch `w1021j/tooling`; classify_reds_on_tag 36/36 UPSTREAM_COLLECT_ERROR) · DEFERRED 2026-10-21: the 36 skip-list rows carry it; the only fix is upstream's (guard the import), offered as an idle `up/` branch if upstream ever asks

### Filed on arrival — 2026-10-18 (land w8)


### Filed on arrival — 2026-10-18 (lane r-state, branch `q/r-state`)


### Filed on arrival — 2026-10-17 (harvest)


### Filed on arrival — 2026-10-17 (lane r-perf)

- **`RT-CHECKPOINT-PM-ENSURE` — `tools/checkpoint_manager._run_git` calls `pm.client.ensure` per git call (a store-root walk each time): ~20% of `test_operator_redo` profiled** · upstream / checkpoints · [[r-perf-2026-10-17]]; also 34 s of `test_checkpoint_gitlinks.py`'s 54 s setup (lane h1-setup, `q/h1-setup`) · upstream issue or a caller-side memo · w8-slow-b 133892f92b: ~11 ms per `_run_git` child in `selected_git_env` → `pm.ensure("git")` (970 `pm.environments.store_root` / 6,402 `pm.paths.repo_root` calls for 193 children) plus a double spawn through PM's `cmd\git.exe` shim (29 ms vs 18 ms for `mingw64\bin\git.exe`) — about half of each git call on Windows · BLOCKED 2026-10-18: upstream — issue text: "`pm.client.ensure('git')` costs ~31 ms a call on Windows, and `tools/checkpoint_manager._git_env` (via `hermes_cli._subprocess_compat.selected_git_env`) pays it once per git spawn (1,954 calls = 31.9 s of `test_operator_redo`'s 150 s alone). cProfile: 82% is `pm.environments.store_root` <- `pm.paths.store_root` / `install_stamp_path` / `repo_root`, ~118 `Path.resolve` per call. `repo_root()` and `lockfile_path()` resolve `__file__` on every call: caching those two takes a call to 18 ms; caching `store_root(root)` per (root, `HERMES_RUNTIME_DIR`) to 3.7 ms." A memo above `pm.ensure` is ruled out by upstream's own contract (`tests/tools/test_git_consumer_environment.py`: "A changed PM selection must affect this same process"), and `pm/paths.py` is not in the footprint — q-pm 2026-10-18


### Filed on arrival — 2026-10-10 (fast gate FG1, filed by the orchestrator)


### Filed on arrival — 2026-10-10 (guard fix, build batch 2 C1–C4, filed by the orchestrator)

- **`RT-SSH-PROFILE-REMOTE-CWD` — An ssh profile's REMOTE cwd is shape-checked with the host's `os.path.isabs`: `tui_gateway/session_workdir.py::_is_remote_cwd_shape`; on Windows under Python ≥ 3.13 `ntpath.isabs("/home/kali")` is False, so `_completion_cwd` drops a named ssh profile's remote cwd to "~" and `_workspace_cwd` refuses it (`session.workspace.move` → 4017)** · upstream / tui_gateway · 4 tests red on pure tag v0.21.6 `818c13be1d`, marked `_up_red_when` (fix/1011-guard-and-tui-reds `462337b735`) · upstream issue (the remote shape wants `posixpath.isabs`) · the four tests are already `_up_red_when`-marked · RULED 2026-10-15 owner (decision sheet w1015i #2): yes — post them together in one sitting · BLOCKED 2026-10-16: owner sitting — post the upstream issue (the remote shape wants `posixpath.isabs`) at the upstream posting sitting

### Filed on arrival — 2026-10-10 (build batch 1, build-1011-B1..B5, filed by the orchestrator)

- **`RT-SKILL-CATALOG-FRONTMATTER` — Upstream `tools/skills_tool._skill_catalog` parses every SKILL.md frontmatter itself, and the kanban environment gate costs 3 ms per tagged skill uncached plus a 1.3 s first-call import** · upstream / skill catalog · build-1011-B2 `9dc0b2ad19` (60/60 parses in a primed cold child) · plan `docs/agent-runtime-harness/planned/skill-catalog-doors-2026-10-15.md` approved by owner 2026-10-15 · BLOCKED 2026-10-18: upstream — issue text: "`_skill_catalog` parses each SKILL.md frontmatter itself and runs the kanban environment gate per tagged skill uncached; accept parsed frontmatter from the caller and memoise the gate per process" · plan `docs/agent-runtime-harness/planned/skill-catalog-doors-2026-10-15.md` · its only caller is upstream

### Filed on arrival — 2026-10-10 (Fable design sweep D1–D3, filed by the orchestrator)

- **`RT-PREFLIGHT-DB-WRITABILITY` — `preflight_db_writability` reads `os.access` on a sidecar it listed a moment earlier; a WAL unlinked in between reports as read-only** · upstream / state repair · design-sweep-d3 § D3.02 · fork carry built by build-1011-B5; upstream PR owed · the fork carry is built (build-1011-B5); the upstream PR remains · BLOCKED 2026-10-18: upstream — issue text: "`preflight_db_writability` lists the -wal/-shm sidecars, then `os.access`es each; one unlinked in between reports the store read-only; re-check existence and skip a vanished sidecar" · fork carry build-1011-B5 stays

### Filed on arrival — 2026-10-10 (fork-fixable sweep lane-1011, filed by the orchestrator)


### Filed on arrival — 2026-10-10 (queue sweep lane-1010, filed by the orchestrator)


### Filed on arrival — 2026-10-08 (lane opus-w1-hermes, moved from fork-hygiene)


### Filed on arrival — 2026-10-06 (lane h-suite-tail-b)

- **`RT-DASHBOARD-AUTH-SCRYPT-IMPORT` — `plugins/dashboard_auth/basic` computes a scrypt `_DUMMY_HASH` at import time (~0.2 s), paid again on every plugin re-import (80–122 scrypt calls per test file in the profiles)** · upstream-owned · evidence: lane h-suite-tail-b profiles · an upstream issue or a caller-side memo, never an edit · no caller-side memo reaches a module-level import-time computation without editing the module · re-measured 2026-10-18 (lane w2-seams): 271–313 ms per scrypt, no caller-side fork fix; issue text in `worktrees/pr-bodies/issue-dashboard-basic-auth-lazy-scrypt.md` · RULED 2026-10-15 owner (decision sheet w1015i #2): yes — post them together in one sitting · BLOCKED 2026-10-16: owner sitting — post the upstream issue at the upstream posting sitting

### Filed on arrival — 2026-10-05 (lane h-defer, name-set sweep)


### Filed on arrival — 2026-10-02 (lane w5-fh, filed by the orchestrator)


### Filed on arrival — 2026-10-01 (instance conversations)


### Filed on arrival — 2026-10-01 (lane rw-h)


### Filed on arrival — 2026-09-29 (lane h11-code)


### Filed on arrival — 2026-09-29 (lane h10-rtseam, filed by the orchestrator)


### Embedded (bundled) Hermes — 2026-09-28 (filed by the launcher orchestrator)

- **`RT-OFFER-SDK-FREE-HTTPX` — Offer the SDK-free httpx client (re-homed `turn_runner`) upstream as a transport "client" door, after the fork polish.** · architecture §4; ask the owner before opening the PR. · RULED 2026-10-10 owner: yes: offer the transport client door upstream · RULED 2026-10-16: owner — "pr branches should remain idle" while upstream is not taking the owner's PRs · DEFERRED 2026-10-18: offer it after the fork polish closes and upstream takes the owner's PRs again — owner 2026-09-29 + 2026-10-16

### Filed on arrival — 2026-09-29 (lane fix-node-deps, filed by the orchestrator)


### Filed on arrival — 2026-09-29 (PR #125262 review follow-up, filed by the orchestrator)


### Filed on arrival — 2026-09-27 (lane PR-REPLIES, filed by the orchestrator)


### Filed on arrival — 2026-09-26 (lane HELD-TESTS, filed by the orchestrator)



### Filed on arrival — 2026-09-26 (lane FIX-TRIAGE, filed by the orchestrator)

- **`RT-HERMES-STATE-SCHEMA-STALE` — `hermes_state_schema.py`'s stale-FTS rebuild never recovers on SQLite 3.45.3 (Windows CPython 3.12.5): `DROP TABLE IF EXISTS messages_fts` from a fresh connection raises `vtable constructor failed: messages_fts` when the FTS5 data is corrupt, so FTS stays detached for good** · `upstream` · reproduced on a bare FTS5 table; the four `test_fts_runtime_rebuild.py` reds are `_up_red` rows in `tests/_downstream/id_markers/upstream_reds.py` (lane TRIAGE); sibling of the `state_db_has_structural_damage` row below · PR candidate: on that raise, drop the FTS5 shadow tables under `PRAGMA writable_schema` and recreate · filed 2026-09-26 (lane TRIAGE) · RULED 2026-10-10 owner: wait for upstream; keep the `_up_red_when(sqlite<3.46)` markers; no VACUUM INTO draft · BLOCKED 2026-10-16: upstream — a stale-FTS rebuild that recovers on SQLite < 3.46

- **`RT-HOSTED-ROOMS-CANNOT-MOVE` — `gateway/hosted_room_discussion.py` (85/33) and `gateway/hosted_rooms.py` (72/4) cannot move into fork modules: their bodies call 6+ upstream privates; retire via the Group Chat host-surface widening PR, not a move** · seams · evidence: `docs/agent-runtime-harness/planned/footprint-drop-2026-09-27.md` Outcome · filed 2026-09-27 · fork diff +143/−37 and +72/−4; the bodies call upstream privates, so a fork module would import six-plus `_names` · RULED 2026-10-16: owner 2026-09-29 "park until group-chat work resumes"; 2026-10-10 "parked stays parked" · DEFERRED 2026-10-18: leave both as seams until group-chat work resumes, then retire them through the Group Chat host-surface widening upstream PR (a move would import six-plus upstream `_names`); re-measured vs merge-base `d923a5eb48`: +106/−44 and +21/−4 — `docs/agent-runtime-harness/planned/footprint-drop-2026-09-27.md` Outcome

- **`RT-PROCESS-STARTUP-UPSTREAM-WORK` — Every `hermes` process pays upstream start-up work no read-only verb uses: importing `hermes_cli.config` runs provider discovery (`_inject_profile_env_vars` → `providers.list_providers`, ~1.6 s, 38 plugin dirs, 27 YAML loads) and `plugins/model-providers/fireworks` calls `get_version_info()` at import (5+ `git` subprocesses for a User-Agent); `main()` then runs `_warn_pending_fleet_restart_on_startup` (`git` via `get_code_identity`, ~0.8-1.7 s). Fork-side cut so far: the land/q4 version-info cache (boot 6 → 4.2 s); the test-child start-up snapshot landed (`aa377ccc5c`). Upstream PR candidates: lazy OPTIONAL_ENV_VARS injection, a lazy User-Agent** · `upstream` · evidence: the HQ3 commit message on lane/hq-b (`perf(cli): …`, profiles 2026-10-01) · PR candidates (w3-perf 2026-10-01): (a) defer `_inject_profile_env_vars`' provider discovery — `OPTIONAL_ENV_VARS`, `CORE_DECLARED_ENV_NAMES` and the platform-manifest precedence together behind one accessor; (b) build the fireworks User-Agent on first request — drafted as local branch `up/fireworks-lazy-user-agent` (57735398159, red recorded); (c) ask git only when the fleet receipt is unfinished or stale · RULED 2026-10-15 owner: approved: open upstream PRs (a) and (b) · BLOCKED 2026-10-18: upstream — re-measured 2026-10-18: `import hermes_cli.config` 1.6–3.1 s under a concurrent test run, module body 0.59 s self (`-X importtime`) · re-measured 2026-10-18 lane h5-boot (test venv, warm bytecode, sandbox home; cProfile to the serve's `ready` frame): `hermes_cli.config` 0.70–1.04 s of which `_inject_platform_plugin_env_vars` 0.42–0.62 s (23 platform manifests parsed again, then re-parsed by the manifest scan) and `_inject_profile_env_vars` 0.16 s; `main()` startup work `_recover_update_debts_on_startup` 0.25–0.44 s and `_warn_pending_fleet_restart_on_startup` 0.24–0.40 s; `hermes_cli/main.py` module-scope command imports a read-only verb never runs — `hermes_cli.backup` (→ `hermes_state_dbfile` → `agent.context_compressor`) 0.22–0.99 s, `model_setup_flows_local` (asyncio) 0.14–0.20 s, `secrets_cli` (rich) 0.10–0.18 s, `update_cmd` 0.2 s, `kanban` 0.23 s, `pm.install` 0.07–0.10 s; upstream share of a `harness --json status` import self-time 0.91 s vs fork 0.50 s · PR candidate (d): `main.py`'s command-module imports move into their `cmd_*` handlers · issue texts (a)–(d) above; (b) drafted `up/fireworks-lazy-user-agent` (57735398159) · every caller is upstream import-time or `main()`, so no fork memo

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


## Filed on arrival — 2026-10-15 (lane w1015b-con-x)


## Filed on arrival — 2026-10-15 (owner: provider SDKs on first setup)



## Filed on arrival — 2026-10-15 (lane e-triage: blockers with no row)


## Filed on arrival — 2026-10-15 (launcher lane w1015e-mc-l)

## Filed on arrival — 2026-10-15 (lane w1015i-packs)

## Filed on arrival — 2026-10-15 (lane w1015j-hermes)


## Filed on arrival — 2026-10-15 (backend build wave A, realms)




## Filed on arrival — 2026-10-16 (backend build wave B, realms)




### Filed on arrival — 2026-10-16 (launcher lane w1016c-mc)


### Filed at the launcher w1016 wrap-up — 2026-10-16


### Filed on arrival — 2026-10-18 (lane q-reds, branch `q/q-reds`)

### Filed on arrival — 2026-10-18 (lane q-stale, branch `q/q-stale`)
### Filed on arrival — 2026-10-18 (lane q-stale, branch `q/q-stale`)


- **`RT-WHETHER-UPSTREAM-POST-TURN` — Whether upstream's post-turn `agent/background_review.py` fork runs on persona turns is unmeasured: `turn_finalizer` spawns it when `_should_review_memory` or `_should_review_skills` (10 tool iterations and `skill_manage` on the lane) holds, and no fork site passes `skip_background_review`** · fork / memory · prep-cost class; the read half landed as `runtime.operator.conversation.memory` (lane r-wire, 2026-10-18) · lane: count review spawns over ten live persona turns from a receipt, then rule `skip_background_review` per persona · BLOCKED 2026-10-18: owner sitting — ten live persona turns on the owner's serve

### Filed on arrival — 2026-10-18 (lane r-product, branch `q/r-product`)

### Filed on arrival — 2026-10-18 (lane h2-sleep)
- **`RT-ROOM-LEASE-LAPSES-MID-CYCLE` — The hosted-room driver renews its room lease only between room cycles (`tui_gateway/hosted_room_driver.py::_ensure_lease` / `_renew_lease_if_needed`), so a cycle that blocks longer than the lease TTL loses the lease mid-turn and the turn never settles; and a successor serve adopts a room whose owner left a task running only once the old lease expires (up to 30 s of restart recovery, the fork's `DiscussionService` default)** · upstream / discussions room driver · lane h2-sleep 2026-10-18: at a 5 s test TTL a real-native room cycle ran 6.5 s and `test_real_group_compare_discuss_target_and_reopen` red; the fork now sets the TTL through `DiscussionService(lease_ttl=)` (8bcbe70242) · BLOCKED 2026-10-18: upstream — issue text: "`HostedRoomRuntime` renews a room lease only between cycles; renew from a heartbeat while an attempt executes, and let a successor with the same gateway identity adopt a lease whose `process_generation` is provably dead instead of waiting out the TTL"

### Filed on arrival — 2026-10-18 (lane h3-plugins, branch `q/h3-plugins`)

### Filed on arrival — 2026-10-18 (lane h4-hotpath, branch `q/h4-hotpath`)
- **`RT-I18N-BUNDLED-PER-HOME` — `agent/i18n.py::_load_catalog` re-parses the bundled locale YAML once per `(HERMES_HOME, lang)`: 23.8% of 3,668 profiled seconds over 12 files (68% of `test_goal_dispatch`)** · upstream / i18n · [[r-perf-2026-10-17]] § h4-hotpath · BLOCKED 2026-10-18: upstream — issue text: "`_load_catalog` caches the merged catalog per `(home, lang)`, and on a miss `_load_bundled` re-parses `locales/<lang>.yaml` (260–330 KB; ~0.65 s with pure-Python ruamel 0.18.16, which 3.14 installs without the C loader). The bundled layer does not depend on the home, so every new profile home — each profile of a multiplexed gateway, each profile `gateway migrate` plans for, each test home — pays the full parse again. Cache `_load_bundled(lang)` by the file's `(path, mtime_ns, size)` and merge the home's overlay/pack layers over a copy; `reset_language_cache` clears it."
- **`RT-CONFIG-NOFILE-REBUILD` — `hermes_cli/config.py::_load_config_impl` caches nothing when the home has no `config.yaml`, so every read rebuilds the defaults (~2 ms; 61,049 rebuilds, 14.6% of 3,668 profiled seconds, all 23 files)** · upstream / config · [[r-perf-2026-10-17]] § h4-hotpath; per SQLite open via `hermes_state_wal.apply_wal_with_fallback`: 2.52 vs 0.37 ms/open without/with a `config.yaml`, `test_discussion_runtime` 72.5 → 41.2 s with one (re-measured 2026-10-18) · BLOCKED 2026-10-18: upstream — issue text: "`_load_config_cache_sig` returns `cache_sig=None` when neither the user nor the managed `config.yaml` exists, and `_load_config_impl` then skips `_LOAD_CONFIG_CACHE`, so each `load_config`/`load_config_readonly` deep-copies `DEFAULT_CONFIG`, canonicalizes and expands it again (2.1 ms vs 0.11 ms with a file, Windows). Readers that run per item multiply it: `plugins_loader._resolve_plugin_load_timeout` reads config once per plugin load (16,022 calls in 12 test files), `hermes_state_wal.resolve_journal_mode` once per SQLite open. Cache the absent state under a sentinel signature (`(0, 0, 0, 0)` for the missing user file, as the managed half already does); creating the file changes the signature, so the next read sees it."
- **`RT-AUX-KEY-CHAIN-LOAD-CONFIG` — `agent/auxiliary_client._resolve_api_key_provider` walks ~48 providers per auto resolution, each paying `hermes_cli/auth._model_level_key_env` → `load_config()` (a full deepcopy) plus a pool load: 34 resolutions → 1,530 `load_config`, 1,648 pool loads, 40% of `test_compression_rotation_state`** · upstream / auxiliary client · [[r-perf-2026-10-17]] § h4-hotpath · BLOCKED 2026-10-18: upstream — issue text: "When no auxiliary key is configured, `_try_discovery_chain` → `_resolve_api_key_provider` tries every API-key provider; per provider `resolve_api_key_provider_credentials` → `_resolve_api_key_provider_secret` → `_model_level_key_env` calls `load_config()` (a deepcopy of the whole merged config) only to read `model.provider`/`model.key_env`, and `_select_pool_entry` → `_load_pool_with_credentials` loads the pool. Read the `model` block once per resolution (or use `load_config_readonly()` — the value is only read) and skip providers with no pool and no env key before loading their pool. Each compression's auxiliary resolution pays the whole walk."

## Filed on arrival — 2026-10-18 (lane h5-boot)

## Filed on arrival — 2026-10-18 (land h1018)


## Filed on arrival — 2026-10-18 (owner sitting: Work on todo boards)


## Filed on arrival — 2026-10-18 (design: dispatcher and libraries)


### Filed on arrival — 2026-10-18 (lane w2-phone, branch `w2/phone`)

- **`RT-UPSTREAM-TEST-RACES-TWO` — Two upstream tests race their own harness, not the product: `tests/tools/test_browser_eval_supervisor_path.py::_make_supervisor_with_cdp_fn` starts the loop thread and returns before `run_forever`, so `evaluate_runtime`'s `loop.is_running()` check fails on a slow schedule; `tests/agent/test_run_agent.py::TestExecuteToolCalls::test_sequential_tool_calls_run_without_delay` patches `agent.tool_executor.time.sleep`, which is the `time` module's attribute, so any other live thread's nap trips `assert_not_called`** · upstream-owned (both test files) · lane w2-reds 2026-10-18: green alone x3 on main; planted controls red — a 0.2 s delay before `run_forever` gives `assert False is True`, a background `time.sleep(0.001)` thread gives "Called 151950 times" (formerly FORK-CI-FLAKY-THREE, CI run 33969282189) · upstream PR: wait on a started-Event before returning the supervisor; patch a name the executor imports, or assert on the executor's own sleep calls · DEFERRED 2026-10-18: the fix is an upstream PR, and prepared PR branches stay idle until upstream takes the owner's PRs again (`FORK-24-UPSTREAM-PR-BRANCHES`) — owner 2026-10-16

### Filed on arrival — 2026-10-18 (lane w2-realm, branch `w2/realm`)

## Filed on arrival — 2026-10-18 (land w2)

- **`RT-CONTEXT-MANIFEST-WITHIN-KIND` — /context manifest marks every non-empty candidate of one kind loaded, but the builder loads only the nearest .hermes.md / first CLAUDE.md** · upstream / prompt context · `agent/context_file_sources.py::list_context_file_sources` vs `agent/prompt_builder.py::_load_hermes_md`/`_load_claude_md`; the w2-agent `winner = None` carry made it visible across kinds · retire via the `context_files.load_all` PR (per-candidate loaded flags) · BLOCKED 2026-10-18: upstream — the `context_files.load_all` door (issue #125257); prepared PR branches stay idle (owner 2026-10-16)

## Filed on arrival — 2026-10-18 (land w3)

### Filed on arrival — 2026-10-18 (lane w5-misc, branch `w5/misc`)

### Filed on arrival — 2026-10-18 (lane w5-sched, branch `w5/sched`)
- **`RT-SCHEDULE-SYNC-AND-KNOB` — `store/schedules/` is not a realm-sync family (plan §2.3 says key-wise like `workspace_slots`); the knob half LANDED (lane w6-misc: root config `agent_runtime.scheduler.max_parallel`, read each tick)** · fork / scheduling · `agent_runtime/work_store/schedule_store.py`, `agent_runtime/realm_sync/document_family.py`; plan `docs/agent-runtime-harness/planned/dispatcher-and-libraries-2026-10-18.md` §2.3 · RULED 2026-10-18: owner — schedules stay local to the machine that armed them for now; the realm-sync family waits for a design of delete propagation and per-fire publish · DEFERRED 2026-10-18: owner — schedules local per machine until the sync design is planned

## Filed on arrival — 2026-10-19 (launcher wave w1020)

- **`RT-BUNDLED-PHONE-PROFILE` — the Stage 2 phone package profile for `scripts/bundle_profile_package.py` (beside `bundled-desktop`) does not exist, so the launcher cannot retire `tool/mobile_core/wheel.lock.json` for the desktop lock's commit with a phone profile** · `scripts/bundle_profile_package.py` · launcher row `DIST-MOBILE-CORE-WHEEL-LOCK` slice 2, plan `EterniaLauncher/docs/embedded_hermes/planned/MOBILE_WHEEL_LOCK_2026-10-19.md` · filed 2026-10-19 by launcher lane w1020-core · BLOCKED 2026-10-21: another lane — `RT-BUNDLED-PHONE-POOL` (stages S1–S2 landed; S3's packaging receipt needs a phone-scoped pool)
- **`RT-REALM-COURSE-SUBJECT` — `RealmSyncCredential` accepts `realm_id = course:<course_public_id>` for the git-course clone credential (backend Stage 5 packet item 1/5; agent authoring commits on a branch through it)** · `eternia-backend/docs/architecture/planned/education-git-course-lane.md` Stage 5 · launcher sheet `EterniaLauncher/docs/education/planned/GIT_COURSE_STAGE5_STUDIO_SHEET_2026-10-19.md` §2.8 · filed by launcher lane w1020-spatial-edu · BLOCKED 2026-10-21: another lane — `RT-COURSE-AUTHORING-RULINGS` (C1–C2 landed: runtime.course.checkout / commit; C3 open-a-PR waits on the ruling; C4 docs ride C3)
- **`RT-WIN-CONSOLE-FLASH-CODEX-SWITCH` — A Windows console window flashes when the Agent Console switches a chat to openai-codex** · owner 2026-10-19 13:04:41Z (launcher `[MissionModelPick]` chosen=openai-codex/gpt-6-sol): the launcher spawns nothing on that path (RPC-only; its serve child is started detached, with no console), so a console child of hermes opened it. Candidate: `agent/transports/codex_app_server.py::check_codex_binary` runs `codex --version` without `windows_hide_flags()` while the Popen beside it hides; audit the openai-codex select / models / first-turn paths for subprocesses spawned without CREATE_NO_WINDOW and pin one with a Windows test · launcher `MC-PROVIDER-SWITCH-LOCKS-PICKER` waits on it (filed by launcher lane w1020-console) · BLOCKED 2026-10-21: owner sitting — switch a chat to openai-codex on the Windows box and watch for the flash (check_codex_binary now hides its console, 620de2c049)
- **`RT-SNAPSHOT-BUILD-SLOW-AFTER-RESEED` — the launcher showed "snapshot build 6327ms" on the owner's first boot of `acct-26858805fff7de3b` right after the reseed + import of 348 chats and 17 persona instances** · owner screenshot 2026-10-20 · measure which snapshot sections dominate on a store of that size (chat directory over 348 sessions? persona-instance hydration?) and whether it repeats on warm boots; cut the hot section or make it incremental · BLOCKED 2026-10-21: owner sitting — read that boot's snapshot_build_core sections= and snapshot_agents_readiness lines on the owner's machine (history summary is bounded in code; w1021h-turn)

## Filed on arrival — 2026-10-19 (land w10, b05ccafe29)

- **`RT-NATIVE-WORKER-UPSTREAM-BOOT` — a native worker's remaining ~5 s before its first reply is upstream engine work no caller-side memo can key safely: `tui_gateway.server` import 3.4–4.5 s (`hermes_cli.auth` 1.6 s via `local_env_policy`; `tui_gateway.contracts` 1.1 s), the first agent build 2.8–3.9 s (`run_agent` + `model_tools` + builtin discovery), `model.options` 1.4–2.5 s first call (408 `load_pool` for 279 checks, `auth.json` re-read each), and the hourly scratch prune's `reap_processes_rooted_in` over every host process** · upstream-owned / turn latency · w10-turncost profile (the fresh-scratch stamp memo landed, first turn 12.6 → 9.2 s, n=5 loaded) · BLOCKED 2026-10-19: upstream — issue text: "import `hermes_cli.auth` on first credential use and build the contract models on first validation; warm the first agent build off-thread at `tui_gateway.entry` boot; share one auth/config/.env snapshot per `model.options` payload keyed by mtime; skip the scratch reap when nothing is doomed"
- **`RT-DELEGATION-KNOB-ENV-DEAD` — the delegation knob env fallbacks are dead: DEFAULT_CONFIG supplies `max_concurrent_children` and `child_timeout_seconds`, so `DELEGATION_MAX_CONCURRENT_CHILDREN` / `DELEGATION_CHILD_TIMEOUT_SECONDS` never apply (env 7 → getter 10)** · upstream-owned / `tools/delegate_tool_config.py::_knob` · `docs/downstream/agent-console-subagents-settings-2026-10-19.md` § Measured · BLOCKED 2026-10-19: upstream — issue text: "DEFAULT_CONFIG's delegation defaults shadow the DELEGATION_* env fallbacks in `_knob`; read env before the config default, or drop the dead fallbacks"
- **`RT-LENS-FORGED-TURN-TOOL-ADMISSION` — A forged Lens investigate turn runs with the persona's full tool set (receipt `tool_admission: full`); admit per turn** · fork / Lens · plan p10-agent §5.2 decision 5 · BLOCKED 2026-10-21: owner decision — which tools does an unattended Lens investigate turn get (the bundle is cached per persona, so a per-turn narrowing breaks actor reuse)? · Recommend: the read-only lens tools, via the session-scoped permission store's blocked_tools on a session created before the turn
- **`RT-W10-LIVE-CHECKS` — two wave-10 live checks with no row of their own: the delegate/chat/work guidance delta (209 chars in the tool-guidance receipt block) and the Alertmanager bearer curl (202, then 409 on replay)** · fork / live proof · `docs/agent-runtime-harness/planned/live-proof-sitting-2026-10-18.md` § Wave 10 rows W10-4 and W10-7 · BLOCKED 2026-10-19: owner sitting — run both at the live-proof sitting

## Filed on arrival — 2026-10-20 (launcher plan: edition switch and the shared namespace store, `EterniaLauncher` `9185222120`)

- **`RT-NAMESPACE-ADOPT` — `hermes namespace adopt --from-dir <dir> [<id>…] [--dry-run]`: Developer Edition only (`_developer_edition_only`), module `agent_runtime/namespace_adopt.py` excluded from the bundle closure beside `namespace_seed`; per manifest-valid namespace: refuse busy (either side) and an existing target, `os.replace` on one volume else copy+verify(count,sizes)+remove, manifest gains `adopted_from`/`adopted_at`** · fork / `hermes_cli/namespace_cmd.py`, `agent_runtime/bundle_profiles/bundled-desktop.yaml` · plan §5 · mutation: adopt a busy namespace → the busy test reds · RULED 2026-10-20: owner — move once, Developer-Edition-only, nothing ships to release; then (Q1) "default should be appdata indeed with an override to where it is now", so nothing moves · DEFERRED 2026-10-20: not needed while `ETERNIA_HERMES_NAMESPACES_DIR` keeps an existing store in place (launcher `MC-OWNER-NAMESPACES-ADOPT`); re-enter if a developer must physically move a store
