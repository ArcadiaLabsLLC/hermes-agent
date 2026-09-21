---
type: program
program: mission-control
status: active
cursor: "2026-09-21 — the SURFACE program is the launcher's; this note is the runtime-side pointer. The launcher's own refactor program (wave 4) is at 4 grandfathered units; its chat-panel tranche merged 2026-09-21."
tags: [program/mission-control, program]
---

# Mission Control (runtime side)

Mission Control is the launcher's command deck for this runtime: the spatial office, per-agent chat, the board, the read model. **The program note, the canon and the queue all live in the launcher's brain.** This note exists so a hermes session knows where to go and what the runtime owes the surface.

## Where the truth lives

- Program note: `EterniaLauncher/Launcher_Brain/10 — Programs/Mission Control.md`.
- Canon: `EterniaLauncher/docs/mission_control/00-index.md` (surface) ↔ [`docs/agent-runtime-harness/00-index.md`](../../docs/agent-runtime-harness/00-index.md) (runtime). Cross-linked, never duplicated.
- Queue: `EterniaLauncher/Launcher_Brain/20 — Active Initiatives/mission-control-queue.md` — **both repos**. A runtime finding is filed there, on arrival, claimed with `TAKEN` before work starts.
- Stage C QA (driving the launcher through the `launcher_qa` MCP surface): `EterniaLauncher/docs/stages/qa-reboot/`; the hermes-side skill is `launcher-mcp-operations`.

## What the runtime owes the surface (the contracts)

| contract | hermes side | launcher side | gate |
|---|---|---|---|
| CLI argv surface | `scripts/dump_cli_contract.py` → `tests/fixtures/hermes_cli_contract.json` | `tool/hermes_cli_contract/` (vendored copy) | the repo that MOVED goes red; re-vendor in the same wave |
| character payload keys | `scripts/dump_payload_contract.py` → `tests/fixtures/charsheet_payload_contract.json` | `tool/charsheet_payload_contract/` | same; a REMOVED key is the dangerous half |
| parity envelope (wire) | byte-pinned goldens (canon 03/07) | byte-pinned goldens | additive-only; observability = receipts |
| stream/response fixtures | `scripts/generate_agent_runtime_*_fixtures.py` | the launcher's `ready.json` recapture (code_tree hashes `agent_runtime`, so any hermes source change moves that fixture) | |
| RPC method manifest | `serve_rpc._METHODS` + `params` blocks (R-C8: the 18-key message) | the method-lane lowering; `args_not_carried:*` = an argv wall | [[0003 — RPC route first]] |

## Cross-repo rulings that bind both sides

- [[0003 — RPC route first]] — every touched write lane moves to the method lane; argv marked for delete.
- The multi-device canon: launcher doc 10 + hermes doc 09 (2026-09-06) retired stale claims in 01/03/05/06.
- The launcher's refactor program (`EterniaLauncher/docs/mission_control/planned/mission-control-refactor-program.md`) and its playbook are the method this repo's [[Downstream Refactor]] adopts.

## Open questions the runtime is waiting on

See [[Open Questions for Launcher]] — the Mac CP-9 read, the C5 re-run, and which verbs the launcher still lowers to argv (the refactor plan's §4.2 rows wait on that).
