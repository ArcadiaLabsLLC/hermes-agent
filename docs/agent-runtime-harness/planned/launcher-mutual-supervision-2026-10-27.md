# Planned — the bundled harness supervises its launcher (the hermes half)

**Status:** planned 2026-10-27 (planning lane w1027k-h-plan) for rows `RT-LAUNCHER-WATCHDOG`,
`RT-LAUNCHER-RELAUNCH`, `RT-GAME-PROCESS-WATCH` and `RT-PLAY-SESSION-HANDBACK`. The launcher
half is `EterniaLauncher/docs/mission_control/planned/LAUNCHER_HARNESS_SUPERVISION_2026-10-27.md`
(launcher lane w1027k-plan-host; rows `MC-HARNESS-LAUNCHER-HEARTBEAT`,
`MC-LAUNCHER-RELAUNCH-REHYDRATE`, `DIST-GAME-MODE-CLOSE-WHILE-PLAYING`,
`HERMES-BUNDLED-LIFETIME-HOST-AMENDMENT`). **This plan CONFIRMS that plan's wire contract
unchanged** (§2) and settles what it left to hermes: the restart limit and backoff, the
recovery of a watch after a harness restart, and the three clarifications in §2.
Owner doc: [`../09-multi-device-runtime.md`](../09-multi-device-runtime.md) ("The runtime
outlives the launcher"). Product context: `EterniaLauncher/docs/subsystems/HEADLESS_LAUNCHER_PLAN_2026-10-27.md`.

**The ruling this serves (owner, 2026-10-27, "agreed"):** "Change the bundled-lifetime rule
yea it should be more dynamic then, if launcher hangs it can relaunch itself and get
rehydrated by its harness, or if its harness dies the harness can be rebooted by launcher?"
The harness lives as long as the user has not quit; an explicit Quit stops both and
nothing revives them.

## 1. Problem

Today the bundled harness is BOUND to its launcher. The launcher starts
`harness serve --parent-pid <its pid>`; `agent_runtime/parent_watch.py` watches that pid
(a `SYNCHRONIZE` handle on Windows, `kill(0)` / `getppid()` on POSIX) and
`hermes_cli/harness_parts/serve/session.py::_on_parent_gone` drains with end reason
`parent_exited` (`hermes_cli/harness_parts/serve/end_reason.py`). A crash and a Quit look
the same; a hung launcher is invisible; a launcher that closes for a game takes the
harness with it, so nothing sees the game end and nothing relaunches the launcher.

Two facts in the tree shape the design:

- A non-service serve dies on stdin EOF (`EndReason.STDIN_EOF`); only `--service` treats
  EOF as "the starter detached". Watching a game with no launcher is only possible on a
  `--service` serve (the launcher's L11 already closes only over the loopback socket).
- Ops are per transport: `hermes_cli/harness_parts/serve/constants.py` holds `OPS`,
  `OPS_STDIO_ONLY` and `OPS_GATEWAY_DENIED`, and `hermes_cli/harness_parts/serve/manifest.py::ops_manifest`
  advertises by membership. An op that can make the harness START A PROCESS must never be
  reachable from a paired gateway device.

## 2. The wire contract — confirmed as the launcher plan names it

Ops on the existing NDJSON `{"op": …}` lane, answered by
`hermes_cli/harness_parts/serve/handle_message.py`'s op table:

| op | fields | reply |
|---|---|---|
| `launcher_beat` | `seq`, `pid`, `state` ∈ `running` · `suspended` · `closing_for_game` · `quitting`, `window_visible`, `executable`, `build`, `supervise`, and with `closing_for_game` (hermes also accepts it with `suspended`) a `game` | `launcher_beat_ok {seq, watching}` |
| `play_sessions_pending` | — | `{sessions: [{session_id, game_id, ended_at \| null, last_seen_at, exit_code \| null, outcome ∈ exited · still_running · lost}]}` |
| `play_sessions_ack` | `session_ids` | `{ok}` — the only delete |

`game` = `{session_id, canonical_game_id, mapping_id, title, pid, executable, install_dir, started_at}`;
`game_id` in a pending record is that `canonical_game_id`. Relaunch argv:
`<executable> --harness-relaunch=<crashed|hung|game_ended>` plus `--start-hidden` when the last
beat had `window_visible: false` or a watched game is still running. Beat every 5 s;
hung = no beat for 45 s of time the harness was awake.

**Three clarifications hermes adds (no rename):**

1. **Local transports only.** The three ops join `OPS_GATEWAY_DENIED`, so a gateway device
   neither sees them in its manifest nor can send them.
2. **A dropped connection with the pid still alive is not yet a crash.** It starts the
   45 s hang clock; a reconnect that beats again clears it. Only a gone `pid` with a last
   state other than `quitting` / `closing_for_game` is a crash at once. Why: a socket blip
   must not get a live launcher killed.
3. **`watching: true` needs a `--service` serve.** On a non-service serve the reply is
   `watching: false`, which the launcher's L4 already answers by staying suspended.

## 3. Decisions

1. **The owner module is a new fork package, `agent_runtime/launcher_supervision/`.**
   `contract.py` (frozen value objects and parsing for §2 — models layer), `policy.py` (the
   pure transition table: state × event → action, the restart budget, the hang clock —
   policy layer, no I/O), `watchdog.py` (wiring: the re-targeted pid watch, the beat clock,
   persistence), `relaunch.py`, `game_watch.py`, `play_sessions.py`. The serve calls in
   through the op table and one hook in `hermes_cli/harness_parts/serve/session.py`.
2. **Supervision is earned by a beat.** Until the first `launcher_beat` with
   `supervise: true`, the serve behaves exactly as today (`--parent-pid` drains). Every
   transition is a row in `policy.py`'s table and emits a `launcher_supervision` receipt
   line to `agent.log` naming the event and the action.
3. **The parent watch is re-targeted per beat.** A beat whose `pid` differs from the
   watched one disarms the old `ParentWatch` and arms one on the new pid, recording the
   pid's OS creation time (`psutil.Process(pid).create_time()`) at that moment, so a
   reused pid is never mistaken for the launcher on POSIX (Windows already holds a
   handle). `--parent-pid` stays the initial target.
4. **Crash → relaunch; Quit → stop.** Pid gone with last state `running` / `suspended`
   (and `supervise: true`) → relaunch `crashed` (W2; W1 records it and drains as today).
   `quitting` acked, then the existing stop frame → drain, new end reason
   `launcher_quit`; nothing is relaunched after `quitting`, and a `quitting` launcher whose
   pid is still alive 30 s later is not killed and not relaunched — the harness drains.
   `supervise: false` (a debug build) → record only, never kill or relaunch.
5. **Hang → kill the launcher pid only, then relaunch.** Hung = §2's 45 s of awake time with
   the pid alive and state `running`. "Awake time" sums the beat clock's own ticks and
   drops any tick whose wall-clock gap exceeds three tick lengths (the machine slept).
   Hermes terminates that one pid (`TerminateProcess` / `SIGKILL`) — never the tree, so a
   game the launcher started survives — which also frees the single-instance mutex the
   launcher plan names, then relaunches `hung`.
6. **`suspended` turns hang detection off,** and a crash under `suspended` is not
   relaunched until the game ends (the harness takes the `game` it was given, or relaunches
   at once when it was given none).
7. **Restart budget: 3 crash/hang relaunches per rolling 10 minutes, backoff 2 s, 10 s,
   30 s.** A `game_ended` relaunch is not counted. A relaunch with no beat from the new
   process within 60 s counts as failed. On exhaustion the harness stops relaunching and
   drains with end reason `launcher_restart_limit` — a fail-safe, so no invisible harness
   outlives a crash-looping launcher. The budget is persisted, so a harness restart does
   not reset it.
8. **The relaunch executable is verified.** A beat's `executable` must real-path to the
   same file as `psutil.Process(pid).exe()`; a beat that disagrees is answered and
   ignored for supervision (`launcher_identity_mismatch` receipt). This is what stops a
   local caller from turning a beat into "run this program". The spawn is
   `[executable, --harness-relaunch=<reason>, (--start-hidden)]` with
   `hermes_cli/_subprocess_compat.py::windows_detach_flags` on Windows and
   `start_new_session=True` on POSIX, so the GUI is not in the harness's process tree; the
   environment is the harness's own minus `HERMES_*`.
9. **The OS ending the session is not a crash.** A harness that has seen `logoff`,
   `ctrl_close` or `SIGTERM` (`EndReason`) relaunches nothing; the first backoff (2 s) gives
   the OS time to deliver that when the launcher dies first.
10. **Persistence.** `<store_root>/launcher_supervision/state.json` (last beat, watched pid
    and creation time, budget) and `<store_root>/launcher_supervision/games/<session_id>.json`,
    written atomically.
11. **Who it applies to.** Any runtime that receives beats; relaunching is the bundled
    lifetime's call. A Developer Edition service that receives beats applies the same
    table (the launcher plan's L6 leaves it to the runtime); nothing is relaunched for a
    runtime no launcher ever beat to.
12. **The hermes side of the lifetime-rule amendment** is 09's "The runtime outlives the
    launcher" section, 03's op list and `parent_watch.py`'s module docstring (which quotes
    embedded-hermes D1, "crashing leaves no bundled Hermes running"). The launcher's
    amendment is its own row, `HERMES-BUNDLED-LIFETIME-HOST-AMENDMENT`.

### Game watching (RT-GAME-PROCESS-WATCH)

13. **Watch by locator, cross-platform through `psutil`** (already a dependency,
    `pyproject.toml`; the bundled-phone profile never reaches this code). The game runs
    while (a) the handed-over `pid` is alive with the creation time recorded at receipt,
    or (b) a process of this user has `executable` as its executable or one under
    `install_dir`. Poll every 5 s. A store bootstrapper that exits at once is covered by
    (b) and by a 60 s start grace in which "nothing found" is not yet an end.
    `watching: true` is answered only when at least one locator resolves at receipt.
14. **The game has ended** when neither holds for two consecutive polls. With the launcher
    closed that relaunches it (`game_ended`); with it alive (`suspended`) it only records.
15. **Harness restart mid-game.** The watch is on disk from receipt (decision 10) with
    `last_seen_at` refreshed every 60 s. A harness that boots and finds an active watch
    re-applies the locators: still running → keep watching (relaunching on end if no
    launcher beats); gone → close the record as `outcome: lost`, `ended_at: null`,
    `last_seen_at` kept. If the harness dies while the launcher is closed for a game,
    nothing relaunches either until the user starts the launcher; the record survives
    and is handed back then.

### Play-session handback (RT-PLAY-SESSION-HANDBACK)

16. **The record is §2's**, one per watched game, keyed by `session_id`; `outcome` is
    `exited` (end observed: `ended_at` set, `exit_code` only when the handed-over pid was
    observed exiting with one), `still_running`, or `lost` (decision 15). Hermes reports
    what it observed; it computes no duration and owns no play time.
17. **Stored** in the game file until acked; capped at 64 records and 30 days, oldest
    dropped first, each drop logged with its session id (never silent).
18. **De-duplication is the launcher's** (its L9: the session id is the key, ending is
    idempotent). Hermes deletes only on `play_sessions_ack`, so delivery is at least once.

## 4. Slices

**W1 — beats, re-targeted watch, quit vs crash recorded** — BUILT 2026-10-28 (lane w1028a-h-plan):
`agent_runtime/launcher_supervision/` (`contract.py`, `policy.py`, `watchdog.py`) and
`hermes_cli/harness_parts/serve/launcher_supervision.py`. Two departures from the list below: only
`launcher_quit` joins `EndReason` (`launcher_restart_limit` lands with W2, its only producer), and
W1 persists nothing (decision 10's `state.json` lands with W2's budget, the first thing that must
survive a harness restart). The wire is §2 unchanged; `watching` is always false until G1.
- `agent_runtime/launcher_supervision/__init__.py`, `contract.py`, `policy.py`, `watchdog.py` — new.
- `hermes_cli/harness_parts/serve/constants.py` — `launcher_beat` in `OPS_EVERY_TRANSPORT`
  and `OPS_GATEWAY_DENIED`; `hermes_cli/harness_parts/serve/handle_message.py` — `_op_launcher_beat`.
- `hermes_cli/harness_parts/serve/session.py` — the hook: a supervising beat replaces
  `_on_parent_gone`'s drain with the policy's action; no beat → unchanged.
- `hermes_cli/harness_parts/serve/end_reason.py` — `launcher_quit`, `launcher_restart_limit`.
- `agent_runtime/parent_watch.py` — re-arm support and the docstring amendment;
  `docs/agent-runtime-harness/09-multi-device-runtime.md`, `docs/agent-runtime-harness/03-transport-and-wire.md`.
- In W1 a crash or hang is DETECTED and recorded and the serve drains as today; nothing
  is relaunched yet, so W1 ships safely before W2.

**W2 — relaunch, kill-on-hang, budget** — BUILT 2026-10-29 (lane w1029a-h-rt-b; 09 § "The runtime
outlives the launcher" is the contract). Departures: a `suspended` crash WITH a `game` keeps W1's row
until G1 (decision 6's wait needs the game watch); "OS ending" (decision 9) is read as any latched end
reason, which also covers a non-service serve's stdin EOF; `state.json` holds the budget and the last
beat, not the watched pid's creation time (re-read at arm).
- `agent_runtime/launcher_supervision/relaunch.py` — new; `policy.py` gains the relaunch,
  backoff and budget rows; `watchdog.py` persists the budget.

**G1 — game watch** (row `RT-GAME-PROCESS-WATCH`, after W2)
- `agent_runtime/launcher_supervision/game_watch.py` — new; the beat's `game` and the
  `watching` answer; boot-time resume in `watchdog.py`.

**P1 — play-session handback** (row `RT-PLAY-SESSION-HANDBACK`, after G1)
- `agent_runtime/launcher_supervision/play_sessions.py` — new; `play_sessions_pending` /
  `play_sessions_ack` in `constants.py` (both lists) and `handle_message.py`.

Tests for all four: `tests/agent_runtime/test_launcher_supervision_policy.py` (the pure
table), `tests/agent_runtime/test_launcher_supervision_ops.py`, and serve-level cases
beside `tests/hermes_cli/test_harness_serve_parent_watch.py`.

## 5. Test plan (each with its killing mutation)

- **W1, local only:** the gateway manifest lacks `launcher_beat` and a gateway connection
  sending it is denied; the loopback manifest lists it (positive control).
  *Mutation:* leave it out of `OPS_GATEWAY_DENIED` → red.
- **W1, re-target:** a beat with a new pid moves the watch; the old pid exiting then
  changes nothing. *Mutation:* keep watching the first pid → red.
- **W1, quit vs crash (table):** pid gone after `quitting` → `drain(launcher_quit)`; after
  `running` with `supervise: true` → `record_crash` (W1) / `relaunch(crashed)` (W2);
  with `supervise: false` → record only. *Mutation:* swap the first two rows → both red.
- **W1, hang clock:** 45 s of awake ticks with no beat → `hung`; 44 s → nothing; 45 s of
  wall time containing a 30 s sleep gap → nothing. *Mutation:* count wall time → the sleep
  case reds.
- **W1, connection drop:** connection closed, pid alive, beat 10 s later → no crash.
  *Mutation:* treat a drop as a crash → red.
- **W1, suspended:** under `suspended` an overdue beat yields nothing.
  *Mutation:* ignore state in the hang check → red.
- **W2, identity:** a beat whose `executable` is a different file than the pid's own is
  never relaunched. *Mutation:* compare basenames → a same-name different-file case reds.
- **W2, budget:** the fourth crash in 10 minutes → `drain(launcher_restart_limit)`; a
  `game_ended` relaunch does not count. *Mutation:* count `game_ended` → red.
- **W2, tree safety:** the hang kill terminates the launcher pid and its spawned child
  survives. *Mutation:* kill the tree → red.
- **W2, real spawn:** a fake launcher script beats, is killed, and is relaunched with
  `--harness-relaunch=crashed`; after `quitting`, never.
- **G1, bootstrapper:** a handed-over pid that exits at once while a process under
  `install_dir` runs is still running, and `watching` is true. *Mutation:* watch the pid
  only → red.
- **G1, restart mid-game:** a game file with the process gone → `outcome: lost`,
  `ended_at: null`; with the process alive → resumed. *Mutation:* stamp `ended_at = now` → red.
- **P1, at least once:** `play_sessions_pending` twice returns the same records; `ack`
  deletes only the named ids. *Mutation:* delete on pending → the second call reds.
- **P1, cap:** the 65th record drops the oldest and logs it. *Mutation:* drop silently →
  the receipt assertion reds.

## 6. Open questions

- **A harness that dies while the launcher is closed for a game** relaunches nothing until
  the user starts the launcher (decision 15). Should an OS-level start (the templates in
  `docs/agent-runtime-harness/reference/service/`) cover the bundled harness for that
  window? **Recommend: no** — play time is still recovered at the next launcher start;
  only the automatic relaunch after the game is lost, and an OS-started bundled harness is
  the Developer Edition's product shape. Not blocking any slice.
