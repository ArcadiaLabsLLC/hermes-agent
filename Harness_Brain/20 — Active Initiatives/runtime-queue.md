---
type: queue
program: mission-control
status: open
tags: [queue, program/mission-control, runtime]
---

# Runtime — the hermes half of the Mission Control queue

- [ ] **Step 6: expose profile delegation defaults and execution-host spawning pause through the existing owned subagent connection.** Owner approved 2026-10-16. Reuse native config read/write/managed policy and native pause state; preserve exact owner/generation checks across native, isolated compute and operator paths, with per-seam footprint accounting and behavioral proof. No parallel settings or execution authority. · fork / Agent Console · READY 2026-10-16 **TAKEN 2026-10-16 claude (r-chatsend)**


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

### Filed on arrival — 2026-10-16 (build lane h-bundle-speed, branch `build/h-bundle-speed`)


### Filed on arrival — 2026-10-16 (build lane h3-runser, branch `build/h3-runser`)

- [ ] **POSIX turns still serialize behind one process lock: the fork writes `HOME` per profile turn because upstream's in-process `expanduser`/`Path.home()` readers have no context hook** · upstream door (run-serialization decision 3) · `agent_runtime/profile_context.py::persona_profile_context` (the `HOME` write and its pinned-readers comment) · draft the one upstream door for a context-aware home hook (`~` in `skills.external_dirs`, the `~/.codex` / `~/.qwen` credential files); once it lands, delete `_PROCESS_HOME_LOCK` on the h3-runser branch and POSIX gets per-root turns like Windows · DEFERRED 2026-10-16: owner — prepared PR branches stay idle while upstream is not taking the owner's PRs
- [ ] **`persona_profile_context(export_env=True)` has no production caller once run-serialization S5 lands** · fork / dead code · `agent_runtime/profile_context.py::persona_profile_context` (the `os.environ` save/mutate/restore block) · delete the env-writing mode, its INVARIANT comment and `persona_profile_scope`'s reason to exist; re-point `tests/agent_runtime/test_persona_binding_child_env.py` (asserts `os.environ` inside the context) at child envs only · run-serialization S5 landed (`7c3bb31a12b`); no production call passes `export_env=True` · READY 2026-10-16 **TAKEN 2026-10-16 claude (r-deadcode)**
- [ ] **`docs/agent-runtime-harness/planned/serve-cwd-per-run-paths.md` plans the per-run paths that replace `os.chdir`; run-serialization S4 (branch `build/h3-runser`) built them through the terminal scope** · fork / stale doc · `agent_runtime/profile_runner/workdir.py::_agent_workdir` · after the h3-runser landing, archive the plan under a header naming S4 · S4 landed `7c3bb31a12b` · READY 2026-10-16 **TAKEN 2026-10-16 claude (r-deadcode)**
- [ ] **A fresh-root serve without `HERMES_HEAD_HOME` fails every persona turn with `chat_session_db_unavailable`** · fork / serve boot · `agent_runtime/persona_chat_durability.py::default_persona_session_db` refuses when the serve's process-home override has no authoritative head; the launcher always sets the variable, a hand-started serve does not (measured on a temp root, lane h3-runser 2026-10-16) · the serve boot should record its own home as head when none is pinned (it already reports `head.outcome = no_explicit_head`), or refuse to boot with that sentence · READY 2026-10-16 **TAKEN 2026-10-16 claude (r-turnrec)**
- [ ] **CLI route S4's push half is unproven live: a re-armed settle was due but no listener was attached, so no delivery was observed** · fork / RPC lane · `hermes_cli/harness_parts/serve/settle_push.py::SettlePush._push_due_settles` · with a launcher (or a `harness stream` client) attached, re-arm an undelivered settle from a shell and record the pushed frame and the ack · READY 2026-10-16 **TAKEN 2026-10-16 claude (r-turnrec)**

### Filed on arrival — 2026-10-16 (build lane h1-lineage)

- [ ] **A turn that reuses the resident actor's stamped native history (lineage-stamp S3) leaves no mark on the turn record: only `context_native_history_ms` drops, so "reused or read" is inferred from a duration. Add a typed `context_native_history_source` (`resident` / `read`) beside it — `_PRE_ADMIT_TIMING_KEYS` only admits ints, so it needs its own field on the phases/timing receipt** · fork / `hermes_cli/harness_parts/persona/chat_turn_commit/run.py::_build_context`, `hermes_cli/harness_parts/persona/chat_admission.py::_PRE_ADMIT_TIMING_KEYS` · evidence lands with `build/h1-lineage` S3 (`PersonaChatRuntimeRegistry.resident_native_history`) · S3 is on main (`PersonaChatRuntimeRegistry.resident_native_history`, landed with fc3350d3044) · READY 2026-10-16 **TAKEN 2026-10-16 claude (r-turnrec)**

### Filed on arrival — 2026-10-16 (build lane h4-seeds)
- [ ] **`realm sync revert --to <version>` cannot move a LEVEL whose published copy changed between versions** · fork / realm sync · `agent_runtime/realm_revert_version.py::_upstream_moved_rows` walks office, boards, instances, canvases, persona defs and skills but no levels, so only a locally drifted level is restored; add a `_pair_rows(SyncFamily.LEVEL, …)` over `read_remote_levels` of both subtrees (found while landing the level arm, plan `realm-level-revert-arm-2026-10-15` S2) · READY 2026-10-16 **TAKEN 2026-10-16 claude (r-realm-lens)**

### Filed on arrival — 2026-10-16 (release merge v0.22.2, daily branch at upstream acc3cada0da)

- [ ] **Owner, optional: the live profile `config.yaml` still lists the five pre-fold `browser_vault_*` tool names in its chat-lane defer list; they work only through the `_FOLDED_TOOL_NAMES` alias in `agent_runtime/config/knobs.py::chat_lane_defer_tools`** · fork-owned · q/vault lane `f522492a3b3` · replace them with `browser_vault`, then the alias can be dropped at a later release · BLOCKED 2026-10-16: owner sitting — edit the live profile `config.yaml` chat-lane defer list on the Windows box
- [ ] **v0.22.2 puts `tools.connectors.gateway.wire` (pydantic) on the phone turn path: upstream's new `tools/connectors/gateway/files.py` imports it at module scope for two plain values (`CONNECTOR_FILE_MAX_BYTES`, `execute_error_family`) via `tool_search` → `connectors/search` → `bridge` → `files`; `test_embedded_phone_session.py[phone]` is red (merge-caused, the only one left at landing). Recommended: an upstream PR moving the two values out of `wire.py` (or importing lazily); a fork guard in `files.py` would raise the footprint to 223 and needs an owner ruling** · fork-owned (`agent_runtime/bundle_profiles/bundled-phone.yaml`) · rel-0222-reds report; `scripts/bundle_profile_closure.py --profile bundled-phone` tip vs `e829d753e12` · RULED 2026-10-16: upstream PR route; idle branch `fix/connectors-files-lazy-wire` (`372b92ffcad`, body in `pr-bodies/`); the phone build stays red until upstream takes it · DEFERRED 2026-10-16: owner — prepared PR branches stay idle while upstream is not taking the owner's PRs
- [ ] **Daily branch at upstream e6899c8090d (`integration/upstream-daily` = `04c26f21a27`, rebuilt 2026-10-16): six merge-caused reds remain unfixed** · seams · `test_shell_hook_resync` x2 (the fork's `refuse_tool_call` pre_tool_call hook appears in upstream's hook list), `test_canonical_session_inventory` (a session narrowed to `['terminal']` still gets `skills`), `test_notification_admission_refusal[completion]`, `test_gateway_migrate_multiplex::test_update_hook_reads_a_masked_default_unit_as_an_opt_out`, `test_completed_process_results` (timeout); all green on origin/main; the discussion-checkpoint, safe-worker config and contract-catalog reds are fixed on the branch (`bb396e1d856`, `b9d8afa288e`, `04c26f21a27`) and the harness_core ratchet re-measured green · fix on `integration/upstream-daily` before the next release merge · READY 2026-10-16 **TAKEN 2026-10-16 claude (r-sync)**



### Filed on arrival — 2026-10-15 (launcher lane w1015i-mc)

- [ ] **The serve's chat_turn_provider_refused block carries the provider's raw response body as `message`** — a 404 web page reached the launcher as "<!DOCTYPE html>…"; send the typed summary the serve already logs (`summary=HTTP 404 — Not Found`) as `message` and keep the body in the log · launcher side fixed in `EterniaLauncher` 79bdf72fb1 · READY 2026-10-16 **TAKEN 2026-10-16 claude (r-turnrec)**

### Filed on arrival — 2026-10-15 (orchestrator: QA bundle build under load)


### Filed on arrival — 2026-10-15 (owner sitting: first real QA bundle build)


### Filed on arrival — 2026-10-15 (owner sitting: send-prep live proof)




- [ ] **Connections: trace the missing browser sign-in `done` event for the isolated QA profile.** Owner report/review 2026-10-14: ChatGPT or Codex Subscription web sign-in completed, but the login-stream `done` event did not reach the Launcher and the pane remained pending; the selected isolated profile subsequently had a credential entry and canonical `logged_in=true`. Root cause is unproven: no historical completion frame was captured. Start at producer `hermes_cli/provider_browser_login.py::run_browser_login` (`send` of `done`), trace `agent_runtime/serve_rpc/provider_signin.py` and the consumer `EterniaLauncher/lib/shared/provider_connections/provider_connection_state.dart::ProviderSetupController` under the same profile; capture redacted lifecycle/transport evidence and pin reliable terminal delivery. The Launcher projection reconciliation on `fix/sol-connect-20261014` is a safety net, not the root-cause fix. Preserve the QA binding; never capture credentials or account identifiers. · fork / launcher seam · found 2026-10-14 sol-connect review · code read 2026-10-15: run_browser_login sends done only after _save_codex_tokens returns, ProviderSignIns._pump folds it only while the session is ACTIVE, and the registry lives in one serve process, so a serve restart between the credential write and the next poll answers login_not_found to a pane still pending · BLOCKED 2026-10-16: owner sitting — one live ChatGPT/Codex browser sign-in on the isolated QA profile (Windows box), capturing the poll replies and the serve pid

### Filed on arrival — 2026-10-15 (lane w1015h-prov)


### Filed on arrival — 2026-10-15 (launcher lane w1015h-misc-l)

- [ ] **Studio palette: a 'recolour one swatch' character-draft op recorded as a hermes draft step (op-log schema + replay) — the launcher studio-queue 'Palette operations' row waits on it** · owner ruling 2026-10-15 · filed by launcher lane w1015h-misc-l · NEEDS PLAN 2026-10-16: where a draft's palette lives (no palette field or op log exists in `agent/charsheet/draft/` `draft.json` schema 1 — only stages and the `ImageRevisionStore`), whether an op log is a schema-2 field or a sidecar beside `draft.json`, the recolour op's shape (swatch index or source colour → target, tolerance), replay order against re-rolled rows and the install (`installed.py`), the verb (CLI + `serve_rpc`, MCP admission) and its lock class

### Filed on arrival — 2026-10-15 (launcher lane w1015h-mc-l)


### Filed on arrival — 2026-10-15 (lane w1015h-comp-l)

- [ ] **Speech pack exact-source manifest (owner GPL ruling 2026-10-15: accept GPL for the separately downloaded speech pack, ship licence + notice, host the exact source next to the pack)** — the packager emits, per copyleft component in each pack (piper-tts and the espeak-ng compiled into it as `espeakbridge.pyd` + `espeak-ng-data`), the exact corresponding source archive and its hash in a source manifest beside `licenses.json`. Launcher side moves second: `scripts/ci/bundled_hermes/seal.py` + `scripts/deploy/publish_engine_packs.py` upload it beside the pack, and the D4 contract changes in both repos in one move · launcher companion-queue D4 row. · NEEDS PLAN 2026-10-16: where the EXACT corresponding source comes from (piper-tts sdist at the shipped version vs the piper1-gpl tag archive with the espeak-ng commit its espeakbridge.pyd was built from), how the packager fetches and pins it offline (hash, cache, refuse on mismatch), the source-manifest schema beside licenses.json (`scripts/bundle_licenses.py` already names espeak-ng under piper-tts), and the D4 contract field both repos change in one move

### Filed on arrival — 2026-10-15 (lane live-qa)

- [ ] **Asked "is there an existing QA session I can reuse to take a Launcher screenshot?", Base answered "Yes" and named instance `personainst_qa_cf20b758ee50`, which is not on the roster (the roster has `personainst_qa`), from four `session_search` calls and no roster/state receipt, and offered reuse instead of a fresh QA instance per task** — the F4/F5 failure of `EterniaLauncher/docs/mission_control/SIX_SCREENSHOT_FINDINGS_2026-10-01.md` reproduced after HQ1/HQ2; the answer should come from the first-class roster/instance detail with its hot/cold state, and an id built from a chat-root suffix must never be offered as an instance · fork / harness-runtime-model skill guidance + `session_search` · evidence: QA home `profiles/base/logs/agent.log` 07:20:53–07:21:13 (2026-10-15, chat `persona_chat_personainst_profile_base_c79130b80c0e`, tool_turns=9); launcher capture `b4-p2-qa-reuse_20261015072114768.png` · launcher row: mission-control-queue "P2 — Investigate Agent Console response/workflow acceptance" · guidance + harness_query schema steer landed bd2ddc962a7 (session_search is history not state, no id cut from a chat root, fresh instance per QA task) · BLOCKED 2026-10-16: launcher — mission-control-queue "P2 — Investigate Agent Console response/workflow acceptance" re-runs the prompt on a Base chat against a live serve

