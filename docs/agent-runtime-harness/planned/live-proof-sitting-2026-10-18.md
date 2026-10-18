# The live-proof sitting — plan (2026-10-18)

Status: **PLANNED, not run.** One sitting that clears the hermes queue's live-proof rows by driving
the owner's real, shipped Launcher through the app-function MCP (`eternia_mcp`), reading hermes
receipts and logs from disk, and handing the owner only what needs his hands. Written by lane
`live-sitting-plan`. Queue rows are not edited here; the sitting's landing commit edits them.

Scope: the 48 rows whose status reads `BLOCKED …: owner sitting` in
`Harness_Brain/20 — Active Initiatives/runtime-queue.md` (37) and `fork-hygiene-queue.md` (11).

| class | rows | where |
|---|---|---|
| (a) MCP sitting — bridge + a shell + disk reads; the owner only clicks Allow | 22 | §3 |
| (b) quiet box — idle workstation, no human, before the sitting | 5 | §2 step 1 |
| (c) owner in person | 19 | §4 |
| (d) stale — precondition gone on main / on the box | 2 | §5 |

The bridge is a different door from the `launcher_qa` MCP that the `launcher-mcp-operations` skill
drives: it reaches only the app functions' outside projection — no sign-in verbs, no `dev_login`,
no `clickButton`, no QA bus (`EterniaLauncher/docs/embedded_hermes/planned/APP_MCP_RUNTIME_SWITCH_2026-10-13.md`
§3). Account and pairing entries are absent (`launcherAgentOnly`). `launcher.agent_chat.send`,
`launcher.harness.restart`, `launcher.settings.set` and `launcher.view.capture` are `confirm`:
**every send raises the Allow card, so the owner stays at the screen for the Launcher-route turns.**
Turn-count rows that do not need the Launcher route ride `hermes harness mission-chat message`
(runs in the live serve, no card), to keep the Allow clicks to the rows that need them.

---

## §0 Owner setup (before the sitting)

1. Run the installed Launcher built at or after launcher `00a5dea4f9` (app-MCP S5: `eternia_mcp.exe`
   beside the Launcher executable). `launcher.app.about` reads the build commit back in step §3 row
   `RT-RETIRE-LEGACY-TOP-LEVEL`.
2. **Settings › General › Agents › Let other programs operate Eternia** — on. The status line must
   read "Listening on port N since HH:MM". Leave it on for the whole sitting; Stop on the amber bar
   ends it.
3. Signed in to the Launcher as usual (the bridge cannot sign in). Mission Control open on the
   operator profile the serve receipt names; a Neko instance and a Dev instance on the roster.
4. Leave alone: the alice gateway until §3 row `RT-GATEWAY-START-MANAGED-PYTHON`; no lane, test run
   or build running on the box (the timings are idle-box numbers); no other Claude session committing
   in the primary checkout.
5. Box idle (no game, no build) for §2 step 1, which runs unattended before you sit down.

## §1 How Claude Code connects

From the bridge's own docs (`EterniaLauncher/tool/app_mcp_bridge/bin/main.dart`,
`docs/embedded_hermes/subsystems/README.md` § "Connecting an outside agent"):

```
claude mcp add eternia -- "<install dir>/eternia_mcp.exe"
```

or the `.mcp.json` entry the Settings tile's **Copy .mcp.json entry** fills in:
`{"mcpServers": {"eternia": {"command": "<install dir>/eternia_mcp"}}}`. Register it before the
session starts (a session loads MCP tools at start). The bridge reads `app_mcp.json` (`url`, `token`,
`pid`, `opened_at`, `protocol_version`) from the Launcher's support directory on every request, so
Stop and re-open need no client restart; with no file it answers `initialize` with an error naming
the switch and exits 2. Check: `tools/list` shows no `launcher_account_open_section`;
`launcher_navigation_state` answers.

Disk reads (no bridge): the serve's `agent.log` under the profile's `logs/`, the serve receipt, the
Launcher diag log (`eternia_launcher_diag.log` in the user temp directory: `[MissionServe]`,
`[MissionStream]`, `[MissionChatTiming]`), and `hermes harness observe turn-timing --check`.

## §2 Order of runs

