# 10 — Operator command directory

**Start with the task, not the subsystem.** This directory covers the Hermes
command surface behind Launcher Mission Control. It is not a Launcher keyboard
palette and does not claim that QA MCP can attach to a normal Launcher window.

- [All commands and flags — generated from the live parser](reference/harness-commands.md)
- [Architecture and contracts](00-index.md)
- [In-turn agent tools](harness-skills/harness-runtime-model/references/tool-inventory.md)

The generated reference owns syntax. This page owns recipes, scope and cautions;
the linked domain docs own behavior. CLI declarations live in
`hermes_cli/harness_parts/parser/`; `hermes_cli.harness.build_parser` assembles them.

## Before you start

**READ** means inspect; **WRITE** changes durable state; **EXECUTE** starts or
steers agent work and can incur provider charges. This classification applies to
the recipes below, not automatically to every command under a command group.

Replace `WORKSPACE_ID`, `PERSONA_ID`, `INSTANCE_ID`, `SESSION_ID`, `MAP_ID` and
`UNIQUE_REQUEST_ID` with values you discovered, not guessed IDs. Examples are
single-line commands usable from Bash or PowerShell. Do not paste WRITE/EXECUTE
examples until you intend that action. For help, append `--help` at any depth.

Profile and runtime store are different: a profile chooses configuration and
authentication; the runtime root chooses the world being inspected or changed.
Check `snapshot.parity.resolution.store_root` and `snapshot.parity.profile` when
CLI and Launcher disagree. Use an explicit workspace on writes. A successful
write is followed by a read of the exact target; stored state alone is not proof
that a running Launcher has rendered it. See [data ownership](02-runtime-data-and-shapes.md)
and [transport](03-transport-and-wire.md).

## Inspect a level — READ

```bash
hermes harness workspace list --json
hermes harness snapshot --json
hermes harness office show --workspace WORKSPACE_ID --full --json
```

- `workspace list`: discover workspace IDs and realm membership.
- `snapshot`: `active_workspace_id` / `active_realm_id` identify runtime selection;
  they are not a direct read of a particular window's current UI selection.
- `office show --full`: placed actors, unlike `agent list` (definitions) or
  `persona list` (instances). Read `actor_defs[].persona_instance_id` and
  `actor_defs[].item_defs[]`; agent items have `kind: agent`, `display_name`, and
  `position: [x, y]`. Other items may be scenery, not agents. Without `--full`,
  `actors` is a count. An unauthored office can omit `actor_defs` entirely.
- Do not report a complete inventory when `actors_truncated` or
  `actors_unreadable` is nonzero. `conflict_actor_keys` identifies conflicted actors.

**Launcher counterpart:** Mission Office scene. [Office contracts](06-office-and-board.md)
own actor/item shapes and the `runtime.office.*` RPC family.

## Choose and place an agent — READ, then WRITE

```bash
hermes harness agent list --json
hermes harness agent create --persona PERSONA_ID --workspace WORKSPACE_ID --display-name "Launcher Dev Agent" --idempotency-key UNIQUE_REQUEST_ID --json
hermes harness office show --workspace WORKSPACE_ID --full --json
```

Choose the persona from `agent list` (the configured Launcher Dev persona is
commonly `dev`; the display name does not select the persona). `agent create`
creates the instance, chat root and office placement together. Omit `--pos` for
a runtime-selected free slot, or pass `--pos 3 -2` for an intentional XY position.
Use the same idempotency key only for a retry of the same request, a fresh one for
a new placement. Omitted `--skill` inherits the persona's skills; repeat
`--skill SKILL_ID` only to supply an explicit assignment.

The response names `persona_instance_id`, `default_chat_session_id`, `actor_key`
and `position`. Verify that exact instance in the office readback. **Placing does
not send it work.** `persona instance create` is a lower-level roster/recovery
surface, not a substitute for this complete placement command.

**Launcher counterpart:** agent drop / Add new instance to level.
**RPC:** `runtime.agent.create`. See [unified create](06-office-and-board.md) and
[chat/create lifecycle](05-chat-turn-lane.md).

## Rename, move or retire — WRITE

### Rename the instance

```bash
hermes harness persona instance update-profile INSTANCE_ID --display-name "Launcher Dev — UI" --json
hermes harness persona show INSTANCE_ID --json
```

This edits the instance profile; verify its name there. Do not assume every
cached scene-item label changed merely because the instance profile did.
**Launcher counterpart:** agent profile editing; the instance/profile contract
lives in [system architecture](01-system-architecture.md).

### Move an existing placement (advanced)

```bash
hermes harness office show --workspace WORKSPACE_ID --full --json
hermes harness office actor-upsert --workspace WORKSPACE_ID --persona-instance-id INSTANCE_ID --actor-json actor.json --expect-revision 3 --dry-run --json
```

