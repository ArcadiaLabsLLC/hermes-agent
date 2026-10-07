---
type: program
program: mission-control
status: active
cursor: "2026-10-07 — inline agent-chat admission and thread roster reads use the runtime head, not the sender profile; real inline-handler regression covers two sender homes and sibling targets. Live relay/thread-opening acceptance remains in the Launcher console audit. Earlier Discussion qualification is unchanged; broad suite and host-safety investigations remain in fork-hygiene."
tags: [program/mission-control, program]
---

# Mission Control (runtime side)

Mission Control is the launcher's command deck for this runtime: the spatial office, per-agent chat, the board, the read model. **The program note and the canon live in the launcher's brain; the queue is split by repository — the hermes half is [[runtime-queue]] here.** This note exists so a hermes session knows where to go and what the runtime owes the surface.

## Where the truth lives

- Program note: `EterniaLauncher/Launcher_Brain/10 — Programs/Mission Control.md`.
- Canon: `EterniaLauncher/docs/mission_control/00-index.md` (surface) ↔ [`docs/agent-runtime-harness/00-index.md`](../../docs/agent-runtime-harness/00-index.md) (runtime). Cross-linked, never duplicated.
- Queue: [[runtime-queue]] for rows whose fix lives in this repository (split fork-owned / seams / upstream-owned); `EterniaLauncher/Launcher_Brain/20 — Active Initiatives/mission-control-queue.md` for the launcher half. A finding is filed on the side that must move first, on arrival, and claimed with `TAKEN` before work starts ([[0012 — The hermes half of Mission Control is queued here, split by ownership]]).
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
