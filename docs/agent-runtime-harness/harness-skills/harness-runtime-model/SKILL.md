---
name: harness-runtime-model
description: Hermes Agent Runtime mental model AND the operating manual for Mission Control — personas / instances / chats / graph / board / office, the first-class commands to view and operate them, helper delegation without context bloat, and (in references/) the live operating loop: place-message-delete a QA instance, read MCP admission receipts, triage stalled turns, capture Stage C proof, preserve evidence. Use instead of low-level DB/Python/scripts.
metadata:
  hermes:
    surfaces: [mission_chat]
    modes: [standard]
    load_policy: required_preload
---

# Harness Runtime Model

**Chat is the only lane.** There is no goal, task, mission plan, stage graph, daemon,
worker, run, proof gate, lane, or swarm certification (removed 2026-07-30; that memory
is stale). A request arrives as a chat turn on an existing persona instance, you do the
work with your own tools in that turn, and you answer in that same chat. Nothing
dispatches you, and nothing gates your reply.

**Model:** **persona** = a profile-backed agent definition (data, not hardcoded).
**persona instance** = a durable placement of it (`personainst_<role>_agent_<hash>`).
**chat session** = the durable root a turn runs on; an instance points at one
operator-chat root and can hold several. An unknown role is carried, not rejected,
and never filters your tools.

**The runtime agent graph is a picture, not a program.** `flow_graph.py` stores one
operator-authored document per owner (`graph_id: runtime:<owner>`) and reconciles
`persona_instances[].steered_by` from it — *who steers whom*. **It enforces nothing,
routes nothing, picks no next agent, creates no instances and binds no work.** Never
answer "what runs next?" from it — nothing runs next.

**Two messaging paths, and only two:** `mission-chat message` (operator/CLI; the live
serve runs it, `--in-process` forces this shell) and `agent_chat_send` (agent → agent).
There is no assignment surface.

**The Mission Board is planning state only.** A card never starts, routes, or changes anything.

`hermes` == `python -m hermes_cli.main`. There is no `hermes harness runtime`
command. Always `--json`. Never use raw DB / Python / ad-hoc scripts / hand-edited store files to inspect or mutate.

## Operating loop — load the reference that matches the task

Operating detail lives in `references/`, fetched with `skill_view` — read the one
that matches BEFORE acting:

- `references/operations.md` — **the operating loop**: roots and homes, start
  checklist, the fresh-instance-per-QA recipe, MCP admission receipts, stalled-turn
  triage, evidence, report shape. Read before operating live.
- `references/persona-chat.md` — operator channel, the new-chat contract, turn
  identity, `agent_chat_send` and the relay policy.
- `references/proof.md` — Backend/Launcher proof commands and the Stage C MCP recipe.
- `references/debugging.md` — snapshot parity envelope, UI⟷harness divergence classes.
- `references/model-notes.md` — the why behind the sections below.

## The work contracts — load by role and order size

Separate skills, never folded in here (detail: `references/model-notes.md`):
`harness-dev-delivery` (ALWAYS-ON for every dev turn) · `staged-deep-audit-delivery`
(load on a staged multi-stage order; wraps dev-delivery) · `eternia-writing-plans`
(plan documents) · QA turns load `harness-qa-verdict` INSTEAD of the dev contract —
QA judges work, never patches code.

## Non-negotiables

- Do not trust an agent summary as proof, and never claim something works from code
  inspection. Run it, and cite the receipt (tool-trace row, artifact path,
  `client_message_id`/`turn_id`, `mcp_calls_spent`).
- Every `harness_query` answer names its `observer` (store root, home, serve pid or
  `external_cli`): read it first. Roster/office/board/graph answers are home-independent;
  **admission, model, and profile answers are not** — the launcher's serve child runs
  under `profiles\base` or the persona's bound profile, not your CLI's `alice`. Say
  which home produced any receipt you report (`references/operations.md`, "Roots").
- **A claim cites its receipt.** "I have MCP access" says which level it reached:
  configured/admitted (`harness_query` `instance` → `mcp`, resolved now under its home) or
  EXERCISED (a turn's `profile_timing.mcp_calls_spent` > 0, or the `mcp__*` call's trace
  row) — without the last, say "admitted, not exercised". "There is a (live) QA session"
  names ids `live_qa` returned VERBATIM — never `session_search` (history, not state), an
  id cut from a chat root, a grep hit, the Launcher window; a QA task takes a FRESH instance.
- **Archive-never-delete**, including the verb named `delete` (a full alias of
  `retire`, which archives and preserves chat history). There is no hard-delete verb
  to reach for.
- Visual claims need Stage C proof captured through the MCP path in
  `launcher-mcp-operations` — the only sanctioned one. If it is blocked, record the
  exact blocker and still attach command/code proof. Never kill Tony's live Launcher.