### Filed on arrival — 2026-10-15 (lane w1015h-rt-h)
- [ ] **A serve with resident chats off (`persona_chat.hot_sessions_enabled`, default False — the QA home) never pre-connects or keeps a socket warm, so every turn's api:1 handshakes after the pool's 20 s `keepalive_expiry`: 6/6 turns `conn=new` (connect 6.5–15.5 ms + TLS 12.0–15.7 ms) and a mid-turn tool gap over 20 s reconnects too (api:5 `conn=new`)** · runtime / turn latency · `agent_runtime/idle_turn_keeper.py` (armed only where resident chats are kept), `agent_runtime/provider_preconnect.py` · evidence: QA home `profiles/base/logs/agent.log` 2026-10-15 07:17–07:29 (serve 7e24ded80e): no `idle_turn_keeper`/preconnect receipts, `agent_init` client built every turn · lane: decide whether the keeper should arm without the resident registry (~25 ms/turn) or this stays the documented cost of hot sessions off · RULED 2026-10-16: owner accepted the recommendation — `idle_turn_keeper` arms on every serve that has taken a turn in the last five minutes, resident chats or not · READY 2026-10-16 **TAKEN 2026-10-16 claude (r-turnrec)**

### Filed on arrival — 2026-10-15 (audit lane a1015-hrt)


### Filed on arrival — 2026-10-15 (lane w1015b-rt-h)


### Filed on arrival — 2026-10-14 (Console execution controls)





### Filed on arrival — 2026-10-12 (composer thinking meter)


### Filed on arrival — 2026-10-11 (lane h-s17, one-action-layer S17)

- [ ] **The R10 entry-id gate (landing from lane h-s17, `tests/tooling/`) sees only the dotted spelling `launcher.<area>.<verb>`; the Launcher's tool-name spelling of the same id (`launcher_<area>_<verb>`, from `appFunctionToolName`) walks through.** Live instance: an incident comment in `tools/tool_search_downstream.py` names `launcher_generated_list`. A naive `launcher_\w+` pattern would flag fork module names (`launcher_app_functions`, `launcher_client_requests`), so the answer is a typed name rule (tool names derived from the listed entry only, or a shared name-shape the gate can enumerate), not a wider regex. Plan: `EterniaLauncher/docs/embedded_hermes/subsystems/ONE_ACTION_LAYER_2026-10-10.md` R10. · fork · no in-tree enumeration of Launcher tool names exists (the 11 `launcher_<a>_<b>` tokens in fork source are module, ContextVar and dict-key names) · NEEDS PLAN 2026-10-16: the vendored `launcher.app_functions.list` fixture the gate enumerates from — where it lives, who refreshes it from the Launcher, and how drift reds

### Verified Console history PR #7 follow-up — 2026-10-11





### Filed on arrival — 2026-10-10 (D2.07 redesign, filed by the orchestrator)


### Filed on arrival — 2026-10-10 (guard fix, build batch 2 C1–C4, filed by the orchestrator)

- [ ] **Charsheet and workspace-slot JSON verbs state no root: 24 verbs found by the D3.17 graph scan (18 `_cmd_characters_*`, 6 `_cmd_workspace_slots_*`) answer an empty library / slot document from a wrong root with `ok: true`; attaching resolution is a `charsheet_payload_contract.json` + launcher-mirror change** · fork / json-root · `tests/hermes_cli/test_harness_json_root_observability.py` LEDGER (`_CHARSHEET_REASON`, `_WORKSPACE_SLOTS_REASON`), build-1011-C4 · the charsheet verbs answer from HERMES_HOME (`characters_dir`), not the store root; every payload's key set moves the vendored contract · NEEDS PLAN 2026-10-16: a home block or `resolution` per verb family, and the paired hermes + launcher-mirror landing of the re-vendored contract
- [ ] **board_card fold: the `runtime.board.*` twins ack but publish no fold; a fold needs its producer inside `board_lock` (board-surface-rpc-lane.md rule 3)** · fork / board · `agent_runtime/serve_rpc/board.py` (build-1011-C4) · plan `docs/agent-runtime-harness/planned/board-card-fold-2026-10-15.md` approved by owner 2026-10-15 · BLOCKED 2026-10-16: owner sitting — S0 live end-to-end timing (ack → full core → Launcher repaint) on a running serve + Launcher, Windows box; S1–S4 gate on its number

### Filed on arrival — 2026-10-10 (build batch 1, build-1011-B1..B5, filed by the orchestrator)


### Filed on arrival — 2026-10-10 (Fable design sweep D1–D3, filed by the orchestrator)

- [ ] **Provider request-start evidence is recorded at agent-ready rather than transport dispatch.** `hermes_cli/harness_parts/persona/chat_turn_commit/run.py::_agent_ready_for_steer` sets `provider_request_started` before conversation prompt assembly and transport; generic failures in that gap still lack proof of whether a request left Hermes. Bind dispatch evidence to the actual transport boundary while preserving uncertainty for ambiguous executions; sol-prov separately fixes positively identified local provider refusals. · fork / chat outcome evidence · found 2026-10-14 sol-prov · transport-boundary evidence exists (`provider_request_dispatched` from the `conversation_request_sent` marker, d382d9ee645; the emitter's first byte, aebec101fbf); reading its absence as "not sent" first needs proof that it fires on every provider path (non-stream/argv lanes, every transport) · READY 2026-10-16 **TAKEN 2026-10-16 claude (r-turnrec)**
- [ ] **Two whole-document realm-sync appliers are one module twice (`level_sync.py`, `map_sync.py`); a third family would be a third copy — class answer `realm_sync/document_family.py`** · fork / realm sync · design-sweep-d2 § D2.12 · the level/map MOVE onto `realm_sync/document_family.py` is a dedicated MOVE lane · BLOCKED 2026-10-16: launcher — spatial-office-scene-queue "Bind `UserPrefabStore` to hermes `runtime.prefab.{list,get,set,clear}`"

### Filed on arrival — 2026-10-10 (fork-fixable sweep lane-1011, filed by the orchestrator)


### Filed on arrival — 2026-10-10 (queue sweep lane-1010, filed by the orchestrator)


### Filed on arrival — 2026-10-10 (release merge v0.21.6 reds)


### Filed on arrival — 2026-10-09 (owner report: "this chat I cannot delete")

### Filed on arrival — 2026-10-09 (owner report: Agent Console silent after the toolvis 1b landing)

### Filed on arrival — 2026-10-08 (launcher lane opus-qa-hygiene)

### Filed on arrival — 2026-10-08 (gateway restart after a live-checkout fast-forward)
- [ ] **`hermes --profile alice gateway start` raises `ManagedPythonUnavailable` ("no Hermes virtualenv found") even when run by the managed venv's own interpreter (the managed venv's `Scripts/python.exe -m hermes_cli.main`), while `hermes_cli.gateway._detect_venv_dir()` in that same interpreter returns the venv; `gateway restart` drained the gateway and then could not bring it back, so the operator is left with no gateway. Cause unproven — read the `gateway_windows.start` → `_spawn_detached` → `_launcher_settings` path for a re-exec or an env scrub before `resolve_managed_python`. Worked around with a detached `gateway run`.** · fork / gateway service (Windows) · `hermes_cli/gateway_windows.py::_launcher_settings`, `hermes_cli/gateway_downstream.py::resolve_managed_python` · evidence: 2026-10-08 ~21:55 restart, alice `gateway.log` (stopped 21:54:58, manual run up 21:58:16). Also seen: the shell's PATH `hermes` resolved to a leftover test shim `/tmp/rb7-identity-flip-559b6bbd/hermes/bin/hermes` · read 2026-10-15: resolve_managed_python sees only sys.prefix, VIRTUAL_ENV and <checkout>/.venv|venv, and the launcher venv sits outside the checkout, so any interpreter whose sys.prefix is not that venv raises · BLOCKED 2026-10-16: owner sitting — the failing traceback from a live `gateway start` on the Windows box

### Filed on arrival — 2026-10-08 (owner ask: capability vs. cost-trim quietness, Neko QA-build turn)

### Filed on arrival — 2026-10-08 (warm send-prep integration review, `196ec6159d`)
- [ ] **The first turn after boot is 770 ms and the first after 105 s idle is 441 ms, against a warm 259.5 ms, with the actor prewarmed and reused; re-take each (n=1) and attribute by phase against the warm table** · runtime / turn latency · evidence: [Integrated receipts](../../docs/agent-runtime-harness/planned/warm-prep-integration-2026-10-08.md) · BLOCKED 2026-10-16: owner sitting — the n=1 re-takes on the owner's live serve (Windows box)
- [ ] **OWED live proof: the 259.5 ms warm median is a reference-client number on a fresh history at `a43466214c`; re-take warm/cold/idle on the post-relay head through the Launcher route (capability bridge, `[MissionChatTiming]` spans joined) and on a real long history (H8)** · runtime + launcher / live proof · evidence: [Integrated receipts](../../docs/agent-runtime-harness/planned/warm-prep-integration-2026-10-08.md) · covers send-prep H8 (history cloning, sanitization and token estimation on real-sized histories) · BLOCKED 2026-10-16: owner sitting — warm/cold/idle turns through the Launcher route on a real long history (Windows box)
- [ ] **Send-prep H2 + H6 UNRESOLVED: skill preload (65–95 ms historically on Dev) and package stamps/preload checks did not reproduce on the fresh Neko route; re-measure on a skill-heavy persona using the existing `context_skill_preload_ms` receipts before changing either** · runtime / measured send-prep · `agent_runtime/skill_resolution.py`, `skills_context.py` · evidence: [Integrated receipts](../../docs/agent-runtime-harness/planned/warm-prep-integration-2026-10-08.md) · H2 reproduces on Dev (`context_skill_preload_ms` median 73; the cost sits in upstream `agent/skill_commands.py::build_preloaded_skills_prompt`/`skill_view`); H6 2–5 ms, below the bar (`docs/agent-runtime-harness/planned/warm-prep-integration-2026-10-08.md` § Attribution pass; design-sweep-d1 § D1.10) · RULED 2026-10-10 owner: WAIT on the upstream frontmatter-in-result door (no six-input memo) · BLOCKED 2026-10-16: upstream — the frontmatter-in-result door (`docs/agent-runtime-harness/planned/skill-catalog-doors-2026-10-15.md`)
- [ ] **Send-prep H7 UNRESOLVED: request build is 47–50 ms per warm turn and is broader than the web-search lookup (separate row); split it with the existing `profile_conversation_request_*_ms` parts and name what kwargs / tool-JSON work remains, keeping the final wire-tool receipt** · runtime / measured send-prep · `agent/transports/codex.py::ResponsesApiTransport.build_kwargs`, `capture_final_request_tools` · evidence: [Integrated receipts](../../docs/agent-runtime-harness/planned/warm-prep-integration-2026-10-08.md) · split on Neko n=8: request build 48 = kwargs 41 + middleware 4 + preflight 1; kwargs is upstream `ResponsesApiTransport.build_kwargs`, its fixture-confirmed share is the web-search selection (`docs/agent-runtime-harness/planned/warm-prep-integration-2026-10-08.md` § Attribution pass; design-sweep-d1 § D1.11) · RULED 2026-10-15 owner: wait for the upstream web-search fix, no short cache · BLOCKED 2026-10-16: upstream — the active-search-provider fix (Seams row "request_built resolves every web-search provider's availability")

### Filed on arrival — 2026-10-08 (GenUI comparison turn audit, Amelia turn `agent-chat-send-db7a2d34-731b-4cc8-bc0b-d00b7394f753`)

- [ ] **The always-on harness skills are paid per turn through `skill_view` instead of once in the cached prefix: Amelia turn `agent-chat-send-db7a2d34` (2026-10-08) read `harness-dev-delivery` (13.7 KB) and `harness-runtime-model` (18 KB, frontmatter `load_policy: required_preload`) by tool, and the relay receipt shows `required_preload_skills: []` — `required_preload_skill_ids` filters the persona's OWN assigned identifiers by surface, and nothing is assigned, so the mechanism never fires. Owner ruling owed: which skills each harness persona preloads, then assign them (persona config, not code) and compress their bodies to short operational rules per the 2026-10-08 plan; a preloaded skill `skill_view` re-reads should answer "already in your prompt" cheaply.** · fork / `agent_runtime/mission_chat_turn_context.py::_required_preload_skills`, `agent_runtime/skill_resolution.required_preload_skill_ids`, persona skill assignment · filed by lane host-guidance 2026-10-08 · RULED 2026-10-10 owner: skills load on demand by default; each persona preloads at most its top one or two · RULED 2026-10-15 owner: Launcher Dev and Backend Dev preload the delivery contract; Neko and Base preload the runtime model; everything else loads on demand · the preload half landed 6d7938ce1ab; the "preloaded skill_view re-read answers cheaply" half is upstream `tools/skills_tool.py` · DEFERRED 2026-10-16: owner — prepared PR branches stay idle while upstream is not taking the owner's PRs
- 2026-10-08 evidence for the GenUI selection row below: with the eager pair delivered (runtime `94043a1a42`, listing `26 core/visible tools kept, 18 deferred` at 13:23:09), the first-response path still did not call `launcher_generated_list` directly — the turn loaded five skills (`launcher-generated-ui`, `harness-dev-delivery`, `harness-continuity`, `harness-runtime-model`, one not found; ~44 KB of skill text), searched, described, queried the roster, took the wrong door, then relayed to a peer and burned the rest of the 240 s on the deadlock row above. The profile-local skill is a second copy of the tool contract (it says "discover with `launcher_generated_list`" without saying it is direct); F2 of the launcher audit stands.


### Filed on arrival — 2026-10-07 (GenUI selection audit)




