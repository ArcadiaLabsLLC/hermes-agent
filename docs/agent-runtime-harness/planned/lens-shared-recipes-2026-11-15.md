# Planned — sharing a Lens monitor's recipe with a workspace (2026-11-15)

**Owner domain:** Lens (`agent_runtime/lens/`) and realm sync (`agent_runtime/realm_sync/`). Parent plan
[eternia-lens-in-hermes.md](eternia-lens-in-hermes.md). Row `RT-LENS-SHARE-RECIPE-TO-WORKSPACE` (task
`TASK-ETERNIA-LENS`), ruling `OR-2026-11-09-lens-shared-recipes-opt-in`. **Status:** designed, not built
(lane w1115k-hdesign); the §9 build rows are filed and wait for a review batch.

The owner's ruling, 2026-11-09: "remote workspaces with lens setups shouldn't autmatically make my pc run
them, it should be only the recipe gets shared and you choose to enable it, like if i join a server".

## Decisions taken, owner may overrule

Standing order 2026-11-12: "if a decision comes up investigate fully and go with the recommended".

| # | Decision | Option taken | Alternative rejected | Why |
|---|---|---|---|---|
| 1 | Which channel carries a recipe | Realm sync: a `lens_recipe` whole-document family beside `level` | The backend; a workspace template | The backend holds no Lens model and a template does not move between machines (the row's 2026-11-10 handoff, confirmed in the tree). The whole-document class already exists (`realm_sync/document_family.py`) with three descriptors on it |
| 2 | Where a pulled recipe lands | On a **shelf** of files (`store/lens_recipes/<workspace>/<monitor>.json`); a DRAFT is written only when this PC's person presses Add | The pull writes each recipe straight into `LensStore.create` (what the row's handoff sketched) | `monitors.monitor_id` is one primary key for every workspace, `create` rewrites a standing draft and plants a next-revision draft on a sealed monitor, and a monitor counts against `MAXIMUM_MONITORS` (64): a pull that calls `create` lets a peer overwrite this PC's drafts and fill its capacity. With a shelf no synced code path reaches the Lens store at all, so the opt-in fence gets stricter, not looser |
| 3 | What a recipe's credential names do on arrival | Add renames every `credential_ref` to a fresh local name, `shared:<monitor_id>:<ref>`, which is unset here | Keep the publisher's ref name | A credential is found by name alone (`credentials.resolve_credential`), with no host bound to it, and `runtime.lens.preview` reads a draft with it. A shared recipe naming a ref this PC already holds would send that secret to the recipe's URL on the first preview. A fresh name cannot collide |
| 4 | What an `act` recipe may do alone on arrival | Add drops `automation.actions`; the level stays `act` | Keep the publisher's list | What a monitor may change without asking on this PC is this PC's person's decision. Without the list every change is a proposal (`manifest.py`), which is the safe reading of the same recipe |
| 5 | Which sources may be shared | `http_json`, `prometheus`, `push` | Every feed kind | `sql_readonly` names an absolute file path on the publisher's disk; `command_allowlisted` carries the argv it runs. Neither is a recipe another PC should receive in v1; refused by name, never dropped silently |
| 6 | How a recipe stops being shared | A withdrawn document (`withdrawn: true`, no manifest) replaces it | Deleting the shelf file | In the document class `upstream_absent` is never a delete, so a removed file would stay on every peer's shelf for ever. A withdrawn document travels like any edit. A monitor a peer already added keeps running: their PC, their choice |
| 7 | Drift and revert | Built, as the last slice, on the `level` family's pattern | Status counts only (the `prefab` family's shape) | The row asks for the arms, and a publisher who edited a shared recipe needs an exit that is not "publish it" |

## 1. What exists today (read on `origin/main` 28f52558)

- **Nothing carries Lens between machines.** The store is one SQLite file per runtime
  (`lens/store.py::lens_root`); `tests/agent_runtime/lens/test_lens_shared_recipes_opt_in.py` fences it
  (no module whose path matches `sync|remote|adopt|template|_take|_merge` imports `agent_runtime.lens`).
