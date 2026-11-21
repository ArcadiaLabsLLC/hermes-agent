# Planned — an agent's template is its persona; does every live agent need a placement?

**Status:** plan written 2026-11-21 by lane w1118a-tplplan for row
`RT-AN-AGENTS-TEMPLATE-IS-ITS-PERSONA-AND-EVERY-LIVE-AGENT-IS-A-PLACED-INSTANCE`
(`Harness_Brain/20 — Active Initiatives/runtime-queue.md`, review w1118a.77).

**RULED 2026-11-21 by the owner: option (iii), template-only, keeping the copies in use.** The owner's
words and what they change are in §8. One answer changed: §3(a), channels (a live chat belongs to an
instance; the agent's saved chat history stays the agent's). The build rows of §7 are filed.

The owner's five points on the row are **questions**, not rulings (the owner said so). Each is answered
below with what the code does today and what it would become.

Owner docs: [`../01-system-architecture.md`](../01-system-architecture.md) (instances and channels),
[`../05-chat-turn-lane.md`](../05-chat-turn-lane.md) (sends). Earlier plans on the same row:
[`global-singleton-persona-instances.md`](global-singleton-persona-instances.md) (stale) and
[`canonical-channel-global-storage-2026-10-27.md`](canonical-channel-global-storage-2026-10-27.md)
(shipped 2026-10-27: a canonical row carries no workspace pointer).

Evidence labels used below: **read** means read in code on `origin/main` at `7c4d020dce` (hermes) and
`3fd93a77242` (Eternia). **guess** means not proven, and the build row it names must check it first.

---

## 1. Words this plan keeps apart

- **Persona.** The agent's definition: its name, role, model defaults and its Hermes profile (the
  profile home holds SOUL, memory, skills and the session database). This plan calls it the
  **template**.
- **Instance.** One live copy of a persona that runs turns. Stored as a `PersonaInstance` row
  (`agent_runtime/models.py`). `workspace_id` is optional. `None` means "runtime-global", in no workspace.
- **Placed instance.** An instance with a `workspace_id` and an office seat. Its id is
  `personainst_<persona>_agent_<hex>` (`persona_instance_id_for_placement`), or one named from the create
  key.
- **Canonical instance.** The one instance per persona whose id is `personainst_<persona>`
  (`persona_instance_id_for`). Examples: `personainst_base`, `personainst_neko_supervisor` and
  `personainst_profile_<name>`. The test for it is
  `agent_runtime/persona_assignments/identity.py::is_canonical_persona_channel`. It compares the id
  with the persona's id. It does not look at the id's shape. Since 2026-10-27 the canonical row never
  carries a workspace (`store.py::_decode_instance` and `chat_binding.py::_apply_open_fields`).
- **Not the same thing: a placed instance whose seat is gone.** Examples are the doctor's
  `unplaced_rows` (`harness_doctor/census.py`), the reconciler's `unplaced-instance` prune
  (`persona_instance_identity.py`, `PRUNE_REASON_UNPLACED`), `persona seat-unseated` (`agent_create/seat.py`)
  and Eternia's `mission_office_removal_plan.dart`. These are broken placements, not canonical rows.
  This plan does not change them.
- **Not the same thing: an unseated create.** `runtime.agent.create` with no workspace makes a NEW
  persona and profile, plus a first instance named from the create key, with no workspace
  (`agent_create/perform.py::finish_unseated`, `mint_new_agent`). That instance is unplaced, but it is
  not canonical. Such personas are `is_independent_agent_persona` and get no canonical row
  (`persona_assignments/store.py::ensure_for_personas` skips them). Today's code therefore already
  has one kind of agent with no hidden copy.
- **The word "canonical" is overloaded.** Several functions use it to mean "the one correct spelling
  of an id", not "the canonical instance":
  - `canonical_persona_instance_id` (it normalises `persona_personainst_x` and `persona:<id>`);
  - `agent_retire.py::_canonical_instance_id`;
  - `realm_sync/publish_scans.py`'s "canonical instance id" for actor keys;
  - `harness_doctor/census.py`;
  - the Eternia palette's `canonicalHarnessInstanceId`.

  These do not depend on the canonical instance. §3(c) matters because of this.
