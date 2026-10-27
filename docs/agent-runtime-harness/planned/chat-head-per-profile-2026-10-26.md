# Planned — each agent's chats in its own agent profile (RT-CHAT-HEAD-PER-PROFILE, 2026-10-26)

**Owner domain:** chat turn lane ([05-chat-turn-lane.md](../05-chat-turn-lane.md)), runtime data
([02-runtime-data-and-shapes.md](../02-runtime-data-and-shapes.md)).
**Status:** RULED 2026-10-26 (lane w1026a-h-b, by the wave brief's "go with recommendations"); build rows in §5.
**Spec:** [naming-and-address-map-2026-10-25.md](naming-and-address-map-2026-10-25.md) ruling 4 — "a persona
instance's chat head is its own agent profile, so each agent has its own `state.db` and its own recall;
reads and writes move together through `chat_session_scope`, and existing chats in `base` move once."

## 1. What is true today (read 2026-10-26 on `main`)

- Every persona-chat transcript is in ONE `state.db`: the head `agent_runtime/chat_session_scope.py`
  resolves. The launcher names it (`HERMES_HEAD_HOME=<namespace>/profiles/base`), and that env rung
  outranks the per-conversation `INSTANCE_RECORDED` rung (`PersonaInstance.chat_head_home`).
- `tools/session_search_tool.py::session_search` searches the `db` the turn hands it — the chat head, so
  `profiles/base` — and opens `get_hermes_home()/state.db` only for a worker's `RuntimeSessionStore`.
  Recall during a Mission Control turn therefore searches EVERY agent's chats: a cross-agent recall, not
  per-agent recall. The runtime proof of which handle a turn passes is build row CH1.
- Upstream already ships a two-store session move: `hermes_state_profile_repair.py`
  (`export_session_for_move` → `import_moved_session` → `delete_moved_session`): copy into the target,
  then delete from the source only when the target holds at least as many messages; a crash between the
  two leaves a duplicate the next run settles. FTS rows follow the messages table's own triggers.
- Mints go through ONE seam since 2026-10-26: `agent_runtime/persona_chat_continuity/mint_receipts.py::
  mint_chat_root`, with the caller's `session_db`.

## 2. Decisions (each `Decided (plan):`)

1. **The head of a chat is its instance's profile home.** Decided (plan): `chat_head_for(instance)` =
   `profiles/<instance.profile_id>`, and `profiles/base` for an instance with no profile (base is then
   just one more agent profile, not the shared head). The mint records it on the instance
   (`chat_head_home`) as it does today, but from this derivation instead of the process head.
2. **The ladder: the instance rung outranks the launcher's env head for a named conversation.** Decided
   (plan): `RELAY_CONTEXT` > `INSTANCE_RECORDED` (when the record names a per-profile head) >
   `ENV_HEAD_HOME` > pointer > declaration > ambient. The env head stays the PROCESS default (reads with
   no `session_id`: rosters, the cockpit's "which store" probe), so the launcher keeps setting
   `HERMES_HEAD_HOME` and needs no change for writes. The `ChatScopeMismatch` between the env head and the
   record stops being a mismatch for records stamped by the new derivation (a typed `head_kind:
   per_profile` on the record says which).
3. **The move is one verb, dry-run by default, per instance, idempotent.** Decided (plan): `hermes harness
   persona chat-head migrate [--instance <id>] [--apply] --json`. For each instance, every session whose
   meta names it (`persona_instance_id`), plus its compression lineage (children by `parent_session_id`),
   is copied into the instance's profile `state.db` with upstream's move primitives; the instance's
   `chat_head_home` flips only after its whole set copied and verified; only then are the `base` rows
   deleted. Until an instance flips, its chats read from `base` exactly as today — the owner's data stays
   readable until moved. A second run reports `present` and changes nothing. Never run by a lane against a
   live namespace; the operator runs `--apply`.
4. **Cross-agent reads fan out over the heads that exist.** Decided (plan): the cockpit's reads that list
   chats across agents (the roster's last-message preview, history search) group instances by head and
   open each `state.db` once per read, read-only, through `chat_session_scope.open_chat_session_db`. N is
   the number of agent profiles in the namespace (single digits), so no index is added.
5. **A relay turn runs on the TARGET's head.** Decided (plan): `RELAY_CONTEXT` today pins a nested relay
   turn to the operator's head. Under ruling 4 agent B's relay chat belongs in B's profile, so the relay
   context carries the operator identity, not a head; the target instance's rung answers the head.
6. **Recall becomes per-agent by construction.** Decided (plan): no change to upstream's
   `session_search`; it searches the `db` the turn hands it, and that db is now the agent's own.

## 3. Recommendation

Build CH1 first (it pins today's behaviour so CH2 has a red), then CH2 + CH5 together (one ladder
change), CH4, and CH3 last; the operator applies the move after CH2–CH5 are live.

## 4. Not decided here

- Whether `profiles/base` keeps any chat after the move (it holds the `base` persona's own chats — the
  seeded agent — and nothing else). No owner call needed unless that agent is retired.

## 5. Build rows (hermes `runtime-queue.md`)

`RT-CHAT-HEAD-CH1-RECALL-PIN`, `RT-CHAT-HEAD-CH2-LADDER`, `RT-CHAT-HEAD-CH2B-WRITERS`,
`RT-CHAT-HEAD-CH2C-FIRST-BIND-STAMP` (§7.3), `RT-CHAT-HEAD-CH3-MOVE-VERB`,
`RT-CHAT-HEAD-CH4-CROSS-AGENT-READS`, `RT-CHAT-HEAD-CH5-RELAY-HEAD`.

## 6. Open — the writer side (found building CH2, lane w1026c-h-rt-a, 2026-10-26)

*Decided in §7 (2026-10-27); kept as the evidence the decisions answer.*

§2.2 moves the READ ladder; nothing in §2 moves the writes, and the two cannot move apart (the
2026-07-27 read-lane gap is exactly a read and a write resolving different heads). Read on `main`:

- The send lane opens its SessionDB BEFORE it loads the instance:
  `hermes_cli/harness_parts/persona/chat_turn_message.py` calls `_default_persona_session_db()`
  (`agent_runtime/persona_chat_durability.py::default_persona_session_db`, process scope →
  `HERMES_HEAD_HOME`) and only then builds the `PersonaInstanceStore`; the fresh-root mint
  (`_mint_send_root` → `mint_chat_root(session_db=…)`) writes into that handle.
- The same process-scope acquisition is the writer for `chat_open.py` (three sites, incl. its mint),
  `chat_delete.py`, `lifecycle_commands.py`, `chat_verbs/turn_resolve.py`,
  `conversations/migration.py::migrate_conversation`, `snapshot/details.py` (three) and
  `profile_context.py`; `operator_history.py`, `operator_undo.py`, `operator_session_models.py`,
  `continuity.py` and `persona_assignments/scan.py` call `resolve_process_chat_scope()` directly.
- One writer handle is held per process (`agent_runtime/chat_session_writer.py::ChatSessionWriterOwner`,
  one scope per `acquire`) and the prewarmed resident actor keeps the `session_db` it was built with
  (`persona_chat_actor_prewarm.py`, `ProfileAgentRunner(session_db=…)`); CH1's pin shows that handle is
  what recall searches.
- The stamp writer `persona_assignments/chat_binding.py::_stamp_chat_head` stamps the PROCESS scope
  every turn, so it would overwrite a per-profile stamp with `profiles/base` on the next turn.

What the plan must decide before CH2 builds: which of these acquisitions resolve per instance (a
`scope_for_instance(instance)` door beside `resolve_process_chat_scope`, and the send lane loading the
instance first), how the writer lease and the resident actor hold one handle per head, and when the
mint may stamp `per_profile` on an instance that already has chats in `base` (only on a first mint, or
only via CH3's flip).

## 7. The writer side — decided (lane w1027e-h-plan, 2026-10-27)

### 7.1 Problem

§2.2 moves the read ladder; §6 lists every writer that still acquires the PROCESS scope. If a record
says `per_profile` while any writer still opens `profiles/base`, the conversation splits exactly as in
the 2026-07-27 read-lane gap. Reads and writes must change through one door, and nothing may stamp
`per_profile` until every writer honours it.

### 7.2 Decisions (each `Decided (plan):`, with why)

1. **The record carries its kind.** `PersonaInstance` (`agent_runtime/models.py`, beside
   `chat_head_home`) gains `chat_head_kind: str | None` — `process` | `per_profile`; `None` reads as
   `process` (every row on disk today). It joins `_OPEN_CHAT_TRACKED_STORE_FIELDS` in
   `agent_runtime/persona_assignments/store.py` and, like `chat_head_home`, projects to no wire field.
   *Why:* §2.2's `head_kind` must live on the row the ladder already reads
   (`recorded_instance_chat_head`), not in a second store.
2. **The derivation has one authority.** `chat_head_for(persona, instance)` =
   `resolve_persona_profile(persona).profile_home` (`agent_runtime/profile_context.py`) for
   `instance.profile_id or persona.hermes_profile` — the same home the persona RUNS in, so the chat, the
   worker store and recall agree; an instance whose persona inherits the active profile gets the process
   head (`profiles/base`). *Why:* a second path-join next to `get_profile_dir` is the two-derivation
   defect the scope module exists to retire.
3. **The record is the fact once stamped; a later profile change does not move it.** `ensure_for_personas`
   rewrites `profile_id` when a persona's profile changes (`store.py` line ~154); a `per_profile` record
   keeps its recorded home, and moving it is CH3's verb. *Why:* re-deriving per read would silently
   re-home a live conversation.
4. **One instance door beside the process door.** `chat_session_scope.resolve_instance_chat_scope(instance)`
   answers `INSTANCE_RECORDED` for a `per_profile` record whose home exists, the process scope for every
   other record, and a typed refusal (`chat_head_missing`) for a `per_profile` record whose home is gone —
   never a fallback to `base`, because a fallback write is the split. `resolve_chat_session_scope(session_id=)`
   gives the same answer through the ladder: a `per_profile` record outranks `ENV_HEAD_HOME` and raises no
   `ChatScopeMismatch` against it (§2.2); `RELAY_CONTEXT` stays on top until CH5.
5. **Which acquisitions move.** Per conversation (the instance door, or `resolve_chat_session_scope` with
   the session id in hand): the send lane (`hermes_cli/harness_parts/persona/chat_turn_message.py` —
   the SessionDB open moves BELOW `_session_target`, so the instance is known first; the
   `session_db_open_ms` timing moves with it), `chat_open.py` (three sites), `chat_delete.py`,
   `lifecycle_commands.py`, `agent_runtime/chat_verbs/turn_resolve.py`,
   `agent_runtime/conversations/migration.py::migrate_conversation`, `agent_runtime/snapshot/details.py`
   (three), `agent_runtime/continuity.py::_session_db` (resolves the PARENT session it writes into), and
   the resident actor prewarm (`agent_runtime/persona_chat_actor_prewarm.py`, from its root's instance).
   Already per conversation, no change: `operator_history.py`, `operator_undo.py` and
   `operator_session_models.py` use `session.scope` from
   `persona_chat_history/messages.py::existing_chat_session`, which resolves
   `resolve_chat_session_scope(session_id=)`. Stay PROCESS by design: `root_anchor.py`,
   `root_observability.py`, `chat_live_log/files.py`, `lens/store.py`, `serve/session.py`,
   `persona_assignments/scan.py` (the `explicitly_named` posture) — none writes a transcript.
   `default_persona_session_db()` keeps its name and becomes the process-only acquisition; a
   `persona_session_db_for(scope)` beside it takes the resolved scope.
6. **The writer lease already holds one handle per head.** `ChatSessionWriterOwner.acquire` keys leases
   by `scope.db_path` (`agent_runtime/chat_session_writer.py`), so a request that touches two heads holds
   two leases; §6's "one writer handle per process" is not what the code does and needs no change — only
   its callers must pass the instance scope.
7. **The resident actor is keyed by its head.** The prewarmed actor's runtime signature
   (`mission_chat_turn_context.mission_chat_runtime_signature_components`) gains the head's `db_path`, so
   a CH3 flip invalidates the actor instead of leaving it writing `base` through its held `session_db`.
8. **The stamp writer never downgrades.** `persona_assignments/chat_binding.py::_stamp_chat_head` leaves a
   `per_profile` record untouched (the process scope may only stamp `process` records). It stamps
   `per_profile` in exactly two cases: (a) the bind of an instance that has never been bound
   (`default_chat_session_id` empty before this bind, `chat_head_home` unrecorded) and holds no session in
   the process head whose meta names it (one query, run only on that first bind); (b) CH3's flip after its
   copy verifies. *Why:* case (a) starts every new agent in its own profile without a migration; the
   query guards the legacy rows that predate the stamp; anything else is CH3's to move.
9. **Order.** Nothing stamps `per_profile` (case a) until the writers (CH2B) and the relay head (CH5) are
   live: until then a `per_profile` record exists only in tests, so CH2-LADDER and CH2B are inert in
   production and each lands alone.

### 7.3 Slices

| row | lands | files |
|---|---|---|
| `RT-CHAT-HEAD-CH2-LADDER` | decisions 1, 2, 4, 8's no-downgrade guard | `agent_runtime/models.py`, `agent_runtime/persona_assignments/store.py`, `agent_runtime/chat_session_scope.py`, `agent_runtime/persona_assignments/chat_binding.py` |
| `RT-CHAT-HEAD-CH2B-WRITERS` | decisions 5, 7 | the per-conversation sites in decision 5, `agent_runtime/persona_chat_durability.py`, `agent_runtime/persona_chat_actor_prewarm.py`, `agent_runtime/mission_chat_turn_context.py` |
| `RT-CHAT-HEAD-CH2C-FIRST-BIND-STAMP` | decision 8 (a) | `agent_runtime/persona_assignments/chat_binding.py` |

### 7.4 Test plan (each slice's killing mutation)

- CH2-LADDER: a fixture instance stamped `per_profile` at `profiles/alice` under
  `HERMES_HEAD_HOME=profiles/base` — `resolve_chat_session_scope(session_id=)` answers `profiles/alice`,
  `INSTANCE_RECORDED`, no mismatch; positive control: the same row stamped `process` answers `base`.
  Mutation: drop the per_profile branch above the explicit rung → red. Second: `_stamp_chat_head` on the
  `per_profile` row leaves it unchanged; mutation: remove the guard → the row reads `base` → red. Third:
  home deleted → `chat_head_missing`, never `base`.
- CH2B: one send to a `per_profile` instance writes its messages into `profiles/alice/state.db` and none
  into `base` (row counts on both files); positive control: a `process` instance writes `base`. Mutation:
  restore the send lane's process acquisition → red. Per moved site, one parametrised case over the
  decision-5 list (an enumerated set read from the call sites, not retyped). Actor: flipping the record
  changes the runtime signature; mutation: drop `db_path` from the components → red.
- CH2C: first bind of a fresh instance stamps `per_profile`; a never-bound legacy instance with a session
  in base whose meta names it stays `process`. Mutation: skip the base query → the legacy case goes red.

### 7.5 Open questions

None for the owner: every choice above is technical and follows ruling 4. §4's question (what stays in
`base`) is unchanged.