- **One create door, and it writes a DRAFT:** `LensStore.create(manifest, proposal=, proposer=,
  workspace_id=)`. `seal` freezes the draft and does not change state; only `runtime.lens.enable` reaches
  `ENABLED`, the one state the poller reads. A draft over a sealed monitor is its pending next revision.
- **A manifest holds no secret by construction** (closed schema, `manifest.read_manifest`; a URL with
  userinfo is refused at the feed reader). A feed names a credential by `credential_ref`; the bytes live in
  `<head home>/lens/credentials.json`, written by `runtime.lens.credential.set {ref, scheme, secret}`.
  `runtime.lens.get` already answers `credentials: [{feed_id, ref, set, rotated_at}]` for a draft.
- **The whole-document family class** (`realm_sync/document_family.py`): one `DocumentFamily` descriptor
  per family (`level_sync.LEVEL_FAMILY`, `map_sync.MAP_FAMILY`, `prefab_store.PREFAB_FAMILY`; prefab is
  nested, token `<profile>/<prefab>`). Stored verbatim, adopt / converge / keep local / HOLD per document
  against a never-synced baseline, an `extra_check` per family, refusals typed. `level` also has drift rows
  (`realm_sync/level_drift.py`) and a revert arm (`realm_revert_level.py`, table `realm_revert._FAMILY_ARMS`).
- **Where the tree differs from the row.** The row and its handoff say a pull "lands as a DRAFT through
  `LensStore.create`". This plan does not do that (decision 2). The draft is still written by that one
  door, and only that door; it is written when the person adds the recipe, not when the pull arrives.

## 2. The shelf: one fact, one store

"What this workspace shares" and "what this PC runs" are two facts. The Lens store keeps the second and is
not touched by anything synced. The first is a shelf of documents:

- **Path:** `store/lens_recipes/<workspace token>/<recipe id>.json` (`paths.lens_recipe_path`; published
  at the same relative path). `<recipe id>` is `paths.safe_path_token(monitor_id)`.
- **Document** (closed keys, `version` required by the class):

  ```json
  {"version": 1, "workspace_id": "ws_…", "monitor_id": "site-health", "withdrawn": false,
   "manifest": { …the sealed manifest, canonical… }}
  ```

  A withdrawn recipe is `"withdrawn": true, "manifest": null`.
- **What travels:** the sealed manifest only: sources, trigger rules, automation level and caps, schedule,
  guidance text, `persona_id`, and the NAMES of credential refs. **What never travels:** a credential
  value, an Episode, a receipt, an observation, an ingress route or its secret, the monitor's state or
  revision, a draft. None of them is in the document, and nothing reads them to build it.
- **One module, `agent_runtime/lens/recipe_shelf.py`** (`__layer__ = "stores"`): the descriptor
  `LENS_RECIPE_FAMILY`, the document reader and the two pure functions below. It imports
  `lens.manifest` and never `lens.store`.
  - `read_recipe_document(parsed)` is the family's `extra_check`, so it runs at every door (share, publish
    scan, pull, revert): closed keys, `read_manifest` on the manifest, `manifest.monitor_id ==
    monitor_id`, every feed kind in `PORTABLE_FEED_KINDS`. Typed `RecipeRefusal`:
    `recipe_not_portable`, `recipe_invalid`, `recipe_misfiled`.
  - `localize(manifest)` is what Add writes: each `credential_ref` renamed `shared:<monitor_id>:<ref>`
    (through `opaque_id`; a name past the id bound is refused, never cut), `automation.actions` removed.
