# Instance versus profile-worker latency

Controlled baseline, not cutover approval. Base: `ebed3b5bae` plus the probe tests.

## Measurement

Windows, Python 3.13.15, three fresh test processes per route. Each process opens
one session and sends one cold and two warm turns. Both use the real serve RPC
dispatcher and agent loop, the same synthetic profile, model, prompt and local
OpenAI-compatible provider. No paid requests or user profiles. Compute isolation
is off for both; the desktop worker factory remains subprocess-based.

Times start **after the service is ready**. Open includes discovery and native
session creation. Admission, first observed answer and completion start at Send.
No typing delay or artificial prewarm wait. Observation polls at 25 ms plus RPC
round-trip time. The provider returns one text fragment, so this is not a token
streaming or UI-render benchmark. CLI bootstrap and production boot prewarming
are outside this experiment.

Milliseconds; cold columns are medians of three, warm columns of six:

| Route | Open | Cold admission | Cold first answer | Cold complete | Warm first answer | Warm complete |
|---|---:|---:|---:|---:|---:|---:|
| Instance | 188 | 21 | 3,719 | 3,768 | 337 | 389 |
| Profile worker | 3,949 | 52 | 2,614 | 2,651 | 66 | 114 |

Open-to-first-answer totals: instance 3,843 / 3,929 / 3,896 ms;
worker 6,479 / 6,563 / 6,583 ms. These totals must not hide the slower instance
reply after Open. If the user types while opening/prewarming completes, that
post-open cost matters. Warm instance overhead is about 271 ms higher here.
No causal performance diagnosis is claimed.

## Evidence and bounds

- Tests: `test_instance_first_turn_latency.py`, `test_worker_first_turn_latency.py`.
  One shared probe; no replacement session manager or runtime changes.
- Both exercise three actual streamed turns, check model/credential isolation,
  record JUnit timing properties and drain their test runtime.
- `test_conversation_latency_observation.py` rejects historical answers being
  counted as new output. Removing the worker turn filter and setting the instance
  answer count to one failed both tests; restoring them passed both.
- Local receipts: `receipts/instance-conversations/{instance,worker}-latency*.xml`
  and corresponding `.log` / `.resources.jsonl`; observation mutation and restored
  logs share that directory. Six measured runtime runs passed without retries.
- Tests ran serially in a Windows job capped at 4 GiB / 24 processes, with a
  210-second wall limit and 12-GiB host free-memory reserve. No guard fired.

Run each lane separately through `scripts/run_tests.sh -j 1 --file-timeout 180
--file-retries 0 tests/agent_runtime/test_<lane>_first_turn_latency.py`, passing
`-- --junitxml=<receipt> -o junit_family=legacy`. Each receipt must have its own
path. Never run against live profiles or bypass the canonical hermetic runner.

## Still owed

Keep the worker. Qualify the final adapter/engine/UI with the same real provider,
profile, model and prompt, cold and warm, before retirement. Preserve first-delta
streaming and investigate the measured post-open/warm difference in that path.
The earlier 12-second operator report is a different workload and is neither
confirmed nor disproved by this loopback baseline.

## Stream-enabled phase attribution, October 2

Three new isolated runs per lane, six warm turns each, at `85f686e74e` plus
the stream-enabled instance probe. Same controlled workload and limits above;
these supersede neither the original sample nor the required live comparison.
The probe reads the native journal's existing `profile_timing` projection,
also used by the Harness history query. No new runtime instrumentation.

| Route | Open | Cold first answer | Warm admission | Warm first answer | Warm complete |
|---|---:|---:|---:|---:|---:|
| Instance | 189 | 4,828 | 26 | 387 | 506 |
| Profile worker | 4,409 | 3,479 | 55.5 | 90 | 126 |

The warm first-answer delta is **+297 ms**, completion **+380 ms**.
Instance warm `profile_timing` medians (milliseconds unless flagged):

| Native phase | Median |
|---|---:|
| `session_db_open_ms` | 15 |
| `context_skill_preload_ms` | 18.5 |
| `context_signature_ms` / `context_hud_ms` | 2.5 / 2.5 |
| `observability_skill_rows_ms` | 1 |
| `runtime_resolve_ms` | 0 (cached in all six) |
| `agent_construct_ms` | 61 |
| ↳ context engine / core state / memory skills / provider client | 38.5 / 7 / 5 / 4.5 |
| `conversation_call_ms` | 130 |
| ↳ turn context / system prompt restore / provider dispatch | 14.5 / 3 / 14 |
| ↳ provider first delta / stream consume | 12 / 0 |
| `result_normalize_ms` / `budget_checks_ms` | 0 / 0 |
| `resident_actor_reused` | **0 in all six warm turns** |

Nested spans overlap; their medians must not be summed. The worker does not
publish these phases, so a per-phase *cross-route subtraction* is unavailable.
These records locate instance costs, not all 297 ms of the difference: admission,
unrecorded preparation/commit work, read delivery and polling remain in the
end-to-end number. This fixture leaves hot sessions at the native default; no
resident actor was reused. Do not generalize that flag to production.

Receipts: `{instance,worker}-phases-{1,2,3}.xml` and bounded logs under the
same local receipt directory. All six runs passed; no guard fired. Keep the
profile worker pending matched live latency and console parity.