`actor.json` is an actor object containing `persona_id`, `persona_instance_id`
and `items`, **not** the complete `office show` envelope. Preserve the target's
item IDs and other fields, changing only the intended item's `position`.
The readback calls this collection `item_defs`; the write payload calls it
`items`. Replace example revision `3` with the target **actor's** current
revision, not the surface revision. Inspect the dry-run before removing
`--dry-run` to apply; re-read the same office afterward. On a revision conflict,
read and reconcile rather than forcing. Do not add `--resurrect` or
`--allow-class-key` as an error workaround.

**Launcher counterpart:** scene move. **RPC:** `runtime.office.upsert`.
The actor payload and concurrency contract live in [Office and board](06-office-and-board.md).

### Retire a placed agent

```bash
hermes harness agent retire INSTANCE_ID --reason "Operator removed placement" --json
hermes harness office show --workspace WORKSPACE_ID --full --json
```

Archive operation, not permanent history deletion: it retires the instance and
archives its bound office actors. Confirm the intended instance is absent from
the active placements and inspect any reported per-actor failures.
**Launcher counterpart:** remove placed agent. See [retirement](06-office-and-board.md).

## Chat with an instance — WRITE / EXECUTE

Create a new empty session on the existing instance (**WRITE**, no agent turn):

```bash
hermes harness persona instance open-chat --persona PERSONA_ID --persona-instance-id INSTANCE_ID --new-session --idempotency-key UNIQUE_REQUEST_ID --json
```

Use the returned session ID for the next commands. Opening selects/binds a chat;
it does not run a turn. The Launcher counterpart is its new-chat/session selection.

Send work (**EXECUTE**):

```bash
hermes harness mission-chat message --persona PERSONA_ID --persona-instance-id INSTANCE_ID --session-id SESSION_ID --client-message-id UNIQUE_REQUEST_ID --message "Inspect the requested change and report findings." --json
```

Capture the response's turn/session identity. Accepted or queued is not completed;
read the transcript and runtime state. A provider refusal is not a successful turn.
Do not blindly retry an outcome-unknown response; see [chat error handling](05-chat-turn-lane.md).

Read the transcript (**READ**) or steer an in-flight turn (**EXECUTE**):

```bash
hermes harness persona chat history --session-id SESSION_ID --json
hermes harness mission-chat steer --session-id SESSION_ID --client-message-id UNIQUE_REQUEST_ID --message "Limit this to inspection; do not edit." --json
```

**Launcher counterpart:** Agent Console / Operator Channel. These are the operator
CLI doors to the canonical chat lane. In-model agents use `agent_chat_send` when
available, not a new subprocess. [Chat turn lane](05-chat-turn-lane.md) owns the contract.

## Environment, maps and folders — READ / WRITE

Inspect (**READ**):

```bash
hermes harness level show --workspace WORKSPACE_ID --json
hermes harness map list --json
hermes harness map show --map MAP_ID --full --json
```

The level document describes the environment; the office describes placed actors;
the map catalogue contains named scene documents. They are not interchangeable.
**Launcher counterpart:** level/map authoring. See [Office and board](06-office-and-board.md).

Preview changes (**WRITE recipes, dry-run only as shown**):

```bash
hermes harness level set --workspace WORKSPACE_ID --document level.json --dry-run --json
hermes harness office set-folders --workspace WORKSPACE_ID --folders "Agents,Desks,Review" --dry-run --json
```

Use a valid document exported/read from the level contract, not an invented
payload. Inspect the preview, then apply intentionally by removing `--dry-run`.
For a level replacement, use `--expect-sha256` with the stored-byte hash (or
`none` when creating only if absent). For folders, use `--expect-revision` with
the current surface revision. These replace state, not append patches; preserve
unrelated contents. Read back with `level show` / `office show --full`.

## Diagnose the connection and runtime — READ

```bash
hermes harness status --json
hermes harness doctor --json
hermes harness observe --json
hermes harness work list --json
```

`doctor` is inspection **as shown**; repair flags change that scope. Inspect the
root/profile, typed errors and task-specific receipts instead of assuming an
empty panel means an empty runtime. [Observability](07-observability.md),
[boot/lifecycle](04-boot-and-lifecycle.md) and [transport](03-transport-and-wire.md)
explain the evidence. Never restart or reap the operator's Launcher merely to
attach a QA session. `stagec-smoke` QA attachment is not normal-window control.

## Keeping this directory current

The exact command inventory and help text are generated; recipes above are
hand-authored and their argument syntax is checked against the same parser.
From the repository root:

```text
python scripts/emit_harness_command_directory.py --write
python scripts/emit_harness_command_directory.py --check
python -m pytest -q -p no:cacheprovider tests/scripts/test_emit_harness_command_directory.py
```

Parser changes regenerate the reference in the same commit. Generation only
constructs parsers; it never executes the documented writes. Tests validate
example syntax, not credentials, resource existence or operational success.
The generated reference is a browsable CLI catalogue, not a new runtime/RPC
registry or a shipped Launcher command palette.
