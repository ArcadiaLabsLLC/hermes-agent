# Upstream merge 2026-09-25 — design for the next weekly merge (lane MERGE-DESIGN)

**Lane:** MERGE-DESIGN (design sitting: no merge, no production code; branch `lane/merge-design`, cut from
`origin/main` @ `9e5c578673`). **Queue row:** `Harness_Brain/20 — Active Initiatives/fork-hygiene-queue.md`,
"Next weekly merge: upstream `27df3b8847`…". **Rules of record:** `Harness_Brain/50 — Agent Handoffs/Merging
upstream.md` (the steps), `Harness_Brain/30 — Decisions/0006 …` (a real merge, weekly, in a worktree),
[`harness-plugin-and-upstream-seams.md`](harness-plugin-and-upstream-seams.md) §1 rules 9 and 10 (adopt
upstream's; a second door is a duplicate authority), `Harness_Brain/10 — Programs/Upstream Sync.md` § Each merge
(the supersession pass).

The note answers one question: what the merge lane must do so that `hermes harness serve` still boots and
`hermes postinstall` still completes after `upstream/main` is merged, and what every other conflict resolves to.

---

## 1. Sizing — from the tree, not the row

Taken 2026-09-25 with `git merge-tree --write-tree origin/main upstream/main` after `git fetch upstream`
(`origin/main` = `9e5c578673`, `upstream/main` = `ac2ffe60d0`, merge base `749220ef00`). The row was sized at
`27df3b8847` on 2026-09-24; the tree has moved since and the tree wins:

| | the row said | the tree says today |
|---|---|---|
| upstream tip | `27df3b8847` | `ac2ffe60d0` (2026-09-25 13:49 −0500) |
| range | "3,390 files" | `749220ef00..ac2ffe60d0`: **1,831 commits** (219 first-parent), 3,785 files, +221,722 / −97,815 |
| conflicts | 54 files / 73 hunks | **55 files** — 53 content conflicts carrying **74 hunks**, plus **2 modify/delete** |
| deleted modules fork code imports | `agent/ssl_guard.py` ← `hermes_cli/harness_parts/serve.py`; `hermes_cli/dep_ensure.py` ← `hermes_cli/_downstream_cli.py` | the same two modules; the serve importer is **`hermes_cli/harness_parts/serve/boot.py`** (`_prewarm_provider_runtime`) — `serve.py` was split into a package after the row was written |

`27df3b8847` ("bundles & unified installer") is a MERGE commit (parents `749220ef00`, `f05c6c522a`) and both
deletions ride under it: `2f20ceb6f7` "refactor(tls): trust the OS certificate store, one resolver" deletes
`agent/ssl_guard.py`, `agent/errors.SSLConfigurationError`, `tests/agent/test_ssl_ca_guard.py`,
`tests/hermes_cli/test_certifi_repair.py` and rewrites `agent/ssl_verify.py` around `install_truststore()`;
`5e4a2a3d24` "refactor(pm): remove legacy dependency and launch managers" deletes `hermes_cli/dep_ensure.py`
(and `tests/hermes_cli/test_dep_ensure.py`) in favour of the `pm/` package (`pm.ensure`, `pm.installed_package`,
`pm.shell.bash`, `pm.lazy_installs_allowed`).

**Every upstream-deleted non-test module, and who still imports it in the MERGED tree** (`git grep` over the
merge-tree result `9677e0339d`; eight modules deleted in the range — `agent/ssl_guard.py`,
`hermes_cli/dep_ensure.py`, `hermes_cli/gateway_service_unit.py`, `hermes_cli/plugin_python_deps.py`,
`hermes_cli/update_cmd_deps.py`, `scripts/ci/publish_e2e_evidence.py`, `scripts/install_psutil_android.py`,
`tools/environments/local_gitbash_probe.py`; six have no importer left):

| deleted module | production importer in the merged tree | fork test files importing it |
|---|---|---|
| `agent/ssl_guard.py` | `hermes_cli/harness_parts/serve/boot.py` (`verify_ca_bundle` in `_prewarm_provider_runtime`) | `tests/agent/test_shared_ssl_context.py` |
| `hermes_cli/dep_ensure.py` | `hermes_cli/_downstream_cli.py` (`ensure_dependency`, `ensure_git_bash`, `_DEP_CHECKS` in `cmd_postinstall`) | `tests/hermes_cli/test_postinstall_noninteractive.py`, `tests/hermes_cli/test_dep_ensure_downstream.py`, `tests/tools/test_find_bash_windows.py` (one import of `_resolve_windows_git_bash`) |

Every OTHER importer on `origin/main` today — `agent/agent_init.py`, `hermes_cli/doctor_platform.py`
(`verify_ca_bundle`), `acp_adapter/entry.py`, `hermes_cli/main_tui_launch.py`, `tools/browser_tool_install.py`
(`ensure_dependency`) — is an upstream file whose upstream version already carries the re-seat, and none of them
conflicts: the merge takes upstream's re-seat for free. The deleted upstream tests the fork had edited in place
(`test_ssl_ca_guard.py`, `test_certifi_repair.py`, `test_dep_ensure.py`,
`test_dep_ensure_noninteractive_spawn.py`, `tests/tools/test_browser_homebrew_paths.py`) are not in the conflict
list either: the fork had not touched them since the base, so the merge deletes them cleanly.

Two deleted SYMBOLS matter beyond the modules: `agent.errors.SSLConfigurationError` (only `ssl_guard` raised
it; the fork's `hermes_cli/doctor_platform.py` catch of it is inside an upstream hunk the merge replaces) and
the certifi premise itself — `agent/process_bootstrap.py`'s fork-added `shared_ssl_context()` (ledger row, class
G4, +70/−3) memoizes a certifi bundle parse that the truststore design no longer performs. §2.1 rules on it.

**Upstream test helpers that replace fork ones in the conflicted tests:** upstream now ships
`tests/_fixtures/platform_gating.py` (the `@pytest.mark.platforms(...)` mark), `tests/_fixtures/live_system_guard.py`
and `tests/_fixtures/env_filter.py` (the blocks `tests/conftest.py`'s two 300/550-line hunks were carved out of);
the fork's `tests/_home_env.py` and `tests/_fork_scope.py` stay fork-only.

**A prerequisite the lane pays before any test runs:** upstream adds the `truststore` dependency
(`pyproject.toml` +5 in `2f20ceb6f7`); the shared test venv `C:/Users/beast/.venvs/hermes-test` does not have it
(`import truststore` → `ModuleNotFoundError`, checked 2026-09-25). Install it first, as `snowballstemmer` and
`firecrawl-anydoc` were at the 2026-09-24 merge.
