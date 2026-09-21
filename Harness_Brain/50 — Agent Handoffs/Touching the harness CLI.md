---
type: handoff
program: downstream-refactor
tags: [handoff, program/downstream-refactor, program/agent-runtime-harness]
---

# Touching the harness CLI

For any change under `hermes_cli/harness.py` or `hermes_cli/harness_parts/`. Reach for this before adding a verb, moving a handler, or repointing a test patch.

> [!important] The seven parts are not modules yet — they are text exec'd into harness.py's globals
> `_load_command_parts` in `harness.py` reads `persona_commands`, `runtime_commands`, `board`, `office`, `level`, `flow_commands`, `checkpoint_commands` and runs each with `exec(..., globals())`. Every name in every part resolves through harness.py's dict. 263 test patches on `harness.<name>` work only because of that (67 own, 155 imported, 41 part-defined). If you turn a part into a real module, code inside it resolves names in ITS globals and a patch on `harness.X` becomes a no-op that passes. `monkeypatch.setattr` raises on a MISSING attribute, not on a present-but-unused one. The refactor plan's H1 lane and gate W0-G4 (harness binds no callable defined elsewhere, allowlist: `build_parser`, `emit_harness_error`, `_cmd_characters_*`) are the fix; do not half-do it.

## Read order

1. [[Downstream Refactor]] → plan §0.4 and §2 Wave 1 (H1) in `docs/agent-runtime-harness/planned/downstream-god-file-refactor.md`.
2. [`docs/agent-runtime-harness/01-system-architecture.md`](../../docs/agent-runtime-harness/01-system-architecture.md) — the command surface and how parts are wired (`build_parser` → `set_defaults(func=…)`).
3. `hermes_cli/_downstream_cli.py::build_downstream_parsers` — the seam into upstream's parser.

## Hard rules

- `serve.py` is a real module (it owns the stdout swap and tests import it by path) — the pattern the others follow.
- A part never imports `hermes_cli.harness` (cycle); shared helpers go to `harness_parts/_common.py` (a leaf).
- Any argparse change: `python scripts/dump_cli_contract.py --check`, and READ the diff before `--write`. A removed command or flag is a launcher button that exits 2; re-vendor the launcher's `tool/hermes_cli_contract/` in the same wave.
- New write verbs are RPC methods, not argv ([[0003 — RPC route first]]).
- `hermes harness` handlers resolve `HERMES_HOME` at call time ([[Architecture Invariants]] rule 1); `_apply_profile_override()` has run before any handler in a CLI process, and has NOT under pytest.

## Surface map

- Families in `build_parser` (1,712 lines today): roots, gateway, skills, workspace, realm, persona, chat, characters, doctor, serve, office/board/level/flow/checkpoint.
- Handlers: `_cmd_<family>_<verb>`; chat turn = `_cmd_mission_chat_message` → `_mission_chat_commit_turn` (persona_commands); serve = `harness_parts/serve.py::_cmd_serve` → `serve_loop`.
- Tests: `tests/hermes_cli/test_harness_*.py`, `tests/agent_runtime/` (patch `harness.<name>` today; part modules after H1).