- **A screenshot request is a `launcher_qa` call, never a build.** A screenshot of a
  tab is ONE call, `mcp_launcher_qa_open_app_tab(tab: <tab>, screenshot: true)`: it
  attaches, navigates, settles and captures, and is already in your tool list (no
  `tool_search`); `mcp_launcher_qa_screenshot_window` is "what is on screen now" in an
  ALREADY-attached session. A typed blocker (`app_not_attached`, `launch_stale_stagec_copy`,
  …) is REPORTED, never cleared with `flutter build windows`. A build runs in the background
  in your own worktree (`harness-dev-delivery`, "Launcher Commands").
- **QA sign-in is REAL**: `get_auth_state` first; a guest → `launch_or_attach` with
  `browser_login:true` (stored QA account). `dev_login` = chrome only. A `launcher_qa` reply that opens
  "Note: the launcher QA tool is out of date …" means its answers may be wrong: relay it
  to the operator verbatim ("… was out of date … rebuilt itself" is informational).
  Both: `references/proof.md`.
- Image lines pass through UNTOUCHED — reproduce every `MEDIA:<absolute image path>`
  line, and every bare absolute screenshot path, VERBATIM on a line of its own, in
  your own reports and in every relay, quote, and summary. Canonical rule:
  `launcher-mcp-operations` SKILL.md, "Screenshot capture and delivery".
- Never write raw secrets into SessionDB (recall-reachable). Do not overwrite
  unrelated local changes.
- If agents loop, stall, or take the wrong proof path, that is a Harness gap: name
  the command, the typed error, and the missing receipt. "It hung" is not a report.

## View

| See | Command |
|---|---|
| runtime health / diagnostics | `hermes harness status --json` · `hermes harness doctor --json` |
| configured agent definitions | `hermes harness agent list --json` |
| roster · one instance + its MCP resolution · an instance's chats with hot/busy/cold · is there a live QA session | tool `harness_query` (`question=roster\|instance\|sessions\|live_qa`) · CLI `hermes harness query <question> [id] --json` |
| an instance's resolved tools and blocks | `hermes harness persona tool-diff <persona_id> --json` |
| a chat session's transcript | `hermes harness persona chat history --session-id <root> --json` |
| stored agent-graph documents | `hermes harness flow list --json` · `hermes harness flow show <graph_id> --json` |
| planning boards and cards | `hermes harness board list --json` · `hermes harness board show <board_id> --json` |
| realms / workspaces / Projects (repo slots: `references/operations.md`) | `hermes harness realm list --json` · `workspace list --json` · `project list --json` |
| aggregate read-model (what the Launcher renders) | `hermes harness snapshot --json` — evidence capture only, **never a lookup** (~900 KB, tens of seconds a call) |
| shared skills substrate | `hermes harness skills inventory --json` · `skills catalog --json` |
| level agents shown in Mission Control | Stage C MCP `mcp_launcher_qa_get_buttons` with `scope=mission_control.agent` |
| compact Mission Control graph probe | Stage C MCP `mcp_launcher_qa_get_widget_state` with `widget=mission_control.graph` |

**Not for level agents:** `status.agents` and `agent list` show
configured/installed Harness agents, not what is placed on a level — use the `roster` and
`mission_control.agent` rows above.

## Removed — unlearn these

Removed 2026-07-30 — do not reach for them or repeat them as live (detail:
`references/model-notes.md`): `hermes harness task show <id> --json` and every `task`
verb; `blueprint list/run --bind` and the `.mission_plan` field (`.stages`, `.edges`,
`.agent_topology`); the old default graph **Neko scope → Backend Dev → Launcher Dev**
and the rule that **QA is a node only if the selected blueprint binds it**; `run show`,
`proof list`, `worker list`, `lane list`, `swarm status|enable`, `tick`,
`run-until-settled`; the `mission_goal_create` tool and `--allow-mission-goal`; the
snapshot's goal, stage, run, proof and incident sections — gone, not missing.

## In-turn tools

<!-- BEGIN GENERATED: harness_core inventory -->

36 tools · generated from the registry by `scripts/emit_harness_tool_inventory.py` · do not edit by hand. If a tool exists for it, the tool is the answer; the full table with descriptions is `references/tool-inventory.md`.

| toolset | tools | use it for |
|---|---|---|
| `agent_chat` | `agent_add_instance` · `agent_chat_dispatches` · `agent_chat_installs` · `agent_chat_log_path` · `agent_chat_open` · `agent_chat_send` · `agent_chat_threads` · `harness_query` | teammates: list, message, read, dispatches, transcript path; `harness_query` for roster / instance / sessions / live QA lookups |
| `board` | `board_card_add` · `board_cards` | record follow-up work — planning state only |
| `clarify` | `clarify` | ask the operator a question mid-turn |
| `delegation` | `delegate_task` | hand a bounded subtask to a helper with fresh context |
| `terminal` | `process_manage` · `terminal` | run commands and manage background processes |
| `file` | `patch` · `read_file` · `search_files` · `write_file` | read, write, patch and search files |
| `web` | `web_extract` · `web_search` | search the web and pull a page's content |
| `browser` | `browser_vault` | stored-credential browser sign-in (vault) |
| `browser-cdp` | `browser_cdp` · `browser_dialog` | raw CDP and dialog handling for the same browser |
| `browser-use` | `browser_exec` | drive a real browser: navigate, click, type, read, screenshot |
| `skills` | `skill_manage` · `skill_search` · `skill_view` · `skills_list` | find, read and author skills |
| `memory` | `memory` | durable profile memory |
| `todo` | `todo_list` | your own in-turn checklist |
| `session_search` | `session_search` | search your own past sessions |
| `vision` | `vision_analyze` | analyze an image |
| `code_execution` | `execute_code` | run code in the sandbox |
| `course` | `course_checkout` · `course_commit` · `course_pull_request` | author a course: checkout, commit, PR |