- **Filed where it says** — a document whose `workspace_id` / `monitor_id` do not tokenize to its folder
  and file name is not listed and is named `recipe_misfiled` (the slot documents' `slot_document_misfiled`).

## 3. The four arms

| Arm | What happens | Built on |
|---|---|---|
| **Publish** | `_lens_recipe_publish_scan(workspaces)` lists the shelf documents of this realm's workspaces only (token's first part in the realm's workspace tokens — the level scan's scope rule) as verbatim artifacts; a document that fails `read_recipe_document` publishes nothing and is refused typed. The publish records the hashes as the new baseline (`publish.BASELINE_FAMILIES` row) | `document_publish_scan`, `update_document_baseline_after_publish` |
| **Pull** | `PullApplier("lens_recipe_sync", …)` runs `apply_document_pull` over `store/lens_recipes/`: a new or untouched recipe is adopted onto the shelf, an identical one converges, one only this PC changed is kept, one both changed is HELD (parked, exit `realm sync resolve`). A recipe for a workspace that is not this realm's is refused `recipe_outside_realm`, never written. **Nothing is created, sealed or enabled.** The ack carries `lens_recipe_sync` unconditionally (`source: null` = an older publisher) | `apply_document_pull`, plus one new optional argument `admit` (token → refusal reason or None) that the level family can adopt (§8) |
| **Drift** | One `store_drift` row per shelf document that differs from the baseline (`added` / `changed` / `removed`), keyed `<workspace token>/<recipe id>`; held and refused documents give no row; counts `lens_recipes_changed/added/removed` | `level_drift.py`'s shape, registered in `drift.DRIFT_WALKS` |
| **Revert** | `realm sync revert --item lens_recipe:<token>` restores the last-pulled bytes through the shelf's `DocumentStore.write`; a recipe the realm never carried is archived under `lens_recipe_conflicts/archive/`, then cleared | `realm_revert._FAMILY_ARMS` row, `realm_revert_level.py`'s three functions |

A revert or a pull changes the shelf only. A monitor this PC already added is never rewritten by either:
it shows `update_available` (§4) and the person adds the update or leaves it.

## 4. The RPC verbs (`agent_runtime/serve_rpc/lens_recipes.py`, tier `console`)

Every write is an RPC method; refusals carry `data.reason`.

| Verb | Params → result | Notes |
|---|---|---|
| `runtime.lens.recipe.list` | `{workspace_id?}` → `{recipes: [row], held: [recipe_id], refused: [{recipe_id, reason}]}` | Absent `workspace_id` is the active workspace. Reads the shelf and, per row, this PC's monitor of that id |
| `runtime.lens.recipe.share` | `{monitor_id}` → row | Writes the SEALED manifest (never a draft) to the shelf. `not_sealed`, `recipe_not_portable` (detail names the feed), `recipe_needs_workspace` (a monitor with no `workspace_id`) |
| `runtime.lens.recipe.withdraw` | `{workspace_id?, recipe_id}` → row | Writes the withdrawn document. `recipe_not_found` |
| `runtime.lens.recipe.add` | `{workspace_id?, recipe_id}` → monitor (as `runtime.lens.get`) | `LensStore.create(localize(manifest), workspace_id=…, recipe_hash=…)`: a new DRAFT, or a sealed monitor's next-revision draft when this workspace already holds that monitor (an update). `recipe_not_found`, `recipe_withdrawn`, `monitor_exists` (the id belongs to another workspace's monitor), and `create`'s own `capacity_refused` / `monitor_retired` |

A row is `{recipe_id, workspace_id, monitor_id, state, manifest, summary}`.

- `state` — a table over (shelf document, this PC's monitor of that id in this workspace, its
  `recipe_hash`): `not_added` · `added` (hash equal) · `update_available` (hash differs) · `withdrawn`.
- `summary` (derived, so Eternia does not parse a manifest): `{level, sources: [{feed_id, kind, host}],
  scheduled, needs_credentials: [ref], private_network, suggested_actions: [tool]}`.