- [ ] **Verify and improve first-response selection of existing Launcher generated-content tools for ordinary comparison requests.** · fork / `tools/tool_search_downstream.py::never_defer_tool_names`, `agent_runtime/launcher_app_functions.py` · observed Amelia turn `agent-chat-send-1f241d5d-e572-488c-987c-c75b55155963` (2026-10-07 23:27:12Z) loaded `hermes-agent` and returned Markdown; the correction turn searched successfully for all five generated tools, and `agent-chat-send-19bd6f54-a744-427c-9e5f-aaa82eb30d44` successfully listed/created native Composition/Text. Its model-input receipt (`ctx_bc3da2d48efa6016`, `final_model_input.tool_schema.final_model_tools`) offers 27 direct tools and keeps generated tools behind discovery; the quoted workflow resolves as profile-local `launcher-generated-ui`, with no required preload. This demonstrates a selection failure, not a missing bridge or a proven sole cause. Evaluate direct exposure of existing discovery/create tools and shared capability guidance without duplicating the Launcher catalog/dispatcher, granting tools to unlinked sessions, changing permissions, or mutating an active conversation's cached prefix. Prove ordinary-language selection across agents; retain exact refusal handling and measure prompt cost. Launcher owner: `EterniaLauncher/lib/core/services/hermes/runtime/data/capabilities/harness_generated_capabilities.dart`. · delivery landed 2026-10-08 (host-owned opt-in for list/create; [Qualification](../../docs/downstream/genui-discovery-qualification-2026-10-08.md)) · live 2026-10-15 (QA serve 7e24ded80e, Base): still fails — plain Markdown, tool_turns=0, with all five generated tools declared alwaysLoaded by the Launcher, so the miss is the model choosing Markdown with the tools in view · NEEDS PLAN 2026-10-16: the WHEN guidance the host sends for comparisons (`agent_runtime/launcher_app_functions.py` `app_function_guidance_lines`), the live A/B protocol across agents/providers on the owner's QA serve, and the prompt-token budget the guidance may cost

### Filed on arrival — 2026-10-07 (native turn anchor carrier)


### Filed on arrival — 2026-10-07 (latency source recheck)



### Filed on arrival — 2026-10-06 (lane h-slim-prompt)

- [ ] **`base/auth.json` read failed at a turn's start (`hermes_cli.auth: could not read ...profiles\base\auth.json, leaving the store on disk untouched`, 12:07:05.613) and the credential pool then reported `no available entries (all exhausted or empty)` (12:07:05.269); the launcher showed "openai-codex: this credential needs attention" while codex turns succeeded — a transient read (lock/partial write?) surfaces as a credential fault** · runtime / provider credentials · evidence: agent.log 2026-10-07 12:07:05 + launcher banner screenshot · lane: find the reader racing the writer, make the read atomic/retried, and never raise needs-attention on one failed read · 2026-10-07/2026-10-14: a synthetic auth-reader failure settles typed `provider_unavailable` with disk unchanged; the historical reader/writer race and the needs-attention mapping remain unproved (`docs/agent-runtime-harness/planned/runtime-evidence-wave4-2026-10-07.md`) · RULED 2026-10-15 owner: book a weekly operator sitting on the Windows box and run this check there · BLOCKED 2026-10-16: owner sitting — the weekly Windows-box sitting
- [ ] **Prewarm still holds _WORKDIR_LOCK through single steps it cannot interrupt (live 20:23:47: system_prompt_build_ms=7855, construct_ms=5318); a turn arriving mid-step waits that step** · runtime / turn latency · evidence: agent.log 2026-10-06 20:23:47 prewarm_first_turn line · lane: move system-prompt build and construction off the lock, or split them into yieldable steps · designed in `docs/agent-runtime-harness/planned/design-sweep-d1-2026-10-10.md` § D1.04 (investigation; the measurement protocol is in the plan) · BLOCKED 2026-10-16: owner sitting — the D1.04 live measurement on the owner's serve (Windows box)
- [ ] **Every new process pays the cold snapshot sections again: on an idle box against a copy of the operator's store agents_readiness costs 10.6 s and prompt_observability 7.3 s on a process's first build (warm 0.6 / 1.2 s); ~5.7 s of the 17.9 s is first imports and plugin discovery, the rest is SKILL.md frontmatter through ruamel (2,004 parses, ~4.8 s), the codex credential-pool probe (~2.7 s), kanban toolset detection (~2.9 s) and the second skill-catalog walk (~3.8 s) — all memoised per process only, so the serve's snapshot worker pays 35 s / 30 s at boot under contention (agent.log 2026-10-06 20:23:50, pid 40444) and the first boot after a checkout change adds the 149-dir bytecode recompile; the argv-child half of the pile-up is cut (lane h-boot-pileup: a standalone `harness stream` relays to the live serve)** · runtime / boot cost · evidence: lane h-boot-pileup commit body (per-function wall split, idle copy, 2026-10-06) · lane: one owner for the skill walkers with a cross-process parse cache keyed by file signature; the ruamel / credential-pool / kanban halves are upstream-owned (caller-side memo or seam) · traced against upstream ee8dd6c8863: ours to fix; designed in `docs/agent-runtime-harness/planned/design-sweep-d1-2026-10-10.md` § D1.05; CF-1/CF-2/CF-3 built (defbee0ae6..48ed69a21f); the kanban offer-time remainder's only caller is upstream `tools/skills_tool._skill_catalog`, so it needs an upstream door (`docs/agent-runtime-harness/planned/skill-catalog-doors-2026-10-15.md`) · DEFERRED 2026-10-16: owner — prepared PR branches stay idle while upstream is not taking the owner's PRs
- [ ] **The serve keeps `harness stream` argv readers (`caller=cli`) attached long after the launcher settled on its hub lane: four `stream_attach op=harness_stream purpose=cli_stream` at 19:01:43.368 (beside the hub's conn-1 subscribe), two still framing every turn of one chat at 19:03:51 (`turn_section … source=reused caller=cli` x2 per section) and LEADING full `snapshot_build reason=demote caller=cli` cores (1.4–2.2 s, 19:02:14, 19:03:14, 19:03:16, 19:04:11) the hub would otherwise not pay; the launcher holds one hub and zero argv streams by design (`EterniaLauncher/lib/…/mission_stream_lane_lifecycle.dart` `resolveOnGreeting` cancels the argv lane), so either the cancel never reaches the serve's argv stream or the lane was opened after the hub — find which, end the reader with its client** · fork / `hermes_cli/harness_parts/runtime_commands.py::_cmd_stream` + serve argv lanes · evidence: `profiles/base/logs/agent.log` 2026-10-06 19:01:43–19:04:11 (serve 274eb9bb6c, pid 14988), launcher diag `[MissionStream] lane=argv reason=serve_absent` x2 23:00:48Z then `lane=hub` 23:01:42Z; lane h-prep-contention commit body · LIVE 2026-10-15 (QA home): REPRODUCED — four `harness_stream purpose=cli_stream` attaches opened AFTER the hub with no detach, still framing turns with `caller=cli`; no argv process alive, so the readers are serve-side; b931a2de996 names request/connection/max_frames on the attach line and adds a `stream_detach` line · RULED 2026-10-15 owner: book a weekly operator sitting on the Windows box and run this check there · BLOCKED 2026-10-16: owner sitting — one more sighting under the new lines at the weekly Windows-box sitting, naming the connection that never cancelled

### Filed on arrival — 2026-10-06 (lane h-pool-starve)

- [ ] **Attribute the recorded first-turn stall before moving post-send work.** · runtime / turn latency · evidence: existing 375 ms stall receipt; `transport_phase_trace.py::phase_trace_for`, `title_upgrade_defer.py`, `skill_root_freshness.py::revalidate_served_roots` · **Action:** after `h-idle-turn`, take stack samples and controlled persistence/title/refresh ablations against the same fast response. Move only work demonstrated to delay response consumption, using existing turn-window/finalization mechanisms. **Done when:** first text improves without worse streaming; persistence remains exactly once and completes before actor reuse; retry, cancellation, no-request and failure paths pass; title fallback survives. Coordinate refresh behavior with `h-idle-turn`, not a competing scheduler. · **No assumed 375 ms saving.** · 2026-10-07: no historical 375 ms attribution; stack/refresh/persistence sample missing (`docs/agent-runtime-harness/planned/runtime-evidence-wave4-2026-10-07.md`) · RULED 2026-10-15 owner: book a weekly operator sitting on the Windows box and run this check there · BLOCKED 2026-10-16: owner sitting — stack samples and ablations at the weekly Windows-box sitting
- [ ] **Resolve the turn-two cache miss from final dispatched requests, not post-turn `agent.tools`.** · runtime / prompt cache · **Prerequisite:** the existing `h-cache-hit` final-wire-tools capture row and tool-pin ownership finding. **Action:** compare turns 1–3’s actual prefix, ordered tools, model/effort, route, cache scope, and session pin; repair only demonstrated unintended drift. **Done when:** deterministic request/pin consistency tests pass and matched live runs report input/cached tokens plus first-text distributions. Distinguish prefix drift from provider-side cache availability. Record hashes/counts, not sensitive prompt bodies or credentials; do not lower permissions, required preloads, or reasoning to meet the target. · 2026-10-07: the R034 final dispatched wire/tools capture is outstanding; no authenticated cache-token distribution (`docs/agent-runtime-harness/planned/runtime-evidence-wave4-2026-10-07.md`) · RULED 2026-10-15 owner: book a weekly operator sitting on the Windows box and run this check there · BLOCKED 2026-10-16: owner sitting — matched live runs at the weekly Windows-box sitting

### Filed on arrival — 2026-10-06 (lane h-send-window)


### Filed on arrival — 2026-10-06 (lane h-turn1-conn)


### Filed on arrival — 2026-10-06 (lane h-turn1-again)


### Filed on arrival — 2026-10-06 (lane h-model-pick)


### Filed on arrival — 2026-10-06 (lane h-newchat-t1)


### Filed on arrival — 2026-10-06 (lane h-cache-hit)


### Filed on arrival — 2026-10-06 (lane h-conn-pool)

- [ ] **Re-read turn 1 on the next prewarmed Neko chat after h-conn-pool lands: the pre-connect now warms the turn's own request client and the default config already shares one pool (offline + real-edge probe: turn 0 rides the HEAD's connection), so a turn-1 `tls_done` there means something else took or killed the warm connection between prewarm and turn — read `tls_done`, `client_built→request_sent` and `prewarm_first_turn_warmup_ms`** · fork / chat turn · evidence: lane h-conn-pool `3b0cbc20ab` body · LIVE 2026-10-15 (QA serve 7e24ded80e): every turn's api:1 is `conn=new` while api:2+ reuse — the 20 s `keepalive_expiry` reap (`agent/process_bootstrap.py`) that `agent_runtime/idle_turn_keeper.py` prevents, and the keeper does not arm with resident chats off (row "A serve with resident chats off…", RULED 2026-10-16) · BLOCKED 2026-10-16: owner sitting — turn-1 stamps on a prewarmed Neko chat after the keeper change lands (Windows box)

### Filed on arrival — 2026-10-06 (lane h-readiness)


### Filed on arrival — 2026-10-06 (lane h-snapshot-offproc)


### Filed on arrival — 2026-10-05 (lane h-prompt-design; h-turn1-c)

- [ ] **With `lean_operative_rules` on, the threading and `clarify_token` rules reach the agent only through `agent_chat_send`'s describe doc, and an eager tool is rarely described; the R4 A/B must check one teammate clarify answer goes back on its `clarify_token`, or the bullets move into `harness-mission-lead` (operator-home skill)** · fork / chat lane · evidence: lane h-prompt-surface `ba499069be` · lane: R4 A/B · BLOCKED 2026-10-16: owner sitting — the R4 A/B (ten live turns, flag on) on the owner's serve; the clarify-token check rides it

### Filed on arrival — 2026-10-05 (launcher lane docs-dev, filed by the orchestrator)


### Filed on arrival — 2026-10-05 (lane h-turn1-c1-design)


### Filed on arrival — 2026-10-05 (launcher lane console-1a, filed by the orchestrator)


### Filed on arrival — 2026-10-05 (owner live turns, "turns still feel slow")




- [ ] **Remove the h-turn1 A5 stamps from upstream `agent/turn_api_request.py` (8 lines marked `# fork seam: h-turn1 A5`) once the first-turn `build_api_request` cost is fixed — owner kept them 2026-10-05 as a TEMPORARY diagnostic against the 2026-09-29 DOORS-A ruling (`bfee7eb896`); the file returns to upstream bytes and the footprint fixture drops by one** · seam / `agent/turn_api_request.py` · evidence: `lane/h-turn1-tail` `4b49ff114b` · the cost row was folded into this one at 11dedd066f6; the 8 stamp lines are still in `agent/turn_api_request.py` · BLOCKED 2026-10-16: owner sitting — a live first-turn read of the A5 stamps on the owner's serve

- [ ] **Every chat turn ships ~22k input tokens: Neko "hi" read `in=21957` (tool_search tier 1: 28 core/visible tools kept, 51 deferred, deferred listing ~20,232 tokens); the provider's send→first-text leg is 1.4–2.2 s on a 12-token reply. Measure what the 22k is made of (system prompt, tool schemas, deferred listing, skills) and what a smaller first-turn surface would cost the agent** · fork / prompt surface · evidence: neko `agent.log` 2026-10-05 19:16:28 `API call #1 … in=21957`; plan `plan/h-prompt-design` `0d71896c74` (R1–R5 taken 2026-10-05; owner amends R1: only the five `browser_vault_*` tools are deferred) · landed 2026-10-06 hermes `f779903ba7` (S0–S3, S6, S4 behind `agent_runtime.mission_chat.lean_operative_rules`) · BLOCKED 2026-10-16: owner sitting — the next live first turn's S0 per-part receipt, `cache=` on a second chat, and the R4 A/B (10 turns, flag on)





