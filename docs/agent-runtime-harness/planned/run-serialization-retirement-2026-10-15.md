# Retire process-wide run serialization so an approval wait blocks only its own root (design)

Status: PLAN — written 2026-10-15; owner approval owed. Row: runtime-queue,
"Retire process-wide run serialization before a human approval wait can be
independent of unrelated agent roots".

## In plain English

The serve runs every agent turn in one process, and a single lock lets only one
turn run at a time. That was done on purpose: each turn temporarily rewrites
process-wide settings (home folder, auth folder, working directory) and puts
them back after, which is only safe if nobody else is running. The cost: when a
turn stops to ask the operator "may I run this command?", **every other agent on
the machine waits too** until the human answers. This plan removes the reason
for the lock — the process-wide rewrites — and then shrinks the lock.

## Evidence (tree at `origin/main` 428e2b0dd09)

- The lock and why it is wide: `agent_runtime/profile_runner/workdir.py`
  `_WORKDIR_LOCK` (l.77) and its comment (l.60–76): `persona_profile_context`
  save/mutate/restores `HERMES_HOME`, `HOME`, `HERMES_AUTH_HOME`,
  `HERMES_AGENT_RUNTIME_ROOT`; `_agent_workdir` does `os.chdir` and sets
  `TERMINAL_CWD`.
- Held across the whole turn: `agent_runtime/profile_runner/execute.py`
  `AgentRunExecution.scopes` (l.507–550), lock first, MCP teardown last.
- The pinned raw-env readers that keep the writes alive:
  `agent_runtime/profile_context.py` l.315–345 — in-process plugins reading
  `HERMES_HOME` raw (`plugins/memory/openviking`), spawn sites inheriting
  ambient `os.environ`, `HOME` for `expanduser`/`Path.home()` (no context
  hook), `HERMES_AGENT_RUNTIME_ROOT` for the legacy terminal envelope.
  `HERMES_AUTH_HOME` is already mirrored into a ContextVar.
- The approval wait itself is upstream's queue (`tools/approval.py`), entered
  through `agent_runtime/session_controls.py::session_approval_scope`.
- Prewarm already works around the lock (`_ACTIVE_RUNS` counter, workdir.py).

## Target shape

- **One run context, no process writes.** Home, auth home, runtime root and cwd
  live in ContextVars set by `persona_profile_context(export_env=False)` for
  every in-process reader; every spawn builds its env from the context through
  `tools/environments/local.py`'s factories (already bridge the override); the
  terminal envelope reads the context, not `HERMES_AGENT_RUNTIME_ROOT`.
- **No `os.chdir`.** Tools resolve relative paths against the context cwd;
  spawns pass `cwd=`.
- **`HOME`** (the one write with no context hook): on Windows it is not the
  home authority (USERPROFILE is) — measure; on POSIX, readers via
  `expanduser` in fork code get a context-aware helper, and upstream readers are
  listed for a door.
- **Lock shrinks** to a per-root lock (`RootRunLock(root_id)`) keeping one turn
  per chat root, which the conversation model needs anyway.

## Owner decisions (recommendation first)

1. **Context-scope the readers (recommended) vs a child process per root.** A
   process per root isolates everything for free but multiplies memory and cold
   starts, and duplicates the compute-host design. Context-scoping is the end
   state the code comments already name.
2. **Interim "park" step?** A turn could release the lock while blocked in the
   approval wait and re-enter its profile context on wake. Recommend **no** —
   other threads of the parked run (background spawns, MCP pumps) would see the
   wrong env; it trades a visible stall for an invisible race.
3. **Upstream readers.** Recommend: fork code is context-scoped in this program;
   upstream raw readers (`openviking`, `expanduser` sites) go into one door draft
   for the owner's posting sitting, and the `HOME` write stays until it lands.
4. **Proof bar.** Recommend a live two-root proof is required (decision below,
   S5), not only unit tests.

## Slices (build order)

- **S1 — census** (report): every fork read of the four env vars and of
  `os.getcwd()`/relative-path opens on the turn path; output a table in a field
  note. No code change.
- **S2 — spawns from context.** Every fork spawn site builds env via the local
  factories. Killing mutation: one site reverts to `env=os.environ` → a test
  running two contexts in two threads and spawning `python -c "print(env)"`
  sees the other root's home → red.
- **S3 — terminal envelope + runtime root from context.** Killing mutation:
  read `HERMES_AGENT_RUNTIME_ROOT` again → the two-thread envelope test reds.
- **S4 — remove `os.chdir`**; cwd from context. Killing mutation: restore the
  chdir and run two roots concurrently → a relative-path write lands in the
  wrong root → red.
- **S5 — shrink the lock** to per-root; `export_env=False` everywhere except the
  `HOME` write (still serialized behind a narrow lock until the upstream door).
  Live proof: two personas, root A blocked on an approval, root B completes a
  turn; profiles, stores and command envs never cross (event log + store
  diffs recorded).

## Blast radius

`agent_runtime/profile_runner/`, `agent_runtime/profile_context.py`, the
terminal envelope, every fork spawn site (S1 counts them), MCP admission scope.
High risk path: credentials and homes. Each slice lands alone.

## What it retires

Process-wide serialization of agent turns, the prewarm stand-down workaround's
reason to exist, and the lost-update race the comments guard against.
