# Session skills verification — 2026-09-24

The validated fork scope ran once on the skills candidate: 568 files,
9,539 passed, 78 failed, 18 skipped. The same failing files plus the frozen-home
gate ran on unchanged baseline `120a7f5a36`: 1,346 passed, 79 failed, 2 skipped.
Every candidate failure reproduced on that baseline. This is **not** an
all-green suite. Focused skills/ACP tests passed; the separately caught missing
layer declarations in the new modules were corrected and the layer gate passed.

Before landing, the candidate rebased cleanly onto `ebc8ce4430`. Incoming work
already repairs the S41, remote-dispatch and dispatch-tally fixtures listed
below. The skills/ACP and import-layer tests passed again after that rebase;
the full-scope counts above describe the earlier measured candidate, not a
second full run on the rebased tree.

## Existing failures, not waived

| Finding | Failing subjects |
|---|---|
| Gateway TLS fingerprint/real-socket failures | gateway TLS, media fetch, peer cross-install chat/media, two roots, local llama gateway, serve gateway/chat-reply/peer lanes, remote dispatch |
| Refactor-era fixtures retain removed subjects | scope-use serve acceptance references removed `hermes_cli/harness_parts/serve.py`; S41 import gate expects retained `WorkerSessionState` |
| Historical references absent in this clone | flag-binding and mid-test-undo gates require `upstream/main`; tombstone gate requires `4a21f0779`; they correctly fail closed |
| Frozen home references | `gateway/mirror.py` and `tui_gateway/server.py` retain import-time home witnesses |
| Already queued | empty-WAL fixture under SQLite 3.53.1; no-kanban dependency; rejected-event dispatch tally |

The runtime cause of the gateway failures is not established by this comparison;
only their pre-existence is. Restore the gate's baseline references from verified
history, not by changing assertions. Findings route to the fork-hygiene queue.

Cross-client native evidence and presentation checks are recorded in
`EterniaLauncher/docs/companion/planned/SKILLS_SLICE_2026-09-24.md`.
