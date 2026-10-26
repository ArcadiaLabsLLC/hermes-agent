# Planned — the general todo: one Work authority, every surface a view (RT-GENERAL-TODO-PLAN, 2026-10-25)

**Owner domain:** transport and wire ([03-transport-and-wire.md](../03-transport-and-wire.md) § Native Work
methods), the office and board ([06-office-and-board.md](../06-office-and-board.md) § The board).
**Status:** RULED 2026-10-25 (lane w1025b-h-misc, by the wave brief's "go with recommendations"); G1 and G2 BUILT 2026-10-26 (lane w1026a-h-b); build rows
filed in §5. **Read:** hermes `origin/main` `eed79e6933` — `agent_runtime/work/` (`WorkScope`, the five
`runtime.work.*` methods), `agent_runtime/work_store/` (the default brain, `normalize_default_brain`), and
the naming spec [naming-and-address-map-2026-10-25.md](naming-and-address-map-2026-10-25.md) § The board.

## 0. The owner's words

- "our future general todo system will also be displayed there" — the Mission Board — "and its not only
  going to be displayed in the mission control" (2026-10-25).
- "our brains todo is meant to be displayed in the mission board" (2026-10-25).

## 1. What is true today

- A Work owner is a WORKSPACE (`agent_runtime/work/model.py::WorkScope`): its todo board is the brain queue
  notes of every repo slot it binds, read from the tip by `runtime.work.list`, written through hermes' own
  worktree, one row = one line with an ID (Harness ADR 0011 § Row grammar).
- A workspace with no repo folder gets a machine-local DEFAULT brain
  (`agent_runtime/work_store/default_brain.py`); its rows move into the first bound repo brain once.
- Readers: the Mission Board's Queues view (launcher `MC-WORK-W4-BOARD`) and the Intelligence Projects TODO
  preview (launcher `COMP-PROJECTS-TODO-PREVIEW-OBSERVE`, gated on `RT-WORK-OBSERVE-MANIFEST-PARAMS`).
- Two different things share the word and stay separate: upstream's `todo` toolset (an agent's in-session
  checklist, gone with the session) and the messaging `todolist` content (a backend-owned chat attachment).

## 2. Decisions (each `Decided (plan):`, ruled with the plan)

1. **A general todo is a Work row on a Work board — not a new store.** Decided (plan): the general todo
   reuses the row grammar, IDs, statuses and the `runtime.work.*` verbs. A second store for "personal"
   todos would be a second authority for one fact (a thing to do), which is the shape this repo retires.
2. **Three board kinds, one owner type.** Decided (plan): `WorkScope` grows a `kind` —
   `workspace` (today: the repo brains a realm workspace binds), `personal` (one per operator per machine:
   a local-only brain under the namespace, never in a repo), `agent` (one per persona instance: its own
   list, a view filtered by `assignee`, NOT a separate note — an agent's todo is the rows assigned to it
   across the boards it can see). So only `personal` is new storage; `agent` is a filter.
3. **One authority on one machine: hermes.** Decided (plan): v1 authority is the local runtime's Work verbs.
   Cross-device is the multi-device runtime's job (a far install's board read through its own
   `runtime.work.list`, as `agent_chat_installs` reaches far rosters) — never a copy. The backend becomes
   the authority only for todos that must reach PLAYERS or devices with no runtime (the phone companion
   without a paired PC); that is §4, owner-gated.
4. **Every surface is a view.** Decided (plan): Mission Board, Intelligence Projects, Home and the phone
   companion all read `runtime.work.list` with a `kind` filter; none writes except through `runtime.work.*`.
   The launcher holds no todo state of its own.
5. **The in-session `todo` list may PROMOTE, never sync.** Decided (plan): an agent may turn an item of its
   upstream `todo` checklist into a Work row (`runtime.work.start` on its `agent`/`personal` board); the two
   lists are never mirrored. Messaging todolists are untouched.

## 3. Recommendation

Build §5 G1 (personal board) and G2 (agent filter) on hermes; the launcher's Home and Mission Board views
follow as launcher rows. Leave the backend half (§4) until the owner names a player-facing todo.

## 4. Owner-gated (not built)

- Backend-held todos for players / runtime-less devices: a backend Work mirror with one direction of truth.
  Recommend: defer until a player-facing todo exists; then the backend owns those rows and hermes reads
  them, never both writing.

## 5. Build rows

- hermes `RT-GENERAL-TODO-G1-PERSONAL-BOARD` — `WorkScope.kind` + the `personal` board (local brain under
  the namespace; `runtime.work.capabilities` advertises it).
- hermes `RT-GENERAL-TODO-G2-AGENT-VIEW` — `runtime.work.list` `kind=agent` filter by `assignee` across the
  boards the instance can see.
- launcher (filed by the orchestrator): Home + Mission Board read the `personal` / `agent` kinds through
  the existing Work bridge.
