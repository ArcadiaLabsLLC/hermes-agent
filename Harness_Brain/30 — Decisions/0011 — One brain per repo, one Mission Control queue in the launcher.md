---
type: adr
id: 0011
status: amended-by-0012
date: 2026-09-21
tags: [adr, brain, process]
---

# 0011 — One brain per repo, one Mission Control queue in the launcher

> [!summary]
> This vault (`Harness_Brain/`) is the hermes fork's child brain, shaped like `Launcher_Brain/` and routed from the same parent. It adopts the launcher's ADR 0025 work-tracking rule (one master TODO of pointers, one queue per DOMAIN, reports split on arrival, claim-before-start). **Mission Control's queue stays in the launcher's vault and covers both repos** — the domain is the surface, not the checkout. This vault holds exactly one queue, [[fork-hygiene-queue]], for the repository as a fork.

> [!note] Amended 2026-09-22
> The queue clause is superseded: the hermes half of Mission Control is now [[runtime-queue]] in this vault, split by ownership — [[0012 — The hermes half of Mission Control is queued here, split by ownership]]. The rest stands.

> [!note] Amended 2026-10-18 — the row grammar is the launcher's, and lives here
> Owner decisions 2026-10-18: the launcher's queue-row grammar is canonical across the three repos, every row carries an ID, and `VERDICT` is retired in favour of `BLOCKED … owner decision` / `RULED`. The launcher's Mission Control Queues tab reads this vault's `type: queue` notes straight from the checkout, so a row off the grammar is invisible or mis-filed on the owner's board. § Row grammar below is the grammar's one home in this repo; `tests/tooling/test_work_queue_row_grammar.py` enforces it on every `type: queue` note under `Harness_Brain/`. The reference is the launcher's parser, `EterniaLauncher/lib/features/mission_control/work_queue/policy/work_queue_row_parser.dart`. Amended 2026-10-18 (Work W1): the optional assignee segment and engine-minted WORK-<6> IDs; the launcher's twin amendment is ADR 0025 "Amendment 2026-10-18b".

## Row grammar

Identical in the launcher, this repo and the backend; do not diverge.

- **One physical line per row:** `- **`<ID>` — <title>** · <segment> · …` (no `- [ ] ` checkbox).
- **`<ID>` is required**, uppercase `^[A-Z0-9][A-Z0-9._-]*$`, unique across this vault's queues. Mint a domain-prefixed short slug (`RT-…` in [[runtime-queue]], `FORK-…` in [[fork-hygiene-queue]], `DEAD-…` in [[dead-code-burn-down-queue]]); never renumber an existing ID.
- **Segments** are separated by ` · ` outside backticks. A pointer is a backticked repo-relative path, optionally `path:line` or `path::symbol`; another repo's file carries its repo prefix.
- **EXACTLY ONE status segment:**
  - `READY <date>` — a lane can start it now;
  - `BLOCKED <date>: <reason> — <detail/pointer>`, reason ∈ {`owner decision`, `owner sitting`, `backend`, `hermes`, `launcher`, `upstream`, `another lane`}. `backend` / `hermes` / `launcher` name the sibling repo the row waits on; `upstream` means only a blocker outside the three repos (NousResearch, a provider, a library); `another lane` is a lane in this repo. A live serve, the Windows box or an idle workstation is `owner sitting`. **A lane-blocked row names the row it waits on, so it cannot sit in limbo** (owner, 2026-10-18): for `backend`, `hermes`, `launcher` and `another lane` the text after ` — ` opens with the blocking row's ID in backticks — `BLOCKED <date>: launcher — `MC-SOME-ROW` <detail>`. A same-repo (`another lane`) ID must be a row in this vault unless the repo is named right after it. `upstream`, `owner decision` and `owner sitting` need no ID. The rows that predate this rule are a shrink-only ceiling (`BLOCKER_ID_CEILING` in the lint);
  - `DEFERRED <date>: <why>`;
  - `NEEDS PLAN <date>: <what the plan must decide>` — the honest default for unscoped work.
- **An open owner question** is `BLOCKED <date>: owner decision — <question> · Recommend: <answer>`. Once answered it becomes a `RULED <date>: <decision>` record beside a real status.
- **Records beside the status:** `RULED <date>: <decision>`, always dated; write new ones with the colon straight after the date (`RULED 2026-10-15: owner — …`), which is the form the board reads as a ruling (older `RULED <date> owner: …` records are kept as written). `VERDICT`, `DESIGN`, `OWNER`, `PLAN` and `VERIFY` are not statuses and never open a segment.
- **Claim:** `**TAKEN <date> <who>**` on the row's own line — after a bare `READY <date>` as its own ` · ` segment. A claim, never a status.
- **Assignee (amendment 2026-10-18, Work W1):** an optional segment `assignee: persona:<token>` names who the
  row is FOR — `<token>` is a persona instance id (this instance) or a persona id (any instance of that
  persona); the token is `[A-Za-z0-9_.-]+`. At most one such segment; a segment opening `assignee:` in any
  other shape is a defect. A claim by the engine is `**TAKEN <date> persona:<instance_id>**`; a claim by a
  lane keeps its lane name. The assignee is not a status and does not change the status.
- **Engine-minted IDs (amendment 2026-10-18, Work W1):** a row the Work engine appends is `WORK-<6>` —
  `WORK-` plus six base32 characters (`[A-Z2-7]{6}`), minted by the engine, unique within the brain like
  any ID. Lane rows keep their domain prefixes; nothing existing is renumbered.

## Context

The hermes side had no brain: standing rulings lived in one operator's per-machine session memory (~50 entries), cursors in plan headers, and the launcher's Mission Control queue already carried hermes rows. Opening a second Mission Control queue here would create the "two copies of a moving list" defect ADR 0025 retires. The operator asked for the vault on 2026-09-21 ("populate the new obsidian brain … with our fork specific logic").

## Decision

- Folders mirror the launcher: `00 — Maps`, `10 — Programs`, `20 — Active Initiatives`, `30 — Decisions`, `40 — Cross-Brain`, `50 — Agent Handoffs`, `60 — Operations`, `Templates`.
- Truth routing: the canon (`docs/agent-runtime-harness/`) and the fork contract (`docs/downstream-development.md`) own facts; this vault owns navigation, WHY, cursors, handoffs and gotchas; session memory is scratch that graduates here.
- Cross-repo cites use a repo prefix in backticks, never a link (the launcher's dead-link gate reads a bare `docs/…` token as its own; this repo's `doc_cite_adjacency` walks `docs/` only, but the convention is shared).
- The vault is committed (like `Launcher_Brain/`); `.obsidian/` is runtime state, read only for Obsidian setup.

## Consequences

- The launcher's brain owes a `Harness Brain Pointer` (queue row). The parent brain routes to hermes only through two contract notes today.
- Runtime findings are filed in the launcher's queue from a hermes session — cross-repo, on arrival.

## Alternatives

A brain in the parent for both (rejected: repo-relative links break across machines); no brain, memory only (rejected: per-machine, per-operator, invisible to lanes).
