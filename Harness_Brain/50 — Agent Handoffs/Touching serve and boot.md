---
type: handoff
program: agent-runtime-harness
tags: [handoff, program/agent-runtime-harness]
---

# Touching serve and boot

For any change to `hermes harness serve`: `harness_parts/serve.py` (`serve_loop`, the drain, the socket lane, the gateway listener), `agent_runtime/serve_socket/`, `serve_registry.py`, the prewarms, the boot timeline. Reach for this before touching anything the launcher's restart path exercises.

> [!important] This is the restart-fence code, and its proofs are field proofs
> The runtime died at EVERY launcher restart in the post-rebuild field run (5/5) before RB-1..RB-9 and RS-1..7 landed; the killers were the boot sweep run blind on the loading-fallback identity and a build-behind restart spawning a second runtime mid-drain that lost the socket lock. Unit gates: RB-7 (reproduces the field byte for byte, red-first), RO-9 (both arms). The proof that closes a row is an OPERATOR BOOT reading the receipts, not a green suite.

## Read order

1. [`docs/agent-runtime-harness/04-boot-and-lifecycle.md`](../../docs/agent-runtime-harness/04-boot-and-lifecycle.md) — spawn → authoritative, stage by stage, each with its receipt.
2. [`03-transport-and-wire.md`](../../docs/agent-runtime-harness/03-transport-and-wire.md) — frames, the drain (`_finish_drain` releases the socket lock), `gateway_block_when_no_listener`.
3. [`09-multi-device-runtime.md`](../../docs/agent-runtime-harness/09-multi-device-runtime.md) + `EterniaLauncher/docs/mission_control/10-multi-device-architecture.md` — the runtime that outlives its launcher, registration, the redial.
4. `EterniaLauncher/docs/mission_control/planned/runtime-observability.md` — RO-1..RO-9, the sidecar, the timeline tool (`dart run tool/mission_runtime_timeline.dart`).

## Hard rules

- `serve_loop` is ONE 3,760-line function with 39 closures; `_handle_message` reads 21 enclosing locals + 4 `nonlocal`s. Until the refactor's H4 lane lands `ServeSession`, a change here is a change inside a closure — check what it captures.
- The boot timeline line (`harness serve boot timeline: k=v …`) and the `ready` frame are byte-compared fixtures on the launcher side; the launcher's `ready.json` recapture moves whenever `agent_runtime` source changes (code_tree hash).
- The serve's `HERMES_HOME` is `<store>/profiles/base`; the register row is `serve_instances/<pid>.json`; the socket owner lock is `SocketOwnerLock`. A second runtime on the same store is the defect, never a fallback.
- Windows: the runtime lives in the venv redirector's kill-on-close Job; intermediaries spawn through the base interpreter `-c` with `CREATE_NO_WINDOW` (the WMI arm dropped the caller env — RL-17, struck).
- Never run a serve from a test; the hermetic-home fixture and `HERMES_HOME` at call time keep tests off the live store.

## Receipts to quote

`ready` frame, boot timeline line, `serve_instances/<pid>.json`, the RO-1 sidecar, `install_connection` receipts, `hello_ok` (carries gateway), `link_dropped` → redial (RL-18), the drain deadline. If the change is about the pre-admit span, that is [[Touching a chat turn]].
