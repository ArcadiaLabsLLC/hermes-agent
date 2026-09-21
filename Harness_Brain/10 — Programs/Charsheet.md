---
type: program
program: charsheet
status: active
cursor: "2026-08-29 — one shared character library FULLY LIVE; two full 8-way runs complete (moss golem staged, fire imp one-shot); the 3-defect slicer wave + 4 operator-found defects fixed and pushed both repos; Plan H (8-way) CLOSED 2026-08-27. Open: efficiency audit rulings R-1/R-2/R-3 (72% overhead, root = per-persona preload gap); 3 owner decisions (CharaPayload tier, boundary exemption, ocw fixture); the refactor's C1 lane splits pipeline.py and draft.py."
tags: [program/charsheet, program]
---

# Charsheet

The character-sheet pipeline: an operator authors a character (concept, style), the draftsman produces a turnaround, rows, states and thumbs, the sheet is validated (mirrored-art detection, palette) and composed, and the launcher renders the payload. `agent/charsheet/` + `hermes harness characters …` + the payload contract.

> [!info] Cursor
> `cursor::` see frontmatter.

## Where the truth lives

- Source: `agent/charsheet/pipeline.py` (run, `validate_sheet`, `detect_mirrored_art`), `draft.py` (`CharacterDraft`: `create`, directions, rows, `add_state`, thumbs, `compose`, `status_payload`), `palette.py`, `revisions.py`; CLI in `hermes_cli/harness.py` (`_cmd_characters_*`, moving to `harness_parts/characters_commands.py` in the refactor's H2 lane).
- Contract with the launcher: `hermes_cli/charsheet_payload_contract.py` → `scripts/dump_payload_contract.py` → `tests/fixtures/charsheet_payload_contract.json`; vendored in the launcher at `tool/charsheet_payload_contract/`. **A removed key is the dangerous half** (three moves landed blind before the gate: `handednessAccepted` added and threw everywhere, `cardSafe` removed, the conditional `sheet` slot).
- Skill: `docs/agent-runtime-harness/harness-skills/harness-charsheet-authoring/SKILL.md`.
- Plans: `planned/charsheet-turn-efficiency-2026-08-29.md` (the 72 % overhead audit), `archive/charsheet-add-state.md`.
- Shared library and the 8-way runs: session memory `project_shared_character_library`, `project_charsheet_8way` (graduate the standing facts here when the rulings close).

## Facts an agent forgets

- Stage C proof for a sheet is a screenshot through the launcher's MCP surface, not a unit test — `harness-qa-verdict` says when it is required.
- The serve's cross-persona `HERMES_HOME` prewarm bleed was found by Stage C of Plan H (top finding, filed in the launcher's queue).
- MEDIA lines de-mangle `\t`; silent QA-card verbs and the even-slot thumb sever were operator-found defects — the reply-contract skill amendment is live-verified.
