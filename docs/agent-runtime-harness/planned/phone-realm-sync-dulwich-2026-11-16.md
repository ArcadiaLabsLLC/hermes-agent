# Planned — realm sync on a phone: dulwich as the second git, behind one port — 2026-11-16

**Owner domain:** realm sync (`agent_runtime/realm_sync/`), the bundled phone profile
(`agent_runtime/bundle_profiles/bundled-phone.yaml`), packaging (`scripts/bundle_profile_package.py`,
`scripts/bundle_profile_gate.py`). Parent plans: [bundled-phone-pool-2026-10-22.md](bundled-phone-pool-2026-10-22.md)
§1.2 (the 28-distribution phone closure), Eternia `EterniaLauncher/docs/embedded_hermes/subsystems/SPEC_2026-09-28.md`
§4.1 ("Realm sync — needs a git replacement") and §6 (size budget).
**Row:** `RT-PHONE-REALM-SYNC-BACKEND-UNCHOSEN` (group `phone-harness`, Eternia's `TASK-PHONE-HARNESS`), closed by this
plan into the slice rows of §8. **Status:** PLANNED (plan lane w1115e-dw); no slice is built.
**Measured / read:** 2026-11-16 against hermes `origin/main` 9384ac67c7; dulwich 1.2.21 in a scratch CPython 3.14
venv, with a throwaway spike (nothing of it committed); the phone closure walk
(`scripts/bundle_profile_closure.py::profile_walk` over `bundled-phone`, 2597 kept first-party modules).

## Owner ruling, 2026-11-16

> "yes" — to dulwich (pure-Python git) as the phone's second backend under the one git module
> `agent_runtime/realm_sync/git.py` (`_git` / `_git_clone`), both backends held by one shared test suite,
> rather than syncing through the realm host's web API.

## 1. What is true today

- Every realm-sync git process goes through `agent_runtime/realm_sync/git.py`: `_git` / `_git_clone` /
  `run_sync_git`, which call `agent_runtime/git_cmd.py::run_git` (`subprocess.run` of the host's git).
  Callers PARSE git's text: `_git_state` splits `rev-list --left-right --count`, `history.py` splits a custom
  `log --format`, `publish.py` and `_retire_shared_clone` test `status --porcelain` output, `_push_was_rejected`
  greps stderr for `[rejected]`.
- On a phone `agent_runtime.git_cmd` is not packaged; `agent_runtime/loop_tool_lifecycles.py` places a loud
  stand-in (`GIT_COMMAND: _loud(GIT_COMMAND, "run_git")`), so every realm verb raises `LifecycleNotShipped`.
  The phone profile records the gap (`bundled-phone.yaml` § `unswitched`: "Realm sync").
- The realm modules ship in the phone bundle (closure walk, 2026-11-16): `agent_runtime.realm_sync.*`,
  `agent_runtime.git_remote_adopt`, `agent_runtime.realm_leave`, `agent_runtime.realm_rekey_outside`,
  `agent_runtime.realm_revert_version`, `agent_runtime.serve_rpc.realm` are all kept; the realm verbs reach the phone
  through `runtime.realm.*` (`agent_runtime/serve_rpc/realm.py`).
- The credential is brokered per call: the Launcher passes `credential` inline on each `runtime.realm.*` RPC
  (`serve_rpc/realm.py::_credential` → `RealmSyncCredential.parse`); `git_extra_config()` renders it as
  `http.extraHeader=Authorization: <git_authorization>` (`Basic …` or `Bearer …`), passed as `-c`, never written to
  `.git/config` (Decision 4). Hermes keeps no realm token of its own on any device.

## 2. Decisions

- `Decided (plan):` **one typed port, two backends, chosen once per call by profile.** `+agent_runtime/realm_sync/git_port.py`
  declares `SyncGit` (a `Protocol`, the verbs of §3) and its typed results (`RepoState(ahead, behind, conflicts, dirty)`,
  `PushOutcome` = `PUSHED | REJECTED`, `FetchOutcome` = `FETCHED | EMPTY_REMOTE`, `MergeOutcome(conflicts)`,
  `LogEntry(sha, at, author, paths)`). `+agent_runtime/realm_sync/git_binary.py` is today's argv, moved behind the
  verbs (`_git` / `_git_clone` / `run_sync_git` stay in `git.py` as the binary half's runner); `+agent_runtime/realm_sync/git_dulwich.py`
  is the second. `git.py::sync_git(repo)` returns the backend for this call. Why a port and not an argv translator
  under `_git`: an argv translator would make dulwich re-render git's porcelain, log and stderr text only for the
  callers to parse it back, and every new flag a caller adds would be a silent gap; typed verbs remove the parsing
  on both sides and let one contract suite hold both backends (§5). It is still the one git module: the port, the
  selection and both backends live in `realm_sync/`, and nothing above it names a backend.
- `Decided (plan):` **the backend is chosen by profile, never by sniffing.** Config key `realm_sync.git_backend`
  (`SyncGitBackend(Enum)`: `BINARY` default, `DULWICH`), read at CALL time through `hermes_cli.config.cfg_get` in
  `git.py::sync_git_backend()`; an unknown value raises `RealmSyncError("sync_backend_unknown")`, never falls back.
  Registered in `agent_runtime/bundle_profiles/manifest.py::KEYS_READ_OUTSIDE_DEFAULTS`; `bundled-phone.yaml`
  sets `realm_sync.git_backend: dulwich`. Nothing ever asks "is there a git binary?": `shutil.which`, `host_tools.git_command`
  failure and the `LifecycleNotShipped` stand-in are never a selector (a desktop with git missing keeps failing
  loudly, as today).
- `Decided (plan):` **dulwich never starts a process.** iOS `subprocess` raises `ENOTSUP`, and the phone gate scans
  only first-party modules (`bundle_profile_gate.py::gate`, `walk.kept`), so dulwich's own spawners are invisible to
  it. The backend therefore never calls `porcelain.clone/pull/push/fetch` or `client.get_transport_and_path` (which
  may build `SubprocessGitClient` / `SSHGitClient`); it constructs `Urllib3HttpGitClient` for `http(s)://` and
  `LocalGitClient` for `file://` and plain paths, refuses `ssh://` and `git@` with `sync_remote_unreachable`
  (`safe_details.reason: "transport_not_on_this_device"`), and builds commits from objects (no `do_commit`, so no
  hook in `.git/hooks` can run). A source gate pins the negative (§5).
- `Decided (plan):` **the remote side wins exactly as `-X theirs` does today, on both backends.** dulwich has no
  strategy option: `porcelain.pull` merges with `_do_merge` (no `-X`), `merge.merge_blobs` needs the `merge3`
  package for any both-sides edit, and `merge3` is GPL-2.0-or-later only (dulwich itself is Apache-2.0 OR
  GPL-2.0-or-later) — not shippable in the Eternia app. `+agent_runtime/realm_sync/merge_theirs.py` subclasses
  `dulwich.merge.Merger`, overriding `merge_blobs` for blobs both sides changed with a stdlib `difflib` diff3 that
  keeps each side's separate hunks and takes theirs where hunks overlap; tree-shape conflicts (modify/delete,
  file/directory) stay conflicts in the index (stages 1/2/3), as git leaves them. The spike (§4.1) shows it equal
  to git on every content case.

## 3. Verb map (every git call realm sync makes)

Callers: G = `realm_sync/git.py`, P = `publish.py`, H = `history.py`, U = `pull.py`, R = `remote.py`,
A = `agent_runtime/git_remote_adopt.py` (reached from G with `run=run_sync_git`), L = `realm_leave.py`,
K = `realm_rekey_outside.py`, V = `realm_revert_version.py`. "dulwich" names the API the backend uses.

| port verb | today's argv | callers | dulwich |
|---|---|---|---|
| `init()` | `init` | G | `Repo.init`; HEAD → `refs/heads/main` |
| `clone(url, auth)` | `clone <url> <dir>` + `-c` auth | G `_git_clone` | `Repo.init` + `remote_add` + `fetch` (below) + checkout of the remote HEAD branch + upstream config — never `porcelain.clone` |
| `remote_url(name)` | `config --get remote.origin.url` | G, A | `repo.get_config().get((b"remote", name), b"url")` |
| `remotes()` | `remote` | G `_has_remote`, L | config sections `remote.*` |
| `remote_add(name, url)` | `remote add origin <url>` | G, A | `porcelain.remote_add` |
| `remote_remove(name)` | `remote remove origin` | G, R, L | `porcelain.remote_remove` **plus** deleting `refs/remotes/<name>/*` itself — dulwich drops only the config section (read in `porcelain.remote_remove`), and `_follow_server_repository` relies on git dropping the stale tracking refs |
| `current_branch()` | `symbolic-ref --short -q HEAD` | G | `repo.refs.get_symrefs()[b"HEAD"]` |
| `resolve(ref)` | `rev-parse [-q] --verify HEAD`, `rev-parse HEAD`, `rev-parse -q --verify refs/remotes/origin/<b>`, `rev-parse --verify -q <x>^{commit}` | G, H, P, A, V | `dulwich.objectspec.parse_commit`; `None` when absent |
| `is_repo()` | `rev-parse --git-dir` | A | `Repo(path)` opens |
| `rename_branch(new)` | `branch -M <b>` | G `_align_branch` | set `refs/heads/<b>`, repoint HEAD, delete the old ref |
| `point_head(branch)` | `symbolic-ref HEAD refs/heads/<b>` | G | `refs.set_symbolic_ref` |
| `is_tracked(path)` | `ls-files -- .gitattributes` | G | `path in repo.open_index()` |
| `upstream()` | `rev-parse --abbrev-ref [--symbolic-full-name] @{u}` | G, H, P, A | `branch.<b>.remote` + `.merge` config → `origin/<b>` when that ref exists |
| `set_upstream(branch)` | `branch --set-upstream-to=origin/<b>`; `push -u` | A, P | config write, never with a credential |
| `state()` → `RepoState` | `diff --name-only --diff-filter=U`; `rev-list --left-right --count HEAD...@{u}`; `rev-list --count HEAD --not --remotes`; `status --porcelain` | G `_git_state`, `_merge_remote` | conflicts = `ConflictedIndexEntry` paths; ahead/behind = `repo.get_walker(include, exclude)` counts; dirty = `porcelain.status` non-empty (untracked counted, as git's `??`) |
| `changed(paths, untracked_all)` | `status --porcelain [-- paths]`, `status --porcelain --untracked-files=all` | P, G `_retire_shared_clone`, K | `porcelain.status`, filtered by path prefix |
| `add(paths, all_under)` | `add -- <paths>`, `add -A -- realms` | P, K | `porcelain.add` **plus** index removal of deleted files under the path (`add -A` stages deletions; `porcelain.add` does not) |
| `commit(message, trailers)` | `commit [-q] -m <msg> [-m <trailer>]` | P, K | `Commit` built from `index.commit` tree, author = committer = `SYNC_IDENTITY`, ref moved with `set_if_equals`; no hooks |
| `move(old, new)` | `mv <old> <new>` | K | `os.replace` + index entries re-keyed |
| `fetch(auth, branch=None)` → `FetchOutcome` | `fetch`; `fetch -q origin <b>` | G `_refresh_remote_tracking`, A | `client.fetch(path, repo)` + `refs/remotes/origin/*` imported; a missing remote branch = `EMPTY_REMOTE` (A's `couldn't find remote ref`) |
| `pull_fast_forward(auth)` | `pull --ff-only` | G `_pull_remote_into_repo` | fetch + `graph.can_fast_forward` + `index.update_working_tree(allow_overwrite_modified=False)` + ref move |
| `merge_remote_theirs(auth)` → `MergeOutcome` | `pull --no-rebase --no-edit -X theirs` | G `_merge_remote` | fetch + `find_merge_base` + `merge_theirs.three_way` (§2) + index (conflict stages) + working tree + merge commit (two parents, `SYNC_IDENTITY`) |
| `merge_unrelated_ours(tip)` | `merge -q --allow-unrelated-histories --no-edit -X ours <tip>` | A | `three_way_merge(base=None)` with the ours-on-overlap twin (A only merges path-disjoint trees, `.gitattributes` aside, ours) |
| `push(auth, set_upstream)` → `PushOutcome` | `push`; `push -u origin HEAD`; `push -q -u origin HEAD:<b>` | P `_push_upstream`, A | `client.send_pack` whose `update_refs` refuses a non-fast-forward itself → `REJECTED` (see §4.2: the client does not) |
| `reset_hard(ref)` | `reset -q --hard origin/<b>` | A | `porcelain.reset(repo, "hard", ref)` |
| `merge_base(a, b)` / `is_ancestor(a, b)` | `merge-base HEAD <tip>`; `merge-base --is-ancestor <c> HEAD` | A, G `_retire_shared_clone` | `graph.find_merge_base` / `graph.can_fast_forward` |
| `tree_paths(ref)` | `ls-tree -r --name-only <ref>` | A | recursive tree walk |
| `has_remote_refs()` | `for-each-ref --count=1 refs/remotes` | U | `refs.keys(base=b"refs/remotes")` |
| `log(refs, subtree, limit)` → `[LogEntry]`, `newest(ref, subtree)` | `log -1 --format=%H <ref> -- <sub>`; `log --date-order -n<k> --format=… --name-only <refs> -- <sub>` | H | `repo.get_walker(include, paths=[sub], order=ORDER_DATE, max_entries)`; names from `tree_changes` |
| `read_tree_at(sha, rel)` | `cat-file -e <sha>:<rel>`; `archive --format=tar -o <f> <sha> <rel>` | V | tree lookup; files written straight out (the binary half keeps `archive`) |

`_push_was_rejected`'s stderr tells become the binary half's private way to answer `PushOutcome.REJECTED`; auth
failures become typed on both (`HTTPUnauthorized` → `sync_auth_failed`, the `host_refusal` row keeps its code).

## 4. What the spike proved (scratch venv, CPython 3.14, dulwich 1.2.21; no code kept)

### 4.1 Remote-side-wins merge

Ten scenarios, each a bare remote, a member who commits and a teammate who pushed first; the member's
`git pull --no-rebase --no-edit -X theirs` against two dulwich mergers on a copy of the same clone. Result trees
compared by hash:

| scenario | git `-X theirs` | dulwich, diff3 theirs (chosen) | dulwich, whole document theirs |
|---|---|---|---|
| disjoint files | merged | same tree | same |
| same line, both sides | theirs | same tree | same |
| far hunks, one file | both hunks | **same tree** | differs (drops ours) |
| overlap + a far hunk of ours | theirs + ours's far hunk | **same tree** | differs |
| `manifest.json` both rewrite | theirs | same tree | same |
| add/add, different bytes | theirs | same tree | same |
| modify/delete, delete/modify | conflict, path listed | conflict, same path | same |
| both delete | merged | same tree | same |
| file vs directory | conflict, `p~HEAD` listed | conflict, `p` listed | conflict, `p` |

Without `merge3` installed the chosen merger still resolves every row (it never calls `make_merge3`). The one
difference is the NAME git lists for a file/directory clash (`p~HEAD`); both refuse `sync_conflict`, and the
suite pins the refusal and a conflict list naming `p`, never the spelling.

### 4.2 Push with the brokered header

A `dulwich.web` smart-HTTP server in a thread, refusing any request whose `Authorization` is not the token:
a push with no header → `HTTPUnauthorized`; a push through `Urllib3HttpGitClient(url, config=<in-memory ConfigDict
with http.extraHeader>)` → accepted, `.git/config` byte-identical and free of the token; fetch with the same client
→ accepted. Two facts the build must carry:
- **`Urllib3HttpGitClient(extra_headers=…)` is stored and never sent** in 1.2.21 (`_http_request` reads
  `pool_manager.headers` and `_auth_header`, never `_extra_headers`); the header goes in through the config, or
  for a `Basic` credential through `username` / `password`, which dulwich sends only to the credential's own origin.
  A `Bearer` header set through the config rides the pool's headers, so S4 adds an origin check of its own and a
  test that a redirect to another origin never carries it.
- **`send_pack` does not refuse a non-fast-forward**: a diverged push went through and replaced the teammate's
  commit on the remote. `git push` refuses it client-side; the backend's `update_refs` must check
  `can_fast_forward(remote_old, local)` and answer `REJECTED` without sending — or a phone would overwrite another
  member's publish.

No credential helper is involved: dulwich consults one only through an `auth_callback`, which the backend never
passes (`get_credentials_from_store` is exported, never called by the client), and it reads no askpass.

## 5. The shared suite

- `+tests/agent_runtime/test_realm_sync_git_port.py` — the port contract, every verb of §3, each test
  parametrized over `SyncGitBackend` (fixture `sync_git_backend` in `tests/agent_runtime/conftest.py`, which sets
  `realm_sync.git_backend` in the test's config). Real repositories in `tmp_path`; fixtures may build remotes with
  the git binary (the desktop CI has it), the code under test never does on the `DULWICH` arm.
- `+tests/agent_runtime/test_realm_sync_merge_parity.py` — §4.1's ten scenarios: each runs the BINARY and
  DULWICH `merge_remote_theirs` from one starting state and asserts equal tree ids and equal conflict sets
  (file/directory by path prefix). Killing mutation: take theirs whole in `merge_theirs` → "far hunks" reds.
- `+tests/agent_runtime/test_realm_sync_dulwich_transport.py` — an in-thread `dulwich.web` server with a token
  check: auth header sent, `.git/config` free of it, 401 → `sync_auth_failed`, a diverged push → `REJECTED` and
  the remote tip unchanged (killing mutation: drop the fast-forward check → the remote tip moves, red), a
  cross-origin redirect never carries the header, `ssh://` refused.
- The existing real-repository realm suites — `test_realm_sync.py`, `_clone_per_realm`, `_clone_before_first_publish`,
  `_eol`, `_history`, `_identity`, `_local_remote`, `_publish_race`, `_publish_accounting`, `_workspace_slots`,
  `_ledger_union`, `_level_artifact`, `_skill_inbox`, `_profile_destinations`, `_tables`, `_host_refusal`,
  `test_git_remote_adopt.py`, `test_realm_leave.py`, `test_realm_revert_version.py` (~240 tests) — run on both
  arms through the same fixture, except tests that assert on argv or patch `run_git` (they stay BINARY-only,
  marked so by name in the fixture's skip list, which may only shrink).
- **No git on the DULWICH arm**: the arm's fixture installs the `agent_runtime.git_cmd` stand-in
  (`loop_tool_lifecycles.ensure_lifecycle_placeholders((GIT_COMMAND,))`) and prepends an empty `PATH`, so any
  binary call raises — the row's "realm sync runs under the phone profile without a git binary", proven on Linux.
- `+tests/agent_runtime/test_realm_sync_dulwich_spawns_nothing.py` — a source gate (a NEGATIVE, so a walk is the
  right proof): `git_dulwich.py` and `merge_theirs.py` never name `subprocess`, `get_transport_and_path`,
  `porcelain.clone|pull|push|fetch`, `SubprocessGitClient`, `SSHGitClient` or `do_commit`. Killing mutation:
  call `porcelain.clone` in `clone()` → red.

## 6. The phone closure

- **Adds one distribution: `dulwich` 1.2.21.** Its one hard requirement, `urllib3>=2.2.2`, is already in the
  closure (`uv.lock` pins 2.8.0); `typing_extensions` is required only below Python 3.12. `merge3` is NOT added
  (§2). Optional extras (`paramiko`, `merge3`, `pgp`, …) are never requested.
- **Native parts:** dulwich publishes Rust extension wheels (`_objects`, `_pack`, `_diff_tree`) for desktop
  platforms **and for Android** (`cp314-cp314-android_24_arm64_v8a`, 1.60 MB), **none for iOS**, and one pure
  wheel (`py3-none-any`, 762,744 bytes). Every extension import is guarded in dulwich (`objects.py`, `pack.py`,
  `diff_tree.py` fall back to Python). A hash-pinned install of only the pure wheel's hash on this box took the pure
  wheel (no `.so`, 3.2 MiB on disk as source) — the selection mechanism S7 uses.
- **The gate has a blind spot here:** `bundle_profile_gate.py::is_pure` passes any distribution whose `uv.lock`
  entry has a `none-any` wheel, but the pool installs the most specific wheel for the target — so on Android the
  native wheel would ship while the gate reads "pure". S7 makes the gate judge the wheel the target installs.
- **Size:** +0.73 MiB compressed (the pure wheel) on the 11.3 MiB of the 28 closure wheels (§1.2 of the pool
  plan), about 6%; on disk 3.2 MiB of source, before the bundle's bytecode bake. Against the budget (≤18 MiB
  Android delta per ABI, ≤25 MiB iOS, Eternia `SPEC_2026-09-28.md` §6) it is small, but the budget itself has
  never been measured (Eternia `MC-PHONE-SIZE-BUDGET-NEVER-MEASURED`); S7 records the bundle's size with and
  without dulwich.
- **Where it is declared:** an optional extra `realm-sync-pure = ["dulwich==1.2.21"]` (additive, fork-commented,
  like `speech-tts`), also listed in `dev` so the desktop test env runs the DULWICH arm; `bundled-phone.yaml`
  `packaging.extras: [realm-sync-pure]`. The desktop installer does not ship it.

## 7. Callers outside realm sync

From the 15 `agent_runtime` modules (plus `hermes_cli`'s update/version tooling) that call git outside
`realm_sync/`:

- **Run on a phone, so they move onto the port (S2):** `git_remote_adopt.py` (realm sync's own adoption, already
  handed `run=run_sync_git`; its `_Door` becomes the verbs; the default brain's promotion keeps the binary half),
  `realm_leave.py` (`runtime.realm.revoked` drops the clone's remotes), `realm_rekey_outside.py` (a re-join moves
  the realm subtree and commits), `realm_revert_version.py` (`runtime.realm.sync.revert` with `to`).
- **Left out — none runs git on a phone:** `realm_rekey_git.py` returns at `git_runs()` (no worktree or brain
  is cut on a phone); `work_store/writer.py`, `work_store/default_brain.py`, `brain_remote.py`, `slot_worktrees.py`,
  `repo_context.py`, `checkpoint_reviewed_restore.py`, `course_authoring.py`, `build_stamp.py`, `build_identity.py`,
  `batch/lane_git.py`, `spawn_stand_ins.py` serve workspace brains, repo slots, worktrees, checkpoints, courses and
  build identity — the paired desktop's per Eternia `SPEC_2026-09-28.md` §4.3 ("Git-backed sub-agent worktrees");
  `work/service.py` and `batch/lane_git.py` are not even in the phone closure. They keep answering the loud stand-in.
- **Left out, filed:** `realm_publishing/push.py` is reachable on a phone (`runtime.realm.publishing.push`) but
  publishes a folder from disk; on a phone it would raise the stand-in's internal error rather than a typed
  refusal (read in code, not reproduced) — row `RT-PHONE-REALM-PUBLISHING-SAYS-NOT-ON-THIS-DEVICE`, follow-up.

## 8. Slices

`+` marks a file that does not exist yet. Each slice names its killing mutation; the red goes in its commit body.
S1–S6 are hermes code only; S7 waits on lane w1115e-pb (`RT-PHONE-BUNDLE-NEEDS-TWO-LIBRARIES-IT-LEAVES-OUT`,
which is changing `bundled-phone.yaml` and the packager tests now) and ruling §9.1 is made (owner, 2026-11-16: the pure wheel on both phones).

**S1 — the port and its binary half, inside realm sync** (row `RT-PHONE-REALM-SYNC-GIT-PORT`). No behaviour
change. Files: `+agent_runtime/realm_sync/git_port.py`, `+agent_runtime/realm_sync/git_binary.py`,
`agent_runtime/realm_sync/git.py` (`sync_git`, `sync_git_backend`, `SyncGitBackend`; G's callers on verbs),
`agent_runtime/realm_sync/publish.py`, `agent_runtime/realm_sync/history.py`, `agent_runtime/realm_sync/pull.py`,
`agent_runtime/realm_sync/remote.py`, `agent_runtime/realm_sync/__init__.py` (module map),
`+tests/agent_runtime/test_realm_sync_git_port.py`, `tests/agent_runtime/conftest.py` (`sync_git_backend`, BINARY
only for now). Killing mutation: `state()` swaps ahead and behind → the port test and `test_realm_sync.py` red.

**S2 — leave, re-key and restore-a-version on the port** (row `RT-PHONE-REALM-SYNC-PORT-REACHES-LEAVE-REKEY-REVERT`).
Files: `agent_runtime/git_remote_adopt.py` (`_Door` → the port; `run=` kept for the brain's binary use),
`agent_runtime/realm_sync/git.py` (adopt called with the port), `agent_runtime/realm_leave.py`,
`agent_runtime/realm_rekey_outside.py`, `agent_runtime/realm_revert_version.py`,
`tests/agent_runtime/test_git_remote_adopt.py`, `tests/agent_runtime/test_realm_leave.py`,
`tests/agent_runtime/test_realm_revert_version.py`. Killing mutation: `remote_remove` keeps the tracking refs →
the moved-repository test reds.

**S3 — dulwich's local verbs** (row `RT-PHONE-REALM-SYNC-DULWICH-LOCAL-STEPS`). Every verb of §3 that touches
no network. Files: `+agent_runtime/realm_sync/git_dulwich.py`, `pyproject.toml` (`realm-sync-pure` extra, `dev`),
`uv.lock`, `tests/agent_runtime/test_realm_sync_git_port.py` (DULWICH arm), `tests/agent_runtime/conftest.py`,
`+tests/agent_runtime/test_realm_sync_dulwich_spawns_nothing.py`. Killing mutation: `add(all_under=…)` stops
staging deletions → the re-key port test reds on the DULWICH arm only.

**S4 — dulwich's transport with the brokered sign-in** (row `RT-PHONE-REALM-SYNC-DULWICH-TRANSPORT`).
`clone`, `fetch`, `pull_fast_forward`, `push` over `Urllib3HttpGitClient` / `LocalGitClient`; the header from
`RealmSyncCredential` in memory (`Basic` → `username`/`password`; `Bearer` → an in-memory config, origin-checked);
the fast-forward check before any send; `ssh://`/`git@` refused; 401 → `sync_auth_failed`; stderr-free typed
errors scrubbed through `_scrub_config_values`. Files: `agent_runtime/realm_sync/git_dulwich.py` (or
`+agent_runtime/realm_sync/git_dulwich_transport.py` if the module passes 800 code lines),
`+tests/agent_runtime/test_realm_sync_dulwich_transport.py`. Killing mutation in §5.

**S5 — the remote side wins, the same on both** (row `RT-PHONE-REALM-SYNC-REMOTE-WINS-MERGE`).
`merge_remote_theirs` and `merge_unrelated_ours` on dulwich: `+agent_runtime/realm_sync/merge_theirs.py` (stdlib
diff3, the `Merger` subclass, conflict stages written to the index, the merge commit), `git_dulwich.py`,
`+tests/agent_runtime/test_realm_sync_merge_parity.py`. Killing mutation in §5.

**S6 — the phone profile picks dulwich; the whole realm suite holds both** (row `RT-PHONE-REALM-SYNC-BACKEND-BY-PROFILE`).
Files: `agent_runtime/realm_sync/git.py` (the reader's refusal of an unknown value),
`agent_runtime/bundle_profiles/manifest.py` (`KEYS_READ_OUTSIDE_DEFAULTS["realm_sync.git_backend"]`),
`tests/agent_runtime/conftest.py` (both arms over the §5 file list, the shrink-only BINARY-only list, the
no-git arm), `tests/agent_runtime/test_bundle_profiles.py` (the key is a known switch). Killing mutation:
`sync_git_backend()` returns BINARY whatever the config says → every DULWICH arm reds at the stand-in. The
profile line itself lands in S7 (the file is lane w1115e-pb's now).

**S7 — the phone bundle carries the pure dulwich** (row `RT-PHONE-REALM-SYNC-PURE-WHEEL-IN-BUNDLE`).
Files: `agent_runtime/bundle_profiles/bundled-phone.yaml` (`config: realm_sync.git_backend: dulwich`,
`packaging.extras: [realm-sync-pure]`, a `packaging.pure_wheels: [dulwich]` list, the `unswitched` Realm sync entry
removed), `agent_runtime/bundle_profiles/manifest.py` (`pure_wheels` parsed and validated),
`scripts/bundles/requirement_blocks.py` (a pure-listed block keeps only its `none-any` hash),
`scripts/bundle_profile_gate.py` (`is_pure` judges the wheel the target installs),
`tests/scripts/test_bundle_profile_package.py`, `tests/agent_runtime/test_bundle_profiles.py`,
`tests/scripts/test_bundle_profile_gate.py`. Receipt: `--profile bundled-phone` for both targets, the
`packaged … distributions` line naming dulwich, no `dulwich/*.so` in the Android bundle, and `du -sh` with and
without it. Killing mutation: drop the `none-any` hash filter → the Android pool test installs the native wheel, red.

**S8 — live: a realm publishes and pulls on the Android emulator** (row `RT-PHONE-REALM-SYNC-LIVE-ON-EMULATOR`).
The builder of S7 drives Eternia's phone build on the Linux lane box's x86_64 emulator against a staging realm:
publish, a teammate's publish from the desktop, a pull that merges, and the conflict refusal. Waits on S7, Eternia
`MC-PHONE-EMBEDDED-INTEGRATION` (the app starts the embedded engine) and `RT-PHONE-EMULATOR-TARGETS` (an x86_64
bundle); TLS on the phone is `RT-PHONE-TLS-TRUST-UNPROVEN` (dulwich's urllib3 asks `CERT_REQUIRED` of the same
OpenSSL trust).

## 9. Open rulings

- **RULED 2026-11-16 (owner, "rest as reccomended"): charset-normalizer ships its pure wheel on both phones too.** S7 found the phone pools had been installing charset-normalizer's compiled wheels unseen; it is now on `packaging.pure_wheels` beside dulwich (hermes c398c4a2cc), keeping Pillow the only admitted compiled distribution.

1. **Which dulwich wheel ships on Android.** dulwich publishes an Android wheel with compiled Rust parts, but
   none for iOS. Ship the pure wheel on both phones (one behaviour on both, 0.73 MiB, nothing compiled to admit),
   or let Android take the compiled wheel (faster pack and object parsing; a second compiled library next to
   Pillow, admitted under `packaging.admitted_native`, and the two phones running different code)? ·
   Recommend: the pure wheel on both — realm repositories are small JSON trees, so speed is not the limit, and
   one build is what the shared suite proves.
   **RULED 2026-11-16:** owner — "okay yea both as reccomended": the pure wheel on both phones, no compiled
   build on Android, and the phone gate refuses the compiled one (S7, row `RT-PHONE-REALM-SYNC-PURE-WHEEL-IN-BUNDLE`).

## 10. Out of scope

- `realm_publishing/push.py` on a phone (§7, its own row); the desktop backend (stays BINARY; moving the
  desktop to dulwich is not proposed).
- dulwich's unsent `extra_headers` and its non-fast-forward `send_pack` are upstream dulwich behaviour; the
  backend routes around both and pins them, and no upstream issue is opened by this plan.
- Background sync on a phone (OS suspension, Eternia `SPEC_2026-09-28.md` §6): a sync verb runs in the foreground
  like any other RPC.