- **Operator channel.** One Agent Console conversation entry: one row of the console's single
  render contract (`agent_runtime/operator_channels/__init__.py`, "one render contract per operator
  channel"). It is keyed persona + chat session. It is not an external messaging channel (a gateway).

## 2. What the canonical instance is today, who makes it, and who uses it

### 2.1 Who makes it

`PersonaInstanceStore.ensure_for_persona` (`agent_runtime/persona_assignments/store.py`) writes the row
`personainst_<persona>` when it is missing, and announces `persona_instance.created`. When it exists,
the call re-syncs the display name and profile. `ensure_for_personas` runs it for every runtime
persona except independent agents. It is called on almost every read path, not only at startup
(**read**):

- discovery and prewarm:
  - `instance_catalog.py::prepare_instance_catalog`;
  - `persona_chat_actor_prewarm.py`;
  - `bundled_agents/fold_discovered.py`, which also folds discovered channel rows onto it;
- every snapshot build: `snapshot/sections.py`, `snapshot/details.py`;
- status: `status.py`;
- the peer roster: `peer_directory.py::peer_roster_projection`;
- every send:
  - `hermes_cli/harness_parts/persona/chat_turn_message.py`;
  - `chat_turn_target.py`;
  - `tools/agent_chat/addressing.py::_addressable`;
- the CLI `inspect_commands.py`.

So deleting the row does nothing: the next snapshot build makes it again. This is why
`persona_assignments/retire.py` refuses to retire it (`canonical_persona_channel`). The mint is also a
named trigger of the snapshot cache's `never_converged` receipt (`core_cache/restat.py`,
`core_cache/convergence.py`), because a build writes the row it reads.

`namespace_seed/instances.py` only carries existing rows into a seeded namespace. It does not mint
them.

**A fresh install.** The only seeded agent is Base. Three things are called "base"
(`hermes_cli/_namespace_bootstrap.py`, row `RT-THREE-BASES`):

- the install root;
- the `profiles/base` agent profile, which the serve runs under;
- `personainst_base`, "the only seeded agent: an agent you chat with".

The serve's boot also makes the local default realm and workspace, `realm_default` / `ws_default`
(`agent_runtime/default_scope.py::ensure_default_scope`, called from
`hermes_cli/harness_parts/serve/boot_phases.py`). So a fresh install has one agent that is in no
workspace, and one empty workspace.

### 2.2 What depends on it (both repositories)