1. **Quiet box, unattended, before the sitting** (one heavy run at a time; commands per
   `Harness_Brain/50 — Agent Handoffs/Running the tests.md`):
   1. `FORK-STREAM-GAP-STARVED-READER` — `scripts/run_tests_idle.sh` ×10; quote each `{"kind": "idle"}`
      line (`stall_samples`, `stall_max_ms`, `max_lag_ms`). Pass: 10/10 at the 150 ms floor, or the
      floor set from the ten (never lowered to pass).
   2. `FORK-THIRTEEN-TIMEOUT-REDS` — each of the thirteen files alone, one worker; classify Windows
      upstream red → marker / fork-caused → fix row / honest slow → per-test timeout row.
   3. `FORK-SUITE-SPEED-J-REMEASURE` — the bundled gate at `-j 8` and `-j 14` (cores−2) on the same
      tip; record wall time and CPU from the run header; the default becomes what the numbers support.
   4. `RT-NODE-DEPS-LAUNCH-TIME` — in a scratch worktree, hold a `.node` binding open from a second
      node process and run the launch-time `npm ci`; record the EPERM and which of workspace
      selection / node-npm version / `npm_config_*` env triggers it.
   5. `RT-VERIFY-ON-STOP-OFF` — five editing turns ON and five OFF on the QA serve (QA home, not the
      owner's), `agent.verify_on_stop` flipped between arms; record extra calls, tokens and wall time
      per arm from `turn-timing` and the `API call #N … in=` lines.
2. **Batch A — a fresh serve, default flags.** One vault-only commit first (`RT-QUEUE-COMMIT-SERVE-RESTART`),
   then `launcher_harness_restart` (Allow), wait for the prewarm, then the first turns.
3. **Batch B — the same serve, warm.** The warm and idle turns, the long-history chat, the passive
   log reads, the shell-driven settle/board/lens/gateway checks.
4. **Batch C — `agent_runtime.mission_chat.lean_operative_rules` on.** Flip in the profile config,
   `launcher_harness_restart`, ten turns; flip back, restart. Batch B's turns are the OFF arm.
5. **§4 with the owner**, the reboot items last (the reboot gives `RT-HARNESS-SERVE-COLD-BOOT` its
   disk-cold boot and `FORK-NEMO-PYD-OLD-DELETE` its unlocked file).

## §3 The MCP rows

Tool names are the bridge's (`launcher_<id with dots as underscores>`). "Chat" means
`launcher_mission_control_agent_select{agent_id}` → `launcher_agent_chat_new` (or `_open{session_id}`)
→ `launcher_agent_chat_send{text}` (Allow). "CLI turn" means `hermes harness mission-chat message`.

| row | batch | app functions / steps | receipts and log lines to read | pass line | turns |
|---|---|---|---|---|---|
| `RT-QUEUE-COMMIT-SERVE-RESTART` | A | a vault-only commit on the primary (the sitting's own queue edit, `Harness_Brain/` only); wait 60 s; then `launcher_harness_restart` | diag log `[MissionServe] drain` (none after the commit); `agent.log` `home maintenance: code changed to` (none); diag `serve_drain proven=` on the restart | no drain after the vault commit; restart logs `serve_drain proven=yes` | 0 |
| `RT-ARGV-STREAM-READERS-LINGER` | A | none beyond the restart; Mission Control open | `agent.log` `stream_attach op=harness_stream purpose=cli_stream` (with request/connection/max_frames) and `stream_detach`; `turn_section … caller=cli`; `snapshot_build reason=demote caller=cli`; diag `[MissionStream] lane=` | every `cli_stream` attach has its `stream_detach`, or the attach line names the connection that never cancelled (the row's ask) | rides A/B |
| `RT-FIRST-TURN-BOOT-LATENCY` | A, B | boot leg: first Chat send to Neko after the restart; idle leg: wait 105 s, send again | `hermes harness observe turn-timing --check` (cold / after-idle / warm groups); `turn-timing` lines | each leg attributed by phase against the 259.5 ms warm table (n=1 each) | 2 |
| `RT-TURN1-WARM-CONNECTION` | A | the same first Neko turn (keeper landed `77c4337b7a`) | `idle_turn_keeper tick=… refreshed=… socket=…`; turn 1 `tls_done`, `client_built→request_sent`, `prewarm_first_turn_warmup_ms`; api:1 `conn=` | turn-1 api:1 `conn=` reused, no `tls_done` on turn 1 | rides A |
| `RT-REMOVE-H-TURN1-A5` | A | the same first turn | the `RequestBuildLaps` stamps (`agent_runtime/request_build_timing.py`, the 8 `# fork seam: h-turn1 A5` lines in `agent/turn_api_request.py`) on the turn's timing record | first-turn `build_api_request` laps read and within the warm table → the 8 lines return to upstream bytes in a later lane | rides A |
| `RT-PREWARM-HOLDS-WORKDIR-LOCK` | A | send the first turn while the prewarm is still in `system_prompt_build` (send right after `launcher_harness_restart` returns) | `prewarm_first_turn` line (`system_prompt_build_ms`, `construct_ms`); the turn's admit wait in `turn-timing` | the D1.04 number: the turn's wait vs the prewarm step it landed in (`design-sweep-d1-2026-10-10.md` § D1.04) | 1 |
| `RT-CHAT-TURN-22K-TOKENS` | A, C | first Neko turn ("hi"); a second Neko chat's first turn; the R4 arm in C | `prompt_surface` per-part receipt (S0); `API call #1 … in=`; `cache=` on the second chat | the S0 per-part split recorded; `cache=` read; R4 reported with C | 2 + C |
| `RT-SEND-PREP-FIXES-LIVE-PROOF` | B | 8 warm Chat turns, Neko and Dev, one Dev chat of 20+ rows (`launcher_agent_chat_list` → `_open`) | `tool_form_receipt source=unchanged publishes=0 pin_written=0`; `mcp_refresh_ms`; `send_prep_total`; `turn-timing --check` | (a) `mcp_refresh_ms`≈0 and the receipt as quoted on warm turns; (b) before/after on the 20+ row chat; (c) warm `send_prep_total` ≤ 400 ms | 8 |
| `RT-WARM-MEDIAN-LIVE-PROOF` | B | the same Launcher-route turns, plus 3 on a real long history (H8) | `[MissionChatTiming]` spans joined by `turn-timing --check`; warm/cold/idle groups | warm median on the post-relay head through the Launcher route, recorded beside 259.5 ms | rides B + 3 |
| `RT-RESOLVE-TURN-TWO-CACHE` | B | two matched new Neko chats, turns 1–3 each | final dispatched request hashes/counts (prefix, ordered tools, model/effort, route, cache scope, session pin) from the R034 capture; `API call … in=`/cached tokens | prefix drift or provider-side availability named, from hashes not post-turn `agent.tools` | 6 |
| `RT-ATTRIBUTE-RECORDED-FIRST-TURN` | B | stack samples (`py-spy dump` on the serve pid) during 3 fast-response turns; ablations (persistence / title / refresh) one at a time where a knob exists | `turn-timing` first-text; `title_upgrade_defer`, `revalidate_served_roots` timings | the delay to first text attributed to a named step, or "no step delays it" recorded (no assumed 375 ms) | 3 + 3/arm |
| `RT-INSTANCE-CONVERSATION-CUTOVER` | B | CLI turns on an instance conversation vs the profile worker, same persona | `turn-timing` per lane | the qualification's latency half recorded (`instance-conversations-2026-10-01.md`) | 6 (CLI) |
| `RT-WHETHER-UPSTREAM-POST-TURN` | B | ten persona turns (B's sends count; two with ≥10 tool iterations) | `runtime.operator.conversation.memory` read; background-review spawns per turn | spawn count over ten turns recorded → owner rules `skip_background_review` per persona | rides B |
| `RT-AUTH-JSON-TRANSIENT-READ` | B | none; passive over the sitting | `hermes_cli.auth: could not read`, `no available entries`, the Launcher's "needs attention" banner (`launcher_view_capture` if it shows) | zero sightings, or one with its writer named | rides |
| `RT-LIVE-SERVE-AGENTS-READINESS` | B | read the live log; the same walk read-only from a quiet process against the live store | `snapshot_agents_readiness walk_ms=` (live) vs the quiet walk | the 5–10× gap explained or narrowed to a named cause | 0 |
| `RT-CORE-CACHE-WRITES-BUILD` | B | the IC-4 per-family reader audit against the live store | `snapshot_core_cache_write` vs `snapshot_core_cache core_source=` | the family that breaks convergence named (`core-cache-input-closure.md` IC-4) | 0 |
| `RT-SETTLE-PUSH-LIVE-PROOF` | B | with the Launcher attached, re-arm one undelivered settle from a shell (`settle_push.py::SettlePush._push_due_settles`) | `serve_settle_undelivered`, the pushed frame, `settle_acked` | one re-armed settle pushed and acked | 0 |
| `RT-BOARD-CARD-FOLD-RUNTIME` | B | `launcher_mission_control_panel_open` (board); a card move over the `runtime.board.*` twin from a shell | serve ack time; full core received; repaint read by polling `launcher_view_content_state` | S0's number recorded in `board-card-fold-2026-10-15.md`; stop if under tolerance | 0 |
| `RT-LENS-L1-LIVE-PROOF` | B | confirm `plugins/eternia-lens` is in the serve's plugin list; add one real HTTP feed monitor; wait one poll | `runtime.lens.episodes`; the stored evidence row | an Episode raised and its evidence row read back redacted | 0 |
| `RT-GATEWAY-START-MANAGED-PYTHON` | B | `hermes --profile alice gateway start` from the managed venv's interpreter; if it fails, restore with a detached `gateway run` | the traceback; alice `gateway.log` | the `ManagedPythonUnavailable` traceback captured (or a clean start, which closes the row) | 0 |
| `RT-RETIRE-LEGACY-TOP-LEVEL` | any | `launcher_app_about` | build commit | installed build at or after `290449df44` → "go" for the retirement lane | 0 |
| `RT-LEAN-OPERATIVE-RULES` | C | ten Chat turns flag on, one asking a teammate a clarify question | `prompt_surface`; the clarify answer's `clarify_token` | the clarify answer returns on its `clarify_token`, or the bullets move into `harness-mission-lead` | 10 |

Batch C's ten turns also serve `RT-CHAT-TURN-22K-TOKENS`'s R4 A/B. Launcher-route sends (Allow
clicks): about 30; CLI turns: about 6.

## §4 Owner in person

| row | what the owner does | what Claude reads after |
|---|---|---|
| `RT-CONNECTIONS-TRACE-MISSING` | one ChatGPT/Codex browser sign-in on the isolated QA profile | the poll replies, `login_not_found`, the serve pid across the sign-in |
| `RT-SPARK-PRO-USAGE-BUCKET` | authorise a probe of a supported Spark route on the ChatGPT Pro account | the route's reply (no credential captured) |
| `RT-REALM-SYNC-REVERT-TAKES` | needs `launcher.realm_sync.revert` (not exposed; launcher row L-1) or the owner presses Revert in the realm sync panel | in-serve `revert_realm_sync` timing from `agent.log` |
| `RT-REALM-SYNCED-LEVEL-REVERT` | edit a level, then Revert (same missing function, L-1) | `launcher_realm_sync_status` before/after: the level drift row appears and clears |
| `RT-PIPER-FIRST-AUDIO-LATENCY` | install the Piper speech pack (`openphonemizer-en_us.onnx` is not on the box) | then first vs second OOD-word forward timed in a quiet process |
| `RT-FULL-PERSONAASSIGNMENTSTORE` | rule each of the 15 non-terminal rows (Claude reads the census first) | the re-census count |
| `RT-MAC-OPEN-CHAT-BUDGET` | Mac: the `agent.log` for 16:26:40–16:27:40Z (2026-09-07) and the instance row's `status` — if the log has rotated, the row is evidence-lost and closes | — |
| `RT-LOCAL-CHAT-PREP-COST` | Mac: pull and re-read CP-9; Stage 8's ten PC turns can ride §3 batch B | `turn_context_ms`, `builds_overlapped` |
| `RT-ROOT-CONFIG-MISPLACEMENT-CURE` | hand-fix the inert `config.yaml` rows on both machines | doctor `root_config_misplacement` `scope` re-read |
| `RT-SSH-PROFILE-REMOTE-CWD`, `RT-DASHBOARD-AUTH-SCRYPT-IMPORT` | post the two upstream issues in one sitting | — |
| `FORK-MACOS-CI-TRIAGE` | dispatch CI on `main` with the macOS matrix (owner's GitHub account) | the two shards' logs against run `38832830663` |
| `FORK-SECOND-WORKSTATION-ENV` | second workstation: shared `~/.venvs/hermes-test` on Python 3.14, rerun the one file | the 1/1 |
| `FORK-BARE-PYTEST-FILES-SEVERAL`, `FORK-P0-VALIDATED-SUITE-FROZE` | provide a VM or watchdog box off the desktop | the one-file-at-a-time bisect there |
| `FORK-LANE-HOMES-REAL-PATH` | Process Monitor (elevated) on a launcher real-serve sandbox run; read and apply `scripts/prune_user_path.ps1 -Apply` | the user `Path` after |
| `FORK-REQUALIFY-HOST-XFAILS` | one run of the two ids in an elevated shell | XPASS → move to `_unelevated_windows_shell` |
| `RT-HARNESS-SERVE-COLD-BOOT` | reboot (disk-cold) — the same reboot as below | the D1.06 segments: `interpreter_ms`, `interpreter_boot`, `main_import`, `dispatch` on the boot block |
| `FORK-NEMO-PYD-OLD-DELETE` | after the reboot, delete `nemo_relay/_native.pyd.old-0.8.4` from the shared test venv (still present 2026-10-18) | — |

## §5 Stale rows

| row | why |
|---|---|
| `RT-LIVE-PROFILE-VAULT-ALIASES` | no profile `config.yaml` under the live home lists a `browser_vault_*` name (read 2026-10-18; `base` has no chat-lane defer list at all), so there is nothing to replace; the `_FOLDED_TOOL_NAMES` alias drop is now a code lane, not an owner edit |
| `FORK-SHARED-HERMES-CLONE-PACK` | the shared clone reads clean on 2026-10-18: `git count-objects -v` prints no warnings, `garbage: 0`, zero `tmp_pack_*`, zero `.idx` without its `.pack` |

## Launcher rows this plan needs

- **L-1** `launcher.realm_sync.revert` — the realm sync panel's Revert as an app function
  (`confirm`, `localOnly`), over `runtime.realm.sync.revert`, so a revert is drivable and timed
  in-serve. Unblocks `RT-REALM-SYNC-REVERT-TAKES` and `RT-REALM-SYNCED-LEVEL-REVERT`.
