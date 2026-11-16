# A helper result changes Base's Console header in under a second

Windows MUltiversalLabsInc on November 15 local time. Eternia Debug `351c925fb75296a31041f5f65e5f4a47ac60c732`, Flutter 3.47.8, Harness `03d41e58e38ee8b02a2d5d9054dba7af3d39aa2e` (`code_source: checkout`, `code_dirty: false`). The isolated `stagec-smoke-lane-f0c5331320` namespace ran Base on the nonbillable loopback model fixture. Drive used the shipped Console composer and in-app recorder at 1920×1080. CPU was 5%, 1%, and 6% before the retry and 2% after. No compiler process was present before the interval.

Base delegated a helper with a 2.5-second fixture hold. The runtime started the helper-result turn `bg-completion-async_delegation_deleg_f545b709`. The turn journal's `phases.anchored_at` plus `write_ahead` gives the first instant. The QA bus's `running_work_first_seen` gives the first runtime frame and its application for the same turn ID. The final two observations come from consecutive in-app capture frames. Their filename timestamps are local wall time, converted to UTC below. The 14.5-second recording captured 143 frames at 9.9 fps and dropped 2 ticks.

| Observation | UTC on November 16 | Since write-ahead |
| --- | --- | ---: |
| Journal write-ahead | 00:32:37.132307 | 0 ms |
| Running-work row start | 00:32:37.134194 | 1.887 ms |
| [Tick 81, header still says “Standing by”](header-standing-by.png) | 00:32:37.562 | 429.693 ms |
| First frame that carries the chat-turn row | 00:32:37.580215 | 447.908 ms |
| App applies the frame | 00:32:37.580841 | 448.534 ms |
| [Tick 82, header says “Turn running · 0 s”](header-turn-running.png) | 00:32:37.822 | 689.693 ms |

The header and the “Base is working” strip appeared together by 690 ms from write-ahead. The first quiet recording used a 6.5-second helper hold and ended about one second before its forged turn. That turn's start reached a runtime frame in 268.767 ms and the app applied that frame 1.024 ms later. It contributes runtime evidence only. The app (PID 31384) and its private model fixture (PID 51236) were stopped through the lane-scoped `kill_launcher` flow and verified gone.