| Family | Files (hermes unless marked) | What it uses the canonical row for |
|---|---|---|
| **Operator channels** | `operator_channels/summary.py::operator_channel_summary`, `operator_channels/instances.py::channel_identity` | Every instance row becomes a channel entry: a chat-mode row is keyed by its session, and any other row by its instance id (`_channel_key_for_instance`). A persona's canonical row therefore shows as a channel even when it was never chatted with. `channel_identity` falls back to `persona_instance_id_for(persona_id)` as the channel key when no row names an instance. |
| **Scoping and rosters** | `workspace_scope.py` (`exclude_global_canonicals`, `shadow_canonical_by_placement`, `addressable_roster`), `peer_directory.py`, `runtime_hud/ambient.py`, `prompt_observability/snapshot_frame.py`, `batch/dispatcher.py::_workspace_roster`, `work/service.py::_agent_reach` | Under a real workspace, canonical rows are hidden from agents' rosters. Where a persona has a placement, the placement shadows the canonical. With no workspace at all (scope `None`), they are listed. Work treats a runtime-global instance as a member of every workspace's roster, and lets it see every owner's boards. |
| **Bare-persona send fallback** | `chat_target.py::_mission_chat_bare_persona_target`, `chat_turn_target.py` (falls back to `canonical_chat_instance_id`), `tools/agent_chat/addressing.py::resolve_send_target`, `tools/agent_chat/threads.py` | A send to a persona id goes to its one in-scope placement. With none, it goes to the canonical row. `workspace_scope.py` names this "the deliberate residual asymmetry", "gated on the global-row adoption migration". |
| **Chat binding** | `persona_assignments/chat_binding.py`, `lookups.py::resolve_default_chat_session_id_for_instance`, `identity.py::canonical_chat_instance_id`, `persona_chat_session.py`, `chat_open.py`, `chat_request.py`, `chat_turn_message.py::_caller_instance_pin`, `conversations/migration.py`, `own_session_import.py` (`BoundBy.PERSONA_CHANNEL`), `persona_chat_history/history_rows.py`, `trace.py`, `lens/trigger.py`, `harness_query/core.py` | A chat request that names a persona but no instance binds to `personainst_<persona>`. History and trace rows with no instance id are attributed to it. Lens triggers and harness queries look a persona up by that id. An imported session is bound to it. |
| **Identity, steering, repair** | `persona_assignments/steering.py`, `replicate.py` (refuses to replicate it), `repair.py` (`clear_canonical_scope_pointers`, the goal clean-up), `retire.py` (refuses `canonical_persona_channel`), `persona_instance_identity.py` (the reconciler exempts it from the `unplaced-instance` prune) | These guards keep the row alive and global. |
| **Office and realm keys** | `office_store/normalize.py`, `store.py`, `archive.py`, `realm_sync/publish_scans.py`, `realm_sync/drift.py`, `realm_rekey_agents.py`, `scripts/office_actor_rekey_to_instance.py`, `persona_instance_sync/projection.py` (`skipped_canonical`, `REFUSAL_CANONICAL_CHANNEL`), `harness_doctor/census.py`, `snapshot/warnings.py` | Realm sync never publishes a canonical row ("every machine derives its own"). A pull refuses one. Most of the "canonical" actor-key code here is the id-spelling sense, not this row. |
| **Create, seat, copy** | `agent_create/staff.py::idle_instances` (excludes it from reuse), `agent_create/seat.py`, `bundled_agents/sort_existing.py` (the canonical stays with the shipped agent), `agent_duplicate.py` (`canonical_instance_stays`), `agent_copy_delete.py::_retire_channel`, `tools/agent_chat/send.py` | Duplicate will not re-point it. Deleting a copy archives the copy's own channel. Idle reuse never picks it. |
| **External gateways** (found by this plan) | `serve_gateway_auth/*`, `gateway_channel.py::channel_target_refusal` | A gateway credential is bound to instance ids (`bound_instances`). A credential bound to `personainst_<persona>` reaches the canonical row. Whether any live credential names one is a **guess**. |
| **Eternia: Chat list** | `EterniaLauncher/lib/features/ai/conversations/state/conversation_inbox_instances.dart`, `conversation_creation.dart` (the unseated pick) | The personal-instance rows ("Base Agent — New chat") are canonical rows. A pick of an instance with no workspace is treated as a pick of its agent and is resolved to a seated one (row `MC-OUTSIDE-NEW-CHAT-OPENS-ON-AN-UNSEATED-INSTANCE`). |
| **Eternia: new chat resolver** | `EterniaLauncher/lib/features/ai/conversations/state/agent_instance_use.dart`, `EterniaLauncher/lib/app/agent_console/agent_instance_placement.dart` | The rule is "reuse idle, else place in the default workspace", through hermes `runtime.agent.idle_instances` and `runtime.agent.place`. When no default workspace is known it answers the agent it was given, which is the canonical row. |
| **Eternia: agents browser** | `EterniaLauncher/lib/features/mission_control/agents_browser/agents_browser_drawer.dart`, `agent_profile_card.dart` | Already template-shaped. An unplaced persona "owns no operator channel", so it gets no composer and no console. |
| **Eternia: runtime graph** | `EterniaLauncher/lib/features/mission_control/presentation/mission_agent_runtime_graph_projection.dart` | The `unplaced` pointer state is persona-keyed: a persona with no placement. It is already template-shaped. |
| **Eternia: office** | `EterniaLauncher/lib/features/mission_control/office/mission_office_palette_policy.dart` (runtime-global rows grouped as profile backing data), `mission_office_removal_plan.dart` and `mission_office_scene_adapter.dart` (broken placements, a different term) | The palette folds canonical rows into a per-persona card and keeps them off the office. |
| **Eternia: snapshot model** | `EterniaLauncher/lib/core/services/hermes/runtime/data/snapshot/harness_agent_instance.dart` (`workspaceId`: "Null = runtime-global (canonical seeded rows, pre-pointer records)") | Decoding. |
| **Eternia: unseated create** | `EterniaLauncher/lib/core/services/hermes/runtime/data/bridge/mission_action_chat_twin_lane.dart`, `data/capabilities/harness_persona_capabilities.dart` | `agent.create` with no workspace sends no `workspace_id`, and hermes makes an unseated agent. |

Rows in the same cluster, which this plan's ruling decides:

- Eternia `MC-AN-IDLE-PERSONAL-INSTANCES-EMPTY-CHAT-PLACES-ANOTHER-INSTANCE` (BLOCKED on this plan);
- hermes `RT-FU-THE-SHIPPED-MISSION-LEAD-READS-NO-REPOS-RULES`: the shipped lead is a canonical row in no
  workspace, so it has no folder slots;
