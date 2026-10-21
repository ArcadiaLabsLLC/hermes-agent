# Planned — agent authoring on a git course: clone with a course credential, commit on a branch, open the PR — 2026-10-21

**Owner domain:** multi-device / realm sync ([09](../09-multi-device-runtime.md) § Realm sync credentials;
`agent_runtime/realm_membership.py`, `agent_runtime/realm_sync/git.py`); the Work lane's git helpers
(`agent_runtime/git_remote_adopt.py`, `agent_runtime/git_host_account.py`, `agent_runtime/batch/lane_git.py`).
Cross-repo: backend `eternia-backend/docs/architecture/planned/education-git-course-lane.md` Stage 5
(item 5 "agent authoring … nothing new on the backend beyond item 1"); launcher sheet
`EterniaLauncher/docs/education/planned/GIT_COURSE_STAGE5_STUDIO_SHEET_2026-10-19.md` §2 item 8.
**Status:** IMPLEMENTATION-READY (design lane w1021i-plans). One doc, no code.
**Measured / read:** 2026-10-21 against hermes `origin/main` d087df7035; both sibling docs read in place.

Row: `RT-REALM-COURSE-SUBJECT` (runtime-queue § Fork-owned). The parse half is on main (1e7a55248b):
`CredentialSubject.COURSE`, `_SUBJECT_PREFIXES["course:"]`, `admits_realm` false, `has_backend_realm`
false, and `realm_sync/git.py` keeps a course credential out of every realm path.

## 1. What is true today (file::symbol)

- `RealmSyncCredential` (frozen JSON: `realm_id`, `api_base`, `api_token`, `git_url`,
  `git_authorization`, `expires_at`) parses `course:<course_public_id>`; `git_extra_config()` renders
  `http.extraHeader=Authorization: …` as per-invocation `-c` pairs (never `.git/config`, never logged);
  `bearer_headers()` for the backend; expiry is fail-closed.
- The backend mints it at `POST /api/education/git-courses/{id}/clone-credential` (scope `write` for
  the author / editor collaborator, `read` for a reviewer; ~1 h GitHub token, 900 s bearer). Item 5:
  "hermes committing on a branch with a clone credential of scope `write` minted for the PERSONA'S
  player". The App "verifies, never creates" repos; PR review is GitHub's (branch protection + the App's
  check runs); the backend lists nothing for a PR.
- Hermes has every git primitive but no PR door: `git_remote_adopt.adopt_remote(repo, url, *, branch,
  config=…)` (adds/fetches/pushes with `-c` pairs), `batch/lane_git.LaneGit` (fetch, worktree, commits,
  `push_ff`), `git_host_account` (`connected_github`, `create_private_repo` over the REST helper
  `_request(method, path, authorization, body)`), `work_store/writer.Writer` (one op per commit,
  fast-forward push, sparse worktree). The realm credential reaches a serve verb inline
  (`serve_rpc/realm.py::_credential(params)`), parsed by `RealmSyncCredential.parse`.
- Nothing names a COURSE workspace: a persona's authoring target must be addressed by
  `course_public_id`, not by a slot or a realm.

## 2. Decisions

- `Decided (plan):` **a course is a checkout the persona gets per credential, under the store root,
  never a slot and never a realm.** `paths.course_checkout_dir(course_public_id)` =
  `<store_root>/courses/<safe token>/repo`; one clone per course per machine; the credential rides every
  git call as `-c` pairs and is held in memory for the verb's duration only (its `expires_at` is checked
  at every step; an expired one refuses `course_credential_expired` and the launcher re-brokers — it
  already re-brokers for sync).