- [ ] **A queue-only commit on the primary checkout restarts the live serve and stalls the Launcher ~27 s: each of three docs-only commits (`fb5a186264`, `0ed627cea0`, `4adeb0f116`) was followed by a drain whose old serve never proved an exit inside 20 s (`serve_drain proven=no polls=13–14 waited_ms=20503/20848`, pids 28592, 28456), opens deferred behind it (`serve_spawn_deferred reason=drain_in_flight` up to 19,844 ms), an open answered at `+26817 ms`, then a 15.4 s first snapshot build; the code identity should ignore commits that touch no shipped code, and the drain should end the old serve inside its budget** · fork / serve lifecycle (the restart door is the Launcher's `MissionServe`; file its half in `mission-control-queue.md` once this side says what the identity covers) · evidence: base `agent.log` 14:54:08.535 `home maintenance: code changed to 4adeb0f116d1`; `%TEMP%\eternia_launcher_diag.log` 18:48:10 / 18:54:00 / 18:54:15 `MissionServe`/`MissionOpenChat` lines · **LANDED 2026-10-05 hermes `c87f8ed59e` + launcher `0d377ec6b3` (D1–D4); OWED live proof: a vault-only commit on the primary draws no `[MissionServe] drain`, and the next real restart logs `serve_drain proven=yes`.** · BLOCKED 2026-10-16: owner sitting — on the owner's primary checkout, a vault-only commit draws no `[MissionServe] drain` and the next real restart logs `serve_drain proven=yes`


### Filed on arrival — 2026-10-05 (owner screenshot, "screenshot posts" 13:05)


### Filed on arrival — 2026-10-05 (lane hb-c)


### Filed on arrival — 2026-10-04 (launcher lane console-boundaries, filed by the orchestrator)


### Filed on arrival — 2026-10-04 (owner design: builds as first-class background work)



### Filed on arrival — 2026-10-03 (lane h-wakecap)


### Filed on arrival — 2026-10-03 (resident identity audit)


### Filed on arrival — 2026-10-03 (lane h-fence)


### Filed on arrival — 2026-10-03 (launcher lane fx-mc2, filed by the orchestrator)

- [ ] **`harness serve` cold boot dominates Mission Control's first open: total_ms 21592, interpreter_ms 15203 (interpreter_boot 5196, main_import 4016, dispatch 5991) on a disk-cold QA seed, 2026-10-03 — profile and cut the import/dispatch path** · `hermes_cli/harness_parts/serve/boot.py` · launcher fx-mc2 · designed in `docs/agent-runtime-harness/planned/design-sweep-d1-2026-10-10.md` § D1.06 (investigation) · BLOCKED 2026-10-16: owner sitting — the D1.06 protocol on a disk-cold QA seed on the owner's machine

### Filed on arrival — 2026-10-02 (launcher lane mc-a, filed by the orchestrator)


### Filed on arrival — 2026-10-02 (launcher lane mc-pidx, filed by the orchestrator)


### Filed on arrival — 2026-10-02 (launcher lane w12-qa, filed by the orchestrator)


### Owner asks — 2026-10-02 (long tool calls)

- [ ] **DESIGN — long tool calls move to the background (owner ask 2026-10-02: "what would be good agent UX"). Proposed: a call that passes a threshold (~30–60 s, or a tool that declares itself long-running) is promoted to running_work / Background Work; the agent gets an immediate "running in background" result with a handle and may keep talking; the operator may keep chatting; on completion the final result is delivered to the agent as a new event that wakes the turn; running cards offer Send to background and Cancel. Write the design (turn/await semantics, how the result re-enters the conversation, upstream vs fork seams, what the console renders) for the owner to approve before any build** · `fork / runtime` · launcher Background Work panel · RULED 2026-10-10 owner: parked: the design is approved before any build · NEEDS PLAN 2026-10-16: turn/await semantics, how the result re-enters the conversation, upstream vs fork seams, and what the console renders

### Filed on arrival — 2026-10-02 (lane w10-hr, filed by the orchestrator)


### Filed on arrival — 2026-10-02 (owner screenshot: QA turn ended silent; filed by the orchestrator)


### Filed on arrival — 2026-10-02 (launcher lane w10-pkg, bundled Hermes on macOS/Linux; moved here by the orchestrator)


### Filed on arrival — 2026-10-02 (lane w10-s7h, Stage 7 hermes half)


### Owner asks — 2026-10-02 (agent chat is ONE surface; filed by the launcher orchestrator)

- The launcher half of the same ruling (the Agent Console becomes the one chat widget, rendered with Intelligence's materials; `EterniaLauncher/docs/companion/planned/AGENT_CHAT_UNIFICATION_AUDIT_2026-10-02.md`) changes NO hermes method: `runtime.chat.*` and `perform_chat_turn` are the surviving chat lane; the `tui_gateway` worker is the lane that goes. Work on the worker's lifecycle beyond keeping it alive until the cutover is upstream work (the cold-start hello carry under Upstream-owned), not cutover work.

### Filed on arrival — 2026-10-02 (orchestrator, live MCP check)


### Filed on arrival — 2026-10-02 (launcher lane w5-mc, filed by the orchestrator)


### Owner asks — 2026-10-01 (instance conversations)

- [ ] **Instance-conversation cutover remainder:** qualify rich input/activity, recovery and live latency before retiring the profile worker; identity/account/directory/inspection foundation lands separately. · `fork / runtime` · [Plan](../../docs/agent-runtime-harness/planned/instance-conversations-2026-10-01.md#foundation-landing-boundary-october-2) · designed in `docs/agent-runtime-harness/planned/design-sweep-d2-2026-10-10.md` § D2.08 (the instance-conversations plan owns it) · BLOCKED 2026-10-16: owner sitting — the qualification's live latency half on the owner's serve

### Owner asks — 2026-10-01 (Eternia Lens in hermes)

- [ ] **Build Eternia Lens as a fork-owned plugin (`plugins/eternia-lens/`, code under `agent_runtime/lens/`): a poll / push / pull ingest module whose rules raise Episodes that forge ONE chat turn of the selected persona (ADR 0008), on both the bundled profile and the Developer Edition; a Python port of Companion's Monitoring contracts, everything Lens-presentation / Work / repair cut. Stages L0–L4, four owner rulings owed before L0** · `fork / runtime` · plan [eternia-lens-in-hermes.md](../../docs/agent-runtime-harness/planned/eternia-lens-in-hermes.md) · launcher half: `EterniaLauncher/Launcher_Brain/20 — Active Initiatives/mission-control-queue.md` (the L1 fold row) · RULED 2026-10-02 owner: accept all four plan §6 rulings as written (eternia-lens / runtime.lens.*; per-manifest persona defaulting to the selected one; no act level; phones run no poller) · plan `docs/agent-runtime-harness/planned/eternia-lens-program-cut-2026-10-15.md` approved by owner 2026-10-15 · READY 2026-10-16 **TAKEN 2026-10-16 claude (r-realm-lens)**


### Filed on arrival — 2026-10-01 (lane w3-turn)


### Filed on arrival — 2026-10-01 (launcher lane mc-a, filed by the orchestrator)


### Filed on arrival — 2026-10-01 (lane hq-b)




### Filed on arrival — 2026-09-30 (moved from the launcher spatial queue, owner rulings)

- [ ] **A realm-synced LEVEL has no revert arm, so `realm sync status` reports it and the operator cannot act on it** · `hermes-agent` · raised 2026-09-10 by lane H while landing the `level` family, and deliberately scoped out with the reason measured rather than judged. `realm_revert` subscripts `_PROCESS_ORDER[row.family]` directly and dispatches on family for the upstream lookup, the baseline and the store door, so a `store_drift` family added without a revert arm hands `revert --all` a `KeyError` — which is the reason `_flow_graph_status_row`'s own docstring gives for why the CANVAS was not a drift family until its revert arm landed. So the level family ships with a top-level `levels` status row (`publishable`/`unpublished`/`held`/`refused`) and NO drift rows, pinned by `test_the_level_family_is_not_a_store_drift_family` so a later lane has to make the decision rather than inherit it. The work is the arm: a `DRIFT_FAMILY_LEVEL`, a `_PROCESS_ORDER` entry, and the three dispatch sites in `realm_revert.py` · hermes `agent_runtime/realm_sync.py` (`_level_status_row`), `agent_runtime/realm_revert.py`, `agent_runtime/level_sync.py` · moved from the launcher spatial queue 2026-09-30 by owner ruling (`EterniaLauncher/docs/spatial/subsystems/SPATIAL_QUEUE_RULINGS_2026-09-30.md` §C) · RULED 2026-10-10 owner: fold the `levels` status row into `store_drift` (one count) · plan `docs/agent-runtime-harness/planned/realm-level-revert-arm-2026-10-15.md` approved 2026-10-15; S1 family table + S2 level drift rows/arm landed with `build/h4-seeds` (28593ecc42d) · BLOCKED 2026-10-16: launcher — mission-control-queue "Mirror the realm `store_drift` level family in the realm sync status report (hermes realm-level-revert-arm S3)" (filed by the orchestrator); S4 one release after
- [ ] **Realm sync revert takes a very long time (owner report 2026-09-30): measure where a revert spends its time — per-artifact git fetch/checkout, serial HTTP round-trips, a full re-sync after the revert — and cut it; a revert should feel instant next to the sync that produced it** · `hermes-agent` · `agent_runtime/realm_revert.py` · the launcher surfaces it through Mission Control's realm sync controls; no timing has been taken yet · measured 2026-10-02: the argv call paid 5.7–9.2 s of CLI cold start; `runtime.realm.sync.revert` is on the method lane (h-twins) and the launcher binds it method-first (`lib/features/mission_control/sync/realm_sync_method_lane.dart`) · BLOCKED 2026-10-16: owner sitting — time `revert_realm_sync` in-serve on a real realm with the operator's sign-in
- [ ] **User prefabs do not travel: `runtime.prefab.*` (`agent_runtime/prefab_store.py`, store/prefabs/<profile>/) is install-local; add the realm-sync family beside `map_sync` (publish scan, pull applier adopt/keep/HOLD, baseline, status counts) so a profile's shelf follows it across machines** · `hermes-agent` · store + verbs landed by w5-rt 2026-10-02; the launcher binds its `UserPrefabStore` to the verbs first (launcher row) · designed in `docs/agent-runtime-harness/planned/design-sweep-d2-2026-10-10.md` § D2.12 (`realm_sync/document_family.py`, level/map MOVE, prefab = one descriptor) · BLOCKED 2026-10-16: launcher — spatial-office-scene-queue "Bind `UserPrefabStore` to hermes `runtime.prefab.{list,get,set,clear}`"

### Filed on arrival — 2026-09-29 (lane h10b-triage)


### Embedded (bundled) Hermes — 2026-09-28 (filed by the launcher orchestrator)

Plan and rulings: `EterniaLauncher/docs/embedded_hermes/planned/IMPLEMENTATION_2026-09-28.md` (stages named per row) and `ARCHITECTURE_2026-09-28.md` §4. Rule: one Python implementation, universal — enable existing Hermes code, never reimplement; bundle only what is needed.

- [ ] **Messaging platforms (Telegram, Discord, …) as fork work for the headless toolset (full Hermes as a service); off in bundled profiles.** · spec ruling 8. · the off-in-bundled half is in the tree (bundled-desktop.yaml / bundled-phone.yaml deny discord tools and set `gateway.platform_adapters: false`) · DEFERRED 2026-10-16: owner 2026-09-29 "park until Hermes-as-a-service is wanted"; 2026-10-10 "parked stays parked"
- [ ] **macOS / Linux bundled desktop ships no OS secure store: `keyring` (Keychain / Secret Service) is not in the bundled-desktop packaging, so `auth.os_secure_store: true` refuses to start there — add it to those targets' packaging when they exist** · `fork` · evidence: `agent_runtime/host_store/desktop.py::admitted_keyring_backend` · filed 2026-09-28 (lane w5-hdpapi) · `keyring` is in neither pyproject.toml nor uv.lock; add it as an optional extra + networked `uv lock` + bundled-desktop.yaml darwin/linux extras in the change that first builds those targets · DEFERRED 2026-10-16: owner "add keyring when mac/linux builds exist, not now"; prove it at the Mac sitting

### Filed on arrival — 2026-09-29 (lane h11-mcp)


### Filed on arrival — 2026-09-29 (lane h9-bundle)


### Filed on arrival — 2026-09-30 (lane s2-plan — phone gate → zero, one row per lane; work them in the plan's order)

### Filed on arrival — 2026-09-28 (lane p2-hphone)

### Filed on arrival — 2026-09-28 (lane p1-hsplit)

### Filed on arrival — 2026-09-28 (lane w4-hd4)

### Filed on arrival — 2026-09-29 (upstream merge `merge/upstream-2026-09-29`, filed by the orchestrator)

### Filed on arrival — 2026-09-29 (lane h7-phone)

### Filed on arrival — 2026-09-29 (lane w6-hwort)
- [ ] **Piper first audio is ~2 s on a sentence with a name the phonemizer dictionary lacks ("…Mira hasn't joined yet") vs 0.2–0.5 s otherwise — profile the out-of-dictionary path (the model runs per word) and cache or batch it.** · `agent_runtime/speech_phonemize.py`; listening manifest (lane h8-voice, 2026-09-29) · code read: `OpenPhonemizer._predict` is one ORT forward per OOD word, so the likely cost is the first forward on a fresh input shape; owner 2026-09-29: profile once the voice pack is on the box, a warm-up forward at load is the likely cheap fix · BLOCKED 2026-10-16: owner sitting — profile first vs second OOD word with the Piper speech pack + `openphonemizer-en_us.onnx` installed (Windows box)

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

- [ ] **Retire the legacy top-level `remote_gateway.*` / `charsheet.*` read once the launcher writes `plugins.entries.eternia-harness.settings.remote_gateway_listen` / `remote_gateway_port`: empty `LEGACY_KEYS` and delete-and-report the old blocks at one chokepoint** · fork / config · `agent_runtime/harness_settings.py::LEGACY_KEYS` · blocked on the launcher row "Harness config keys move under the plugin manifest" (`mission-control-queue.md`) · filed by lane h-doors 2026-10-03 · launcher writes the new path since 290449df44 (lane mc-doors); retire only once the owner's installed launcher is at or after that commit, or an older launcher's LAN toggle silently stops working · RULED 2026-10-15 owner (decision sheet w1015i #4): check the BUILD line; if it is that build or newer, say go · BLOCKED 2026-10-16: owner sitting — read the installed launcher's BUILD line against 290449df44

### Filed on arrival — 2026-09-24 (seam lane S2)

### Filed on arrival — 2026-09-24 (lanes UPREV, DISP-M)

### Filed on arrival — 2026-09-24 (seam lane S5)

### Filed on arrival — 2026-09-24 (seam lane S4)

### Owner asks — 2026-09-22, filed on arrival

- [ ] **`test_serve_rpc_office_subscribe_live_hub` waits 5 s with no `@pytest.mark.timeout`, so it flakes under a full-suite batch and passes alone** · `fork / suite` · a wait bound over 30 s must declare the marker and this one is under it, so the marker is not the fix — the fix is a wait that observes the hub rather than sleeping toward it. Seen once in lane HM's 221-file touched run, green when run alone · filed by lane HM at its landing 2026-09-22 · every wait in the file is already `_wait_for` under `_DEADLINE_SECONDS`; the failing case is `::test_a_real_office_write_reaches_a_subscriber_as_an_office_patch`, a leak through the process-global `OFFICE_SUBSCRIPTIONS` in combined runs (lane H4 2026-09-24) · DEFERRED 2026-10-16: owner 2026-10-10 "parked until the failing case's `what=` string is captured"

### Contract questions the launcher is waiting on (filed 2026-09-20/21, routed by the 2026-09-22 verdict sheet)

- **The same wire fact decodes to different values on different lanes — exit codes, and int tolerance generally** · `launcher / mission control` · a tool's `exit_code` of `-1` is ABSENT on the bridge's `tool.finished` lane (`missionBridgeNullableInt`, pinned with a stated reason) and `-1` on the persona-chat trace (`_nullableExitCode`, unpinned); `from_offset`/`cap_bytes` refuse a numeric `String` in `remote/` (I3d) while `status_code`/`turn_seq` accept one in `data/` (I3); `code:` in the visibility model ROUNDS a `num` where every other reader truncates. None of this is a copy defect — each is a per-file policy with no wire contract behind it, which is the "parallel resolvers answering the same question differently" shape. C1 preserves every site's behaviour and names the variants; deciding which tolerance the harness wire actually promises is a contract question for the hermes side · `EterniaLauncher/docs/archive/mission_control/refactor-program-2026-09/wave3/wire-decode-family.md` §2.2 · RULED 2026-10-15 owner: one hermes contract note settles it: strict integers on the wire · READY 2026-10-16
- **Two resolvers answer "did `harness realm adopt` succeed?" differently in one file** · `launcher` · `_adoptRealmDefinition` refuses on `exitCode != 0 || payload == null || payload['ok'] == false`; `setUpGrant` refuses on `exitCode != 0 || (payload?['ok'] == false)`, so a null envelope is a FAILURE in one and a SUCCESS in the other for the same CLI verb. Z3 preserves both deliberately; unifying them is a behaviour CHANGE needing its own review and producer-side receipt evidence · `EterniaLauncher/lib/features/mission_control/sync/realm_sync_service.dart`, Z3 note §5, §8.3 · `_adoptRealmDefinition` is in `sync/realm_sync_default_workspace_commands.dart` and `setUpGrant` in `sync/realm_sync_service.dart` · RULED 2026-10-15 owner: one hermes contract note settles it: an empty realm-adopt reply is a failure · READY 2026-10-16

- **`MissionAgentLogStatus.fromWire`'s `whenAbsent` divergence is a live wire-contract question for hermes** · `launcher / mission control` · after B28 one decoder reads eleven harness words for both doors, but an ABSENT value still reads `idle` on a persona-instance row and `unknown` on a snapshot log row. The fold made the divergence a named parameter rather than picking; whether hermes intends the two to differ is unanswered · `EterniaLauncher/lib/features/mission_control/data/snapshot/mission_snapshot_status_and_envelope.dart` · moved from the launcher queue 2026-09-22 (wave 8 sheet) · RULED 2026-10-15 owner: "unknown" everywhere; don't claim idle without evidence · READY 2026-10-16

### Owner design changes — 2026-09-18 (the generic-desk landing, hermes `f1268bd017`)

- **A dropped legacy desk leaves its hermes actor file behind** · `hermes` · the launcher deletes a persona-addressed desk at its load chokepoint and reports the count (owner ruling 5, 2026-09-18), but the drop is a READ: `before` and `after` are both already clean, so `officeVacatedActorKeys` measures nothing and no `runtime.office.remove` is sent. A desk that shared an agent's actor is dropped from that file on the next write to it; a desk that was the only item under its address is never rewritten. The census that would have reported it was deleted in hermes `f1268bd017`. Decide: a one-shot sweep, or leave it. · RULED 2026-10-15 owner: clean them up once and report the count (the standing delete-old-schema-and-report rule) · READY 2026-10-16
- **`OfficeItem.minted_kind` is stamped on every upsert and, since hermes `f1268bd017`, has NO reader** · `hermes` · its only consumer was the retired desk-litter census; it is persisted provenance outside the content hash and the wire, so removing it is a stored-data decision · `docs/agent-runtime-harness/07-observability.md`. · the standing owner rule (old schema: delete and report, 2026-09-18) answers it: drop the field and its stamp, strip and count the stored key at the office load chokepoint · READY 2026-10-16
- **A generic desk write still pays ONE `scan_actors`** · `hermes` · a desk actor names no `persona_instance_id`, so it is a CLASS-KEYED payload and `_guard_class_keyed_write` scans the directory; the retired fence took two scans to one, not to zero — the generic-desk plan's cost claim was half right. Decide with launcher slice 2 whether desk writes should leave the class-key fence · `test_office_store.py::test_a_generic_desk_write_pays_the_CLASS_KEY_scan_and_only_that_one`. · NEEDS PLAN 2026-10-16: whether desk writes leave the class-key fence, decided with launcher slice 2

### Discussion Tables (hermes half) — from the 2026-09-17 reviews of `codex/discussion-tables-*`

- **Discussion Tables (hermes half): a retention pin leaks on a crash between `_retain` and `disband_room`** · `hermes` · `agent_runtime/discussions/service.py:316-318`; a pin on a still-live room is reclaimable by no lane (age/tombstone exempt pins, the byte lane selects `disbanded_at IS NOT NULL`) and `unpin_room_history` has no production caller that could clear it. Strictly narrower than the per-run leak the fix retired. Reviewer plant B, 2026-09-17 review of `codex/discussion-tables-fix` @ `20b148694e` (verdict LAND). · the pin owner is ruled on the `run.end` row below (hermes clears leftover pins at start-up) · READY 2026-10-16
- **Discussion Tables (hermes half): D3 closes the typed-refusal lane by subclass, leaving three families on the raw-text boundary** · `hermes` · `agent_runtime/discussions/rpc.py:90-105`: `DiscussionPolicyError` (the base), the `DriverStateError` family (`gateway/hosted_room_driver.py:104-111`) and checkpoint `RuntimeError`s (`gateway/hosted_room_policy_checkpoint.py:183,291,298`) still reach `serve_rpc` as `handler_failed` with `f\"handler error: {exc}\"`. Latent — not live-reachable today. Same review @ `20b148694e`. · the policy base and `DriverStateError` family are typed in f42f717188b; the checkpoint's three plain `RuntimeError`s are raised by upstream `gateway/hosted_room_policy_checkpoint.py`, so typing them is an upstream door (a typed subclass) · DEFERRED 2026-10-16: owner — prepared PR branches stay idle while upstream is not taking the owner's PRs
- **Discussion Tables (hermes half): `run.end` still refuses on a non-`RoomNotFound` disband failure** (e.g. `AuthorityConflictError`) — decide whether a terminal run may release its claims with the room undisbanded · `hermes` · `agent_runtime/discussions/service.py::_finalize_room`; residual named by the 2026-09-17 D2 fix lane on `codex/discussion-tables-fix` @ `20b148694e`, deliberately not widened there. · RULED 2026-10-15 owner: hermes clears leftover pins at start-up; an ended run may release its seats and leave the room marked for that same clean-up · READY 2026-10-16

### The ghost agent — filed 2026-09-11 from the office removal-lane fix

- **The snapshot's `unplaced-instance` parity warning is OWED, and the two ways to feed it were both measured too expensive** · `hermes` · the reconcile lane classifies and prunes it (`classify_unplaced_persona_instances`, phase 2b), but `_parity_warnings` cannot: the evidence is "an ARCHIVED office actor names this instance", and the snapshot's `offices` section carries LIVE actors only. Measured on the live store 2026-09-11: **82 archived actor files / 59 KB across 2 workspaces against 4 live actors**, with no retention policy, so carrying the ids on the wire is an unbounded list on every snapshot and decoding them in `_offices_summary` is a 21× increase in files read on the snapshot build path, both growing with every removal forever. Needs a ruling on which cost to pay (or a retention policy first — the row below). Until then an operator learns about a ghost by running `harness persona-instance reconcile --dry-run`, never from the launcher. · `agent_runtime/snapshot/` `_parity_warnings` / `_offices_summary`; the classifier and its evidence gatherer are in `agent_runtime/persona_instance_identity.py`. · RULED 2026-10-15 owner: keep the last 20, as the agent archive already does; then the ghost warning is cheap enough to show in the launcher · READY 2026-10-16
- **The office archive directory has no retention, and that is what makes the row above expensive** · `hermes` · 82 files / 59 KB after roughly six weeks on a store with 4 live actors; every `remove_actor` adds one and nothing ever removes one. `persona_instances_archive/` has a 20-entry retention (`.ended.json` rows do too); this directory does not. It is cheap while nobody reads it and it is exactly what any new reader has to walk. · `agent_runtime/office_store.py` `_archive_actor_locked` / `paths.office_archive_dir`. · RULED 2026-10-15 owner (row above): keep the last 20 · READY 2026-10-16
- **`agent.create` refuses an unmarked placement id; the office write lane accepts one, and that pair is how the ghost was minted** · `hermes` · `perform_agent_create` answers `placement_id_not_discriminable` ("supply the `<persona-token>_agent_<hex8>` shape"), but `PersonaInstanceStore.add_instance` takes any token and `OfficeStore.upsert_actor` will place the result, so `persona instance create` + a scene save produces an instance-backed actor with no marker — `personainst_chara_a2_7b31d0e4`, the 09-11 ghost. Either the second route should mint marked ids or the create door's refusal is protecting a discriminator nothing else relies on any more. Needs a ruling, not a patch; the launcher no longer depends on the marker for its archive lane. · `agent_runtime/agent_create/`, `agent_runtime/persona_assignments.py` `add_instance`; the pin that the refusal still exists is `test_the_placement_verb_really_does_refuse_this_id_shape` in `tests/agent_runtime/test_persona_instance_unplaced.py`. · RULED 2026-10-15 owner: mark ids everywhere, so there is one id shape and one rule · READY 2026-10-16

### Runtime observability — filed 2026-09-06 from the post-rebuild field run

- **The Mac did not answer `runtime.persona.instance.open_chat` inside the budget three times while its snapshot stream flowed, and its Neko instance reads `status=running` with no visible activity, which is exactly the cockpit's occupied-chat dialog condition** · `hermes` (Mac read) + `launcher` · 2026-09-07 16:26:51 / 16:27:06 / 16:27:39Z `open_chat lane=method install=912c69ce… outcome=unknown reason=call_timeout retry=same_key`; `fold_applied persona_instance x1` from the Mac 5 s and 24 s after the first two. Needs the Mac's `agent.log` for 16:26:40–16:27:40Z and the instance row's `status`; the launcher's open-chat receipt should name WHICH budget expired (the connector's default or the lane client's 30 s). · `restart-drain-fence.md` §3 names it · BLOCKED 2026-10-16: owner sitting — the Mac's `agent.log` for 16:26:40–16:27:40Z and its instance row's `status` (Mac)
- **The local chat prep cost is now a measured baseline** · `hermes` · `turn_context_ms` 620 / 829 / 1,233 / 4,730 with `builds_overlapped` 1 / 0 / 2 / 3 on four idle local turns (2026-09-06 15:29–15:30Z), the provider itself 0.9–1.5 s — `planned/chat-turn-prep-cost.md` (hermes canon) is re-armable as a stage against these numbers. · plan `docs/agent-runtime-harness/planned/chat-turn-prep-cost.md` (rulings CP-1..CP-9, Stages 6–10): Stage 6 landed hermes `a319021acc` / launcher `a4b8e390c`; CP-9's PC read taken and Stage 7 landed hermes `483bcf6fab` (write_ahead p50 844 ms; skill work 74–89 % of it, so Stage 8 is billed on live turns); no `codex/prep-cost-stage8-one-walk` branch exists — re-verify Stage 8's state before claiming; owed: CP-9's Mac half, Stage 7's ten-turn number, the launcher `ready.json` re-capture · BLOCKED 2026-10-16: owner sitting — CP-9's Mac read (the Mac pulls and re-reads) and live operator turns for Stage 8

### Snapshot build latency on Windows — filed 2026-09-08

- **The live serve's `agents_readiness` walk costs 5-10x the same walk in a quiet process, and nothing explains the difference** · `hermes` · `snapshot_agents_readiness walk_ms=` reads 651-1595 ms across 664 samples in the operator's `agent.log`, against 126-155 ms for the identical five-persona walk measured read-only against the same live store from an isolated process; the 2026-08-22 note in the walk itself records 146 ms and matches the quiet figure, so the algorithm is not what moved — the serve process is · `docs/agent-runtime-harness/planned/windows-path-syscall-cost-2026-09-08.md` "What the measurement did NOT explain" item 1 · found while profiling the build for the memo landed at hermes `6d79b6d724`. · BLOCKED 2026-10-16: owner sitting — a live-serve investigation on the owner's box
- **The core cache writes on every build and has never once been served on this install** · `hermes` · 2,094 `snapshot_core_cache_write` lines against ZERO `core_source=cache` serves in one `agent.log`; the same code DOES serve on a quiescent copy of the same store (226-241 ms against a 1.0-2.2 s cold build), so convergence is the whole blocker — and "just stop writing" is dead as a remedy because disabling the write-back entirely bought 4 ms · `docs/agent-runtime-harness/planned/core-cache-input-closure.md` 2026-09-08 addendum, which is the field half of its own IC-4 "measure first" gate · the per-family reader audit that plan demands is still owed. · BLOCKED 2026-10-16: owner sitting — the IC-4 per-family reader audit measured against the live store
- **`sections_top=` prints three of the build's seven sections, and every remedy plan that reads attribution off `agent.log` is reading a truncated list** · `hermes` · this is how `prompt_observability` — which ties `agents_readiness` for the top slot on this install (180.8 ms vs 170.2 ms warm) — went unnamed by the whole boot-window programme; the full `sections_ms` map exists and the receipt shows a third of it · `agent_runtime/snapshot/` `_log_snapshot_build_core` / `build_receipt_facts`, same note item 5. · the launcher joins builds on `build_ms`+`sections_top` equality (`mission_boot_timeline.dart`, limit 3), so the fix is an additive `sections=` field on the receipt line, landed with the launcher parser in one wave · READY 2026-10-16

- **Full `PersonaAssignmentStore` retirement is gated on a residual-row census that came back NONZERO (81, unchanged at the 2026-09-04 re-census)** · `hermes` · blocked on an OPERATOR settle of the 15 non-terminal rows, not on implementation; the launcher half is closed (§AX2 / Z1, `EterniaLauncher` `bf33487b2`). Routed out of the launcher Mission Control queue 2026-09-22 (wave 8, lane docs-2) per `EterniaLauncher` `9de7b2bfd`. · BLOCKED 2026-10-16: owner sitting — settle the 15 non-terminal rows in the owner's live store

### Harness CLI and the doctor — 2026-08-30 / 2026-09-02 hand-backs, 2026-09-12 skill sync

- **`root_config_misplacement` has a cure and a denominator; the 9-vs-2 comparison needs re-reading** · `hermes` · the finding half landed 2026-09-04 (w12/m5, hermes `42d54af562`): `remediation` (present even when `ok`) and `scope` (`profiles_examined` / `root_only_key_patterns`) from the rows' own walk; doctor `schema_version` 9. A row is (profile × concrete key) and two of four patterns are per-persona, so 9 vs 2 across two machines compares inventories. What remains is operator-only: re-read the two stores against `scope` and fix the genuinely inert rows by hand — there is deliberately no automated repair, because rewriting an operator's `config.yaml` is not a write the doctor takes. · BLOCKED 2026-10-16: owner sitting — re-read both machines' stores against `scope` and hand-fix the inert `config.yaml` rows (Windows box and Mac)



### Filed on arrival — 2026-09-25 (lane R4)



### Filed on arrival — 2026-09-25 (lane S2B)

### Filed on arrival — 2026-09-25 (lane S2A)

### Filed on arrival — 2026-09-25 (lane 2B-C)


### Filed on arrival — 2026-09-25 (lane B2)


### Filed on arrival — 2026-09-25 (lane B3)


### Filed on arrival — 2026-09-25 (lane B4, filed by the orchestrator)


## Seams



### Filed on arrival — 2026-10-15 (door PR lanes doors-a, doors-b)

- [ ] **J2 hosted-room limits: at the NEXT release merge (the tag carrying upstream `676238c81b8`), slices A2 (`_conclude` on `_bounded_task_delta` + always-frozen `input_context`) and A3 (per-instance checkpoint transcript bound); the fork's `member_id=` hunk on `tui_gateway/hosted_room_driver.py::submit` retires free; the J2a/J2b/B0 upstream PR prep waits (PR branches idle)** · seams · `docs/agent-runtime-harness/planned/hosted-room-j2-limits-2026-10-16.md` (q-j2 `ab0eb8a6d89`, recommendations taken) · BLOCKED 2026-10-16: upstream — the release tag carrying upstream `676238c81b8`
- [ ] **Doors sheet §C part B (gh/Qwen `adopt_external_logins` bug fix) has no prepared branch; part A shipped as `feat/secret-file-store` (634f2ab083)** · seams · doors-a lane report 2026-10-15; sheet on `h-doors-2` §C · build a branch from upstream/main with a body in `pr-bodies` · DEFERRED 2026-10-16: owner — prepared PR branches stay idle while upstream is not taking the owner's PRs




- [ ] **`pm/_fork_extend_environment.py` reaches three private `pm` names (`pm.operations._require_install_allowed`, `pm.operations._requirements`, and the fork's own additive `pm.environment._retry_sync_on_sharing_violation`, which the gate reads as upstream because `pm/environment.py` is) to run the in-place provider-SDK install; grandfathered at land-w1015b so the owner-ruled feature lands — open a public door (or route through an `_upstream_doors.py`) and drop the three fixture rows** · seams / private upstream import · `tests/fixtures/import_layers_grandfathered.json`, `tests/tooling/test_fork_import_layers.py::test_no_new_site[private_upstream_imports]`, 8f2d79a87ba · found 2026-10-15 land-w1015b · needs a public upstream door for `pm.operations._require_install_allowed` / `_requirements`; the fork's additive `pm.environment._retry_sync_on_sharing_violation` goes public in the same move; an `_upstream_doors.py` relay would only move the rows · DEFERRED 2026-10-16: owner — prepared PR branches stay idle while upstream is not taking the owner's PRs
- [ ] **Qualify the held checkpoint upstream candidates against native user value and maintainer demand.** Native write extraction and reviewed consumers are complete in Console history PR #7, with separate behavior-preserving extraction `71ba58a781`. Before any submission, check open issues/discussions and overlapping PRs and apply the evidence/value bar in the footprint ledger; product neutrality alone is insufficient. Busy/wait is a separate candidate. Retention pins accompany qualified resumable restore or remain held. No upstream submission is authorized by this row. · seam / checkpoints · `docs/agent-runtime-harness/planned/upstream-footprint-ledger.md`, `docs/agent-runtime-harness/planned/console-history-followup-verification-2026-10-11.md` · RULED 2026-10-15 owner: no, not yet; there is no sign upstream wants them · DEFERRED 2026-10-16: owner "no, not yet. There is no sign upstream wants them."


### Filed on arrival — 2026-10-10 (guard fix, build batch 2 C1–C4, filed by the orchestrator)

- [ ] **The /context manifest says "shadowed" for files the fork's prompt actually loads: `agent/context_file_sources.list_context_file_sources` marks lower-priority kinds `shadowed`, but the fork's `build_context_files_prompt` loads every kind** · seam / prompt context · design-sweep-d1 § D1.12 S2 (build-1011-C2) · the fix is a non-additive hunk in upstream `agent/context_file_sources.py` (drop the winner rule) to match the fork's load-every-kind builder carry · DEFERRED 2026-10-16: owner — prepared PR branches stay idle while upstream is not taking the owner's PRs

### Filed on arrival — 2026-10-10 (fork-fixable sweep lane-1011, filed by the orchestrator)

- [ ] **The gateway's `_drain_gateway_watch_events` and `_async_delegation_watcher` discard or requeue by a hard-coded event-type list, so every new fork completion-queue type needs another upstream hunk** · seam / gateway · `a7ac57819b` (M2.01) · waits on the held door PR "route unknown completion_queue types" · DEFERRED 2026-10-16: owner — prepared PR branches stay idle while upstream is not taking the owner's PRs

### Filed on arrival — 2026-10-10 (queue sweep lane-1010, filed by the orchestrator)

- [ ] **Each per-turn MCP admission (register, then teardown) moves `registry._generation`, so the `model_tools.get_tool_definitions` memo misses: ~200 ms rebuild vs 0.1–0.5 ms warm, on actor construction and tool_search** · seam / tool registry · `queue-sweep-2026-10-10/L3-outcomes.md` L3.14 and draft I · the memo key and the registry generation live in upstream `model_tools`/registry · NEEDS PLAN 2026-10-16: an upstream door versus a fork-scoped generation that per-turn MCP admission does not move

### Filed on arrival — 2026-10-10 (release merge v0.21.6 reds)



### Filed on arrival — 2026-10-08 (warm send-prep integration review, `196ec6159d`)

### Filed on arrival — 2026-10-08 (native connection ownership cleanup)

### Filed on arrival — 2026-10-06 (upstream sync planning; AFTER the next release merge)


- [ ] **request_built resolves every web-search provider's availability on every request (`agent/transports/codex.py::_alias_wire_tools` → `_openai_prefers_native_web_search` → `agent/web_search_registry.get_active_search_provider`: credential-pool loads, auth-file reads, nous account lookups; 85–105 ms live, ~100 ms on the fixture)** · runtime / turn latency · evidence: h-warm-phases commit 01b1a9a0f8 body · measured 2026-10-08 (`docs/agent-runtime-harness/planned/warm-send-prep-measurements-2026-10-08.md`); every fix site is upstream (`agent/transports/codex.py`, `agent/web_search_registry.py`) · RULED 2026-10-15 owner: wait for the upstream fix; no short cache (a stale cache can send the wrong search tool) · BLOCKED 2026-10-16: upstream — the active-search-provider fix in `agent/web_search_registry.py`
- [ ] **Native conversation recovery lives inside ~15 upstream `tui_gateway/` files and is the top repeat merge conflict (`session_workdir`, `session_lifecycle`, `methods_session`, `event_replay`, `rpc_dispatch`, `server_requests`, `contracts/sessions` conflicted in the 2026-09-29 merge and/or the 2026-10-06 dry run): move the logic into fork modules, leave one-line call sites. Start only after the next release merge lands** · `seams / tui_gateway` · ledger `carry` rows "native conversation recovery"; `Merging upstream.md` · designed in `docs/agent-runtime-harness/planned/design-sweep-d2-2026-10-10.md` § D2.09 (two MOVE clusters + four door-PR rows) · BLOCKED 2026-10-16: another lane — the next release merge (`Merging upstream.md`)
- [ ] **Four upstream door PRs would retire 23 fork-edited upstream files (optional-module 6, SDK fallback 3, secret-file store 7+2, provider access 5): the design is on branch `h-doors` (`d3d91edc7f`, its upstream-doors plan, not on main). Owner go needed before the Opus build lanes; land the plan with the first lane; open no upstream PR without the owner's OK** · `seams / upstream doors` · `h-doors` · RULED 2026-10-10 owner: go: the four door-PR Opus build lanes on `h-doors`, and open the four upstream PRs · part A shipped as `feat/secret-file-store` (634f2ab083) · DEFERRED 2026-10-16: owner — prepared PR branches stay idle while upstream is not taking the owner's PRs
- [ ] **When a door PR lands upstream and reaches a release: delete the fork hunks it retires, file by file, per the plan's "fork deletion" section, and lower `tests/fixtures/upstream_footprint.json`** · `seams / upstream doors` · `upstream-doors-2026-10-06.md` · BLOCKED 2026-10-16: upstream — a release carrying one of the four door PRs

### Filed on arrival — 2026-10-06 (lane h-prereq-window)


### Filed on arrival — 2026-10-06 (lane h-model-pick)


### Filed on arrival — 2026-10-06 (lane h-conn-pool)


### Filed on arrival — 2026-10-06 (lane h-readiness)


### Filed on arrival — 2026-10-05 (lane h-prompt-tools)


### Filed on arrival — 2026-10-04 (lane hb-a)


### Filed on arrival — 2026-10-03 (lane h-mcpwake)


### Filed on arrival — 2026-10-02 (instance-conversations)


### Filed on arrival — 2026-10-01 (lane w3-turn)

- [ ] **Retire the compute-host cold-start carry: `tui_gateway/host_supervisor.py` waits a fixed 10 s for the child's hello while the child imports `tui_gateway.server` first (5.6–6.2 s idle, 10.8–28.5 s loaded); the fork added `_HELLO_COLD_START_GRACE_SECS` (additions only). Upstream PR: a configurable hello budget, or the hello sent before the heavy import** · `upstream / tui_gateway` · ledger row `tui_gateway/host_supervisor.py` (cold-start hello grace, 2026-10-01) · RULED 2026-10-10 owner: yes: open one upstream PR for a configurable compute-host hello budget (default 10 s) · draft: local branch `up/compute-host-hello-budget` (fd282272f8e, `dashboard.compute_host_hello_timeout_secs`, red recorded) · DEFERRED 2026-10-16: owner — prepared PR branches stay idle while upstream is not taking the owner's PRs

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

- [ ] **Nine Stage 2 rows the ledger said the surface "has" wait on five widening PRs nobody owns, and none is on §Stage 3's P-list** · `seams / upstream` · `register_command` with gateway context + `busy_policy` (`/queue-status`, 4 rows); a terminal command-guard hook consulted by `_check_all_guards` with a typed result (the envelope gate); a per-call usage ledger in the turn result (`usage_ledger`, 3 rows); a tool-schema transform hook (wire briefs); a register-toolset PR (bundle membership, `harness_core`). Each needs a P-number, an owner and a fallback in `docs/agent-runtime-harness/planned/harness-plugin-and-upstream-seams.md` §Stage 3 · evidence: `docs/agent-runtime-harness/planned/upstream-footprint-ledger.md` rows marked "DESIGN (lane S2)" / "waits on" · filed by lane S2 2026-09-24 · the tool-schema transform ask is REFUTED (upstream `llm_request` middleware rewrites `api_kwargs.tools`) · RULED 2026-10-10 owner: fork-side `/queue-status` through `pre_gateway_dispatch`, no re-cut — in the tree (98b4553ef03, `agent_runtime/gateway_queue_status.py`) · BLOCKED 2026-10-16: upstream — merges of #123977 command_guard, #123978 per-call cost + Codex parity, #123979 register_toolset

### Filed on arrival — 2026-09-24 (disposition wave, lane DISP-C)

### Filed on arrival — 2026-09-23 (seam lane S45, Stage 4/5/6 inventories)

- [ ] **177 of the 252 upstream test files the fork edits hold in-place edits, not fork tests. Stage 5's MOVE lanes cannot retire them, and its `[up-fp] files −242` target is not reachable (MOVE ceiling 28)** · `seams / tests` · these need a disposition pass (a batched portability/hermeticity PR upstream, or carry with a reason) before Stage 5's gate means anything. Evidence: the same note §1.1–§1.3 · filed by lane S45 2026-09-23 · RULED 2026-09-23 owner: upstream, separate PRs per fix class; never carried · RULED 2026-10-10 owner: no re-file; drop each carry upstream now covers, keep the rest with a ledger reason, re-count at the next release merge · BLOCKED 2026-10-16: another lane — the next release merge (`Merging upstream.md`), which needs a fresh upstream/main

### Standing

- **Discussion Tables (hermes half): pin exempts rooms from the gateway byte budget while its own comment says it does not, and no test touches any new gateway symbol** (`pin_room_history`, `max_active_events`, `DiscussionLimits`, `request_reconciliation`, `stop_unresolved`) · `hermes` · `gateway/hosted_rooms.py:556-577`; degrades stock Group Chat retention, not only discussions. Same review @ `f4abe884a9`. · `d33dff5bbd` covered the three symbols · BLOCKED 2026-10-16: owner decision — should a pinned room count against the gateway byte budget (fix the code to its comment) or stay exempt (fix the comment)? · Recommend: count it, so a pin cannot degrade stock Group Chat retention, then an upstream door PR
- **Spark has a Pro usage bucket but Hermes's ChatGPT-account Codex route rejects it** · observed 2026-09-16: the live model catalog omitted Spark, the same account's usage response named the separate `codex_bengalfox` bucket, and a minimal `gpt-5.3-codex-spark` request returned HTTP 400 "not supported when using Codex with a ChatGPT account." The picker now shows it disabled. Investigate a supported runtime route before enabling it · `EterniaLauncher/docs/mission_control/subsystems/model-picker-account-catalog-contract-20260916.md`, `hermes_cli/codex_models.py`. · BLOCKED 2026-10-16: owner sitting — probe a supported Spark route with a live ChatGPT Pro account



## Upstream-owned


### Filed on arrival — 2026-10-10 (fast gate FG1, filed by the orchestrator)

- [ ] **`tests/verify/test_environment_and_runner.py::test_readiness_timeout_when_nothing_listens` hits the 30 s pytest-timeout on Windows under plain `scripts/run_tests.sh`** · upstream / suite · build-fastgate-FG1 verify-plain run · lane: `scripts/classify_reds_on_tag.py`, then skip-list row or upstream issue · diagnosed 2026-10-15: not a tag red but a 30 s race — `agent/verify/runner.py::_run_start_phase` terminates the shell only; on Windows the start command's own child keeps the stdout pipe, so `proc.stdout.read()` blocks until it exits; the product defect (verify's start phase hangs on Windows) is upstream's · RULED 2026-10-15 owner (decision sheet w1015i #2): yes — post them together in one sitting · BLOCKED 2026-10-16: owner sitting — post the upstream issue at the upstream posting sitting

### Filed on arrival — 2026-10-10 (guard fix, build batch 2 C1–C4, filed by the orchestrator)

- [ ] **An ssh profile's REMOTE cwd is shape-checked with the host's `os.path.isabs`: `tui_gateway/session_workdir.py::_is_remote_cwd_shape`; on Windows under Python ≥ 3.13 `ntpath.isabs("/home/kali")` is False, so `_completion_cwd` drops a named ssh profile's remote cwd to "~" and `_workspace_cwd` refuses it (`session.workspace.move` → 4017)** · upstream / tui_gateway · 4 tests red on pure tag v0.21.6 `818c13be1d`, marked `_up_red_when` (fix/1011-guard-and-tui-reds `462337b735`) · upstream issue (the remote shape wants `posixpath.isabs`) · the four tests are already `_up_red_when`-marked · RULED 2026-10-15 owner (decision sheet w1015i #2): yes — post them together in one sitting · BLOCKED 2026-10-16: owner sitting — post the upstream issue (the remote shape wants `posixpath.isabs`) at the upstream posting sitting

### Filed on arrival — 2026-10-10 (build batch 1, build-1011-B1..B5, filed by the orchestrator)

- [ ] **Upstream `tools/skills_tool._skill_catalog` parses every SKILL.md frontmatter itself, and the kanban environment gate costs 3 ms per tagged skill uncached plus a 1.3 s first-call import** · upstream / skill catalog · build-1011-B2 `9dc0b2ad19` (60/60 parses in a primed cold child) · plan `docs/agent-runtime-harness/planned/skill-catalog-doors-2026-10-15.md` approved by owner 2026-10-15 · DEFERRED 2026-10-16: owner — prepared PR branches stay idle while upstream is not taking the owner's PRs

### Filed on arrival — 2026-10-10 (Fable design sweep D1–D3, filed by the orchestrator)

- [ ] **`preflight_db_writability` reads `os.access` on a sidecar it listed a moment earlier; a WAL unlinked in between reports as read-only** · upstream / state repair · design-sweep-d3 § D3.02 · fork carry built by build-1011-B5; upstream PR owed · the fork carry is built (build-1011-B5); the upstream PR remains · DEFERRED 2026-10-16: owner — prepared PR branches stay idle while upstream is not taking the owner's PRs

### Filed on arrival — 2026-10-10 (fork-fixable sweep lane-1011, filed by the orchestrator)

- [ ] **`tests/conftest.py` step 3b pins `hermes_state.DEFAULT_DB_PATH` only when `hermes_state` is already imported, so an argless `SessionDB()` is import-order dependent; the fork unpins by node id (`tests/_downstream/state_db_scope.py`)** · upstream / suite · `ddf83ac62a` (M4.06) · lane: upstream issue (order-independent pin) · the fork side is done (`tests/_downstream/state_db_scope.py` unpins by node id) · RULED 2026-10-15 owner (decision sheet w1015i #2): yes — post them together in one sitting · BLOCKED 2026-10-16: owner sitting — post the upstream issue (order-independent pin) at the upstream posting sitting

### Filed on arrival — 2026-10-10 (queue sweep lane-1010, filed by the orchestrator)


### Filed on arrival — 2026-10-08 (lane opus-w1-hermes, moved from fork-hygiene)


### Filed on arrival — 2026-10-06 (lane h-suite-tail-b)

- [ ] **`plugins/dashboard_auth/basic` computes a scrypt `_DUMMY_HASH` at import time (~0.2 s), paid again on every plugin re-import (80–122 scrypt calls per test file in the profiles)** · upstream-owned · evidence: lane h-suite-tail-b profiles · an upstream issue or a caller-side memo, never an edit · no caller-side memo reaches a module-level import-time computation without editing the module · RULED 2026-10-15 owner (decision sheet w1015i #2): yes — post them together in one sitting · BLOCKED 2026-10-16: owner sitting — post the upstream issue at the upstream posting sitting

### Filed on arrival — 2026-10-05 (lane h-defer, name-set sweep)


### Filed on arrival — 2026-10-02 (lane w5-fh, filed by the orchestrator)


### Filed on arrival — 2026-10-01 (instance conversations)


### Filed on arrival — 2026-10-01 (lane rw-h)


### Filed on arrival — 2026-09-29 (lane h11-code)


### Filed on arrival — 2026-09-29 (lane h10-rtseam, filed by the orchestrator)


### Embedded (bundled) Hermes — 2026-09-28 (filed by the launcher orchestrator)

- [ ] **Offer the SDK-free httpx client (re-homed `turn_runner`) upstream as a transport "client" door, after the fork polish.** · architecture §4; ask the owner before opening the PR. · RULED 2026-10-10 owner: yes: offer the transport client door upstream · DEFERRED 2026-10-16: owner 2026-09-29 "wait until the fork polish is done"; prepared PR branches stay idle while upstream is not taking the owner's PRs

### Filed on arrival — 2026-09-29 (lane fix-node-deps, filed by the orchestrator)

- [ ] **node-deps: launch-time `npm ci` on Windows fails EPERM when a loaded native binding under `node_modules` is held open (the retry covers ENOTEMPTY only), and the npm error goes to stderr only, so "source-update completion failed" loses the real cause** · `upstream` · `scripts/build/node-deps.mjs` `runNpmCi`, `hermes_cli/source_build.py` `run_source_script` · reproduced 2026-09-29 in a worktree (lightningcss `.node` held by a second node process); the live checkout self-healed at the 12:03 pm sync · filed 2026-09-29 · `runNpmCi` (`scripts/build/node-deps.mjs:67`) retries only on ENOTEMPTY; upstream already skips `npm ci` on an unchanged lockfile via the `--reuse` receipt; the local draft `up/node-deps-reuse-installed-superset` ebd22f05fa covers only the workspace-union trigger · RULED 2026-09-29 owner: HOLD that branch until the EPERM's trigger (workspace selection / node-npm version / `npm_config_*` env) is proven · RULED 2026-10-15 owner: book a weekly operator sitting on the Windows box and run this check there · BLOCKED 2026-10-16: owner sitting — reproduce the held-handle EPERM at the weekly Windows-box sitting and name its trigger

### Filed on arrival — 2026-09-29 (PR #125262 review follow-up, filed by the orchestrator)


### Filed on arrival — 2026-09-27 (lane PR-REPLIES, filed by the orchestrator)


### Filed on arrival — 2026-09-26 (lane HELD-TESTS, filed by the orchestrator)



### Filed on arrival — 2026-09-26 (lane FIX-TRIAGE, filed by the orchestrator)

- [ ] **`hermes_state_schema.py`'s stale-FTS rebuild never recovers on SQLite 3.45.3 (Windows CPython 3.12.5): `DROP TABLE IF EXISTS messages_fts` from a fresh connection raises `vtable constructor failed: messages_fts` when the FTS5 data is corrupt, so FTS stays detached for good** · `upstream` · reproduced on a bare FTS5 table; the four `test_fts_runtime_rebuild.py` reds are `_up_red` rows in `tests/_downstream/id_markers/upstream_reds.py` (lane TRIAGE); sibling of the `state_db_has_structural_damage` row below · PR candidate: on that raise, drop the FTS5 shadow tables under `PRAGMA writable_schema` and recreate · filed 2026-09-26 (lane TRIAGE) · RULED 2026-10-10 owner: wait for upstream; keep the `_up_red_when(sqlite<3.46)` markers; no VACUUM INTO draft · BLOCKED 2026-10-16: upstream — a stale-FTS rebuild that recovers on SQLite < 3.46

- **`agent/skill_utils` spends 480 `realpath` + 698 `os.stat` calls per snapshot build** · `hermes` · `_resolved_path` (three call sites under `resolve_skills`) and `is_skill_support_path` (under `_skill_root_registry`); on Windows each `realpath` is an `nt._getfinalpathname` handle open at ~71 us, so this is the second-largest path-syscall term after the one just retired. Upstream-owned file — the fork's leave-upstream-alone rule means the fix is a caller-side memo or a resolver seam, not an edit there · `docs/agent-runtime-harness/planned/windows-path-syscall-cost-2026-09-08.md` item 3. · `_resolved_path` is fork-owned (`agent_runtime/skill_resolution.py`) and `is_skill_support_path` runs only on a registry rebuild since h-chatperf/CP-5 cached the registries; re-measure on a current snapshot build before memoizing · READY 2026-10-16
- [ ] **`gateway/hosted_room_discussion.py` (85/33) and `gateway/hosted_rooms.py` (72/4) cannot move into fork modules: their bodies call 6+ upstream privates; retire via the Group Chat host-surface widening PR, not a move** · seams · evidence: `docs/agent-runtime-harness/planned/footprint-drop-2026-09-27.md` Outcome · filed 2026-09-27 · fork diff +143/−37 and +72/−4; the bodies call upstream privates, so a fork module would import six-plus `_names` · DEFERRED 2026-10-16: owner 2026-09-29 "park until group-chat work resumes"; 2026-10-10 "parked stays parked"

- [ ] **Every `hermes` process pays upstream start-up work no read-only verb uses: importing `hermes_cli.config` runs provider discovery (`_inject_profile_env_vars` → `providers.list_providers`, ~1.6 s, 38 plugin dirs, 27 YAML loads) and `plugins/model-providers/fireworks` calls `get_version_info()` at import (5+ `git` subprocesses for a User-Agent); `main()` then runs `_warn_pending_fleet_restart_on_startup` (`git` via `get_code_identity`, ~0.8-1.7 s). No fork-side cut exists; upstream PR candidates: lazy OPTIONAL_ENV_VARS injection, a lazy User-Agent** · `upstream` · evidence: the HQ3 commit message on lane/hq-b (`perf(cli): …`, profiles 2026-10-01) · PR candidates (w3-perf 2026-10-01): (a) defer `_inject_profile_env_vars`' provider discovery — `OPTIONAL_ENV_VARS`, `CORE_DECLARED_ENV_NAMES` and the platform-manifest precedence together behind one accessor; (b) build the fireworks User-Agent on first request — drafted as local branch `up/fireworks-lazy-user-agent` (57735398159, red recorded); (c) ask git only when the fleet receipt is unfinished or stale · RULED 2026-10-15 owner: approved: open upstream PRs (a) and (b) · DEFERRED 2026-10-16: owner — prepared PR branches stay idle while upstream is not taking the owner's PRs

### Filed on arrival — 2026-10-03 (launcher orchestrator, owner verdicts)
- [ ] **Seed the door-fit PARTIAL keys (`mcp_servers.<s>.env`, `credential_pool_strategies`, `skills.create_dir`/`external_dirs`/`disabled`, `toolsets:`, `approvals.deny`, `HERMES_MANAGED_DIR`) on persona create — owner ruled 2026-10-03 that HERMES seeds them, not the launcher; the values in `docs/agent-runtime-harness/planned/door-fit-2026-09-27.md` § CARRY-DELETE still need owner picks** · fork / persona create · **RULED 2026-10-10 owner:** orchestrator drafts default seed values from door-fit-2026-09-27.md for the owner to approve · plan `docs/agent-runtime-harness/planned/persona-create-seed-values-2026-10-15.md` approved by owner 2026-10-15 · lines 1-2 seeded at mint + startup sweep (`43378428534`, landed with `build/h4-seeds` 28593ecc42d); line 4 seeds with the S3 commit deleting the shared-root search-tier carry; line 5 needs a placement→incompatible-skill computation; line 6 names an unregistered `eternia-persona` toolset and would flip every persona to `profile_config`; line 8 has no glob form of the class+grant envelope (plan § Build status) · BLOCKED 2026-10-16: owner decision — line 3 (`skills.create_dir` = shared root) lets skill_manage write straight into the published root past the hash-guarded promotion door; seed it? · Recommend: no, keep creates profile-local and promote

### Filed on arrival — 2026-10-03 (lane h-twins)

### Filed on arrival — 2026-10-03 (launcher lane rpc-census, filed by the orchestrator)

### Filed on arrival — 2026-10-03 (cold first-chat diagnosis, filed by the launcher orchestrator)

### Filed on arrival — 2026-10-03 (lane h-chatperf)
- [ ] **Native history is re-read from SessionDB and re-filtered against the turn ledger on every turn though the resident actor holds the same lineage; now measured as `context_native_history_ms`** · fork / `hermes_cli/harness_parts/persona/chat_turn_commit/run.py::_build_context` · decide whether a reused actor whose `native_revision` is unchanged may hand its own messages to the turn (SessionDB stays the authority, the revision is the guard) · evidence: turn `15c73e0c` had 168 ms of `context_built` unattributed (1035 − preload 858 − hud 7 − signature 2) · RULED 2026-10-10 owner: yes: a reused actor with an unchanged `native_revision` hands its messages to the turn; SessionDB stays the authority, the revision the guard · plan `docs/agent-runtime-harness/planned/sessiondb-lineage-stamp-2026-10-15.md` approved by owner 2026-10-15; S1–S3 built on `build/h1-lineage` (the turn hand-off is S3, 52.6 → 6.4 ms on an 800-message lineage); S4, the upstream door draft, waits on the orchestrator sequencing it with Phase B wave 2 · S1–S3 landed (fc3350d3044; `build/h1-lineage` has no unlanded patch) · DEFERRED 2026-10-16: S4, the upstream door draft — owner 2026-10-16: prepared PR branches stay idle while upstream is not taking the owner's PRs
- [ ] **A finished MCP job's background-work row is retired only by the SERVE drain (`completions._settled`); a CLI/TUI drain delivers the wake through upstream `drain_notifications` with no settle hook, so the row lingers as ready/failed until `_FINISHED_TTL_S` (30 min). Give the upstream drain path a settle door, or retire on the CLI/TUI consume** · `tools/mcp_job_wake.py` `note_wake_settled`, `_FINISHED_TTL_S`; `agent_runtime/dispatch_delivery/completions.py` `_settled` · no fork-only door exists: every non-serve consume site is upstream; one additive seam in `tools/async_delegation.py` `complete_event_delivery` is the sooner option; the 30-min `_FINISHED_TTL_S` bounds it meanwhile · DEFERRED 2026-10-16: owner 2026-10-05 "PARKED as recommended — waits on its upstream door / the next mcp pin bump"; 2026-10-10 "parked stays parked"
- [ ] **`mcp_jobs.json` (the `mcp_job` running_work checkpoint) is not in the runtime-file skip lists `processes.json` sits in — `hermes_cli/backup.py` `_IMPORT_SKIP_NAMES` and its export list, `hermes_cli/profiles.py` clone skips, `hermes_cli/container_boot.py` `_STALE_RUNTIME_FILES`. The reader already drops dead-writer rows, so this is hygiene (a backup or a cloned profile carries a stale job list), but those are upstream files: add through a fork door or carry** · `agent_runtime/running_work/vocabulary.py` `_MCP_JOBS_FILENAME` · all three are at upstream's merge-base bytes, so a carry widens the upstream footprint by three files for hygiene the reader already covers · DEFERRED 2026-10-16: owner 2026-10-05 "PARKED as recommended — waits on its upstream door / the next mcp pin bump"; 2026-10-10 "parked stays parked"

## Filed on arrival — 2026-10-09 (owner: a built-in way to message a persona through the running serve)

## Filed on arrival — 2026-10-09 (perf programme close-out sweep)

- [ ] **OWNER live proof owed for the 2026-10-09 send-prep fixes: on a rebuilt serve, ~8 warm Neko/Dev turns (one Dev chat of 20+ rows) and read `turn-timing`: (a) tool-form one owner (`settle_turn_tool_form`, plan `docs/agent-runtime-harness/planned/tool-form-one-owner-2026-10-08.md`) — `mcp_refresh_ms`≈0 and `tool_form_receipt source=unchanged publishes=0 pin_written=0` on warm turns, warm median vs 259.5 ms; (b) the native-revision double read (`1ecc5ed668`) — matched before/after on the 20+ row chat; (c) the 400 ms warm `send_prep_total` budget holds. All three are fixture-proved only** · fork / send-prep · evidence: tool-form S0–S4, opus-w1-sendprep report · lane: operator live turns (an agent can send them with `hermes harness mission-chat message`, which now runs in the live serve) · BLOCKED 2026-10-16: owner sitting — ~8 warm Neko/Dev turns on a rebuilt serve, read off `turn-timing`
- [ ] **~8 ms of the warm `context_built` span is still unstamped (journal abandoned-id read, relay marker, registry) after the native-revision fix; below the 5 ms single-part bar today, stamp it if send-prep is worked again** · fork / send-prep · evidence: opus-w1-sendprep attribution section in `docs/agent-runtime-harness/planned/warm-prep-integration-2026-10-08.md` · DEFERRED 2026-10-16: owner 2026-10-10 "not now; stays parked until a send-prep lane"

## Filed on arrival — 2026-10-09 (GenUI wire receipts)



## Filed on arrival — 2026-10-09 (Console history authority audit)

## Filed on arrival — 2026-10-09 (launcher transcript capability audit; the launcher halves are in `eternia_launcher/Launcher_Brain/20 — Active Initiatives/mission-control-queue.md` under the same-dated heading)
- [ ] **No turn-level record says what a turn left behind — tests run and their verdict, commits made, whether they were pushed; `commit` appears only in realm sync and the build stamp.** fork / the turn record, `agent/tool_executor.py` · Derive a typed turn-outcome record from the turn's own tool results (terminal commands matching test/commit/push shapes, their exit codes, file tools' paths) and project it on the turn; a client renders it in its fold summary. Decide first whether derivation belongs to a plugin hook or the executor. Starting point, verified 2026-10-14: upstream `agent/turn_summary.py::TurnSummaryCollector` already tallies a turn from `tool.completed` events ("edited 2 files +18 -3 · read 4 files · ran 3 commands"), but it is CLI display only (`hermes_cli/cli_status_bar_mixin.py`), skips failed calls, and no serve RPC verb or `api_server` endpoint carries it; `TurnReceipt` (execution state) and the settle `TurnOutcome` (accepted/refused) are not this record either. · RULED 2026-10-10 owner: derive the turn outcome in a plugin hook, not the upstream executor · DEFERRED 2026-10-16: owner 2026-10-15 — the hermes half can wait and is not on hermes' next wave

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

- [ ] **Emit running_work and chat mints on the patch lane** — the launcher row "running_work and chat mints on the patch lane" waits on the hermes emitter. OWNER RULING 2026-10-15: on hermes' next wave · fork / serve patch lane · the chat half shipped: a chat turn's running_work row and a new chat's open ride the `persona_chat_turn` / `persona_chat_open` frames (a317870c7f); left is non-chat running_work (build and terminal rows), whose terminal writer is upstream `tools/process_registry.py` · RULED 2026-10-16 owner: no — no read-time projection writes `state.patched` for build/terminal running_work rows; they stay on the full-core lane until hermes owns a fork chokepoint that writes them (reverses the 2026-10-15 yes) · NEEDS PLAN 2026-10-16: the fork-owned writer for build/terminal running_work rows that a keyed `state.patched` can hang off

## Filed on arrival — 2026-10-15 (lane w1015b-con-x)

- [ ] **An in-place provider-SDK install is not entered in pm's feature ledger: `runtime.provider.dependency.install` (`agent_runtime/provider_dependencies.py`, `pm/_fork_extend_environment.py`, wave w1015b-con-x) puts the extra into the running environment with `uv pip install`, so the next generation pm builds for any other reason starts without it and the Connections warning returns** · fork / pm seam · record the extra in the install's selection (the `pm install --extra` ledger) when the in-place install succeeds, or have the generation build carry `extend_environment`'s extras · found 2026-10-15 lane w1015b-con-x · NEEDS PLAN 2026-10-16: how the in-place install is recorded honestly — the venv fact is {extras, stamp} with stamp = expected_stamp(extras) of a LOCK-pinned build (`pm/install.py` `_target_selection`/`_commit_selection`) while `extend_environment` installs pyproject specifiers: (a) extras only, so the next launch builds a generation carrying it; (b) extras+stamp over an unpinned env; (c) install the lock's pins for the extra and write both — recommended (c), else (a)

## Filed on arrival — 2026-10-15 (owner: provider SDKs on first setup)



## Filed on arrival — 2026-10-15 (lane e-triage: blockers with no row)

- [ ] **Publish an exact provider usage/reset contract (per-credential window, used/limit, reset time) on the runtime wire, so the Launcher's usage menu and companion rows stop inferring it.** · runtime / providers · launcher companion row "Qualify an exact runtime usage/reset contract…" waits on it · found 2026-10-15 lane e-triage · DEFERRED 2026-10-16: owner 2026-10-15 on the launcher companion row — the hermes half can wait and is not on hermes' next wave

## Filed on arrival — 2026-10-15 (launcher lane w1015e-mc-l)

## Filed on arrival — 2026-10-15 (lane w1015i-packs)

## Filed on arrival — 2026-10-15 (lane w1015j-hermes)

- [ ] **`hermes_cli/harness_parts/verify_commands.py` (`--mode live-tony`) asserts the store root equals one machine's path — the lowered `store_root()` compared to the literal owner's `<drive>:/Eternia/.hermes/agent-runtime` → `runtime_root_mismatch` — so the verify mode fails on every other machine and passes on this one whatever the configured root** · runtime / harness CLI · compare against the resolved default root (`hermes_constants.get_default_hermes_root() / "agent-runtime"`) or delete the live-tony arm if nothing calls it · READY 2026-10-16 **TAKEN 2026-10-16 claude (r-turnrec)**

## Filed on arrival — 2026-10-15 (backend build wave A, realms)

- **Map backend `409 realms.git_host_binding_lost` like `realms.git_host_unbound` (stop retrying), not to `sync_remote_unreachable`** · `hermes` · the backend's realm sync used to answer a permanent 503 when the GitHub App binding vanished mid-sync; since backend `0543d8b6` (REALM-SYNC-PERMANENT-503-1) it is a typed 409 that will not heal on retry · backend `docs/architecture/contracts/nexus/FRONTEND_STAGES.md` realms errors. · READY 2026-10-16

- [ ] **Compaction never reaches the native conversation lane: `agent/conversation_compression.py` `_emit_compaction_done` calls `status_callback("compacted", COMPACTION_DONE_STATUS)` with two arguments into the profile runner's one-argument `StatusEmitter.emit` (`agent_runtime/profile_runner/status.py`), so it raises inside `_swallow` and is dropped; `agent/compaction_events.py` publishes telemetry only. Forward compacting/compacted as a frame the launcher's conversation lane receives (launcher MC row D03 waits on it)** · found 2026-10-15 w1015j-mcshell · READY 2026-10-16 **TAKEN 2026-10-16 claude (r-turnrec)**


## Filed on arrival — 2026-10-16 (backend build wave B, realms)

- **`REALM-REVOKED-CLIENT` — on backend `realm.revoked` (`personal:`, durable) mark the realm credential expired, stop its sync loop, keep local data; on reason `git_host_unbound` also surface host state** · `hermes` · backend `docs/architecture/02-realms-nexus.md` §4, EVENT_CATALOG `realm.revoked` (backend lane b-commerce, wave B) · `docs/agent-runtime-harness/03-transport-and-wire.md`. · READY 2026-10-16
- **`REALM-LOCAL-CRED-SOURCE` — local realms take their credential from the launcher via backend `POST /api/me/realms/local:<id>/sync/credential` (frozen credential JSON, `realm_id=local:<id>`); keep the local allow stub** · `hermes` · backend 02 §4c · `docs/agent-runtime-harness/01-system-architecture.md` § Realm sync. · READY 2026-10-16
- **`REALM-COURSE-SUBJECT` — map `realm_id = course:<id>` in `RealmSyncCredential` (education git courses now mint clone credentials through backend `POST /api/education/git-courses/{id}/clone-credential`)** · `hermes` · backend lane b-edu, wave B 2026-10-16, `docs/architecture/planned/education-git-course-lane.md` Stage 5. · READY 2026-10-16


- [ ] **The operator chat send (`persona.chat.send` / the chat turn) accepts text only, so a pasted image never reaches a vision model: accept bounded image content parts (PNG/JPEG; the launcher converts BMP/clipboard formats), pass them to the provider as image parts for a vision-capable model, and refuse with a typed error for a model without vision** · seam / operator chat send · launcher `mission-control-queue.md` "A pasted image never reaches the model" (launcher half: `lib/features/agent_console/panel/agent_console_pasted_image_policy.dart` `messageWithPastedImages` sends a text manifest only) · owner sitting 2026-10-15 · NEEDS PLAN 2026-10-16 (lane r-chatsend): the send reaches the model through four text-only seams — `AgentRunRequest.user_message: str` (`agent_runtime/profile_runner/models.py`), `persona_runtime._mission_chat_user_message` (HUD + skill preload fold onto a string), the pre-persisted operator row a pending turn REUSES (`chat_turn_commit/run.py` `reuse_current_user_message`, so a retry would drop the image) and `model_input_observability`; upstream `agent/image_routing.py` (`build_native_content_parts`, `decide_image_input_mode`) is the door. The plan decides: the RPC param shape and bounds (count, bytes, PNG/JPEG magic check), where attachments are stored durably so replay and the launcher bubble can read them, and the refusal when `decide_image_input_mode` answers `text` because an `auxiliary.vision` backend is configured for a vision model

- [ ] **Lens L1: manifests carry `credential_ref`, resolved from the hermes credential pool per read (persona home); redaction test on every evidence path** · plan launcher `EterniaLauncher/docs/companion/planned/MONITORING_CREDENTIALS_SEPARATION_2026-10-15.md` S2 (owner-approved 2026-10-15) · killing mutation: inline the resolved value into the stored evidence row → the redaction test reds · unblocks launcher companion-queue row "Separate ordinary feature-vault migration…" (S3) · READY 2026-10-16 **TAKEN 2026-10-16 claude (r-realm-lens)**
