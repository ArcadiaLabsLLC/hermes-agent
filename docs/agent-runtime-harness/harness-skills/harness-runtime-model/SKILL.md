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

**Two messaging paths, and only two:** `mission-chat message` (operator/CLI) and
the in-model `agent_chat_send` tool (agent → agent). There is no assignment surface.

**The Mission Board is planning state only.** A card never starts, routes, or changes anything.

`hermes` == `python -m hermes_cli.main`. There is no `hermes harness runtime`
command. Always `--json`. Never use raw DB / Python / ad-hoc scripts to inspect.

## Operating loop — load the reference that matches the task

Operating detail lives in `references/`, fetched with `skill_view` — read the one
that matches BEFORE acting:

- `references/operations.md` — **the operating loop**: roots and the `base` vs `alice`
  home caveat, start checklist, extra inspect/operate rows, the fresh-instance-per-QA
  recipe (create · office write · message · delete), MCP admission receipts,
  stalled-turn triage, evidence preservation, final report shape. Read before operating live.
- `references/persona-chat.md` — operator channel, the new-chat contract, turn
  identity, `agent_chat_send` and the relay policy.
- `references/proof.md` — Backend/Launcher proof commands and the Stage C MCP recipe.
- `references/debugging.md` — snapshot parity envelope, UI⟷harness divergence classes.
- `references/model-notes.md` — the explanation behind the work contracts, the
  removed surface, chat continuity and delegation sections below.

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
- Check `.parity.runtime_root` and `.parity.profile` in `harness snapshot --json`
  before believing anything. Roster/office/board/graph answers are home-independent;
  **admission, model, and profile answers are not** — the launcher's serve child runs
  under `profiles\base` or the persona's bound profile, not your CLI's `alice`. Say
  which home produced any receipt you report (`references/operations.md`, "Roots").
- Use first-class harness CLI verbs. Never inspect or mutate runtime state with raw
  DB access, ad-hoc Python, or hand-editing store files.
- **Archive-never-delete**, including the verb named `delete` (a full alias of
  `retire`, which archives and preserves chat history). There is no hard-delete verb
  to reach for.
- Visual claims need Stage C proof captured through the MCP path in
  `launcher-mcp-operations` — the only sanctioned one. If it is blocked, record the
  exact blocker and still attach command/code proof. Never kill Tony's live Launcher.
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
| durable persona instances (the roster) | `hermes harness persona list --json` |
| one instance in detail | `hermes harness persona show <persona_instance_id> --json` |
| an instance's resolved tools and blocks | `hermes harness persona tool-diff <persona_id> --json` |
| a chat session's transcript | `hermes harness persona chat history --session-id <root> --json` |
| stored agent-graph documents | `hermes harness flow list --json` · `hermes harness flow show <graph_id> --json` |
| planning boards and cards | `hermes harness board list --json` · `hermes harness board show <board_id> --json` |
| realms / workspaces | `hermes harness realm list --json` · `hermes harness workspace list --json` |
| aggregate read-model (what the Launcher renders) | `hermes harness snapshot --json` |
| shared skills substrate | `hermes harness skills inventory --json` · `skills catalog --json` |
| level agents shown in Mission Control | Stage C MCP `mcp_launcher_qa_get_buttons` with `scope=mission_control.agent` |
| compact Mission Control graph probe | Stage C MCP `mcp_launcher_qa_get_widget_state` with `widget=mission_control.graph` |

**Do not use for level agents:** `status.agents` and `hermes harness agent list --json`
rosters show configured/installed Harness agents. They do not show which instances are
placed on a Mission Control level. Use `persona list --json` for the live roster and
Stage C MCP `mission_control.agent` for the visible level-agent selection surface.

## Removed — unlearn these

Removed 2026-07-30 — do not reach for them or repeat them as live (detail:
`references/model-notes.md`): `hermes harness task show <id> --json` and every `task`
verb; `blueprint list/run --bind` and the `.mission_plan` field (`.stages`, `.edges`,
`.agent_topology`); the old default graph **Neko scope → Backend Dev → Launcher Dev**
and the rule that **QA is a node only if the selected blueprint binds it**; `run show`,
`proof list`, `worker list`, `lane list`, `swarm status|enable`, `tick`,
`run-until-settled`; the `mission_goal_create` tool and `--allow-mission-goal`.
`harness snapshot --json` is contract 54 with no goal, stage, run, proof, or incident
sections — gone, not missing.

## In-turn tools

<!-- BEGIN GENERATED: harness_core inventory -->

44 tools · generated from the registry by `scripts/emit_harness_tool_inventory.py` · do not edit by hand. If a tool exists for it, the tool is the answer; the full table with descriptions is `references/tool-inventory.md`.