<!-- END GENERATED: harness_core inventory -->

## Operate

**Tools first.** If a tool exists for the row, the tool IS the answer — it runs
inside your turn, mints nothing, and costs no subprocess. A terminal call for a row
that names a tool is a navigation failure: report it (the command you reached for,
the tool you should have used) rather than quietly shelling out. The CLI column is
for rows where no tool exists.

| Do | In-turn tool (first choice) | CLI (only where no tool exists) |
|---|---|---|
| see who your teammates are / which instances you can reach | `agent_chat_threads` (read-only, no mint; `@install/…` reaches a far install) · `harness_query` for the roster, a chat's state, live QA | — |
| see which other installs (machines) you can reach, and who is on them | `agent_chat_installs` (read-only; `install=` fetches that install's roster) | the HUD's `Installs` line already names them — this is the fresh read |
| message a teammate and get the reply in this turn | `agent_chat_send` (`wait=true`; `wait=false` to dispatch and continue) | `hermes harness mission-chat message …` is the OPERATOR's path, not yours |
| read what a teammate said | `agent_chat_open` (tail; `@install/…` reads a far thread, `session_id` required there) · `agent_chat_log_path` (full transcript path, then `read_file` / `search_files`) | — |
| see your background dispatches | `agent_chat_dispatches` | — |
| track follow-up work | `board_card_add` · `board_cards` — planning state only | `hermes harness board card add …` (operator path) |
| ask the operator a question | `clarify` | — |
| hand a bounded subtask to a helper with fresh context | `delegate_task` | — |
| continue a chat root · mint a new one | — | `hermes harness persona instance open-chat` (`--session-id <root>`, or `--new-session --idempotency-key <key>`) |
| steer an in-flight turn · abandon an outcome-unknown one | — | `hermes harness mission-chat steer` · `mission-chat turn-resolve --action abandon` |
| load a skill on the next turn | — | `hermes harness mission-chat queue-skill` |
| re-route a steering edge · replace a whole graph document | — | `hermes harness persona instance steer` · `flow set` (never creates instances) |
| return a child's bounded summary to a parent chat | — | `hermes harness persona instance return-summary` |

Every flag of the CLI rows: `references/operations.md`, "CLI verbs with no tool"; the
complete inventory with descriptions: `references/tool-inventory.md`.

## Persona chat continuity

Message the on-level instance; `session_id` is the stable root and Hermes mints every new one.
On `unknown_chat_session`, `chat_turn_outcome_unknown` or `chat_turn_provider_refused` never
retry the same turn: each has its own repair in `references/operations.md`, "Diagnosing a
stalled or failed chat turn" (the why: `references/persona-chat.md`).

## Delegation — helpers without context bloat

Recipe and flags: `references/operations.md`, "Delegation"; why: `references/model-notes.md`.

- Message ONE helper at a time; the message is the whole handoff (objective, stop
  condition, parent session id). One unanswered approval is never a stop condition.
- **Never slurp** the helper's transcript, logs, or reasoning — carry pointers, and
  return with `persona instance return-summary` (bounded, records `returned_to`).
- Intervene only on a stall, a block, or scope drift, on the SAME chat root.
- **A helper sent to a queue row gets a lane name of its own, in the brief**: a
  `wNNNNx-<slug>` (date, wave letter, slug: `w1120a-qaclaimwin`) or the helper's instance handle
  without the `@` — never its bare persona id (`dev`), shared by every instance, and never
  `persona:<id>` (that hands the row to the Work engine). With none to give, the brief says
  "pick a `wNNNNx-<slug>` lane yourself, without asking". Give it the claim line,
  `dart tool/queue/task.dart --claim <ID> --as <lane> --tree <its own worktree> --push`, run
  from the repo's primary checkout with a timeout of at least 300 s, and the worktree folder:
  OUTSIDE every primary checkout (EterniaLauncher's sibling `EterniaLauncher-worktrees/`,
  hermes's `.worktrees/` beside the clone). "TAKEN by <lane>" under that lane is your helper's.
- **A brief follows the repo's own rules file, never your paraphrase of it.** The rules of each
  folder you work in are in your context under `## <slot> — CLAUDE.md` (or `AGENTS.md`) — the
  folders sheet's checked folders, with its CLAUDE.md / AGENTS.md switch. Brief against that
  text. A finished queue row is CLOSED, which archives it — in EterniaLauncher
  `dart tool/queue/close_row.dart <ID> --done <sha> --commit` — never deleted: never tell a
  helper to delete a row. No `## <slot> —` section in your context means no folder is checked
  for you; say so instead of guessing the repo's rules.