- `monitors.recipe_hash` is one new nullable column, written only inside `lens/store.py` by `create` (the
  new keyword) and by `mark_shared` (the publisher's own monitor, after a share). It is the semantic
  document hash (`document_family.document_hash`), not a second copy of the recipe.
- `share`, `withdraw` and `add` append `lens.recipe.changed {workspace_id, recipe_id, change}`
  (`decision_contract_registry`). After a pull, the ack's `lens_recipe_sync.adopted` is Eternia's cue to
  re-read the list, as it is for levels.

## 5. Turning a shared recipe on (this PC's person, four existing steps after Add)

1. **Add** (`recipe.add`) — the recipe becomes a DRAFT in this workspace. Nothing runs.
2. **Sign in the sources** — `runtime.lens.get` lists each renamed ref as `set: false`;
   `runtime.lens.credential.set {ref: "shared:<monitor_id>:<ref>", scheme, secret}` binds it here. The
   person may instead edit the draft to name a credential they already hold; that is their own write
   through `runtime.lens.create`.
3. **Seal** (`runtime.lens.seal`) — `check_sealable` applies as for any draft (an `investigate` / `act`
   recipe whose `persona_id` this PC lacks is changed in the draft first).
4. **Enable** (`runtime.lens.enable`) — the only step that makes this PC poll.

A `push` feed's recipe arrives without a route: the person registers one here (`runtime.lens.ingress.register`).

## 6. What Eternia shows (launcher half; hermes answers, Eternia draws)

A "Shared with this workspace" list in the Lens panel, from `runtime.lens.recipe.list`: per recipe its
name, sources (kind and host), level, and what it asks of this PC (sign-ins needed, reads a private
address, wants to act). Actions by `state`: `not_added` → Add; `added` → opens the monitor;
`update_available` → Review update (Add, then the existing draft diff and Seal); `withdrawn` → a muted
"no longer shared" line. On a sealed monitor of the active workspace: Share / Stop sharing. An added
recipe is an ordinary draft in the existing list, with the existing sign-in, Seal and Enable controls.

The launcher row to file (for the orchestrator, verbatim, in the launcher's `mission-control-queue.md`):

> - **`MC-LENS-SHARED-RECIPES-LIST` — The Lens panel lists the watches shared with this workspace, and you add one to your own PC as a draft before anything runs** · group: eternia-lens · plan `hermes-agent/docs/agent-runtime-harness/planned/lens-shared-recipes-2026-11-15.md` §4 and §6 · reads `runtime.lens.recipe.list`; Add calls `runtime.lens.recipe.add` and opens the draft with its sign-ins unset; a sealed monitor gets Share / Stop sharing (`runtime.lens.recipe.share` / `.withdraw`); the list is re-read on `lens.recipe.changed` and after a realm pull whose `lens_recipe_sync.adopted` is not empty · designed, not built · done when: on a second machine's QA copy a recipe shared on the first shows under "Shared with this workspace", Add makes a draft that does not poll, and after sign-in, Seal and Enable it polls; read live through `launcher_qa` on Linux · REQUIRES windows, linux · NEW 2026-11-15 · BLOCKED 2026-11-15: hermes — `RT-LENS-RECIPE-SHELF-SHARE-AND-ADD` builds the four verbs

## 7. Tests, each with its killing mutation

| Guarantee | Test (layer) | Killing mutation |
|---|---|---|
| A pulled recipe is never created, sealed or polled | behavioural: pull a realm subtree carrying a recipe, then `LensStore().monitors() == []` and `LensPoller.tick() == 0` | call `LensStore().create` inside the pull applier |
| No synced module can reach the Lens store | AST, extending `test_no_sync_remote_or_template_module_reaches_lens`: the carriers that import Lens are exactly the named realm-sync modules, each imports only `agent_runtime.lens.recipe_shelf`, and `recipe_shelf` does not import `lens.store` | add `from .store import LensStore` to `recipe_shelf.py` |
| Only the operator's RPC adds a recipe | AST: the callers of `LensStore.create` are `serve_rpc/lens.py`, `serve_rpc/lens_recipes.py` and `lens/tool.py` | call `create` from `realm_sync/pull.py` |
| An added recipe cannot read a credential this PC already holds | behavioural: set credential `api`; add a recipe whose feed names `api`; `runtime.lens.preview` of the draft answers `credential_missing` and the mock transport saw no `Authorization` | make `localize` return the manifest unchanged |
| An added `act` recipe may do nothing alone | unit: `localize` output has no `automation.actions` | keep the key in `localize` |
| A command or SQL source is never shared, at either door | unit table over `PORTABLE_FEED_KINDS` (share refuses; a planted remote document is `refused` on pull) | add `command_allowlisted` to the set |
| No secret, Episode or receipt is in a published recipe | behavioural: share a monitor that has a set credential, Episodes and receipts; the published bytes contain none of `LensCredential.secret_forms()` and their keys are exactly the document's five | write `store.get(monitor_id)` (the summary) instead of the manifest |
| A realm cannot plant a recipe in another realm's workspace | behavioural: a subtree with `store/lens_recipes/<foreign token>/x.json` → `refused: recipe_outside_realm`, no file written | drop the `admit` argument |
| A withdrawn recipe cannot be added and reaches peers | behavioural: withdraw, publish, pull on a second home → `state: withdrawn`, `recipe.add` → `recipe_withdrawn` | delete the file in `withdraw` |
| An update never rewrites a running monitor | behavioural: enabled monitor at revision 1; pull a changed recipe; sealed digest unchanged, `state: update_available`; after `recipe.add` the sealed digest is still unchanged and a draft waits | have the pull applier call `recipe.add` |
| Drift and revert agree | the level arm's pair: every drift row is revert-addressable; revert restores the pulled bytes | omit the `_FAMILY_ARMS` row |

## 8. Structural notes for the builder

- **One descriptor, one reader.** `LENS_RECIPE_FAMILY` is the only description of the family; the scan,
  the applier, the status row, the drift walk and the revert arm all take it. No recipe-specific copy of
  `apply_document_pull`.
- **Realm scope is one predicate.** `apply_document_pull(family, realm_id, subtree, *, admit=None)`:
  `admit(token)` answers a refusal reason or None. The recipe family passes "the token's workspace is one
  of this realm's"; the same function scopes the publish scan. The level family pulls with no such scope
  today (`level_sync.apply_level_pull`); row `RT-REALM-LEVEL-PULL-NOT-SCOPED-TO-REALM-WORKSPACES` files it.
- **Workspace re-key.** `realm_rekey_outside.py` already moves `monitors.workspace_id`; the shelf folder
  and each document's `workspace_id` join the store-root JSON re-key (S2 checks which step covers
  `store/lens_recipes/` and adds the folder rename where it does not).
- **Secret-path scan.** `store/lens_recipes/…` carries none of `SECRET_PATH_MARKERS`; the ref names inside
  a document are not paths. The publish refuses a secret path as before.
- **The credential's missing host.** Decision 3 closes the collision for a shared recipe. The underlying
  gap — any manifest that names a ref sends that credential to whatever URL it names — stays for a
  persona's proposal and for an update that changes a source's address after the person signed it in; row
  `RT-LENS-CREDENTIAL-NOT-BOUND-TO-A-HOST` files it with the structural answer (the credential remembers
  the host it was set for).
- **Version skew.** An older hermes has no row for `store/lens_recipes/`: `_destination_for_sync_path`
  answers None and it skips the files; its own publish rebuilds the subtree without them, which a newer
  peer reads as `upstream_absent` — never a delete, so the shelf stays.

## 9. Build slices, in order (rows filed 2026-11-15, `group: eternia-lens`)

1. **`RT-LENS-RECIPE-SHELF-SHARE-AND-ADD`** — `lens/recipe_shelf.py` (document, `read_recipe_document`,
   `localize`, descriptor without sync wiring), `paths` helpers, `monitors.recipe_hash`, the four verbs,
   the event contract, §7 rows 3–7 and the state table. One PC, no realm: share a monitor, see it listed,
   add it in a second workspace's store.
2. **`RT-LENS-RECIPE-REALM-SYNC-FAMILY`** — `SyncFamily.LENS_RECIPE`, the `SYNC_PATH_FAMILIES` row, the
   scoped publish scan and baseline, the pull applier with `admit`, the status row and ack rows, the
   re-key step; §7 rows 1, 2, 8, 9, 10; the fence test's carrier list named. Read live: two namespaces on
   one Linux box, publish from one, pull in the other.
3. **`RT-LENS-RECIPE-DRIFT-AND-REVERT`** — the drift walk and counts, the revert arm, the history item
   shape; §7 row 11.

Eternia's half is `MC-LENS-SHARED-RECIPES-LIST` (§6), startable when slice 1 lands.
