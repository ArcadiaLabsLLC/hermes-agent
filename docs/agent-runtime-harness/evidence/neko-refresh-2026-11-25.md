# Neko refresh while another persona is answering

The Windows incident settlement reported an internal gateway session mismatch as a missing provider. On November 25, the same refusal and a second session-lifetime defect reproduced on Hermes `0aec4e1f3a`. They share the runtime filing `RT-FU-A-SEND-AFTER-A-REFRESH-RUNS-INSTEAD-OF-SAYING-NO-PROVIDER-IS-CONFIGURED`.

## What ran

`tests/agent_runtime/neko_refresh_probe.py` is an opt-in regression probe. From the Hermes test environment run `python -m pytest -q -s tests/agent_runtime/neko_refresh_probe.py`. The probe exercises the real chat-open and history RPCs, mission-chat send, agent factory, in-process gateway and HTTP transport. Its isolated Neko Mission Lead Beta and QA persona use separate placements and chat roots. A loopback model holds the QA persona's request open during Neko's refresh. Counts come from calls to the existing operator agent constructor and requests received at that model.

Refresh here means a fresh RPC open and history read of the same saved chat, followed by a send. The incident involved a Flutter hard refresh on the owner's installation. The probe uses an isolated profile and explicitly establishes the competing native attachment in the last three cases. Which client first held the gateway session in the original incident remains unknown.

| Case | Neko operator builds | Neko model sends | Result |
| --- | ---: | ---: | --- |
| Ordinary refresh, resident reuse off | 1 | 1 | Answered |
| Ordinary refresh, resident reuse on | 0 | 1 | Answered |
| Native owner closed its session before refresh | 1 | 1 | Answered |
| Another native client held Neko's idle session open | 0 | 0 | Exit 2, provider unavailable, original native session removed |
| Another native client had a Neko prompt at the model | 0 | 0 | Same refusal, original busy session removed |
| A read-only observer attached to that busy session and exited | 0 | 0 | No operator send attempted. Observer shutdown removed the original session. |

In all six cases the QA persona was still at the model at the observation point, then finished from its single request. The model requests kept the two personas' prompt markers separate. The idle and busy refusals carried status 0 and the message “the gateway reused a session this turn did not build.” The removed object was the live gateway session. The probe did not establish loss of saved history or cancellation at the provider.

## Where to fix it

Upstream resume can return a session already held by another client. Two fork-owned paths currently treat that return as permission to close it. In `agent_runtime/operator_gateway_turn.py`, `open_actor` closes the returned ID when its own build did not supply that agent. In `agent_runtime/conversations/in_process_peer.py`, `InProcessPeer._route` records a successful resume like a newly owned session and `close` later sends a global close for it. The observer case reaches the latter path without an operator send.

Use the gateway's existing serialized create-or-reuse decision and transport attachments as the authority. Carry the actual acquisition result to the fork's operator and peer cleanup paths. Releasing a borrowed attachment should detach only that client. Closing or replacing an actor requires ownership at the point of release. A separate lookup followed by unconditional close leaves a race. If the gateway needs to expose its acquisition result, extend that existing operation. Keep the resident registry's chat, runtime signature, native revision and writer checks as the authority for reusing an operator actor.

For an incompatible live owner, preserve its session and surface a typed session contention outcome through Hermes' existing turn failure classifier. Retire an idle owner only after a verified handoff, or let its owner release it normally. Admit the pending send once through the existing request identity after release. Keep genuine provider and credential failures on their existing paths. An automatic retry needs positive evidence the original request never ran.

## Closure

Keep all three successful controls and turn the three failing cases green. Also cover a concurrent attach during retirement, a changed runtime signature, and repeated delivery of the same request ID after release. Verify a still-attached native client receives its terminal response, both chats reopen with their own history, and a genuine missing provider still reports setup. Finally repeat the owner-style Flutter hard refresh on a known build with two active persona chats. If it fails, record the acquisition result, attachment ownership and dispatch phase for the colliding session without logging message bodies.

## Windows verification on November 25

The ownership change is on `codex/session-release` (implementation `28e17f158f`, typed refusal `4dbe0fab76`). The fork asks for a fresh operator agent at the gateway's locked resume decision. A collision returns the existing `chat_busy` outcome before attachment or model dispatch. Peer shutdown and individual operator retirement use the gateway's transport disconnect operation. The gateway rechecks for remaining clients before teardown and owns the final agent close. The resident registry still checks persona, writer and runtime identity.

