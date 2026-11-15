# Planned — Lens `act`, and a safe `investigate` (2026-11-14)

**Owner domain:** Lens (`agent_runtime/lens/`). Parent plan [eternia-lens-in-hermes.md](eternia-lens-in-hermes.md)
§2.6 and W9. Row `RT-LENS-ACT-ADMISSION` (task `TASK-ETERNIA-LENS`). **Status:** owner-approved 2026-11-14 (§6); the §7 build rows are filed (lane w1114a-lensrows).

The owner's ruling, 2026-11-14: act is "just an extension of the second; investigate function after the
notify", investigate must be safe "so it doesn't just burn all your tokens", "don't over eingeer", and "a
ruleset prompt that applies to the safety classifier is the core of both".

## 1. What exists today (read on `main` 2026-11-14)

- **Levels:** `manifest.py::AutomationLevel` is `notify | investigate`. `notify` forges no turn; `investigate`
  forges ONE mission-chat turn in a new chat held at `read_only` (`trigger.py::_open_episode_chat`,
  owner RULED 2026-10-22) on the manifest persona's own model (`model=None`).
- **Caps are turn counts, not tokens:** per monitor `daily_turn_cap` (max 96); all Lens
  `agent_runtime.lens.daily_turn_budget` (96 turns/day; past it an investigate is downgraded to a notify).
  The wall clock is `mission_chat_default_max_seconds`.
- **A token bound exists but Lens does not use it:** `profile_runner/budget.py` has `max_total_tokens`
  (80 % warning, trip after the run); the mission-chat door does not pass it, so a forged turn has no token
  ceiling. Per-call tokens are recorded (`usage_ledger.py`, `turn_usage.py`).
- **A rules-prompt safety check exists:** `tools/approval_smart.py` — the auxiliary `approval` model,
  operator rules (`approvals.smart_policy`) in the trusted system prompt, the untrusted input fenced,
  one-word verdict `APPROVE | DENY | ESCALATE`, any failure = `ESCALATE`. Today it only judges flagged
  shell commands. **This design reuses it; it does not add a second classifier.**

## 2. One ruleset, one check

**The ruleset** is plain-language text. Each monitor may carry its own `rules` (sealed with the manifest
revision, so a change is a reseal and shows as a diff); a monitor without one uses the workspace default
(root config `agent_runtime.lens.default_rules`). Shipped default:

> Investigate only when the change is worth a look. Read; never write, send, buy, delete or post.
> Act only with the actions listed for this monitor, and only when the action can be undone.
> Anything else, or anything you are unsure of, goes to the owner.

**As built (RT-LENS-MONITOR-RULES, 2026-11-14).** In code the ruleset is *guidance* (`rules` already
names the trigger list): manifest key `guidance` (optional, ≤ 4 KiB, non-blank, sealed; absent emits no
bytes), `agent_runtime/lens/guidance.py`. The workspace default is not a root-config key: it is a
per-workspace row in the Lens store (`guidance_defaults`), written over the RPC, so it needs no config file
and survives a serve restart; with none, the shipped text above applies. The RPC:

- `runtime.lens.get` adds `guidance: {text, source: monitor|workspace|shipped, draft: null | {text, source}}`
  — the sealed revision's effective rules (a never-sealed monitor's draft's); `draft` is a waiting next
  revision's. A monitor's own rules are written by `runtime.lens.create` (the manifest's `guidance`) and
  frozen by `runtime.lens.seal`.
- `runtime.lens.guidance.default.get {workspace_id?}` and `runtime.lens.guidance.default.set {workspace_id?,
  text: str | null}` → `{workspace_id, text, source: workspace|shipped, updated_at_ms, shipped_text}`;
  absent `workspace_id` is the active workspace, `text: null` restores the shipped text. Console tier; no
  persona tool writes rules (`lens_propose` has no `guidance` argument).

**The check** is `approval_smart`'s guardian with a Lens prompt: the ruleset goes in the system prompt
(trusted); the request goes in a fenced user block (untrusted). It runs at exactly two points:

| Where | What it sees | APPROVE | DENY | ESCALATE / failure |
|---|---|---|---|---|
| **Before the investigate turn** (at admission, after the caps) | monitor name, rule that fired, typed values, budget left today | forge the turn | receipt `notified_by_rules`, no turn | `notified_by_rules`, no turn (fail closed) |
| **Before each mutating tool call** in an `act` turn | tool name, its arguments, whether it can be undone, the Episode summary | the call runs | the call is refused; the model reads "refused by this monitor's rules" | the call becomes a **proposal** (§4) |

**As built (RT-LENS-RULES-CHECK-BEFORE-INVESTIGATE, 2026-11-14).** The guardian's one call is
`tools/approval_smart.py::guardian_verdict` (a fork seam split out of `_smart_approve`); the Lens prompt
and the fenced request are `agent_runtime/lens/rules_check.py`. The door runs it in `LensForge._forge`,
after the caps, the level and the evidence, for every investigate turn and once per digest. A refusal is
receipt `notified_by_rules` (counted by the daily cap like `notified`); every checked receipt carries
`rules_verdict` (`approve|deny|escalate`), `decided_by: rules` and `rules_check_tokens` (the guardian
call's `total_tokens`, for the Episode budget to count).

Read-only tool calls in either level pay no check — the budget (§3) bounds them. The check's own tokens
(a few hundred per verdict, 16 out) count against the Episode budget. Every verdict lands on the receipt
(`decided_by: rules | owner`).

## 3. Investigate made safe

- **Read-only by default** — unchanged (`read_only` chat; `act` is the only way out of it).
- **Hard token budget**, counted from the turn's own usage ledger and checked **between provider calls**:
  - per Episode: **150,000 total tokens** and **30 provider calls**;
  - per monitor per UTC day: **600,000 tokens**;
  - all Lens per UTC day: **2,000,000 tokens** (beside the existing 96-turn budget, which stays).
- **Stop when spent:** at 80 % the turn gets the existing budget-pressure nudge ("write what you have");
  at 100 % it lands (no further calls) and the reply so far is the report; receipt `budget_spent`. A
  monitor or Lens over its daily tokens downgrades the next Episode to a notify (`notified_over_budget`,
  today's behaviour for turns).
- **Shown to the owner:** tokens used / limit per Episode on its receipt, today's per-monitor and all-Lens
  totals on the monitor card; a price is shown when `turn_audit` can price it, else tokens only.

**Built 2026-11-14 (RT-LENS-INVESTIGATE-TOKEN-BUDGET, lane w1114a-hlens-budget).** The ceiling is
`agent_runtime/turn_token_budget.py`: armed by the exit door for the forged turn's client message id,
charged from every provider call's own usage (`usage_ledger.record_usage`, i.e. the `post_api_request`
hook), nudging at 80 % and landing while the landing reply still fits (one more working call plus the
landing, each about the size of the last call, would pass the token limit; or the landing would be the
last call allowed) — the iteration budget is drained, so upstream's finalizer writes the reply that is the
report. The Episode's token ceiling is never more than what the monitor and all Lens have left today. The
limits and the day's spend are `agent_runtime/lens/budget.py`, stored in the Lens store (tables
`budget_limits`, `episode_spend`), so an edit survives a restart and needs no config file; the root
config's `agent_runtime.lens.{episode_token_budget, episode_call_budget, monitor_daily_token_budget,
daily_token_budget, daily_turn_budget}` is only the fallback. Not counted yet: upstream's iteration-summary
call fires no `post_api_request`, so the landing reply's own tokens are not on the receipt (the stop leaves
room for them; row `RT-ITERATION-SUMMARY-CALL-UNCOUNTED`).

The RPC (settled here; the row's "get/set pair" was a guess):

| verb | params → result |
|---|---|
| `runtime.lens.budget.get` | `{monitor_id?, workspace_id?}` → `{lens: {limits: {daily_tokens, daily_turns}, today: {tokens, turns}, bounds}, workspace: {workspace_id, limits: {episode_tokens, episode_calls, daily_tokens}, bounds}, monitor?: {monitor_id, limits: {…same three}, today: {tokens}, bounds}}`; each limit is `{value, source: monitor \| workspace \| lens \| config}`; `workspace` is the given one, else the monitor's, else the active one; `bounds` is `{key: [min, max]}` |
| `runtime.lens.budget.set` | `{scope: monitor \| workspace \| lens, monitor_id? \| workspace_id?, limits: {key: int \| null}}` → `budget.get`'s answer for that scope; `null` clears a key back to the next layer (monitor → workspace → config); a refusal names its field (`unknown_key`, `invalid_integer`, `missing_key`, `unknown_enum`, `monitor_not_found`); takes effect from the next Episode |
| `runtime.lens.receipt` / `receipts` | each receipt that ran a turn carries `budget: {tokens_used, token_limit, calls_used, call_limit, stopped_by: null \| tokens \| calls}`, else `null`; a landed turn's `outcome` is `budget_spent` |

## 4. Act is investigate's next step

`AutomationLevel` gains `act`. An `act` monitor runs exactly as investigate (notify → check → turn, same
budget), but its chat is held at `bounded` instead of `read_only`, and every mutating call goes through the
§2 check with the monitor's `actions` list (tool names it may use alone) in the request.

- **Allowed by the rules** → runs; **refused** → the model is told and carries on read-only.
- **Proposal** (escalated, not listed, or not undoable) → written to the Episode (tool, arguments, why),
  the turn continues without it. The owner approves or denies in Eternia; an approval forges ONE follow-up
  turn in the same Episode chat with that one call pre-admitted (one-shot). Unanswered for **24 h** →
  expired, with a receipt.
- **W9 standing rule kept:** an Episode whose evidence carries untrusted free text (titles, scraped
  strings) may never act alone — every mutating call is a proposal.
- **Undo:** file writes ride the existing checkpoints (`operator_undo.py`), realm writes `realm_revert*`;
  the receipt carries the undo handle. Anything else is marked "cannot be undone" — the default ruleset
  sends those to the owner.
- **Receipt per action:** `{episode, tool, arguments digest, verdict, decided_by, result, undo handle}`.

## 5. What Eternia shows

- **Rules editor:** a "Rules" text field in the monitor authoring form (Mission Control → Lens), with "use
  workspace default"; the workspace default sits in Lens settings.
- **Budget:** "this Episode 40k / 150k · today 120k / 600k tokens" on the monitor card and the receipt.
- **Approval card:** in the Episode chat and the Mission Control inbox — the action, why, which rule sent
  it, undoable yes/no, Approve / Deny, time left.

## 6. Owner decisions

1. **Budget numbers** (150k per Episode, 600k per monitor per day, 2M all Lens per day). *Recommend:* take
   them; they are a few investigations a day on a frontier model and are config, so easy to raise.
2. **The check before every investigate turn**, not only for monitors with their own rules. *Recommend:*
   yes — it is cheap and is what makes the one ruleset govern both levels.
3. **Fail closed:** an uncertain or failed check means "no turn" (investigate) or "proposal" (act).
   *Recommend:* yes.
4. **Free-text evidence never acts alone** (W9). *Recommend:* keep it; a deal title can carry an
   instruction, and a proposal costs the owner one tap.
5. **Proposals expire after 24 h.** *Recommend:* yes; a stale "bid now" is worse than none.

**RULED 2026-11-14, owner:** "yes reccomendations are good , the budget limits should be easily editable" — decisions 1–5 accepted as recommended, and every budget limit (per monitor, the workspace default, the Lens-wide daily cap) must be easily editable by the owner: read and written over the runtime RPC and edited in Eternia's Lens UI, not only in a config file.

## 7. Build rows it implies (filed 2026-11-14: RT-LENS-MONITOR-RULES, RT-LENS-INVESTIGATE-TOKEN-BUDGET, RT-LENS-RULES-CHECK-BEFORE-INVESTIGATE, RT-LENS-ACT-LEVEL, RT-LENS-PROPOSAL-APPROVE-DENY, RT-LENS-UNDO-ACTION; Eternia's under launcher TASK-LENS-ACT-AND-SAFE-INVESTIGATE)

hermes, in order:
1. A monitor carries plain-language rules, with a workspace default (manifest `rules`, sealed; root
   `default_rules`).
2. Investigating stops at a token budget (pass `max_total_tokens` / `max_api_calls` through the mission-chat
   door for forged turns; trip between calls with a landing; per-monitor and all-Lens daily token counters;
   `budget_spent`; budget fields on `runtime.lens.receipt`).
3. One rules check decides whether an investigation runs (the `approval_smart` guardian with a Lens prompt,
   at admission; verdict on the receipt).
4. A monitor can act within its rules (`act` level, `actions` list, `bounded` chat with the check on every
   mutating call, per-action receipts; W9 free-text rule; planted-instruction fixtures).
5. The owner approves or denies what Lens proposes (proposal store, approve/deny RPC, one-shot follow-up
   turn, 24 h expiry).
6. An action Lens took can be undone (checkpoint / realm-revert handles on receipts, `runtime.lens.undo`).

Eternia, in order (each after its hermes row):
1. Edit a monitor's rules and the workspace default (after hermes 1).
2. See the token budget on the monitor card and receipt (after hermes 2).
3. Choose "act" and approve proposals on a card (after hermes 4–5).
4. Undo an action from its receipt (after hermes 6).
