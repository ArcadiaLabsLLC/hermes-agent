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

`RT-CHAT-HEAD-CH1-RECALL-PIN`, `RT-CHAT-HEAD-CH2-LADDER`, `RT-CHAT-HEAD-CH3-MOVE-VERB`,
`RT-CHAT-HEAD-CH4-CROSS-AGENT-READS`, `RT-CHAT-HEAD-CH5-RELAY-HEAD`.
