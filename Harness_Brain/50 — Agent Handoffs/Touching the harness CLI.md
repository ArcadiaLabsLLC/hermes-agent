---
type: handoff
program: downstream-refactor
tags: [handoff, program/downstream-refactor, program/agent-runtime-harness]
---

# Touching the harness CLI

For any change under `hermes_cli/harness.py` or `hermes_cli/harness_parts/`. Reach for this before adding a verb, moving a handler, or repointing a test patch.

> [!important] The parts are real modules (lane H1, 2026-09-24)
> harness.py wires each handler through its part module (`inspect_commands._cmd_persona_list`, from `harness_parts/persona/`) and execs nothing. A name resolves in the globals of the module whose code reads it, so a test patches it THERE: `monkeypatch.setattr(inspect_commands, "load_agent_runtime_config", …)`, not `harness.`. W0-G4 (`tests/tooling/test_harness_namespace_is_thin.py`) reds a re-export shim on harness.py. A name several persona modules read is patched in each module that reads it.

## Read order

1. [[Downstream Refactor]] → plan §0.4 and §2 Wave 1 (H1) in `docs/agent-runtime-harness/planned/downstream-god-file-refactor.md`.
2. [`docs/agent-runtime-harness/01-system-architecture.md`](../../docs/agent-runtime-harness/01-system-architecture.md) — the command surface and how parts are wired (`build_parser` → `set_defaults(func=…)`).
3. `hermes_cli/_downstream_cli.py::build_downstream_parsers` — the seam into upstream's parser.

## Hard rules

- `serve.py` is a real module (it owns the stdout swap and tests import it by path) — the pattern the others follow.
- A part never imports `hermes_cli.harness` (cycle); shared helpers live in `hermes_cli/harness_support.py` (a leaf).
- Any argparse change: `python scripts/dump_cli_contract.py --check`, and READ the diff before `--write`. A removed command or flag is a launcher button that exits 2; re-vendor the launcher's `tool/hermes_cli_contract/` in the same wave.
- New write verbs are RPC methods, not argv ([[0003 — RPC route first]]).
- `hermes harness` handlers resolve `HERMES_HOME` at call time ([[Architecture Invariants]] rule 1); `_apply_profile_override()` has run before any handler in a CLI process, and has NOT under pytest.

## Surface map

- Families in `build_parser` (1,712 lines today): roots, gateway, skills, workspace, realm, persona, chat, characters, doctor, serve, office/board/level/flow/checkpoint.
- Handlers: `_cmd_<family>_<verb>`; chat turn = `persona/chat_turn_message.py::_cmd_mission_chat_message` → `persona/chat_turn_commit::_mission_chat_commit_turn`; serve = `harness_parts/serve.py::_cmd_serve` → `serve_loop`.
- Tests: `tests/hermes_cli/test_harness_*.py`, `tests/agent_runtime/` (patch the part module that reads the name).