The seven cases now live in `tests/agent_runtime/test_neko_refresh.py` on the implementation branch. Cold, warm and released-owner sends reached the model once each. Both collision cases made zero requests, kept the native session, and admitted one new send after its owner released it. The observer leaving first and the original owner leaving first each preserved terminal delivery to the remaining client. The second persona completed once per case and both saved histories retained their own markers. The scoped-disconnect concurrency test also reattached a client between detach and the teardown claim and verified that the gateway preserved it.

The owner-style check used the running Windows debug app, Neko Mission Lead Beta's existing chat in testv4, and Amelia. The account Hermes service had restarted from the patched checkout. The Dart VM and Hermes turn journals give the following UTC times.

| Time | Observation |
| --- | --- |
| 19:34:46.526 | Amelia's marked turn started. Eternia showed “Amelia is working.” |
| 19:34:53.935 | Flutter's new main isolate started after its full restart. The test had switched back to Neko. |
| 19:35:01.513 | Amelia settled with exit 0 and a reply in her own history. |
| 19:35:37.002 | Neko's marked post-refresh message entered execution. The client showed “Replying” and Hermes produced output; the missing-provider banner did not recur on this send. |
| 19:37:59.710 | The tester stopped Neko after its output started investigating the earlier screenshot. Hermes recorded an interrupted turn with exit 0 and no provider refusal. |

Neko's history pane still failed at Eternia’s `MessageMotionProjection._buildIndex` assertion with a duplicate persisted-message row key when the saved transcript loaded. The composer remained usable. This live read verifies admission across the refresh and Amelia's completion. Neko's natural completion and a readable Neko transcript remain unverified. The client filing is `EterniaLauncher/Launcher_Brain/20 — Active Initiatives/mission-control-queue.md`, row `MC-FU-REFRESHED-CHAT-HISTORY-KEEPS-EACH-SENT-MESSAGE-ONCE`.

### Upstream comparison

Upstream main `33522e6dee` was fetched on November 25. The fork already includes upstream `b3014688f9`, which preserves multi-client transport membership and prunes departed viewers. The newer upstream `972a6982b0` protects idle transcript-writer leases. Neither fork caller exists in upstream main, and its resume contract still attaches to an existing live session. The fix uses upstream's disconnect and locked reattach decisions. Provider selection and persona routing continue to use their existing owners.

### Landing status

The runtime patch is in the owner's local checkout and on the remote `codex/session-release` branch. The queue, duplicate-helper and upstream-footprint checks passed after review. The final pre-push check still failed the embedded phone startup test, which also failed on untouched `817a54b86f` before reaching the first chat. Separate filing `RT-FU-THE-PHONE-ENGINE-STARTS-WITH-ITS-SHIPPED-MODULES` tracks the startup imports. The client evidence is on Eternia main in `2ca2eec146`.

### Landed repair and two-persona verification

Hermes main includes the gateway changes, the embedded startup repair `7ee8111f9a`, and saved-history curation `63f5bf73c9`. The phone and full-wheel end-to-end cases passed, including sign-in, a reserved model turn, protected history, no plaintext key on disk, and discussion-service startup. The landing pre-push gate passed.

A read-only inspection of the Neko store identified two different operator sends for which a later compression session had copied the original durable UID, timestamp and platform message ID but appended model context. One was the exact UID from the red screen. The storage display reader intentionally preserves some rewritten generations. The persona history projection now publishes the first visible body of a durable UID once. Separately addressed retries remain distinct. At upstream `33522e6dee` the storage fold still treats summary carriers specially. The fix leaves native replay and upstream storage unchanged.

The owner's running Windows app used Neko Mission Lead Beta on Claude and Amelia on GPT. The first full restart began at 15:08:08 Eastern during Neko's turn. Both replies were visible once after reopening. On the second pass both sidebar entries showed Replying when the full restart began at 15:09:23.031 Eastern. Amelia finished at 15:09:24.702, the new main isolate started at 15:09:25.114, and Neko finished at 15:10:46.839. Neither send was repeated or interrupted. The settlements were `chat-08a2681394a84db9` and `chat-8575f2bb16934297` respectively, each exit zero with no refusal. The saved transcripts had one operator row and one agent row for each marker in both passes. Each persona's reopened conversation showed both of its marked replies once. The older refusal remains in its original historical position.