- `Decided (plan):` **three verbs, one module** `agent_runtime/course_authoring.py` (`policy`), each a
  `runtime.course.*` RPC (console tier) taking the inline `credential` the way `runtime.realm.sync.*`
  does, plus the persona-facing tool the persona calls from a turn (§3 C3):
  - `runtime.course.checkout {credential}` — clone (or fetch) the course repo at its default branch
    through `adopt_remote` (ADDED_FETCHED on first clone into the empty dir; ALREADY thereafter; a
    `url_mismatch` refuses — the dir belongs to another repo).
  - `runtime.course.commit {credential, branch, message, files: {path: text}, deletes: [path]}` —
    on a branch `agent/<persona_id>/<slug>` cut from `origin/<default_branch>`, in a worktree beside the
    clone (the `LaneGit.ensure` shape), write the files (contained under the repo root, `..` refused —
    `Writer._write_files`'s rule), one commit with the persona as author (`user.name = <persona
    display name>`, `user.email = <persona_id>@eternia.agents` as `-c` pairs), push the branch
    (`push -u origin <branch>`, never force; a non-fast-forward refuses `course_branch_diverged`).
  - `runtime.course.pull_request {credential, branch, title, body}` — GitHub REST `POST
    /repos/{owner}/{repo}/pulls` through `git_host_account._request` with the credential's
    `git_authorization` (it is a repo-scoped installation token; GitHub accepts it for `pulls:write`
    only if the App's permission allows — the backend's Stage 5 says the App is `contents` +
    `metadata` today, so see § Open rulings), `base = <default_branch>`, `head = <branch>`; the reply
    carries `{number, html_url}`; an existing open PR for the branch is answered, not duplicated (GET
    `pulls?head=owner:branch` first).
  The owner / repo come from `git_url` (`https://github.com/<owner>/<repo>.git`); any other host
  refuses `git_host_unsupported` (the same word `git_host_account` uses).
- `Decided (plan):` **a course credential admits only `runtime.course.*`.** `realm_sync` already refuses
  it; the new verbs refuse every other subject (`credential_subject_mismatch`), so a realm credential
  cannot author a course and a course credential cannot sync a realm.
- `Decided (plan):` **receipts, no new envelope keys:** `course.checkout {course, outcome}`,
  `course.commit {course, branch, sha, files}`, `course.pull_request {course, branch, number}`.

## 3. Stages

**C1 — checkout** (`course_authoring.py::checkout(credential) -> CheckoutReceipt`, `paths.course_checkout_dir`,
RPC `runtime.course.checkout`). Tests (`tests/agent_runtime/test_course_authoring.py`, fake git through
the `run=` seam `adopt_remote` already exposes, a fake backend-minted credential fixture reusing
`tests/agent_runtime/test_realm_credential_subject.py`'s shape): a `course:` credential clones into the
course dir with the `-c http.extraHeader` pair present on the clone/fetch call and ABSENT from any
`config` write; a `local:` or server credential refuses `credential_subject_mismatch`; an expired one
refuses `course_credential_expired` and runs no git. Killing mutation: drop the subject check → the
mismatch test reds.

**C2 — commit** (`commit(credential, branch, message, files, deletes) -> CommitReceipt`, RPC). Tests: files
land under the worktree, one commit, author is the persona, `push -u origin agent/<persona>/<slug>`
is the push argv; `../x` refuses; a diverged branch refuses `course_branch_diverged` and never passes
`--force`. Killing mutation: drop the containment check → red; add `--force` → the argv assertion reds.

**C3 — pull request** (`pull_request(credential, branch, title, body) -> PullRequestReceipt`, RPC, and the
persona tool `course_pull_request` registered in `harness_toolset.py`'s composite so a persona's turn
can call checkout → commit → PR as one tool each; the tool takes `course_public_id` and resolves the
credential through the Launcher-brokered cache the turn was handed — see § Open rulings). Tests (fake
`_request`): POST body `{title, head, base, body}`; an existing open PR is returned without a POST;
`git_authorization` is the `Authorization` header and never appears in the receipt or the log. Killing
mutation: POST when one exists → the "no duplicate" test reds.

**C4 — docs + contract:** manifest rows, `dump_payload_contract --check`, [09] § Realm sync credentials
gains the course subject's one paragraph; the launcher's sheet §2 item 8 and the backend's item 5 are
pointed at this plan in the landing commit (cross-repo note, filed on their queues as "hermes side
landed").

## 4. Out of scope

Publishing (tag + release: the client's, item 2); PR review / check runs (GitHub + the backend, item 4);
the fork-to-GitHub export (item 3); any course content lint (the backend's `lint_manifest`); a course as
a Work board or slot.

## 5. Open rulings

- Who hands the persona the credential during a turn: the Launcher brokers `clone-credential` for the
  persona's player and passes it inline on `mission.chat.message` (a `course_credential` param the
  turn caches for its duration), or hermes calls the backend itself with the player's bearer? ·
  Recommend: the Launcher brokers and passes it inline — hermes holds no player bearer today, and the
  realm lane already works this way (`_credential(params)`); the tool in C3 reads the turn's cached
  credential and refuses `course_credential_missing` when the send carried none.
- Can the course credential's installation token open a PR? GitHub needs `pull_requests: write` on the
  App; the backend's Stage 5 lists `contents` + `metadata` (+ `checks: write` owed). · Recommend: the
  owner adds `pull_requests: write` to `eternia-server-realms` alongside the `checks: write` it already
  owes; until then C3 ships behind the refusal `pull_request_not_permitted` (GitHub 403 mapped), and
  C1–C2 land first (the branch is pushed; the author opens the PR by hand from the link in the receipt).
