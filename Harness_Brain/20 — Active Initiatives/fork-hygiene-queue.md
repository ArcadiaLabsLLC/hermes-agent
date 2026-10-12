---
type: queue
program: fork-hygiene
status: open
tags: [queue, program/fork-hygiene]
---

# Fork hygiene — open queue

- [ ] **Bound or archive accumulated run receipts through the existing gate store without discarding unresolved first-attempt evidence.** `run_tests_bundled_plan.record_run` appends indefinitely; `last_record` and `GateStore.prior_skip_runs` read the entire `runs.jsonl`, while `GateStore.compact` only compacts green/dependency/module-set records. H13 caps each diagnostic at 64 Ki characters but does not change the existing run-history lifecycle. Define retention/archive semantics once in the store, keeping the latest final-red state and investigation receipts. · fork / suite storage · evidence: named symbols; `docs/downstream/test-safety-evidence-repair-2026-10-12.md` · filed 2026-10-12 test-safety-evidence-repair



- [ ] **Qualify the declared-conversation-scope and backup bundle leaks before changing their isolation policy.** Candidate `292a429351` whole fork gate (2026-10-12) reports `tests/agent/test_declared_conversation_scope.py::TestSourceOverrideDomain::test_the_pre_row_source_matches_persistence` red after 14 preceding members, then green alone; `tests/hermes_cli/test_backup.py` reports 19 failures after agent-list-skill-sources, apply-profile-override and auth-noninteractive tests, then green alone. A bounded 19-file control on unchanged main source `9b9b0d4010` reproduces the scope failure with the exact 14-file prefix and isolated pass; backup passes with its exact three-file prefix. Scope is baseline-proven, backup remains intermittent/unqualified. Neither isolated success nor absence of a feature diff proves the cause. Evidence: named test files and `scripts/run_tests_bundled.py` leak receipts, local logs `history-native-runtime-final-gate.log` and `history-native-new-leaks-main-control.log`. · fork / suite · **READY 2026-10-12 h10-context — H10 fix [PR #8](https://github.com/ArcadiaLabsLLC/hermes-agent/pull/8), 9e5e6e149a; 59 pair tests without retry plus 25 focused passes / 3 skips; shared session-chain landing batch still required. H11 remains UNCLAIMED** · TRIAGE 2026-10-12: [H10/H11](../../docs/downstream/history-red-triage-2026-10-12.md).
- [ ] **Diagnose the Codex responses test process death in a completed fork gate.** On `292a429351` (2026-10-12), bundle 9 dies in `tests/agent/test_run_agent_codex_responses.py`, then that file passes alone and three following members are re-bundled. The full gate finishes, but the green isolated run does not qualify the crash. **TRIAGE 2026-10-12:** the existing runner discards the original bundle output when an isolated retry passes (`run_tests_bundled.run._bundle`), `Death` retains neither exit status nor prefix/output, and `run` removes the event scratch directory. Preserve first-attempt diagnostics through this same runner before attempting the exact-prefix reproduction; do not build a parallel runner or infer a timeout from the missing output. Current-main isolated control passes 69 tests. Evidence: named test and runner symbols, local `history-native-runtime-final-gate.log` and `history-red-triage-hermes-focused.log`. · fork / suite · UNCLAIMED · TRIAGE 2026-10-12: [H12/H13](../../docs/downstream/history-red-triage-2026-10-12.md).


## Filed on arrival — 2026-10-09 console history qualification


## Filed on arrival — 2026-10-09 (final gates)


## Filed on arrival — 2026-10-08 (lane opus-w1-hermes)


## Filed on arrival — 2026-10-08 GenUI qualification

- [ ] **Diagnose the running-turn stream intermittent remaining after the HTTPS-scanning control.** After the operator disabled scanning, the ten H01 files pass across controls (96 distinct passes / one existing skip), with certificate and permission assertions unchanged. On `f6c27f4d0b`, `tests/agent_runtime/test_serve_gateway_chat_reply_lanes.py::test_a_running_turn_publishes_its_own_start_and_end_on_the_stream_lane` fails its six-second start-frame wait under eight-worker load, then both file tests pass serially. The two-roots file also passes all nine when allowed its declared duration; its earlier 120-second cap was a command choice. Trace the start-event publication/fixture boundary before changing behavior or deadlines. The former certificate blocker is qualified; the parallel failure remains evidence. Separate from H03 commentary. · fork / suite · UNCLAIMED · [H01 control and log digests](../../docs/downstream/history-red-triage-2026-10-12.md#https-scanning-control-after-the-operators-setting-change).

## Filed on arrival — 2026-10-06 (lane console-generated-content)



The repository AS A FORK: upstream sync and the boundary, CI, the suite and its gates, the god-file refactor, this vault. Runtime and Mission Control rows do NOT go here — the hermes half is [[runtime-queue]], the launcher half is `EterniaLauncher/Launcher_Brain/20 — Active Initiatives/mission-control-queue.md`. Rows: one line + a pointer, never a restatement; claim with `**TAKEN <date> <who>**` before starting; a landing deletes its row.

## Filed on arrival — 2026-10-06 (lane h-prereq-window)


## Filed on arrival — 2026-10-05 (owner ask: a usable suite)

- [ ] **Per-test full plugin rediscovery is about half of a store-heavy file's CPU: `discover_plugins` ×81 per file ≈ 48% of `test_persona_assignments` profiled time, called from `agent_runtime/tool_visibility._ensure_plugin_tools_registered` after `tests/conftest.py::_hermetic_environment` resets plugin managers; the same reset is the `test_run_agent` floor — needs a ruling on whether bundled-plugin load may be session-cached** · `fork / suite` · evidence: lane h-suite-tail-b `9cc27e7f66` profile · UNCLAIMED · released 2026-10-10 (lane-1010 returned L7.04, owner decision; reason in `queue-sweep-2026-10-10/L7-outcomes.md`) · **RULED 2026-10-10 owner:** yes: session-cache bundled-plugin discovery across tests, with a reset fixture
- [ ] **A bare pytest over files from several test directories hangs `test_gateway_spawn_fence::test_subprocess_run_refuses_the_measured_argv` (the fence is not armed; a real `gateway run` starts) and reddens `test_conftest_isolation_downstream` test_2/test_4; red on main `71079deb70`** · `fork / suite` · evidence: lane h-suite-hermetic report · UNCLAIMED · released 2026-10-10 (lane-1010 returned L8.06, workstation hazard; reason in `queue-sweep-2026-10-10/L8-outcomes.md`)
- [ ] **`test_work_service.py::test_concurrent_retry_admits_one_native_task` load-flakes at 12 workers (wall-clock admission window), red in two different bundles, green at 8** · `fork / suite` · evidence: same plan §1.2 · UNCLAIMED · released 2026-10-10 (lane-1010 returned L6.07, workstation hazard; reason in `queue-sweep-2026-10-10/L6-outcomes.md`)
- [ ] **Owner ask: make the partial (fork-scope) and full test suites fast enough to use — the fork gate ran 872 files / ~13k tests in ~18 min wall at 8 workers (per-file seconds summed 5,977; slowest file 233 s), ~13 tests/s, against the launcher's Flutter suite at ~40,000 tests in 8 min (~83 tests/s); the full scope is 6,066 files and on hold for the P0 freeze. Measure where the time goes (interpreter + import cost per process, conftest/fixtures, hermetic env setup, the slow tail, timeouts, Defender, worker count) and write a staged plan** · `fork / suite` · evidence: landing h-turn1 wave 2 gate log (2026-10-05 20:22–20:40 local) · **TAKEN 2026-10-05 Opus 5.5 (owner session, lane h-suite-speed)** · **PLAN `plan/h-suite-speed` `6d2db880cf`; owner took O1–O5 as recommended 2026-10-06; exec lanes h-suite-runner (stages 0–3), h-suite-tail-a / h-suite-tail-b (stage 4); stage 5 after three identical failure sets, 6–7 after** · **Stages 0–4 LANDED `15d4e37d0d` (2026-10-06; full-tree gate 1059 s → 813 s, 99% utilization); open: stage 5 after three identical failure sets, then 6–7**

## Filed on arrival — 2026-10-05 (lane h-turn1-title)


## Filed on arrival — 2026-10-05 (lane h-turnws, the workstation freeze)

- [ ] **P0 — the validated suite froze the operator's workstation twice on 2026-10-05 (hard freeze, reboot both times), and both times the same four files were in flight: `tests/hermes_cli/test_source_check.py`, `test_source_launcher_publication.py`, `test_source_release_channels.py`, `test_source_release_probe.py`. Run 1: `scripts/run_tests.sh tests/agent_runtime tests/hermes_cli tests/hermes_state`, 8 workers, frozen at 82.5% immediately after `test_source_stamp.py` and `test_spawn_gateway_restart_cooldown.py` reported. Run 2: only the 453 files run 1 never finished, 4 workers, nothing else heavy running, frozen within about a minute, right after `test_source_channel_integration.py` reported (so the in-flight set was a subset of those four). Both runs printed `real store root handed to the gateway fence`, and the operator's own gateway (`hermes_cli.main gateway run`) was up during run 2. NOT reproduced a third time, on purpose. Find which file does it — one at a time, under a watchdog or in a VM, never on the operator's desktop — and until then no lane runs the validated suite on a workstation with these four in scope** · `fork / suite` · the two interrupted run logs are not in the repo; the facts above are their last lines · the 311 `tests/hermes_cli` and 142 `tests/hermes_state` files after that point have NOT run for lane h-turnws · **Added the same day (owner's question):** all four files are UPSTREAM's (listed in `tests/fixtures/upstream_manifest.txt`), so the fork's own landing gate (`scripts/run_tests_bundled.sh …`, `--scope fork`, `docs/downstream-development.md` § "The fork landing gate") would not have run them; the lane ran `scripts/run_tests.sh` over the three directories because `CLAUDE.md` § Commands calls that "THE suite" and its landing discipline says "the validated suite". The two documents disagree about what a landing runs — make `CLAUDE.md` name the fork gate for a landing and keep the full scope for the weekly upstream merge lane · UNCLAIMED · released 2026-10-10 (lane-1010 returned L6.09, workstation hazard; reason in `queue-sweep-2026-10-10/L6-outcomes.md`)
## Filed on arrival — 2026-10-05 (lane h-turnws)


## Filed on arrival — 2026-10-04 (lane hb-a)


## Filed on arrival — 2026-10-03 (resident identity verification)


## Filed on arrival — 2026-10-02 (lane h-rows)


## Filed on arrival — 2026-10-02 (instance foundation)

- [ ] **Resolve intermittent realm-history ordering and validated-suite residuals without declaring retry passes stable.** · `fork / suite` · `test_realm_sync_history.py::test_history_lists_local_and_upstream_versions_with_their_items` fails on candidate and clean main `6c5cc00678`; download-pause assertions and three Git fixture setup errors pass isolated reruns. Raw receipts: `resume-hermes-validated.log`, `resume-main-hermes-residuals.log`, `resume-hermes-final-focused.log`, `resume-main-realm-history.log`. Includes `test_local_download_jobs`, `test_local_models_routes`, `test_delivery_directive`, `test_realm_revert_version`, `test_source_channel_integration`; cause not established. · UNCLAIMED · EVIDENCE 2026-10-03 resident identity: reproduced again on unchanged main `541f497902`; `identity-baseline-suite-2026-10-03.log`, exact failure-set comparison in the [repair note](../../docs/agent-runtime-harness/planned/instance-conversations-2026-10-01.md#resident-identity-repair-october-3). · EVIDENCE 2026-10-07 console relay: red after `test_realm_sync_eol.py` in a completed bundle, green isolated; the same two-file bundle on unchanged `8a5c19d412` passed 7/7. Intermittence remains open, not declared fixed; qualification in `e357dec49a`. · released 2026-10-10 (lane-1010 returned L8.10, too big (part fixed); reason in `queue-sweep-2026-10-10/L8-outcomes.md`) · designed in `docs/agent-runtime-harness/planned/design-sweep-d3-2026-10-10.md` § D3.12: INVESTIGATION: bundle-prefix bisect protocol in the plan · released 2026-10-10

## Filed on arrival — 2026-10-02 (lane w13-hm, filed by the orchestrator)


## Filed on arrival — 2026-10-02 (lane w10-s7h)


## Filed on arrival — 2026-10-02 (lane w5-fh)


## Filed on arrival — 2026-09-30 (GenUI invocation)


## Filed on arrival — 2026-10-01 (lane w3-turn)


## Filed on arrival — 2026-10-01 (lane w3-perf)


## Release validation — 2026-09-23


- **Provider-boundary qualification, October 1:** the existing TLS setup stall and duplicate-name/routing-ladder gate failures were reproduced, not waived; [evidence](../../docs/downstream/provider-access-boundary-2026-10-01.md#qualification). Native provider, plugin and execution checks pass; this does not certify a whole-repository green run.


- [ ] **Diagnose the local CLI startup stall opening the inherited TLS key-log device target.** · The bounded inspector trace stops at `ssl.create_default_context` assigning `keylog_filename`, reached while `pm/downloader.py` constructs its opener during startup; no chat journal was created. Preserve certificate validation and logging oversight; classify host configuration versus startup handling before changing code. [Preflight evidence](../../docs/downstream/launcher-qa-preflight-2026-09-30.md#local-startup-stall). Filed 2026-09-30 Projects QA. released 2026-10-10 (claim by w5-fh 2026-10-02 lapsed; its verdict below stands) · VERDICT 2026-10-02 w5-fh: classified: HOST trigger, UPSTREAM amplifier. Nothing in hermes or the launcher sets SSLKEYLOGFILE (grep; absent from HKCU and HKLM Environment now), so the value was inherited from whatever parent started that QA session. The amplifier is upstream `pm/downloader.py` (upstream bytes): `_OPENER = urllib.request.build_opener(...)` at MODULE scope builds an HTTPSHandler, whose default context reads SSLKEYLOGFILE and opens it at import, on every CLI start that imports the downloader, for commands that never download. Reproduced on the test venv (3.14): SSLKEYLOGFILE to a missing dir or a nonexistent pipe makes `import pm.downloader` raise FileNotFoundError; NUL or CON aborts the process (`OPENSSL_Uplink ... no OPENSSL_Applink`, rc=1); a device whose open blocks stalls exactly as traced. Recommended (a): upstream PR making the opener lazy (built on first request), so a bad key-log target fails the download that asked for TLS rather than CLI startup; certificate validation and key logging are unchanged. (b) the launcher strips SSLKEYLOGFILE from the env it spawns hermes with: hides a deliberate operator setting, not recommended · released 2026-10-10 (lane-1010 returned L7.12, upstream; reason in `queue-sweep-2026-10-10/L7-outcomes.md`)


- **Additional evidence for the claimed validated-suite residuals:** 68 gateway/TLS failures reproduce on clean primary with Python 3.13.15; this does not supersede the separate Python 3.12 green receipt. [Comparison](../../docs/downstream/chat-first-group-qualification-2026-09-29.md#baseline-comparison). Filed 2026-09-29 chat-first-groups.





- [ ] **Isolate wrapper-publication tests before resuming interrupted desktop qualification.** · Whole-PC freeze during the single-worker continuation; running-wrapper publication is the last surviving fixture, not a proven cause. Preserve evidence; use contained off-desktop reproduction, not an unbounded rerun. [Incident boundary](../../docs/downstream/discussion-qualification-2026-09-28.md#host-freeze--qualification-interrupted). Filed 2026-09-28 Discussion qualification. · VERDICT 2026-09-29 h10-fhrel: static read done — `tests/hermes_cli/test_source_launcher_publication.py::test_running_source_launcher_can_republish_itself` runs the freshly published native `hermes.exe`/`.cmd` once (`subprocess.run`, 30 s timeout) and that child rewrites its own running launcher; nothing in the body is unbounded, so the test is a candidate trigger only through the OS/driver side of self-overwrite. Owed: one contained reproduction in a disposable Windows VM with commit/process limits and per-file diagnostics (a box this lane does not have); the updater-retarget half of the residual population is fenced by `319c6ff69d`, so the VM run no longer reaches the primary checkout · OWNER 2026-09-29: park, low priority; needs a disposable VM · VERDICT 2026-09-29 h11-back: parked per the owner decision; no disposable Windows VM on this box, so the one contained reproduction stays owed — (a) run it in a disposable VM with commit/process limits [recommended, when one exists]; (b) close as not-reproduced after the next clean desktop qualification · PARKED 2026-09-29 (released by orchestrator: waits on the owner's trigger in its OWNER line / the VERDICT's named precondition) · released 2026-10-10 (lane-1010 returned L6.13, workstation hazard; reason in `queue-sweep-2026-10-10/L6-outcomes.md`)


### Filed on arrival — 2026-09-29 (h11-mcp landing)


### Filed on arrival — 2026-09-29 (lane h10-fhrest)


### Filed on arrival — 2026-09-29 (lane h7-phone)


### Filed on arrival — 2026-09-28 (lane w5-hstt)

### Filed on arrival — 2026-09-29 (lane h10b-triage — the three-directory triage, one row per class)


### Filed on arrival — 2026-09-28 (lane w4-hfix2)

### Filed on arrival — 2026-09-27 (Windows console signal safety)

- [ ] **Retire the Windows signal-safety carry when upstream adopts an equivalent fix.** · [[Windows console signal safety]]; held upstream candidate recorded in `docs/agent-runtime-harness/planned/upstream-footprint-ledger.md`; no parallel supervisor or PID helper added, no PR submitted. · VERDICT 2026-09-29 h10-fhrel: not retirable yet: `tui_gateway/host_supervisor.py` and the carry's other files at manifest base `ee5f49b943` are still upstream's pre-fix bytes (the fork diff is intact), so upstream has not adopted an equivalent. Owed: re-check at the next upstream merge; retire in that merge's lane if upstream carries it · OWNER 2026-09-29: nothing now; re-check at the next upstream merge · VERDICT 2026-09-29 h11-back: re-checked against upstream/main `0f6554792f` (fetched 2026-09-29, after the `merge/upstream-2026-09-29` round): `tui_gateway/host_supervisor.py::_pid_alive` still calls `os.kill(pid, 0)` and `tests/conftest.py`'s stale-lock sweep still does, so upstream has no equivalent — (a) keep the carry, re-check at the next upstream merge [recommended]; (b) offer the `_pid_exists` swap upstream as a PR · PARKED 2026-09-29 (released by orchestrator: waits on the owner's trigger in its OWNER line / the VERDICT's named precondition) · released 2026-10-10 (lane-1010 returned L7.13, owner decision (standing trigger); reason in `queue-sweep-2026-10-10/L7-outcomes.md`) · **RULED 2026-10-10 owner:** carry stays; re-check at the next release merge

### Filed on arrival — 2026-09-26 (native Hermes qualification)

- [ ] **Finish classifying the validated-suite residuals, including the two worktree-only fleet identity assertions and baseline gateway certificate mismatch blocking registered mutations.** · [Native qualification evidence](../../docs/downstream/native-hermes-qualification-2026-09-26.md); [[Windows console signal safety]] adds an incomplete one-hour run and failures reproduced on primary in 33 of 35 files; no baseline expansion or unrelated runtime repair was made. · VERDICT 2026-09-29 h10-fhrel: the classification needs the validated suite (~1 h) plus the fleet/gateway certificate fixtures on an isolated host; the two siblings this lane could settle from the tree are closed (doc-cite `dd153d6946`, frozen-home refuted `930b335b48`). Owed: the program-end validated-suite run classifies the fleet identity pair and `ServeCertificatePinMismatch` against a clean primary · OWNER 2026-09-29: classify in the same overnight run as the 561 triage · VERDICT 2026-09-29 h10b-triage: both named residuals are green in a worktree — `test_fleet_matrix_down_state.py` 7/7, `test_local_llama_adapter_gateway.py` 2/2 ([triage note](../../docs/downstream/triage-561-2026-09-29.md)); the rest of the validated-suite residual population is outside the three-directory run and still needs the validated suite, so the claim stays · SWEPT 2026-09-30 h13-sweep: the two named residuals are green (h10b-triage); the rest of the validated-suite residual population is unclassified and waits on the program-end validated-suite run · EVIDENCE 2026-09-30 unified-genui: completed 2,173-file run; 101/108 failed assertions and 14 collection/exit failures reproduce on primary; [comparison](../../docs/downstream/unified-document-native-tools-2026-09-30.md#qualification--2026-09-30). · EVIDENCE 2026-09-30 hermes-work-view: 2,176-file run, 31/35 residual assertions and all 14 collection/teardown failure files reproduce on primary; four checkout-dependent fleet/updater assertions remain. [Receipt](../../docs/downstream/hermes-work-view-2026-09-30.md#validation). · EVIDENCE 2026-10-03 resident identity: reproduced again on unchanged main `541f497902`; `identity-baseline-suite-2026-10-03.log`, exact failure-set comparison in the [repair note](../../docs/agent-runtime-harness/planned/instance-conversations-2026-10-01.md#resident-identity-repair-october-3). · EVIDENCE 2026-10-06 operator Stop audit: the whole-tree fork gate selected 891 files; all 113 failure/error nodes in 31 files reproduced on clean pre-fix main, with zero branch-only nodes. Current-main legibility/duplicate-helper/doc-cite drift was also qualified after rebase; [receipt](../../docs/downstream/operator-stop-audit-2026-10-06.md). · EVIDENCE 2026-10-07 console relay: 117 residual failure/error nodes in 35 files match detached unchanged `8a5c19d412`; drift diagnostics also match. The one branch-only plain-head admission regression was fixed and the final 14-file run passed 238 tests. Fork-only scope, exact commands, node-set digest and red/green proof are recorded in `e357dec49a`; no full upstream suite was run. · EVIDENCE 2026-10-10 result-authority: whole-tree fork scope selected 941 files, 11,888 passes; after removing this lane's stale wording-test waiver, all 97 remaining failing/error nodes in 25 files match untouched `d2cb51d7af`. [Exact node sets and controls](../../docs/downstream/native-result-policy-2026-10-10.json). No baseline was expanded. · EVIDENCE 2026-10-10 native representation: all 97 residual nodes reproduce on untouched `f43ffb8efe`; this change's two routing violations were repaired, final focused/structure selection 163 passed. [Review and qualification](../../docs/downstream/native-representation-2026-10-10.json). · released 2026-10-10 (lane-1010 returned L8.13, too big; reason in `queue-sweep-2026-10-10/L8-outcomes.md`) · designed in `docs/agent-runtime-harness/planned/design-sweep-d3-2026-10-10.md` § D3.14: INVESTIGATION: 25-file classification protocol in the plan (fast-gate `classify_reds_on_tag.py` automates it) · released 2026-10-10

  EVIDENCE 2026-10-06 console-generated-content: the 895-file fork gate's exact
  115 failure/error nodes in 33 files reproduce on unchanged `5c0f130723`;
  the 35 unique helper/legibility/citation violation lines also match.
  [Receipt and remaining native acceptance](../../docs/downstream/console-generated-content-2026-10-06.md).

### Filed on arrival — 2026-09-26 (lane FIX-TRIAGE, filed by the orchestrator)





## Filed on arrival — 2026-09-30 (Stage 2 G4 landing, filed by the orchestrator)




## Filed on arrival — 2026-09-30 (launcher engine-build diagnosis, filed by the launcher orchestrator)


## Filed on arrival — 2026-09-29 (footprint attribution, filed by the orchestrator)

- [ ] **Move the phone lanes' edits out of upstream files first: 25 files raised `[up-fp]` 155 → 177 with no reasons rows — `7d80bad505` (p2-hphone, 13), `aae4d60d02` (p2-hsdk, 9), `dbf8257326` (h7-phone, 3). Per file: move the fork behaviour into a fork-owned module or seam and restore upstream's bytes; ONLY an edit that cannot move becomes an upstream-PR candidate (one clean commit on `upstream/main`); keep-with-reasons-row is the last resort. Ratchet the fixture down as files leave.** · `fork / upstream sync` · owner ruling 2026-09-29: "only PR it if it can't move out of upstream files" · the p2-hsdk PR half is also gated on the runtime-queue row "Offer the SDK-free httpx client … ask the owner" · filed 2026-09-29 · 2026-09-29: work it per SEAM CLASS, not per file — the ledger's `hook` rows repeat four one-liners across ~40 upstream files (phone-wheel `loop_tool_lifecycles.shipped()` guards ×12, phone-credential `secret_files.view()/bound()` ×11, phone-history `host_store.history` ×8, provider-SDK `agent.provider_sdks: false` fallback ×9); one fork mechanism per class (import-time placeholder, one path-helper override, one DB-opener override, one SDK shim) retires the whole class · 2026-09-29 h11-fp: phone-wheel class, 4 files back to upstream's bytes (`copilot_acp_client`, `codex_app_server`, `tts_tool_lifecycle`, `image_routing`) and `tts_tool`'s seam hunk, by three more loop stand-ins (`4c712e9e1d`); left in that class, with why: `tools.process_registry` (`client_lifecycle`, `prompt_turn`, `session_notifications`: the registry's surface is too wide for a stand-in and the poller would start), `tools.terminal_tool` (`relay_cwd`, `session_workdir`, `agent_callbacks`: ~30 kept importers catch ImportError, a stand-in turns it into a RuntimeError), `agent_init` (a fork function, the floor row), and the shared-provider lane's files (`auxiliary_client`, `inventory`, `host_supervisor`, `server`) · VERDICT 2026-09-29 h11-fp: credential (`secret_files` x13) and history (`host_store.history` x9) classes redirect I/O at six different upstream primitives (Path reads, `atomic_json_write`, open-append, `sqlite3.connect`, `_connect_tracked_db`, the log handler), so no single fork override exists: (1, recommended) drop app-level sealing on the phone and rely on the OS's file protection for the app container (iOS Data Protection Complete / Android file-based encryption) - retires both classes, ~20 files, no PR - an owner security call; (2) one upstream storage-backend door PR; (3) carry. SDK class (x12): (1, recommended) a phone-only import-time `openai`/`anthropic` shim bound to the SDK-free classes retires the 9 import fallbacks, the 3 builder branches wait on the optional-SDK row; (2) that PR alone; (3) carry · OWNER-DELEGATED 2026-09-29: SDK-fallback class → phone-only `openai`/`anthropic` shim (round 12). NEEDS OWNER: credentials + history classes — rely on the phone OS's file protection instead of app-level sealing (retires ~20 files) is a SECURITY call — released · 2026-09-29 h12-fp: SDK-fallback class 8 of 11 — `agent_runtime/provider_sdk_shim.py` registers a phone-only `openai` (the SDK-free classes under the SDK's names; installed by `EmbeddedServe.start` only when `agent.provider_sdks` is off and no real SDK is importable; the packaging closure proves each unguarded site against it at run time via the omitted row's `stand_in`), so `acp_openai_bridge`, `auxiliary_async_rebuild`, `auxiliary_wire`, `chat_completion_helpers`, `mem0/_openai_llm`, `transcription_cloud`, `tts_streaming` are upstream's bytes again and `codex_runtime`'s SDK hunk is gone. Left, with why: `auxiliary_client` (2 sites, the shared-provider lane's file), `process_bootstrap._load_openai_cls` (its fallback is the desktop's broken-SDK `hermes pm repair` message, not a phone seam). `anthropic` needs no shim (its one site is the `_require_sdk` builder branch); the three builder branches wait on the optional-SDK row. Credentials + history classes untouched (owner security call) · **OWNER 2026-09-30 (phone encryption):** CREDENTIALS stay in the OS secure store (Keychain/Keystore) — keep the behaviour, but replace the ~11 per-file `secret_files` seams with ONE override at upstream's path helper; HISTORY drops app-level sealing (the home-built seal) and relies on OS file protection (iOS strongest protection class, Android app-private + FBE) plus a no-cloud-backup mark on the history folder — the ~8 `host_store.history` seams go back to upstream bytes · 2026-09-30 h13-phone: history class done (8 upstream files), credential class 0 of 13 — HISTORY: the home-built seal is deleted (`agent_runtime/host_store/{history,session_db,envelope,log_records}.py`), `trajectory`, `moa_trace`, `readiness`, `hermes_state_dbfile`, `hermes_logging` are upstream's bytes and the history hunks left `hermes_state`, `agent_runtime_helpers`, `async_delegation` ([up-fp] 173 -> 168); the host contract names `protect_history_dir` (OS file protection + no cloud backup), which `EmbeddedServe.start` calls and refuses without. Left: CREDENTIALS — upstream has no single credential path helper or opener: each of the 13 files builds its path from `get_hermes_home()` / `Path.home()` and reads or writes through `Path` methods, `open()`, python-dotenv or `atomic_json_write`, so the one override is a process-wide `pathlib`/`open`/`utils` patch whose misses write plaintext secrets silently (each ledger row names its site's primitive). Owner choice: (1) carry the 13 seams; (2) one upstream storage-backend door PR (a credential-file read/write hook); (3) the process-wide patch — not recommended · **OWNER 2026-09-30 (credentials):** option (1) — KEEP the 13 per-file `secret_files` seams (no single upstream path helper exists; a process-wide file patch is refused as a leak risk); option (2) filed below as a someday upstream PR — released · SWEPT 2026-09-30 h13-sweep: history class done (h13-phone), SDK class 8 of 11 (h12-fp), credential class kept by owner ruling (someday-PR row below); left: the 3 SDK builder branches wait on the optional-SDK row, and `auxiliary_client` / `process_registry` / `terminal_tool` / `agent_init` stay with the reasons named above · released 2026-10-10 (lane-1010 returned L8.14, owner decision; reason in `queue-sweep-2026-10-10/L8-outcomes.md`) · **RULED 2026-10-10 owner:** nothing movable; the remaining seams stay owner-ruled carries
- [ ] **Move the shared-provider slice's upstream edits behind fork seams: `ccca4c3138` raised `[up-fp]` 180 → 186, and adds `tui_gateway/compute_model_selection.py` as a NEW file inside upstream's tree — check it and the one-line hand-offs (`agent/credential_pool.py`, `hermes_cli/runtime_provider*.py`, `tui_gateway/*`) for a fork-module home; confirm with the slice's author first** · fork-hygiene · evidence: `docs/downstream/shared-provider-authority-2026-09-29.md`, `docs/agent-runtime-harness/planned/upstream-footprint-ledger.md` · OWNER 2026-09-29: round 11 footprint lane, with the phone-edits row above · UNCLAIMED · **FLAG for @Maximus Shaban (OWNER 2026-09-29):** please move `tui_gateway/compute_model_selection.py` into a fork module when your chat-first group seam lands. WHY: it is fork-only logic living inside upstream's `tui_gateway/` folder, so every upstream merge must carry and reconcile it as one more fork file (`[up-fp]` 180 → 186 with this slice); the fork's rule is fork behaviour in fork modules, upstream files touched only by thin seams. The move is small (~30 lines, two import sites in `compute_host.py` / `methods_config_set.py`), and it is yours to time so it does not conflict with work in flight. If you would rather not, say so on this row and the round 11 footprint lane does it after your seam lands · released 2026-10-10 (lane-1010 returned L7.15, owner decision; reason in `queue-sweep-2026-10-10/L7-outcomes.md`) · **RULED 2026-10-10 owner:** move it when the chat-first seam lands

  **Provider-boundary audit 2026-10-01:** native provider reads now use a neutral plugin port; Eternia's owner policy stays downstream. Retain `compute_model_selection` as a native-fix candidate: its locking, control receipt and metadata mirror belong to the existing native compute owner, not Harness. [Evidence and contribution boundary](../../docs/downstream/provider-access-boundary-2026-10-01.md#contribution-boundary). Remaining secure-store seams and upstream submission stay separately scoped; this row is not closed as a whole-fork certification.

## Filed on arrival — 2026-09-29 (lane h10-fhrel, filed by the orchestrator)


## Filed on the move — 2026-09-22 (fork rows the launcher queue had carried since 2026-09-02)

Moved verbatim from `EterniaLauncher/Launcher_Brain/20 — Active Initiatives/mission-control-queue.md`; they are about the repository as a fork, not about the surface. Upstream-owned ones are tagged so: never patched here, a marker or an upstream issue.

- **hermes CI on `main`: the runner crash and the 43 lint errors and the mutation job are fixed; what is left is hb's slices 5–8 and the Issues switch** · `hermes` · **NARROWED 2026-09-06 (w18/ha `57b6964b01`, w18/hc `2b1f6e849c`)** — run 34046863701 (hc's push) is the first with `ruff enforcement (blocking)` and `Changed-line mutation claims` GREEN. **ha, slices 1–4, CLOSED:** all 16 tests across 11 files, one commit per file (`48a690da4c` doc-cite report needs a 4-commit repo under a depth-1 checkout; `188c511bae` + `9765564afa` stale `patch()` targets from `96cfc09a34`; `9463780a78` tool-inventory mutations wrote CRLF; `caffc04c1c` a hand-typed Windows byte count; `43cbb598ef` a real duplicate helper (`realm_sync._ledger_time` == `store._stamp`); `30f1ec6635` a BOM on `install.ps1` from the 2026-07-31 upstream merge; `23a90c6063` `test_env_gap_registry` was a DESIGN fault — a green host was read as "every row rotted"; `cee66b50fd` a witness that had not followed its reader; `d2137867b7` a directory-only git exclude that misses POSIX's symlink, which is also why the worktree GC never reaped on Linux; `ce3dc7f465` `os.path.normcase` on Windows-registry PATH data). Six of the eleven reproduced on Windows and were never platform facts — they live outside the four validated test directories and had simply never been run. **hc, CLOSED except Playwright:** ruff's 43 were all genuine `F821` (38 undeclared names in exec-assembled part-file import headers, 5 a missing `typing.Any`), 0 noqa (`fa0fb62788`, `f29ad6ca6c`, `3af990fca7`); `test_harness_parts_namespace.py` never checked header PRESENCE, ruff is the real gate, said so in `6c629b9122`; the mutation job's exit was right and four registered needles had stopped anchoring — re-derived, each proven KILLED, plus `tests/scripts/test_mutation_claims_still_anchor.py` (`abaace6a87`, `bbc1caafb0`), and a fifth needle went ambiguous on landing over hd and was fixed forward (`2b1f6e849c`). The notifier `notify-main-red` LANDED (`028aceb9c6`) and FIRED on run 34046863701 — and failed on its own step, because **Issues are disabled on `nekwo/hermes-agent`** (register row). **hb, slices 5–8, CLOSED (hermes `962a10d0fb`, 13 commits):** all nine reds and the uncollected `test_tombstone_registry.py` (1,155 tests lost at collection to a `check=True` diff under `fetch-depth: 1`); two were the CI checkout, not the code — `ci.yml` now fetches full history with `filter: blob:none`, and the docket gate had been FALSELY accusing seven backed stages; three were product defects (`_ABS_PATH_RE`'s POSIX branch truncated at the first space, `entrypoint_name` used the host separator, `note_peer_seen` read the clock twice); the eight `stream_frames` goldens were regenerated for a path-tail redaction (`262a165b47`), which the launcher re-vendored 2026-09-06 (w18/lf). **What remains here:** (1) the next main-push run after hb lands must show the eight slices green; (3) the Issues switch, then one red push to prove the notifier end to end; then delete this row. **UNCLAIMED**
- **Three hermes tests the CI runner reports FLAKY, which AGENTS.md calls bugs** · `hermes` · found 2026-09-06 (w18/ha) in run 33969282189's slice logs — `tests/agent_runtime/test_serve_stream_lane_parity.py`, `tests/run_agent/test_run_agent.py::TestExecuteToolCalls::test_sequential_tool_calls_run_without_delay`, `tests/tools/test_browser_eval_supervisor_path.py::TestEvaluateRuntimeDomNodeCrashRetry::test_reference_chain_crash_retries_without_by_value`. All three read as timing-sensitive: convert to controlled time at the mechanism, never a longer deadline; `tests/agent_runtime/test_realm_sync_eol.py` also hit the 30 s per-test cap under contention on this box (36 s alone). Agent work. **UNCLAIMED**
- **`tests/test_coverage_claims_resolve.py` sits on a 180 s wall its own fixture now overruns** · `hermes` · found 2026-09-06 (w18/hd), measured not asserted — the file declares `pytestmark = pytest.mark.timeout(180)` and its comment records `collect_claims()` at 27–31 s over three runs on 2026-09-02; called directly today with nothing else running it took 211.5 s in the primary checkout on unmodified `main` and 279.5 s in a worktree under `X:/wt`, identical corpus census in both (241 md / 4,097 py / 3,089 test / 725 claims). It passed once mid-lane at 176.4 s. The marker was NOT raised. Two questions, one row: did the walk regress (bisect `collect_claims` between 2026-09-02 and today) or did this box's IO, and why is a worktree ~30% slower than the primary (the Defender exclusion covers the primary's drive, not `X:/wt` — check `Get-MpPreference` ELEVATED, it is blind otherwise). Fix the walk or gate the fixture on a cached census; never widen the wall. Agent work. **UNCLAIMED**
- **Desktop E2E on Linux: the sentinel background command is stopped by a terminal-command approval prompt, so no background process ever spawns** · `hermes` (desktop app + E2E harness) · found 2026-09-06 (w18/hg) while closing the "polls the background dot as a turn-is-running signal" row (fixed in hermes `b4c9dfbd56`: `sessionDotState` is right, all three E2E call sites now poll the `Session running` label, plus a unit case pinning working-over-background with its recorded killing mutation). That fix does NOT make the job green. Evidence is the failing run's own page snapshot (`playwright-test-results` artifact of run 34051553815, `error-context.md` of the sidebar-states spec): at the 30 s timeout the sidebar row shows `status "Session running"`, and the tool row shows `Running echo "long bg output" + 6 commands` with 27 s elapsed on a `background=true` call plus a `Run` / `More approval options` / `Reject` approval bar. A background terminal call returns immediately, so the tool never executed: no `running` item, no subagent row, the composer still "Waking up". The gated command is `sidebarCrossBgCommand(releasePath)` in `apps/desktop/e2e/mock-server.ts` (an `echo` then a `for`/`seq`/`sleep 0.1` poll loop on a release file), introduced by `3a3bc41c7e`; the `sleep 5` fallback the other two specs use is never gated. Ruled out from Windows: `tools.approval.detect_dangerous_command` returns `(False, None, None)` for BOTH forms. NOT ruled out: `tools.tirith_security.check_command_security` returns `allow` for both locally, but tirith is not installed on that box, so it is a fail-open, not a verdict; on a CI runner tirith auto-installs from GitHub releases and is enabled by default, and `check_all_command_guards` sends any tirith `warn`/`block` to the same approval gate. Two things to settle, in order: (1) read the approval's `description`/`pattern_key` from the backend on a Linux run (it sits in a collapsed disclosure and is NOT in the Playwright trace DOM) and name the flagging rule; (2) decide whether the fix is reshaping the sentinel command or making the E2E sandbox hermetic (a harness that auto-downloads a third-party scanner binary at test time is a network-dependent input to every terminal-using spec). Do NOT guess a command reshape without (1). The next CI run after `b4c9dfbd56` is the proof, and it will fail at `waitForFunction(finalText)` rather than at the dot poll. Agent work. **UNCLAIMED**
- **hermes pack maintenance is a SILENT no-op on git < 2.32** · `hermes` · `_run_bounded_repack` issues `git repack -d --geometric=2 --write-midx`, which exits 129 on older git; the runner sends both streams to DEVNULL and never reads the return code, then `_claim_repack_slot` suppresses retries for 6 hours. Measured on git 2.31.1.windows.1 — this box. Upstream-owned; decide: warn, fall back to `repack -a -d`, or require 2.32. Ruling 1. · `hermes_cli/web_routers/git.py`, upstream-owned **UNCLAIMED**
- **hermes `gh_auth_status_route` caches a stale logged-out answer on a coarse clock — upstream race, report upstream** · `hermes` · the stale-probe guard compares two `time.monotonic()` reads with `>=`; Windows resolution is 15.625 ms (10000/10000 back-to-back reads identical, deterministic failure of upstream's own `test_gh_auth_refresh_waits_out_a_probe_started_before_it`), Linux still ties 1009/10000. Operator symptom: dashboard says "not signed in to GitHub" for the 5-minute TTL right after signing in. File is byte-identical to upstream — the fork does not patch it. Ruling 3. **UNCLAIMED**
- **hermes kanban worktree teardown on Windows: does cleanup move out of the directory before removing it?** · `hermes` · `test_cleanup_proceeds_when_cwd_was_deleted` is `linux_only` as of hermes `3de9a499d3` because its premise is POSIX (Windows answers WinError 32) — the Windows behaviour of that path is untested, not proven safe. Ruling 2. Related vocabulary gap: only three OS markers exist, so POSIX-generic tests are spelled `linux_only` and drop out of macOS; a `posix_only` marker is the honest fix. · `hermes_cli/worktree_ops.py` is upstream-owned; the `posix_only` marker is fork tooling **UNCLAIMED**

- The unrun-gate class on hermes `main`: nothing on any push lane runs the full suites, so reds accumulate silently. Two instances measured and FIXED 2026-08-30 (hermes `00fa94dd75`): `tests/scripts/test_run_tests_script.py` (pins now follow `$RUNNER_PATH` and the import-pytest venv probe) and `tests/hermes_cli/test_error_exit_code_producers.py` (`runtime_unavailable` left `_KEPT_UNSPENDABLE` — the gateway lane mints it at five sites). The CLASS is NARROWED 2026-09-02: hermes' push gate now exists (`fc2e16349e` — Lane B runs the validated 4-dir lane on `main` pushes), so what stays open is only the dirs outside that lane, e.g. `tests/scripts`, home of the first instance. Evidence: the misc-batch landing report (hermes `5fa9000b2`), both fixes `00fa94dd75`; hermes `AGENTS.md` §Testing. · moved from the launcher queue 2026-09-22 (wave 8 sheet) **UNCLAIMED**
- Hermes's focused suites cannot be trusted under multi-agent load: the named instance is RETIRED by suite-perf Stage 6 — `test_realm_sync.py` now drives `run_harness_in_process` (`tests/agent_runtime/_harness_cli`) and carries no `timeout` at all (verified 2026-09-01). The CLASS survives: an in-test subprocess cap `--timeout` cannot raise is invisible to the runner. Original filing: it timed out at load average ~400 on a command the diff never touched; fifteen failures across two suites on 2026-08-30 were all this class. Either the in-test cap becomes environment-scalable or the wave serializes pytest across agents. Evidence: the misc-batch landing report. **RULED 2026-09-04 evening (operator, recommended answer adopted):** Option 1. There is no scaling helper anywhere today — a repo-wide grep for `HERMES_TEST_SUBPROCESS_TIMEOUT` / `timeout_scale` finds only an unrelated audio test — while 474 test files carry a `timeout=`, so the class is broad and nothing currently absorbs load. Option 2 needs exactly the cross-agent orchestrator the shared-index row above says does not exist, and serializing test runs is a direct tax on the multi-agent workflow this house runs by default. Next: hermes: add the scaled-timeout helper plus its env knob, convert the subprocess caps in the test tree to use it, and add a gate refusing a bare numeric subprocess `timeout=` in `tests/`. · moved from the launcher queue 2026-09-22 (wave 8 sheet) **UNCLAIMED**

## Filed on arrival — 2026-09-24 (lane CARRY2A)



## Filed on arrival — 2026-09-24 (lanes UPPR2, REDS)

- [ ] **updater history guard vs upstream rescue anchor** · hermes_cli/update_history.guard_fork_history parallels upstream 21cc8bfef3/db1ff59937 (anchor discarded commits before the diverged reset); after the next merge two authorities own the diverged path; supersession pass · filed by lane UPPR2 2026-09-24 · VERDICT 2026-09-24 (owner ruling, recorded by lane LEDGER-DOCS): KEEP the fork guard — `guard_fork_history` refuses with exit 2 before any diverged reset, which upstream's updaters (scripts/desktop-update, lane ADOPT group 3) already treat as a non-retryable refusal, so the fork never reaches upstream's rescue-anchor path; it is a RECORDED parallel of 21cc8bfef3/db1ff59937 (ledger row `hermes_cli/update_cmd.py`, G17), re-read in the supersession pass of the next merge — retire the guard there if upstream's anchor covers the fork's no-reset guarantee · SWEPT 2026-09-29 h11-sweep: owner ruling KEEP stands; `guard_fork_history` still live (`hermes_cli/update_cmd.py:770`), fork fix filed upstream as #125265 (open); the work is the supersession re-read in the next upstream merge lane · released 2026-10-10 (lane-1010 returned L8.15, owner decision; reason in `queue-sweep-2026-10-10/L8-outcomes.md`) · **RULED 2026-10-10 owner:** keep; re-read in the v0.21.6 supersession pass row

### Filed on arrival — 2026-09-29 (lane h12-upnew)


## Filed on arrival — 2026-09-24 (disposition wave)


## Filed on arrival — 2026-09-23 (seam Stage 0 lanes)


## Filed on arrival — 2026-09-21 (upstream sync assessment)

- [ ] **PR candidate: run_tests_parallel amortised start-up** · `fork / upstream` · after `76e6fb0dc8` the per-file floor is upstream's own (~1.1 s to session start, ~2.6 s to collected, × every file); the five would-be upstream commits (phase timings, LPT order, small-file batching, POSIX fork workers, lazy root-conftest hooks) are outlined one per bullet with saving and isolation trade; the lane that builds it re-takes the upstream full-suite wall IDLE first (lane SPEED's was loaded) · evidence: `docs/agent-runtime-harness/planned/suite-cost-centres-2026-09-24.md` §8–§9 · fork after-fix baseline 40.7 min idle (2026-09-24) · VERDICT 2026-09-24 (lane SUITE2): the measured PROTOTYPE of the batching bullet is the fork-only `scripts/run_tests_bundled.py` (+ `.sh`, plugin in `scripts/_bundle_plugin/`), core free of fork paths; first idle validated-scope run 1,802 s (30.0 min) vs 2,442.7 s per-file, 91 bundles, reds unchanged — the wall is held up by known-red files whose pytest-timeout kills a whole bundle (see the row below and the cost note §10). Owner decides when the upstream PR series is cut; the lane that cuts it takes the upstream idle wall first. · HOLD: PART 2 starts only on the owner's explicit go (ruling 2026-09-24); measurements allowed · 2026-09-29 h12-upnew: LEFT, not opened — the series needs the upstream idle full-suite wall first (an exclusive ~40 min box) and our open runner PR #125263 on the same file is unreviewed with a body that describes fork-only code (h10b note 1); fix that body before a second runner PR goes up · released 2026-10-10 (lane-1010 returned L6.16, owner decision; reason in `queue-sweep-2026-10-10/L6-outcomes.md`) · **RULED 2026-10-10 owner:** parked stays parked

## Filed on arrival — 2026-09-21 (god-file refactor plan)


## Filed on arrival — 2026-09-21 (brain)


## Filed on arrival — 2026-09-24 (lane CARRY2B)


## Filed on arrival — 2026-09-24 (lane REDS2)


## Filed on arrival — 2026-09-24 (lane CARRY3)


## Filed on arrival — 2026-09-24 (lane TESTS)


## Filed on arrival — 2026-09-24 (lane REDS3)

- [ ] **`test_tui_gateway_server.py::test_notification_poller_live_loop_requeues_foreign_completion_for_owner` is order/timing-flaky: a stray `session.info` frame (this worktree's cwd and branch) reaches its captured writes** · `fork / suite` · red once in a five-file run on `6251144d09`, green alone and green on the next four-file run; find the emitter that outlives its test (a session-info publish from an earlier test's thread) and join or drain it in teardown · evidence: lane REDS3 `.lane-logs/base.log` (`assert [('session.info', 'msg-id-trunc-sid', {...'branch': 'fork/main-reds-2026-09-24'...})] == []`) · VERDICT 2026-09-24 (lane TESTS): DESIGN — the only test naming `msg-id-trunc-sid` is `test_prompt_submit_truncates_by_message_id` (upstream bytes), which starts a daemon `_run_after_agent_ready` thread it never joins; but run alone it calls `server._session_info` zero times (traced) and the pair emitter→victim stayed green under a 0.1–1.5 s delay mutation in `_session_info`, so the stray needs state an earlier co-member leaves (the frame's `branch` key points at a git-meta/cwd publish). Next: capture the stray's stack in the failing five-file run (`traceback` in a patched `_emit`), then join or drain that emitter in a fork teardown; no mechanism landed without a red · SWEPT 2026-09-29 h11-sweep: unchanged: no emitter named, no stack captured; the 09-28/29 tui_gateway commits touched the file but not `test_prompt_submit_truncates_by_message_id`'s unjoined `_run_after_agent_ready` thread; next step is still the patched-`_emit` traceback in the failing multi-file run · released 2026-10-10 (lane-1010 returned L7.16, upstream; reason in `queue-sweep-2026-10-10/L7-outcomes.md`) · released 2026-10-10 (lane-1011 returned M4.08, not reproduced; reason in `queue-sweep-2026-10-10/M4-outcomes.md`)

## Filed on arrival — 2026-09-24 (lane CLOSE)


## Filed on arrival — 2026-09-24 (program-end gate on `c7652475cd`)

- [ ] **`tests/hermes_cli/test_minimax_oauth.py::test_refresh_error_body_bounded_and_readable_with_real_client` is red in its bundle and green on the rerun alone** · `fork / suite` · a co-member leaves a client or transport patched; bisect the bundle pairwise (REDS2 method, `016a6cd71e`) and fix the leak or add the observed pair to `scripts/test_bundles_unbundled.txt` · evidence: `X:/wt/_holds/gate-final-2026-09-24.log` ("red in bundle" line) · VERDICT 2026-09-24 (lane TESTS): DESIGN — not a co-member leak: the gate's exact bundle (#56 recomputed from `c7652475cd`'s unbundled list, minimax at position 5 = "after 5 earlier members") run as one process: 236 passed, 1 skipped. The test streams a 64 KB 400 body over a REAL loopback socket and reads it bounded while the client is open; its one red was under 8 workers — treat as load-timing on the real socket (read the stream to EOF or shrink the body below one socket buffer), not an unbundled pair · SWEPT 2026-09-29 h11-sweep: upstream bytes (d10bb2ab6f), file unchanged since the row; the fork cannot edit the body size in place — the answer is an upstream PR (read to EOF / body under one socket buffer) or a load-timing id-mark, once a second red is logged · released 2026-10-10 (lane-1010 returned L6.17, upstream; reason in `queue-sweep-2026-10-10/L6-outcomes.md`) · released 2026-10-10 (lane-1011 returned M4.04, not reproduced; reason in `queue-sweep-2026-10-10/M4-outcomes.md`)

## Filed on arrival — 2026-09-24 (lane LEDGER-DOCS)


- [ ] **The CI-red notifier can never succeed: `fork-ci-red-notify.yml` opens an issue and the fork repository has Issues disabled (`HttpError: Issues has been disabled in this repository`, run 36610159639) — owner: enable Issues on ArcadiaLabsLLC/hermes-agent, or point the notifier elsewhere (a pinned discussion, a commit status, a Telegram message through the gateway)** · `fork / ci` · filed 2026-09-29 by the orchestrator **UNCLAIMED** · OWNER 2026-09-29: keep the issue notifier (its header records the pusher email ignored 55 times); fix = enable Issues on ArcadiaLabsLLC/hermes-agent — owner's setting · 2026-09-29: Issues ENABLED on the fork (`gh repo edit --enable-issues`, hasIssuesEnabled=true); delete this row when the next red main push upserts the "CI red on main" issue · released 2026-10-10 (lane-1010 returned L7.17, operator live proof; reason in `queue-sweep-2026-10-10/L7-outcomes.md`)

## Filed on arrival — 2026-09-24 (lane DOORS-A)


## Filed on arrival — 2026-09-24 (lane W0)


## Filed on arrival — 2026-09-24 (lane MERGE)


## Filed on arrival — 2026-09-24 (lane H1)
## Filed on arrival — 2026-09-25 (lane R4)


## Filed on arrival — 2026-09-25 (lane S2B)


## Filed on arrival — 2026-09-25 (lane S2A)


## Filed on arrival — 2026-09-25 (lane 2B-A)


## Filed on arrival — 2026-09-25 (lane Q-DEAD-A)

## Filed on arrival — 2026-09-25 (lane B2)

- [ ] **`test_every_stage42_global_flag_is_honored` is a source walk keyed on the name `args`: a flag read through `self.args` or a renamed parameter reads as unhonoured, so phase objects must read flags in the handler** · `fork / gates` · a source walk certifying a POSITIVE guarantee ("this flag is honoured") by spelling — the fork CLAUDE.md gate rule says ask the runtime or the element model; re-key it on the parser's `set_defaults` targets and the attribute reads they reach · evidence: B2 gateway_commands CHANGE body · filed by lane B2 2026-09-25 · VERDICT 2026-09-29 h10-fhrest: widening the visitor to self.args / the first parameter is another spelling and the gate rule forbids certifying a positive guarantee that way; the real re-key is a runtime probe (each set_defaults(func=…) handler driven with a recording Namespace under a side-effect fence), which needs a design for isolating ~50 live handlers — owed: a design sitting picks the fence (dry-run seam vs monkeypatched stores) before a lane builds it · OWNER 2026-09-29: leave, low priority · VERDICT 2026-09-29 h11-back: left per the owner decision — (a) keep the source walk, re-key only when a design sitting picks the handler fence (dry-run seam) [recommended]; (b) monkeypatched-store fence · PARKED 2026-09-29 (released by orchestrator: waits on the owner's trigger in its OWNER line / the VERDICT's named precondition) · released 2026-10-10 (lane-1010 returned L8.17, owner decision; reason in `queue-sweep-2026-10-10/L8-outcomes.md`) · **RULED 2026-10-10 owner:** parked stays parked

## Filed on arrival — 2026-09-25 (lane Q-GATES)

## Filed on arrival — 2026-09-25 (lane B3)


## Filed on arrival — 2026-09-30 (lane h13-test)


## Filed on arrival — 2026-09-26 (lane TRIAGE)


## Filed on arrival — 2026-09-26 (lane ACP-DROP, filed by the orchestrator)


## Filed on arrival — 2026-09-25 (program-end suite on `7df3bee189`, filed by the orchestrator)


## Filed on arrival — 2026-09-25 (batch gates on `6bae3f2484`, filed by the orchestrator)


## Filed on arrival — 2026-09-25 (lane LAYERS-DESIGN, filed by the orchestrator)


## Filed on arrival — 2026-09-25 (lane LLAMA-ALIAS, filed by the orchestrator)


## Filed on arrival — 2026-09-25 (lane W3-A)

## Filed on arrival — 2026-09-25 (round-2 gate pass)


## Filed on arrival — 2026-09-25 (lane W3-C)


## Filed on arrival — 2026-09-27 (lane MERGE-0927)

## Filed on arrival — 2026-09-30 (lane h12-upfix)



## Filed on arrival — 2026-10-04 (lane h-qaeff)


## Filed on arrival — 2026-10-05 (lane upstream-PR review replies)


## Filed on arrival — 2026-10-06 (turn-latency session)

- [ ] **Test and lane homes still land their `bin` on the operator's real user `Path` after the 2026-10-03 PATH fence: 14 of 30 leaked entries were created 2026-10-05 (`stage2-serve-*`, `stage4-gateway-*`, `rb7-identity-flip-*`, `ro9-boot-sweep-*`, `rs7-restart-fence-*`, `p-l-longrun-*`, a lane's `scratchpad/live`); the first one shadowed `hermes` and the operator's `hermes harness observe` died on a deleted interpreter** · fork hygiene / test isolation · evidence: `[Environment]::GetEnvironmentVariable('Path','User')` read 2026-10-06 00:35, dated by each dir's CreationTime; writers are `hermes_cli/_launchers.py` (user-Path merge) and `windows_env.py`, fence `hermes_cli/_registry_write_fence.py` · lane: find the writer the fence misses (a subprocess outside `install_path_fence`, or a root the fence counts as owned), make the gate a positive test, then a one-time cleanup verb the operator runs · released 2026-10-10 (lane-1010 returned L8.19, too big; reason in `queue-sweep-2026-10-10/L8-outcomes.md`) · designed in `docs/agent-runtime-harness/planned/design-sweep-d3-2026-10-10.md` § D3.15 · built by build-1011-B5 (D3.15: 805f8293c9 4045fa25c8 811fc986e7); remaining: stage 0 (Process Monitor on a launcher real-serve sandbox run, owner's box) and stage 3 (upstream -SkipUserPath PR body) not built; operator runs `scripts/prune_user_path.ps1 -Apply` after reading its list (29 of 55… · reason in `queue-sweep-2026-10-10/B5-outcomes.md` · released 2026-10-10
- [ ] **Test and lane runs leave their copied homes, runtimes and venvs in the operator's `%TEMP%`: ~42.7 GiB of `C:` Temp was created 2026-10-01..06, mostly repeated `stage2-serve-*`, `stage4-gateway-*`, `stage8-serve-*`, `ro9-boot-sweep-*`, `rs7-restart-fence-*`, `rb7-identity-flip-*`, `p-l-longrun-*`, `l-l-attach-*` and `hermes-*` folders, even though `HERMES_TEST_TMP_ROOT` points at `X:\Eternia\test-tmp`** · fork hygiene / test isolation · evidence: operator disk report 2026-10-06 (223 GiB of new `C:` files since 2026-08-06, 59.8 GiB of temp test environments); the same folders leaked their `bin` onto the user `Path` (row above) · lane: route every e2e/live-serve fixture's home through `HERMES_TEST_TMP_ROOT`, remove it on teardown (keep only on failure), and add a session-finish sweep that names what it removed · released 2026-10-10 (lane-1010 returned L7.20, too big; reason in `queue-sweep-2026-10-10/L7-outcomes.md`) · designed in `docs/agent-runtime-harness/planned/design-sweep-d3-2026-10-10.md` § D3.08 · built by build-1011-C6 (D3.08: b802ea9d57); remaining: hermes half built; the launcher half (sandboxes under HERMES_TEST_TMP_ROOT + gate-start sweep) is the mission-control-queue row in the lane report · reason in `queue-sweep-2026-10-10/C6-outcomes.md` · released 2026-10-10

## Filed on arrival — 2026-10-06 (lane h-turn1-conn)


## Filed on arrival — 2026-10-07 (owner: upstream integration jobs)

- [ ] **JOB 3 — Establish and maintain `integration/upstream-daily`; never land it.** · fork / upstream sync · [[Merging upstream]], "Daily integration branch" · Use JOB 2's drop / extract / upstream verdicts at every conflict. Create the branch in its own worktree from **`origin/merge/upstream-main-206102314a81`** (owner-specified initial base overrides the runbook's default), merge `origin/main` into it first, then `upstream/main`; preserve history, never rebase or reset. Follow the runbook's regen-driver and generated-file regeneration/check steps. Apply the existing tirith-removal row under "upstream PR triage" on this integration branch: **take upstream's deletion; owner ruling 2026-10-07, the fork keeps no tirith code**; remove `tools.tirith_security` from `agent_runtime/bundle_profiles/bundled-phone.yaml`, delete `hermes_cli/tirith_config.py` and its tests, and retire the other tirith hunks/ledger entries listed in that row without creating a competing owner. Repairs are separate `fix(merge): …` commits; behavior-identical moves are separate `refactor(merge): …` commits. Run tests importing conflicted modules, push the branch, then repeat daily per the runbook (fork main first, upstream main second); report conflicts per file, fixes, and test counts. **Never merge or push this integration branch into `main`.** · **TAKEN 2026-10-07 GPT-6.1 Sol (Job3)**

## Filed on arrival — 2026-10-06 (upstream PR triage)


## Filed on arrival — 2026-10-06 (landing w16)


## Filed on arrival — 2026-10-07 (upstream PR lanes up-drafts / up-door-*)

- [ ] **Since 2026-10-03 the `nekwo` account cannot create upstream PRs or mark its drafts ready (`CreatePullRequest` / ready-for-review FORBIDDEN; comments, edits and pushes still work). Ready and waiting: drafts #132423 #131905 #131904 #131903 #131902 (fixed 2026-10-07), branches `feat/optional-module-door` (`b472d428cf`), `feat/sdk-fallback-door` (`36ba53ebda`), `fix/auto-skips-disabled-provider` (`f134fa0db6`); bodies under the operator's worktrees `pr-bodies/`. The gh half of the secret-store bug fix is covered by third-party #133001; the Qwen half is an owner call (gating it disables the provider)** · `fork / upstream PRs` · owner believes a maintainer-side limit until the backlog is handled · OWNER · released 2026-10-10 (lane-1010 returned L8.24, owner decision; reason in `queue-sweep-2026-10-10/L8-outcomes.md`) · **RULED 2026-10-10 owner:** maintainer-side; nothing for the fork

## Filed on arrival — 2026-10-07 (landing prep/hermes-waves-reviewed)

- [ ] **OWNER: confirm the loosened phone-wheel registration check (was "connector aliases exist when PDF imports", reviewer ask in 1d42960ab6; now "connector pair imported before PDF")** · fork hygiene (suite) · landing fix 69f8d72ae3 · OWNER · released 2026-10-10 (lane-1010 returned L6.26, owner decision; reason in `queue-sweep-2026-10-10/L6-outcomes.md`) · **RULED 2026-10-10 owner:** confirmed (`69f8d72ae3`)

## Found fixing main's reds — 2026-10-07 (lanes h-red-cli/-runtime/-gates/-inherited)

- [ ] **Contract-moving lanes left pinned tests red (H4 envelope fixture + snapshot set, H7 event count, d97ad57e96 argv, 5167db9ce9 producer walk): a contract change must run the tests that pin it** · fork hygiene (suite) · evidence: d677799521 body · lane: name the pinning tests in the producer's docstring or a gate · released 2026-10-10 (lane-1010 returned L8.27, owner decision; reason in `queue-sweep-2026-10-10/L8-outcomes.md`) · **RULED 2026-10-10 owner:** convention: name the pinning tests in the producer's docstring; no gate

## Filed by isolated lifecycle fixture — 2026-10-07


## Filed on arrival — 2026-10-08 final GenUI gate


Process-dock product-half recurrence, 2026-10-08 GenUI qualification: `tests/gateway/test_abandoned_turn_process_cleanup.py` times out in `test_timed_out_turn_reaps_only_its_own_job_on_a_shared_container_key`, at `tools/process_registry.py::_release_finished_handles` → `stream.close()`. The candidate full gate and isolated run hang; untouched `7ea1c17366` first passes all 15 tests, then an isolated repeat hangs at the identical site. This is additional evidence for the existing process-dock/upstream-PR row above. No timeout, environment fence or production cleanup code was changed.

## Filed on arrival — 2026-10-08 native connection ownership gate

- [ ] **Serve exit-flush tests terminate the Windows pytest process after the first skipped case.** · `tests/tui_gateway/test_serve_exit_flush.py` collects eight cases, prints only `s`, then dies in a bundle and alone; zero passes are claimed. The same process death recurs on unchanged `6d90a42dae`, bundled and alone. Evidence: `docs/downstream/native-worker-link-qualification-2026-10-08.md`. Qualify signal behavior with a bounded child process through the allowed upstream/fork test seam. · UNCLAIMED · released 2026-10-10 (lane-1010 returned L8.29, workstation hazard; reason in `queue-sweep-2026-10-10/L8-outcomes.md`)


## Filed on arrival — 2026-10-08 (release merge v0.21.6)

- [ ] **The shared test venv still has nemo-relay 0.8; upstream v0.21.6 passes `additional_plugins_toml` to it and logs a warning — bump the venv's nemo-relay** · fork hygiene (test env) · release lane rel-0216 · UNCLAIMED · released 2026-10-10 (lane-1010 returned L7.31, workstation hazard; reason in `queue-sweep-2026-10-10/L7-outcomes.md`)

## Filed on arrival — 2026-10-09 (lane opus-fix-toolsets-refusal)


## Filed on arrival — 2026-10-09 (perf programme close-out sweep)


## Filed on arrival — 2026-10-09 (landing lane land-h-toolvis; red on detached origin/main 440cba12ce, after the upstream v0.21.6 merge)


## Filed on arrival — 2026-10-10 (release merge v0.21.6 reds, branch `fix/v0216-fork-reds`)


- [ ] **Supersession pass owed for the v0.21.6 release merge: the merge (`3002eaa067`) recorded drop 7 / extract 0 / upstream 0 / kept 21 but no supersession count (runbook `Merging upstream.md` Steps 4-6). For each of the 21 kept fork hunks in upstream files: is it now redundant with v0.21.6 (drop), movable behind a door upstream now offers (extract), or still needed (kept, reason); report the `[up-fp]` line before/after** · fork / upstream sync · merge commit body `3002eaa067`; `docs/agent-runtime-harness/planned/upstream-footprint-ledger.md` · lane: supersession pass (owner offered 2026-10-10) · released 2026-10-10 (lane-1010 returned L7.35, too big; reason in `queue-sweep-2026-10-10/L7-outcomes.md`) · designed in `docs/agent-runtime-harness/planned/design-sweep-d3-2026-10-10.md` § D3.10: PROGRAM-EXISTS: `Merging upstream.md` Steps 4–6 (the supersession pass row) · released 2026-10-10
## Filed on arrival — 2026-10-10 (chat content integrity)


## Filed on arrival — 2026-10-10 (chat-content boundary qualification)

- [ ] **Make retired-symbol matching distinguish identifiers from unrelated substrings.** `tests/agent_runtime/test_tombstone_registry.py` marks `s65 re_prompt (code)` whenever the text contains that spelling, including an unrelated history-boundary value `before_prompt`. The history repair uses the more explicit `before_user_message`, but the gate should exercise identifier/string-value boundaries with positive and negative controls instead of treating a substring as resurrection of the retired action. · fork / suite · UNCLAIMED

- [ ] **Wait for queued-turn completion in the busy-root concurrency fixture, not its callback's early signal.** `tests/agent_runtime/test_busy_root_send_queue.py::test_a_blocked_turn_on_one_root_does_not_hold_a_queued_send_on_another` signals `b_done` inside `run_turn` before its future completes, then expects exactly one occupied root; the actual tally is two. The same assertion fails in the full fork gate and on untouched `7094d8b3ba`. Synchronize at completion while retaining proof that root B runs during blocked root A; do not loosen production scheduling. · fork / suite · UNCLAIMED
- [ ] **Replace upstream debug-share log-label source assertions with behavioral proof at the owned test boundary.** `tests/test_no_source_grep_assertions.py::test_no_new_positive_source_grep_assertion` reports four positive source claims in `tests/hermes_cli/test_debug_share_update_logs.py::TestFullLogUploadLabels`, identically in the fork gate and untouched `7094d8b3ba`. Preserve the no-new-debt gate and upstream ownership; exercise emitted labels instead of expanding its exemption lists. · fork / suite · UNCLAIMED · TRIAGE 2026-10-12: [H05](../../docs/downstream/history-red-triage-2026-10-12.md). **CORRECTION 2026-10-12:** H02 attribution repair cleared the gate (26 pass); retain as inherited test-quality review only, not a runtime or fork-gate defect.
- [ ] **Resolve the path-identity gate finding for upstream volatile Docker mount detection.** `tests/test_path_identity_gate.py::test_no_unregistered_raw_path_comparison_under_tools` reports `tools/environments/docker.py::_is_volatile_mount_spec` raw path comparisons, identically in the fork gate and untouched `7094d8b3ba`. Review the call-site intent and qualify Windows path identity; route a real identity comparison through its owner or document a proven literal-spelling exception without weakening the gate. · fork / upstream integration · UNCLAIMED · TRIAGE 2026-10-12: [H06](../../docs/downstream/history-red-triage-2026-10-12.md). **CORRECTION 2026-10-12:** H02 attribution repair cleared the gate (9 pass); retain contract qualification only, with no code defect established and no exemption owed.

- [ ] **The downstream state-DB guard can observe a partially imported `hermes_state` module during office-subscribe fixture setup.** In a fresh detached history-repair checkout `c5acdd0f7e`, `test_serve_rpc_office_subscribe.py::test_the_reclaim_pair_joins_the_manifest_without_moving_the_contract_version` errored in `_state_db_guard_denies_recorded_root`: `_STATE_DB_GUARD_EXTRA_DENY_ROOTS` did not exist. First attempt: 81 passed / 1 setup error; automatic retry: 82 passed. Qualify the fixture's import boundary without weakening the real-root write guard. Evidence: `console-history-evidence/runtime/repair-clean-final.log`; staged report in PR #7's `docs/agent-runtime-harness/planned/console-history-controls.md`. Not reproduced on the baseline run; retain as intermittent, not baseline-proven. · fork / suite · UNCLAIMED

## Filed on arrival — 2026-10-10 (queue sweep lane-1010, filed by the orchestrator)

- [ ] **Process-global state, the CLASS: the tool registry, `builds.detect._ENABLED`, the resident-chat registry, the idle keeper and memos leak across test files in one bundle, and each leak is found one red at a time; the answer is one fork fixture owning a list of resettable module state, plus a public snapshot/restore on `tools/registry` (upstream PR)** · fork / suite · `53ccebb5e1` (L7.07), `queue-sweep-2026-10-10/L6-outcomes.md` L6.08, L6.30 (585 leaked registrations) · lane: suite isolation
- [ ] **A test run killed by `timeout` leaves a stale `index.lock` in its worktree and blocks that worktree's commits; nothing sets `GIT_OPTIONAL_LOCKS=0` for test children** · fork / suite isolation · seen 2026-10-10 13:24 in lane-1010-L4's worktree (the lane pushed from a second worktree); hypothesis `queue-sweep-2026-10-10/L8-outcomes.md` L8.20 · lane: suite
- [ ] **The registry fence cannot see a PowerShell writer: `scripts/install.ps1` writes the user PATH through `[Environment]::SetEnvironmentVariable`, and `tests/scripts/test_install_ps1_desktop_stage.py` drives it for real** · fork / test isolation · a user-PATH entry `…\test_desktop_stage_uses_pm_syn-25\hermes-home\bin` exists today; launcher sandbox `bin` entries dated 2026-10-07, after the fence `1524ca5552` · lane: suite isolation
- [ ] **The hermetic `DEFAULT_DB_PATH` pin depends on import order: `tests/conftest.py` pins it only if `hermes_state` is already imported, so profile-scoped store tests pass alone and red after any importer** · fork / suite · `queue-sweep-2026-10-10/L7-outcomes.md` L7.01 · lane: suite
- [ ] **`Running the tests.md` misleads on one-file runs: bare `python -m pytest` runs system Python 3.12 without the test venv (false import reds), and `scripts/run_tests.sh` sets `PYTHONUTF8=1`, which hides `write_text`-with-no-encoding failures, so "red under bare pytest" rows keep being filed as product bugs** · fork / suite docs · `queue-sweep-2026-10-10/L6-outcomes.md` L6.19, L6.25; `L4-outcomes.md` L4.01 · lane: docs
- [ ] **The launcher-managed venv is behind the checkout: `.hermes/venvs/hermes-agent` cannot import `hermes_cli.gateway` (`ModuleNotFoundError: hermes_yaml`), so `gateway start` from it fails today** · fork / install sync · `queue-sweep-2026-10-10/L2-outcomes.md` L2.02 · lane: venv sync
- [ ] **Seven upstream test-carry PRs closed unmerged (#121218, #121220, #121221, #121222, #121241, #121244, #121246; #121223 merged), so those fix classes no longer leave the fork by merge** · fork / upstream sync · `queue-sweep-2026-10-10/L3-outcomes.md` L3.27 · lane: owner decision (re-file upstream, or own the carry)
- [ ] **The fork carries a fix inside upstream `tools/file_tools_read_tracking.py` (`fa2677be7b`) after its PR #128647 closed unmerged: confirm a footprint-ledger row and an issue to retire it against (#128639)** · fork / upstream footprint · `git diff v0.21.6 -- tools/file_tools_read_tracking.py`; `queue-sweep-2026-10-10/L4-outcomes.md` L4.07, L4.10 · lane: ledger
- [ ] **`scripts/refactor_census.py` counts decorator-registered functions (singledispatch `.register`, `@method`, routes, `@property`) as unreferenced: 46 of 60 "DEAD" in the post-v0.21.6 census were false positives** · fork / dead-code tooling · `queue-sweep-2026-10-10/L5-outcomes.md` L5.17 · lane: census tooling

## Filed on arrival — 2026-10-10 (fork-fixable sweep lane-1011, filed by the orchestrator)

- [ ] **Fork rebinds of upstream module attributes (`skill_utils._RAW_CONFIG_CACHE`, `SessionDB._read_all` by attribute) are invisible to W0-G6, which sees only from-imports; the gate proves a spelling** · fork / gates · `queue-sweep-2026-10-10/M1-outcomes.md` M1.05, M1.07 · lane: gate
- [ ] **The footprint ledger and the `[up-fp]` fixture are hand-merged per lane: each additive hunk bumps `files` by one (this landing reconciled M1 +1, M2 +1, M3 +4 to 191 by hand) and a Bash heredoc once wrote a backslash as \x08 into both; a scripted `upstream_footprint.py --add-row` removes both hazards** · fork / tooling · lane-1011-M3 commits `181911077c`..`3ce3399209`, the land/1011-batch merges · lane: tooling
- [ ] **`tests/agent/test_skill_commands.py::TestScanSkillCommands::test_scan_never_publishes_a_partially_built_map` flakes (red on base `5734348e63`, green on the batch); the cron lifecycle (3) and code-execution (4) reds of the first whole-tree gate were the live guard over-refusing and a stale XPASS row, fixed by `a1d2628ed8`** · fork / suite · lane-1011 gate log · lane: classify the flake
- [ ] **A whole-tree gate left a stale `index.lock` in its own worktree again (`hermes-1011-batch`, 17:53, blocked the landing commit 1.5 h later)** · fork / suite · second sighting after lane-1010-L4; build lane B4 is building D3.16 (`GIT_OPTIONAL_LOCKS=0`) · lane: B4
- [ ] **`run_tests.sh` re-runs a red file alone, so a test whose red writes real machine state (registry, user PATH) writes it twice; a destructive-on-red test has no opt-out from the retry** · fork / suite · build-1011-B5 D3.15 mutation (2 PATH entries from 1 run) · lane: runner
- [ ] **The shared test venv's SQLite 3.50.4 forces `journal_mode=DELETE`, so no WAL-path behaviour (sidecar races, checkpoints) can be exercised live on the workstation** · fork / suite · build-1011-B5 D3.02 stage 3 · lane: test-venv refresh
- [ ] **`scripts/upstream_footprint.py --ledger` rewrites counts on unrelated rows (`agent/prompt_builder.py` 31→32, `hermes_cli/update_cmd.py` 12→14): the ledger has drifted from the tree** · fork / upstream footprint · build-1011-B5 report · lane: ledger re-derive
- [ ] **The release-merge gate reaches 5,571 upstream files through the root conftest's STANDING fork hunk, which `select_scope` cannot tell from a changed one** · fork / suite · design-sweep-d3 § D3.07 (measured on `3002eaa067`) · lane: build-1011-B4

## Filed on arrival — 2026-10-10 (build batch 1, build-1011-B1..B5, filed by the orchestrator)

- [ ] **`planned/tool-form-one-owner-2026-10-08.md` still argues from "teardown is the isolation guarantee", which design-sweep D1.01 retires (MCP admission now resident per transport session)** · fork / docs · that plan's S1 decision line vs design-sweep-d1 Owner rulings · lane: docs
- [ ] **The `profile_runner.md` layout sheet names `_teardown_mcp_admission`, now `_release_mcp_admission`** · fork / docs · build-1011-B1 · lane: docs
- [ ] **A test helper that launches `bash` from Python on Windows resolves to WSL bash and runs the repo's setup inside WSL (build-1011-B1 built a 558 MB test env under the WSL home; deleted 2026-10-10)** · fork / suite · build-1011-B1 report · lane: runner + brief rule (name Git Bash's absolute path)
- [ ] **`--since-merge` still reaches 2,489 upstream files by import through fork-edited upstream modules the merge re-applied hunks to (`hermes_state.py` 453, `hermes_cli/config.py` 278, `tui_gateway/server.py` 256); extending the unchanged-hunk rule from conftests to modules is an owner call** · fork / suite · build-1011-B4 `fddab198fa` body · lane: D3.07 follow-up
- [ ] **CLASS (third instance): `scripts/run_tests.sh`'s `env -i` allowlist is upstream-owned, so every new fork test variable needs a wrapper (`run_tests_bundled.sh`, `run_tests_idle.sh`, `--git-audit`); answer: one fork-owned env-extension door** · fork / seams · build-1011-B4 `81eb8ed09b`, `b80e56bac8` · lane: runner door
- [ ] **`uvx ruff` and the test-env install flake under concurrent lanes (`os error 32` on the uv cache; `pm` setup once failed with "No module named ipaddress")** · fork / suite · build-1011-B3 report · lane: per-lane `UV_CACHE_DIR` (Running the tests.md) + env-install lock
- [ ] **CLASS: `agent_runtime/dirty_state.py::_git_dirty_state` runs `git status --short --untracked-files=all` on the runtime root without `--no-optional-locks`, so 12 test files that reach it take the checkout's index lock during a gate (`test_status`, `test_s76_assignment_wire_prune`, `test_dispatch_delivery_observability`, `test_retired_surfaces_live_behaviour`, `test_s28_status_observe_shrink`, `tests/hermes_cli/test_harness_cli`, `test_persona_assignments`, `test_s21_hollow_seam_ring`, `test_harness_serve`, `test_provider_health`, `test_root_observability`, `test_snapshot_session_db_ownership`)** · fork / suite isolation · git-audit 2026-10-10 (`--git-audit` gate on land/1011-builds) · lane: add `--no-optional-locks` there and point the tests' root at a tmp repo
- [ ] **`tests/agent/test_system_prompt_downstream.py` (15 calls) and `tests/agent/test_compaction_prompt_rebuild_downstream.py` (3) reach upstream `agent/coding_context.py` (`git status --porcelain=2 --branch`) against the checkout during a gate** · fork / suite isolation · git-audit 2026-10-10 · lane: point those tests' root at a tmp repo (the module is upstream)
- [ ] **`tests/scripts/test_upstream_footprint.py` runs `git diff` (commit vs worktree) against the checkout during a gate (lock-taking)** · fork / suite isolation · git-audit 2026-10-10 · lane: `--no-optional-locks` or a tmp clone

## Filed on arrival — 2026-10-10 (fast-gate design, guard fix, build batch 2 C1–C4, filed by the orchestrator)

- [ ] **Two owners of the "would this argv start a hermes backend" classifier: `tests/_downstream/live_guard_classify.py::backend_spawn_subcommand` and `tests/hermes_cli/_gateway_fence.py::classify` both define `_without_python_c_argv`, entry-index and subcommand helpers; the python -c inert rule lives in only one, and the fence's docstring cites a stale path** · fork / live guard · fix/1011-guard-and-tui-reds report · lane: fold the fence onto the one classifier
- [ ] **W0-G3's name check treats a helper group that loses an owner as a brand-new group, so `god_file_probe --write-fixtures` refuses to record the smaller group (narrowed by hand in build-1011-C1 `ed5c5d165f`)** · fork / gates · `scripts/god_file_probe.compare_sets` · lane: gates
- [ ] **Concurrent lanes break each other's test runs through shared installs: "uv trampoline failed to spawn" while another process rewrote the uv Python install (build-1011-C4), plus the earlier `os error 32` uv-cache locks** · fork / suite · build-1011-C4 report · lane: per-lane test-env isolation

## Filed on arrival — 2026-10-10 (build batch 2 C5–C6, fast gate FG2–FG3, landing 1011-batch2, filed by the orchestrator)

- [ ] **`scripts/check_carried_prs.py` hunks mode reports false DRIFT on Windows: the reverse-apply sends the patch over a text-mode pipe, which rewrites newlines to CRLF; the same check passes when the patch is sent as bytes** · fork / suite gates · build-1011-C5 stage-2 probe
- [ ] **`check_carried_prs.py` errors on all 106 ledger pairs on main (fetched PR heads moved past `reviewed_head`, three refs missing), so it is no landing evidence** · fork / carried-PR sync · build-1011-C5 baseline run · lane: next carried-PR sync
- [ ] **`tests/tools/test_known_file_write_baseline.py` (upstream-owned) is red on main: `test_paged_read_carries_only_when_every_page_was_read` fails and other runs die in 30 s timeouts inside `env.execute` / a shell-backed v4a patch (`file_operations._fenced_read`)** · fork / suite · landing 1011-batch2: red 3/3 on the branch, at merge-base `f420577b6e` red 1/3 + timeouts 2/3; build-1011-C5 · lane: prove upstream-vs-env (classify_reds_on_tag.py), then skip-list row or fix
- [ ] **A carried-PR test in an upstream file hits the 30 s cap: `tests/scripts/test_run_tests_parallel.py::test_isolation_retry_keeps_the_scaled_timeout_and_counts_skips` times out in its bundle and alone; not in v0.21.6, so no upstream table can mark it** · fork / suite · build-1011-C6 D3.13 run, `7625cb7dad` · lane: carried-PR owner
- [ ] **`tests/tui_gateway/test_tui_gateway_server.py` takes 235–540 s and timed out at the 300 s file cap under -j 2** · fork / suite · build-1011-C6 D3.13 run · lane: fast-gate known-red cap / sharding
- [ ] **`run_tests_bundled.run` is at 149 of 150 lines and its closures `_solo`/`_bundle`/`_record` read 6+ enclosing locals; the result cache cannot enter `run` without a run-state object** · fork / suite · build-fastgate-FG2 report · lane: a `_Run` state MOVE (FG1 told)
- [ ] **Process kinds / vias are bare strings across four modules ("known-red", "shard i/k", "whole-check", "rerun", "retry") and the ledger counts them by first word; a typed via is the bar** · fork / suite · `RunLedger.summary`, `SoloPolicy`, `ShardJoin` (build-fastgate-FG2) · lane: with the run-state MOVE
- [ ] **Two spellings of one key: `test_durations.json` is keyed by `_format_file` (OS separators) while the run record is POSIX; `solo.green_seconds` reads both** · fork / suite · `run_tests_parallel._format_file`, `run_tests_bundled_solo.green_seconds` · lane: FG1's rel-keyed durations store
- [ ] **The batch-2 landing gate printed 4 isolation leaks and 5 bundle deaths that nobody chased** · fork / suite · `gate-c.log` (land/1011-batch2) · lane: read the gate's leak/death lines and row each

## Filed on arrival — 2026-10-10 (fast gate FG1, filed by the orchestrator)

- [ ] **The dependency recorder cannot see existence checks (`os.stat`/`Path.exists` raise no audit event): a test whose result depends on a repo file appearing that it never opened or listed can stay a cached green; bounded only by the audit sample and the 14-day max age** · fork / suite · `scripts/_bundle_plugin/hermes_dep_trail.py` (build/fastgate-FG1) · lane: fast-gate §1 follow-up
- [ ] **`run_tests_bundled.sh`'s run-in-hermes-env re-exec compares `$__BUNDLED_DIR` (from a relative BASH_SOURCE, `X:/…` under a drive-spelled PWD) with `run_tests.sh`'s `$SCRIPT_DIR` (`/x/…`) and exits 2 "wrapper is out of date"** · fork / suite · build-fastgate-FG1 lane log (worked around with HERMES_PYTHON) · lane: runner

## Filed on arrival — 2026-10-11 (fast-gate landing, whole-tree gate, filed by the orchestrator)

- [ ] **A test detaches a REAL `hermes update --yes --gateway --branch main --keep-stash` that outlives it: two such processes (test-environment venv python, the desktop updater's `-I -c "…hermes_bootstrap…runpy hermes_cli.main"` hand-off spelling) were still running 11 h and 13 h after the whole-tree gate of 2026-10-11 started them (00:16, 01:51), parents gone; their HERMES_HOME falls back to the real store root when the test does not pin it** · fork / suite isolation · `queue-sweep-2026-10-10/FG-landing.md` · reproduced 2026-10-11 15:07 by `tests/scripts/desktop_update/test_desktop_update_windows_marker.py::test_script_killed_right_after_spawning_the_update_leaves_a_live_marker` (a `custody` PowerShell plus two `update` children outlived it) · lane: make that test reap its children, make it reap its child and pin HERMES_HOME; the gate's leak scan should name a surviving `hermes_cli.main update`
- [ ] **Thirteen files go red in the whole-tree gate by timeout rather than assertion — nine also red on a quiet base `828fdb3c0e` (`test_update_ci_routing`, `test_desktop_build_lock`, `test_run_agent`, `test_icon_flavors`, `test_run_tests_parallel`, `test_known_file_write_baseline`, `verify/test_environment_and_runner`, `test_tui_gateway_server`, `test_serve_exit_flush`) and four at the 30 s per-test edge (`test_install_ps1_native_calls` 27.9 s, `test_no_shadowed_test_definitions` 29–31 s, `test_install_clone_throttle_fallback`, `test_web_server::test_concurrent_first_load_reads_all_succeed_on_fresh_store`)** · fork / suite (the CLASS; four of the nine have their own rows) · `queue-sweep-2026-10-10/FG-landing.md` · lane: classify each (Windows upstream red → marker; fork-caused → fix; honest slow test → a per-test timeout) on the idle box · TRIAGE 2026-10-12: [H09](../../docs/downstream/history-red-triage-2026-10-12.md).
- [ ] **CLASS (third instance): a new lazy import on the turn path silently adds first-turn cost until the turn-cost guard catches it, and that guard's IMPORT check runs only on the idle box because its file is idle-only — v0.21.6's three modules (`97b33c3c49`), the capability probe + netrc (`c3894ae54d`), M2.05's `request_effort` (`c835697c3c`)** · fork / suite · `queue-sweep-2026-10-10/idle-box-2026-10-11.md` · lane: split the guard's import-count check (load-independent) out of the idle-only file so every landing gate runs it; the structural answer is the gate, not a fourth warm-list line
- [ ] **`tests/agent_runtime/test_stream_gap_receipt.py::test_starved_reader_shows_lag_and_late_wakeups` misses its 150 ms lag floor even on the idle box (110 ms on 1 of 2 first attempts, passed on retry); the D3.09 row was closed on the first idle runs too early** · fork / suite · `queue-sweep-2026-10-10/idle-box-2026-10-11.md` · lane: a hog the scheduler cannot skip, or a floor measured on the idle box over ≥10 runs (never lowered to pass)
- [ ] **Hermes sessions have no Launcher QA MCP configured: the owner's "run the MCP check" needs a hand-built stdio client plus `STAGEC_QA_REPO_ROOT` / `STAGEC_LAUNCH_HELPER` (without them `open_app_tab` refuses `launch_helper_missing`)** · fork / tooling · this session 2026-10-11 (scratchpad client; `EterniaLauncher/docs/stages/qa-reboot/mcp/launcher-qa-direct.example.json`) · lane: a project `.mcp.json` entry (or a `scripts/` wrapper) that starts `stagec_qa_mcp_server` with both variables, documented in `Running the tests.md`


## Filed on arrival — 2026-10-11 (Console history final qualification)

- [ ] **Diagnose intermittent Session API commentary loss.** `tests/gateway/test_session_api.py::test_interim_commentary_reaches_session_sse_and_responses_stream` fails in the history candidate gate and also in a fresh run on unchanged main `50a9165fc2` (2026-10-12): a one-file bundle reports 38 passed / one failed, then all 39 pass on the runner's isolated retry. The same bounded main check also passed on an earlier attempt. The candidate has no delta in this test or `gateway/platforms/api_server.py`. This reproduces the baseline failure without another bundled file; an import/order cause is not established. Diagnose event delivery and timing before changing production behavior; a green retry must not erase the first failure. Local evidence: `history-session-main-repeat-1.log`. · fork / suite · UNCLAIMED · TRIAGE 2026-10-12: [H03](../../docs/downstream/history-red-triage-2026-10-12.md).
- [ ] **Reclassify the strict XPASS in bot relay delivery with a native Windows proof.** `tests/tui_gateway/test_bot_relay_methods.py::test_deliver_validates_profile_and_runs_transport` is a strict XPASS on candidate and unchanged main `8a5d6114df`; the other 21 pass and one remains xfailed. Check the inherited Windows failure marker against its original upstream condition before retiring it. · fork / upstream integration · UNCLAIMED · TRIAGE 2026-10-12: [H08](../../docs/downstream/history-red-triage-2026-10-12.md).
- [ ] **Make the PM slow-exit fixture's interpreter requirement reproducible in the supported test environment.** `tests/pm/test_worker_slow_exit_downstream.py::test_a_result_followed_by_a_slow_exit_completes` errors during setup on unchanged main `8a5d6114df`: its plugin requires Python 3.14 but the configured test interpreter is 3.13.15. Qualify through the existing environment/bootstrap owner; do not label this a passing worker-lifecycle test or weaken the plugin requirement. · fork / suite environment · UNCLAIMED · TRIAGE 2026-10-12: [H04](../../docs/downstream/history-red-triage-2026-10-12.md).