| toolset | tools | use it for |
|---|---|---|
| `agent_chat` | `agent_chat_dispatches` · `agent_chat_installs` · `agent_chat_log_path` · `agent_chat_open` · `agent_chat_send` · `agent_chat_threads` | teammates: list, message, read, dispatches, transcript path |
| `board` | `board_card_add` · `board_cards` | record follow-up work — planning state only |
| `clarify` | `clarify` | ask the operator a question mid-turn |
| `delegation` | `delegate_task` | hand a bounded subtask to a helper with fresh context |
| `terminal` | `process_manage` · `terminal` | run commands and manage background processes |
| `file` | `patch` · `read_file` · `search_files` · `write_file` | read, write, patch and search files |
| `web` | `web_extract` · `web_search` | search the web and pull a page's content |
| `browser` | `browser_back` · `browser_click` · `browser_console` · `browser_get_images` · `browser_navigate` · `browser_press` · `browser_scroll` · `browser_snapshot` · `browser_type` · `browser_vault_enter_code` · `browser_vault_fill` · `browser_vault_list` · `browser_vault_save_login` · `browser_vault_unlock` · `browser_vision` | drive a real browser: navigate, click, type, read, screenshot |
| `browser-cdp` | `browser_cdp` · `browser_dialog` | raw CDP and dialog handling for the same browser |
| `skills` | `skill_manage` · `skill_search` · `skill_view` · `skills_list` | find, read and author skills |
| `memory` | `memory` | durable profile memory |
| `todo` | `todo_list` | your own in-turn checklist |
| `session_search` | `session_search` | search your own past sessions |
| `vision` | `vision_analyze` | analyze an image |
| `code_execution` | `execute_code` | run code in the sandbox |

<!-- END GENERATED: harness_core inventory -->

## Operate

**Tools first.** If a tool exists for the row, the tool IS the answer — it runs
inside your turn, mints nothing, and costs no subprocess. A terminal call for a row
that names a tool is a navigation failure: report it (the command you reached for,
the tool you should have used) rather than quietly shelling out. The CLI column is
for rows where no tool exists.

| Do | In-turn tool (first choice) | CLI (only where no tool exists) |
|---|---|---|
| see who your teammates are / which instances you can reach | `agent_chat_threads` (read-only, no mint; `@install/…` reaches a far install) | — |
| see which other installs (machines) you can reach, and who is on them | `agent_chat_installs` (read-only; `install=` fetches that install's roster) | the HUD's `Installs` line already names them — this is the fresh read |
| message a teammate and get the reply in this turn | `agent_chat_send` (`wait=true`; `wait=false` to dispatch and continue) | `hermes harness mission-chat message …` is the OPERATOR's path, not yours |
| read what a teammate said | `agent_chat_open` (tail; `@install/…` reads a far thread, `session_id` required there) · `agent_chat_log_path` (full transcript path, then `read_file` / `search_files`) | — |
| see your background dispatches | `agent_chat_dispatches` | — |
| track follow-up work | `board_card_add` · `board_cards` — planning state only | `hermes harness board card add …` (operator path) |
| ask the operator a question | `clarify` | — |
| hand a bounded subtask to a helper with fresh context | `delegate_task` | — |
| continue an existing chat root | — | `hermes harness persona instance open-chat --persona-instance-id <instance> --persona <id> --session-id <root> --json` (`--session-id` is required unless `--new-session` or `--add-instance`) |
| create a new server-minted chat on an existing instance | — | `hermes harness persona instance open-chat --persona-instance-id <instance> --persona <id> --new-session --idempotency-key <key> --json` |
| find the on-level chat instances an OPERATOR can message | — | `hermes harness persona list --json` → chat-mode `personainst_<role>_agent_<hash>` rows (cross-check Stage C `mission_control.agent` buttons) |
| steer an in-flight streamed turn | — | `hermes harness mission-chat steer --session-id <root> --client-message-id <id> --message … --json` |
| abandon an outcome-unknown turn | — | `hermes harness mission-chat turn-resolve --session-id <root> --client-message-id <id> --turn-id <turn> --action abandon --json` |
| load a skill on the next turn | — | `hermes harness mission-chat queue-skill --persona <id> --session-id <root> --skill <name> --json` |
| re-route a steering edge in the agent graph | — | `hermes harness persona instance steer …` (supports multi-parent fan-in) |
| replace a whole agent-graph document | — | `hermes harness flow set …` (reconciles `steered_by` for the instances it references; never creates instances) |
| return a child's bounded summary to a parent chat | — | `hermes harness persona instance return-summary …` |

The complete inventory with descriptions, and the list of verbs that genuinely have
no tool, is `references/tool-inventory.md`.

## Persona chat continuity

Explanation: `references/model-notes.md`; triage: `references/operations.md`.

- Message the on-level instance. `PersonaInstance.default_chat_session_id` is the
  operator-chat pointer; Hermes mints every new root.
- `unknown_chat_session` on a roster-listed root: do not retry — mint a fresh root
  with `open-chat --new-session --idempotency-key <key>` and message that. The wrong
  store ROOT gives an empty roster; the wrong HOME gives wrong profile answers.
- `session_id` is the stable root; compression may rotate `active_session_id`. Only
  the owning serve process reports `hot`/`busy`/`cold`/`failed`; CLI snapshots say `unknown`.
- `chat_turn_outcome_unknown`: do not retry — `turn-resolve ... --action abandon` the
  exact `(root, client_message_id, turn_id)`, then send as a new turn with a fresh id.
- `chat_turn_provider_refused`: definite "did not run"; `turn-resolve` refuses it.
  Read `provider_refusal.reason`, never the prose; wait out the reset or fix the
  credential, then send a NEW client message id.

## Delegation — helpers without context bloat

Recipe and flags: `references/operations.md`, "Delegation"; why: `references/model-notes.md`.

- Message exactly ONE helper at a time (`agent_chat_send`, or `mission-chat message`);
  the message is the whole handoff: narrow objective, stop condition, parent session id.
- **Never slurp** the helper's transcript, logs, or reasoning — carry pointers.
- Return with `persona instance return-summary` (bounded, redaction-safe, records
  `returned_to`, emits `steer.returned`) — pointers, not payload.
- Intervene only on a stall, an explicit block, or scope drift, by another message on
  the SAME chat root.
