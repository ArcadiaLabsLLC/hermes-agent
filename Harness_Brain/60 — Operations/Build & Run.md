---
type: operations
tags: [operations, build, run]
---

# Build & Run

The fork's day-to-day commands. Upstream's install and CLI docs are `AGENTS.md` § Development Environment and `website/docs/`; this page is the fork's delta.

## Install and hooks

```bash
git config core.hooksPath .githooks      # the ONE hook: post-merge re-installs the canonical skill packages
python scripts/verify_harness_skill_install.py
```

Mission Control's install of hermes for the launcher: `scripts/install-mission-control-hermes.ps1` (operator script; the launcher's own installer calls the equivalent).

## Profiles and homes

- `hermes -p <profile> …` selects `HERMES_HOME=<store>/profiles/<profile>`; `_profile_bootstrap._apply_profile_override()` runs before any import that reads the filesystem — in a CLI process only, never under pytest.
- Live store on this box: `X:/Eternia/.hermes/` (`config.yaml`, `profiles/…`, `agent-runtime/` = `HERMES_AGENT_RUNTIME_ROOT`). The launcher's runtime uses `profiles/base`. Root `HERMES_HOME` writes go to the ACTIVE profile (`active_profile`) — use `-p` explicitly.
- Default model per home since 2026-09-06: `gpt-5.6-luna` on `openai-codex` (`hermes config set`, per profile); a running runtime reads config at boot.

## The runtime

```bash
hermes harness serve                      # the process the launcher spawns (stdio NDJSON + LAN socket lane)
hermes harness serve connect              # attach a console to a running serve
hermes harness doctor [--fix [--dry-run]] # store hygiene, placement census, root-config misplacement
hermes harness persona list | show | instance create | instance open-chat | chat message …
hermes harness gateway id | pair | introduce | devices | peers …
hermes harness realm … | workspace … | skills … | roots …
```

The verb surface is the contract fixture `tests/fixtures/hermes_cli_contract.json`; write verbs are RPC methods ([[0003 — RPC route first]]).

## Fixtures and dumps (run after the matching change)

```bash
python scripts/dump_cli_contract.py --check          # argparse surface
python scripts/dump_payload_contract.py --check      # character payload keys
python scripts/dump_toolset_manifest.py              # the fork's tool inventory
python scripts/emit_harness_tool_inventory.py
python scripts/generate_agent_runtime_stream_fixtures.py
python scripts/generate_agent_runtime_response_fixtures.py
```

## Heavy commands

Background, explicit timeout, log file, exit code unpiped (`; rc=$?; exit $rc`), never polled, never `| tail`. Two full suites on this box contend; one landing at a time. See [[Running the suite]].

## Worktrees

From a NEUTRAL cwd: `git -C X:/Eternia/hermes-agent worktree add X:/Eternia/worktrees/<lane> -b <branch> origin/main`. Never `checkout`/`switch` in the primary; `tests/acp` does not collect from a worktree.