- Eternia `MC-BUNDLED-AGENTS-PICKER-READ-LIVE-WITH-SEATED-AGENTS`: its done-when opens a pick on the
  canonical row.

## 3. The owner's questions

### (a) Channels: should an operator channel depend on an instance, or the other way around?

**Today (read).** A channel is derived from an instance. `operator_channel_summary` walks the instance
rows and makes one channel per row:

- keyed by the row's session when the row is in chat mode;
- keyed by the instance id otherwise (`_channel_key_for_instance`).

History and trace rows join the channel of their session or instance. A row that matches none is
warned `history_without_instance`. So the arrow already runs instance → channel.

The problem is the canonical row. Every persona has one, so every persona gets a channel entry, even
one nobody has chatted with. That entry is the "Base Agent — New chat" row in Eternia's Chat list. In
`channel_identity`, the last-resort channel key is `persona_instance_id_for(persona_id)`. A channel
with nothing else to name it is therefore filed under the hidden copy.

**What it would become (as ruled 2026-11-21, §8).** A **live** chat belongs to an instance: the chat
an instance has loaded and is running turns in. An instance has at most one chat loaded at a time. The
agent's **saved chat history** is not owned by an instance. It stays the agent's (the persona's), and
an instance loads one of those chats on demand (§3(b): `move_chat`, the move ledger). So an operator
channel entry is a live chat on an instance, and a saved chat is listed under its agent until an
instance loads it. Nothing about either requires a hidden copy to exist:

- A placed instance with no chat yet shows as that instance with a New chat action, not as an empty
  channel. Eternia's Chat list already lists seated instances this way.
- A persona with no instance is a template. It shows in the agents browser, which already gives it no
  console.
- The `persona_instance_id_for` fallback in `channel_identity` goes. A history row with no instance
  keeps the existing `history_without_instance` warning.

### (b) Chat history is loaded by an instance on demand: is that already true, and what would change?

**Today (read): yes.** Owner 2026-11-19, row `RT-A-SAVED-CHAT-CAN-MOVE-TO-ANOTHER-INSTANCE-OF-ITS-AGENT`:
`agent_runtime/persona_chat_move.py::move_chat` is the one rebind owner. Opening a saved chat with
`move: true` (`persona_open_chat.py`, `runtime.persona.instance.open_chat`) moves it onto the chosen instance of the same
agent. The move is three writes:

1. the move ledger, `persona_assignments/chat_moves.py`;
2. the transcript's `persona_instance_id`;
3. the bind.

The transcript itself never moves. A chat whose holder was retired still moves; the agent is read from
the retirement archive. A chat's session id names the instance it was minted for
(`persona_chat_<instance>_<hex>`, `chat_session_owner_instance_id`). The ledger is what lets another
instance hold it.

**What would change.** Nothing in the move lane. Two things around it would change:

- A chat request that names a persona and no instance would stop landing on `personainst_<persona>`
  (`canonical_chat_instance_id`). It would use the same "reuse idle, else place" rule Eternia's New chat
  already asks hermes for.
- Existing chats held by canonical rows need a home. The options in §5 differ on exactly this:
  - adopt the row in place, so no chat moves;
  - or retire it and let each chat move on first open, which `move_chat` already supports for a
    retired holder.

### (c) Duplicate and retire operate on instances: why do they reference the canonical instance, and does that make sense?

**Today (read).** They do not depend on it. They guard against it, for two reasons that both come from
the mint:

- **Retire** refuses `canonical_persona_channel` (`persona_assignments/retire.py`). The next snapshot
  build would mint the row again, and every bare-persona fallback in §2.2 lands on that id. A retire
  there could not stick.
- `agent_retire.py::_canonical_instance_id` is a misleading name. It only normalises an id's spelling
  through `canonical_persona_instance_id`. It is not about the canonical row.
- **Duplicate** refuses to re-point it (`agent_duplicate.py::_check_instance`, `canonical_instance_stays`).
  Its id is derived from the ORIGINAL persona: re-pointing `personainst_base` to a copy would leave a
  row whose id names Base and whose persona is the copy. The mint would also make a fresh
  `personainst_base` at once.
- `agent_copy_delete.py::_retire_channel` archives a copy's own canonical row when the copy is
  deleted. This is the one place the row is ended deliberately.

**Does it make sense?** It makes sense only as long as the mint exists. The owner's point stands: an
operation on instances should not know about a special instance.

**What it would become.** With no mint and no canonical rows:

- the retire guard, the duplicate guard and `_retire_channel` become dead code and are deleted;
- `_canonical_instance_id` is renamed to say it normalises a spelling.

Under option (iii) below, an adopted row keeps the id `personainst_<persona>`. It must stop answering
true to `is_canonical_persona_channel`, or the guards would keep firing on an ordinary placed
instance. So the predicate is deleted, not kept.

### (d) Name-addressed sends: can only an instanced persona be messaged? What property should a send address?

**Today (read).** `tools/agent_chat/addressing.py::resolve_send_target` accepts three kinds of target:

- **A `personainst_*` handle.** It is judged on its own facts: the stored row and whether its profile
  exists.
- **A configured persona id.** It passes as given. The handler then resolves it:
  - exactly one in-scope placement → that placement;
  - two or more → `ambiguous_target`;
  - **none → the canonical row** (`chat_target.py`, `chat_turn_target.py`).
- **A display name.** It is matched against the sender-scoped addressable roster:
  - exactly one match → that instance;
  - more than one → `ambiguous_target`;
  - none → `unsupported_persona`.

So today an un-instanced persona CAN be messaged, through the canonical fallback. The closed row
`RT-FU-A-SEND-TO-AN-UNPLACED-AGENT-…` turned out to be a send to the sender itself (9773cba172).
A send to the unplaced Neko did reach it.

**What it would become.** Only an instance can be messaged.

- A send addresses an instance's handle (`personainst_*`, the stable, unique property).
- A name is resolved against what an instance has: its display name, or its persona's display name.
- A persona id is shorthand for "the one placement of this persona in my scope".
- Zero in-scope placements → refused at once, `no_instance_in_scope`, naming `agent_add_instance` (the
  agent's own placement tool), never silently placed and never sent to a hidden copy.
- The operator's own New chat is different: a person starting a chat places one, as Eternia does today.

`_addressable` would also stop minting rows as a side effect of reading the roster. The code comment
itself says "reading it mints the scope's canonical rows".

### (e) Could Base just be a reference template, and would that be simpler?

**Yes.** Base stays: the `base` persona and the `profiles/base` profile, which is also the serve's
head profile and must never be removed. Only the hidden live copy, `personainst_base`, goes. Base then
behaves like every independent agent already does (§1): a template whose live copies are placed.

**Simpler where it shows.**

- There is one kind of live agent.
- Eternia loses the personal-instance branch.
- The bare-send asymmetry closes.
- The shipped lead can have folder slots, because it stands in a workspace.
- About 37 hermes files lose the canonical predicate. The count is from `is_canonical_persona_channel`,
  `row_is_canonical_persona_channel`, `skipped_canonical`, the scope helpers, `canonical_chat_instance_id`
  and `persona_instance_id_for(`, across `agent_runtime`, `hermes_cli` and `tools`.
- The snapshot build stops writing rows it reads.

**Not free.** Existing canonical rows hold chats, sometimes goals, Work assignments, folder-slot
choices and possibly gateway bindings. They need a migration (§5), and the migration has a security
edge (§6).

## 4. A fresh install: what does a first run with no placement chat with?

**Today (read).** It chats with `personainst_base`, in no workspace, whenever a chat is opened without
going through Eternia's resolver:

- the CLI `harness persona chat send base`;
- a lead's bare send;
- a gateway bound to it.

Through Eternia's New chat, the resolver already places Base in `ws_default` and chats there, because
the serve's boot made `ws_default`. The one gap is when no default workspace is known (for example,
the facts are not read yet). Then the resolver answers the agent it was handed, which is the canonical
row.

**Template-only.** No row exists until something is placed.

- The first New chat (Eternia, or the CLI's bare-persona open) runs hermes's one "reuse idle, else
  place" rule in the default workspace. That rule is `agent_create/staff.py::idle_instances`, then
  `runtime.agent.place`. It makes `personainst_base_agent_<hex>` seated in `ws_default`, with its root
  chat, and the chat runs there.
- Upstream's `hermes chat` runs on a profile and has no persona instance, so it is unaffected.
- A send from one agent to an unplaced persona is refused (§3(d)).
- A namespace with **no workspace at all** cannot happen after a serve boot (`ensure_default_scope`).
  If an operator removed the default workspace, the place step refuses `no_workspace` with a sentence
  telling them to make one. This edge case is written down, not worked.

## 5. Options

### (i) Keep canonical instances as they are

- **Migration:** none.
- **Eternia:**
  - the cluster rows get the owner's ruling as they stand;
  - `MC-AN-IDLE` decides how to list the personal row;
  - the shipped-lead rules row needs its own slot path, or a seated lead.
- **Risk:**
  - two kinds of live agent stay;
  - the bare-send fallback keeps landing on an agent with no workspace rules and with Work reach over
    every board (`work/service.py::_agent_reach`);
  - every snapshot build keeps writing rows;
  - the 37-file predicate stays.
- **Size:** XS (rulings on three rows).

### (ii) Template-only, with fresh placements: retire every canonical row; chats move on demand

- **Migration:**
  - a reconciler phase archives each canonical row and records an alias from `personainst_<persona>`
    to nothing (a typed `retired_global_channel` answer);
  - chats stay in history and move on first open (`move_chat`, retired holder supported);
  - gateway credentials, Work assignments, running goals and folder slots on the row must each be
    re-bound or dropped;
  - peers that address `personainst_<persona>` get refused.
- **Eternia:**
  - the Chat list drops the personal rows;
  - a saved chat of a retired holder must open through the move path;
  - the creation flow's unseated branch and the palette's runtime-global grouping go;
  - the snapshot model's null workspace means "older runtime" only;
  - an unseated `agent.create` answers no instance.
- **Risk:** high.
  - Every chat's session id names an instance that no longer exists, so every one leans on the
    ledger.
  - The owner's history lists must show chats whose holder is archived. Whether they do today is a
    **guess**.
  - Gateway bindings and goals break unless each is handled.
- **Size:** XL.

### (iii) Template-only, adopting existing rows in place

The end model is the same as (ii): no mint, every live agent placed. Existing rows that hold something
become ordinary placed instances, **keeping their id**.

- **Migration:** one reconciler phase, dry-run first, a no-op the second time.
  - **Rows that hold something are adopted.** That means a chat, a running or paused goal, a Work
    assignment, folder slots or a gateway binding.
    - The row gets `workspace_id = ws_default` and its realm.
    - It is seated through the one seating write (`agent_create/seat.py::write_seat`).
    - It is stamped `adopted_from_global: <date>`.
    - It emits `persona_instance.reconciled` with `action: "adopted"`.
  - **Rows that hold nothing are archived** (retire's archive, never a delete).
  - **Chats do not move.** The id did not change, so session ids, the ledger, gateway bindings, Work
    assignees and peers addressing `personainst_<persona>` all keep resolving.
- **Edge cases, written down and not worked:**
  - a row mid-turn or holding a running goal is skipped this pass and retried at the next boot;
  - a namespace with no `ws_default` is skipped and reported.
- **Eternia:** the same as (ii), except the saved-chat path needs nothing new.
- **Risk:** medium.
  - The adopted rows keep a legacy-shaped id, so the predicate must go everywhere at once, or an
    adopted row is still treated as canonical.
  - An adopted Base loses Work reach over every board (it becomes a `ws_default` member). This is
    right, but it is a behaviour change to name to the owner.
  - The Default office gains a desk for each adopted agent.
  - Security: §6.
- **Size:** L.

### (iv) Hidden canonical: keep minting the row as an internal key, but never chat on it or list it

- **Migration:** none for rows. The bare-persona fallbacks become "reuse idle, else place" (operator)
  or a refusal (agent sends). Eternia stops listing the rows.
- **Eternia:** the same list changes as (ii).
- **Risk:**
  - the chats existing canonical rows hold become unreachable except by moving them;
  - the 37-file predicate, the mint on every read and the retire/duplicate guards all stay;
  - two kinds of instance stay, with one hidden.
- **Size:** M. This is the cheapest way to fix the user-visible symptoms, but it keeps the design flaw
  that the row filed.

## 6. Security (review w1118a.77)

**What protects the canonical row today (read).** It is machine-local:

- **Realm sync** skips it:
  - `persona_instance_sync/projection.py` lists it in `skipped_canonical`;
  - a pull refuses it with `REFUSAL_CANONICAL_CHANNEL`;
  - `realm_sync/drift.py` passes over it.
- **Peer rosters** omit it under a real scope (`peer_directory.py::peer_roster_projection` through
  `addressable_roster`).

**What a placement exposes (read).** Placing an instance is what exposes it:

- **Realm publish:** realm publish carries every persona referenced by an office placement in the
  realm's workspaces (`realm_sync/persona_artifacts.py::_office_wanted_persona_ids`). It also carries
  that persona's profile files, which includes `memories/MEMORY.md` when the persona includes profile
  memory.
- **Peer reads:** a placed instance in a workspace a peer asks about is listed in the peer roster.
  Its thread tail is then readable by `peer.thread.read` given the session id.

**Rules any migration must follow (options ii and iii):**

1. **Local scope only.** It only ever places into the local default workspace (`ws_default` in
   `realm_default`). It never places into a workspace of a realm with a sync remote. If
   `realm_default` itself has a sync remote, the row is skipped and reported, not adopted. Whether a
   default realm can carry one is a **guess**: `realm_sync/pull.py` mentions "a local-only realm with a
   sync repo". The build row reads it first.
2. **Adopted rows stay invisible to sync and peers.** A row the migration placed (stamped
   `adopted_from_global`) is skipped by realm publish, by realm drift, by the peer roster and by
   `peer.thread.read`, exactly as a canonical row is skipped today. The stamp is cleared only by an
   operator's own act: moving the agent's desk to another workspace, or an explicit share. The
   migration therefore publishes no formerly machine-local chat, memory or profile home through
   either door.
3. **Each chat stays in its account.** Each chat session keeps its `client_scope` (the account that
   owns it). Under (iii) nothing moves. Under (ii) `move_chat` keeps the transcript where it is.
4. **No new remote reach.** No new caller tier can trigger the migration. It runs inside the
   reconciler only, under the store's own locks.

## 7. Recommendation — RECOMMENDED, awaiting the owner

**Option (iii): an agent's template is its persona. Hermes stops making a hidden live copy of every
agent. Every live agent is a placed instance. Existing hidden copies that hold anything become
ordinary agents in the Default workspace, keeping their id and their chats. The ones that hold nothing
are archived.**

Why (iii) over the others:

- It gives the owner's model: one kind of live agent, and Base as a template.
- It costs one migration and no chat moves.
- Ids stay stable, so gateways, Work, peers and saved chats keep working.
- (ii) reaches the same end model, but every chat would lean on the move ledger and every binding would
  need re-pointing.
- (iv) hides the symptom and keeps the flaw.
- (i) leaves the cluster rows open.

Answers this recommendation gives the five questions, for the owner to accept or change:

- **(a)** A chat belongs to an instance. A persona with no instance has no chat. *Changed by the owner
  (§8): a **live** chat belongs to an instance; the agent's saved chat history stays the agent's and is
  loaded into an instance on demand. A persona with no instance has no live chat, but may have history.*
- **(b)** Yes, already true. Nothing moves under (iii).
- **(c)** The guards exist only because of the mint, and they are deleted with it.
- **(d)** Sends address an instance. A persona id means its one in-scope placement. Zero placements is
  refused, naming `agent_add_instance`.
- **(e)** Yes. Base is the template.

### Build rows it would need (named here, NOT filed until the owner rules)

Order: 1 → 2 → 3 in hermes, then 4 in Eternia. 5 is queue housekeeping.

1. **hermes — "A chat or send that names an agent with no instance in reach is placed or refused,
   never sent to a hidden copy"**
   - Operator opens and bare-persona CLI sends run the one "reuse idle, else place in the default
     workspace" rule (`agent_create/staff.py::idle_instances` + `runtime.agent.place`). Files:
     `chat_turn_target.py`, `chat_request.py`, `chat_open.py`, `identity.py::canonical_chat_instance_id`.
   - Agent sends with zero in-scope placements are refused `no_instance_in_scope`. Files:
     `addressing.py`, `chat_target.py`.
   - Size M.
2. **hermes — "Agents that lived nowhere become ordinary agents in the Default workspace, keeping their
   id and chats"**
   - The reconciler phase of §5(iii): adopt or archive, dry-run, idempotent, with the
     `adopted_from_global` stamp.
   - The §6 skips: realm publish, drift, peer roster, `peer.thread.read`.
   - The mid-turn and goal deferral.
   - Its first step reads whether `realm_default` can carry a sync remote, and whether `ws_default`
     always has an office to seat in (**guess**).
   - Size M.
3. **hermes — "Hermes stops making a hidden copy of every agent on startup and on every read"**
   - `ensure_for_persona` stops minting; it keeps only the name and profile re-sync of existing rows.
   - Delete `is_canonical_persona_channel` / `row_is_canonical_persona_channel` and every site in §2.2.
     That includes the retire and duplicate guards, `_retire_channel`, the scope helpers' canonical
     rules, `skipped_canonical`, the Work runtime-global reach and the `channel_identity` fallback.
   - Rename the id-spelling "canonical" helpers.
   - An unseated `runtime.agent.create` makes the agent with no instance.
   - Update `01-system-architecture.md`.
   - Size L. It can be split by family when it is filed.
4. **Eternia — "The Chat list and agent pickers show placed agents and templates only"**
   - Drop the personal-instance rows and the unseated-pick branch (`conversation_inbox_instances.dart`,
     `conversation_creation.dart`).
   - Drop the palette's runtime-global grouping.
   - An unseated `agent.create` answers no instance, and the first chat places one.
   - The snapshot model documents a null workspace as "older runtime".
   - The resolver's "no default workspace known" fallback refuses with a sentence instead of answering
     the agent.
   - Size S–M.
5. **Housekeeping, not a build row.** Once the owner rules:
   - re-state `MC-AN-IDLE-PERSONAL-INSTANCES-EMPTY-CHAT-PLACES-ANOTHER-INSTANCE` (retired by build row 4)
     and `RT-FU-THE-SHIPPED-MISSION-LEAD-READS-NO-REPOS-RULES` (the adopted lead stands in `ws_default`,
     so it can take folder slots);
   - rewrite `MC-BUNDLED-AGENTS-PICKER-READ-LIVE-WITH-SEATED-AGENTS`'s done-when.

If the owner picks another option, rows 1 and 4 survive under (iv), and all four survive under (ii)
with row 2 rewritten as retire-and-move.

## 8. Owner ruling — 2026-11-21

The owner's words, recorded on the plan row as `RULED 2026-11-21: owner`:

- On the recommendation: "happy with the Recommendation: template-only, keeping the existing copies
  that are in use." So option (iii): no hidden copy is made; existing canonical rows that hold something
  are adopted in place into the Default workspace, keeping their id; the rest are archived.
- On channels: "a better framing would be a live chat belongs to an instance, because chat history is
  still a thing". So §3(a) now reads: a live chat belongs to an instance; the agent's saved chat
  history stays the agent's and is loaded into an instance on demand.
- The owner's summary: "keeping the rule that new instances get a workspace would be coherent and no
  need to hide base because there would be no need to instance it in the first place". So every new
  instance gets a workspace, and Base is a template like any persona, with no hidden copy.
- On adoption, after the coordinator explained that a hidden Base copy holding chats becomes an
  ordinary, visible agent in Default: "thats fine we should clean it up though". The coordinator's
  interpretation, for the owner to correct, is written into build row 2's done-when: adoption is a
  one-time migration; an adopted copy whose only content is saved chats is then cleaned up (its chats
  stay in the agent's saved history, loadable into an instance on demand through `move_chat`, and the
  leftover instance is retired); a copy in live use (an open or running chat, a goal, a Work
  assignment, folder slots or a gateway binding) stays an ordinary placed agent; no chat or memory is
  lost. This narrows §5(iii), which kept every chat-holding row: chat-only copies now lean on the move
  ledger, so the §5(ii) question (does Chat history list chats of a retired holder? **guess**) is read
  first by that row.

Filed 2026-11-21 (lane w1118a-tplrows), in this order:

1. hermes `RT-A-SEND-TO-AN-AGENT-WITH-NO-INSTANCE-IN-REACH-IS-PLACED-OR-REFUSED` (§7 row 1);
2. hermes `RT-AGENTS-THAT-LIVED-NOWHERE-BECOME-ORDINARY-AGENTS-IN-THE-DEFAULT-WORKSPACE` (§7 row 2);
3. hermes `RT-HERMES-STOPS-MAKING-A-HIDDEN-COPY-OF-EVERY-AGENT` (§7 row 3), after 1 and 2;
4. Eternia `MC-THE-CHAT-LIST-AND-AGENT-PICKERS-SHOW-PLACED-AGENTS-AND-TEMPLATES-ONLY` (§7 row 4), after 3.

§7 row 5 (housekeeping) was done in the same pass; each cluster row says what happened to it.
