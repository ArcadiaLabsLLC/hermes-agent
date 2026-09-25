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

---

## 2. The two re-seats (rule 9: ADOPT upstream's replacement; never a parallel)

### 2.1 serve's CA check → `agent.ssl_verify.install_truststore()`

**What upstream provides now.** `agent/ssl_verify.py` is the one TLS authority: `install_truststore()`
(idempotent, never raises, returns `bool`; patches `ssl.SSLContext` process-wide through `truststore`) and
`resolve_httpx_verify(...)`, which itself calls `install_truststore()` and hands httpx a shared context
(`_shared_context`) only for an explicit `ssl_ca_cert` or a set `SSL_CERT_FILE`/`SSL_CERT_DIR`. Upstream's own
call sites — `agent/agent_init.py` (in the exact line the fork's `verify_ca_bundle()` occupied),
`hermes_cli/main.py`, `run_agent.py`, `acp_adapter/entry.py`, `tui_gateway/entry.py`,
`hermes_cli/doctor_platform.check_certificates` (which now reports "platform trust store configured" instead of
validating certifi) — all call `install_truststore()` at process start. There is no CA-bundle preflight left
to keep: a missing or corrupt certifi bundle is not a failure mode the platform verifier has, and the
`HERMES_CA_BUNDLE` / `HERMES_SKIP_SSL_GUARD` env reads leave with `ssl_guard` (nothing in the launcher sets
either — checked 2026-09-25).

**Fork function that changes:** `hermes_cli/harness_parts/serve/boot.py::_prewarm_provider_runtime` (fork-only
file). Its second step becomes

```python
    try:
        from agent.ssl_verify import install_truststore

        install_truststore()
    except Exception:
        pass
```

with the docstring's "a broken CA bundle … surfaces on the first real turn with its normal typed error"
sentence rewritten (there is no typed CA error any more; `install_truststore()` logs a warning and returns
`False` when truststore is unavailable). The first step's `shared_ssl_context()` call is ruled below; the
`load_openai_cls()` warm and the `get_tool_definitions` warm are untouched.

**The recorded parallel that retires with it.** `agent/process_bootstrap.py`'s fork-added `shared_ssl_context()`,
`_ssl_context_fingerprint()`, `_SSL_CONTEXT_CACHE` and the `build_keepalive_http_client` hunk that feeds the
memoized context into transports (ledger row `agent/process_bootstrap.py`, +70/−3, `upstream`, class G4) exist
to avoid re-parsing certifi's bundle three times per chat turn. Under truststore no bundle is parsed: the
default context defers to CryptoAPI / Security.framework / OpenSSL's store, and upstream's
`resolve_httpx_verify` already shares the one context that IS expensive (an explicit `ssl_ca_cert`). The memo is
therefore a parallel of upstream's `_shared_context` whose premise is gone, and rule 9 says adopt: **delete the
fork's `shared_ssl_context` family and the `build_keepalive_http_client` verify-forwarding hunk in the merge
lane, drop the `shared_ssl_context()` step from `_prewarm_provider_runtime`, and re-measure serve's first-turn
latency on the merged tree with the boot timeline the serve test already captures** (the ~900 ms/turn figure
in the fork's test docstring was measured against certifi; if the merged tree's first turn regresses instead,
that is a NEW finding to row, not a reason to keep a memo of a parse that no longer happens). The ledger row
and PR **#121647** (`up/ssl-ca-memo`, "perf(ssl): parse the CA bundle once per CA configuration", OPEN upstream
as of 2026-09-25) **retire together**: the PR proposes memoizing a verification upstream has deleted, so it is
closed as superseded by `2f20ceb6f7` with a one-line comment, not rebased. The `agent/ssl_guard.py` ledger row
(+33/−0, "PR candidate: memoize a successful CA-bundle verification per CA fingerprint") leaves the ledger with
the file.

**Tests.**
- `tests/agent_runtime/test_harness_serve.py` already pins the RELATIONSHIP that matters at the serve level —
  the boot captures `serve_boot._prewarm_provider_runtime` as the provider prewarm and runs it after the first
  build — and is unchanged.
- The re-seat itself gets one fork-only unit test beside it (new module in `tests/agent_runtime/`, name it
  `test_serve_prewarm_truststore.py`): monkeypatch `agent.ssl_verify.install_truststore` with a recorder, call
  `_prewarm_provider_runtime()`, and assert it was called exactly once; a second case makes the recorder raise
  and asserts the prewarm still returns. That is the relationship (prewarm → upstream's one authority, failure
  isolated), not a snapshot of the function body. Killing mutation to record in the commit body: replace the
  `install_truststore()` call with `pass` — the first case reds on `calls == []`.
- `tests/agent/test_shared_ssl_context.py` (fork-only; imports `agent.ssl_guard` at module level, so it fails to
  COLLECT on the merged tree) is deleted with the memo it pins. If the owner keeps the memo (§5 Q2), the file
  instead loses its `ssl_guard` import and its three `verify_ca_bundle` cases and keeps the two
  `shared_ssl_context` cases.
- `tests/agent/test_warning_presentation.py` and `tests/acp_adapter/test_entry.py` are upstream files whose
  merged versions no longer name `ssl_guard` / `dep_ensure` (checked in the merge-tree result); nothing to do.

### 2.2 `hermes postinstall` → upstream's package manager (`pm`)

**What upstream provides now.** `pm/` is the one installer: `pm.ensure(name, *, explicit=False, …)` installs a
locked package and returns a `Runner` whose `.env["PATH"]` carries its binaries (`explicit=True` marks "a
deliberate install command — those ARE the remedy the lazy-install policy points at", which is exactly what a
post-install bootstrap is); `pm.installed_package(name)` reads the selected entry without installing;
`pm.lazy_installs_allowed()` is the consent policy (`security.allow_lazy_installs`, `HERMES_DISABLE_LAZY_INSTALLS`
for Docker and the hermetic test harness); `pm.InstallError` is the typed failure; `pm.shell.bash()` is the one
bash resolver (store-staged bash first, then `windows_bash_candidates` — which honours `HERMES_GIT_BASH_PATH`,
Git for Windows roots, `%LOCALAPPDATA%\hermes\git`, and drops the System32 / WindowsApps stubs — then PATH).
The lock (`pm/lock.json`) names `node`, `npm`, `agent-browser`, `chromium`, `ripgrep`, `ffmpeg`, `git`
(win32-only PortableGit, `optional=True`), `gh`, `uv`, `python`, `tirith`, the `llamacpp-*` engines and more.
Upstream's own consumers show the shape: `acp_adapter/entry._run_setup_browser` is now
`pm.ensure("agent-browser", explicit=True)` inside `except (pm.InstallError, OSError)`;
`hermes_cli/main_tui_launch._tui_node_bin` is `shutil.which(bin, path=ensure(bin).env["PATH"])`;
`tools/browser_tool_install` asks `pm.installed_package("agent-browser")` for readiness and `ensure("chromium")`
only under `lazy_installs_allowed()`. Upstream has no `hermes postinstall`; the fork's remains the launcher's
entry point (`hermes postinstall --yes --json`, schema `hermes.postinstall/1`, of which the launcher reads only
`git_bash_path` — `lib/features/mission_control/data/install/hermes_postinstall_verify.dart`, checked
2026-09-25 — so the schema is kept as is).

**Fork function that changes:** `hermes_cli/_downstream_cli.py::cmd_postinstall` (fork-only file, registered by
the harness plugin). Hunk by hunk:

| today (`dep_ensure`) | after (upstream `pm`) |
|---|---|
| `ensure_dependency(dep, interactive=…)` for `node`, `browser`, `ripgrep`, `ffmpeg` | `pm.ensure(name, explicit=True)` for `node`, `agent-browser`, `ripgrep`, `ffmpeg`, each inside `except (pm.InstallError, OSError)` that prints the failure and continues (today's `False` return was non-fatal too). `chromium` is NOT ensured here: upstream installs it lazily on first browser use under `lazy_installs_allowed()`, and the fork ensuring it eagerly would be the second door of rule 10. |
| the `[Y/n]` prompt on a TTY (`interactive=…`) | gone — consent is pm's policy, and `explicit=True` is the deliberate-install signal. `--yes` / `--non-interactive` keep their one remaining meaning (skip the provider setup wizard). |
| `ensure_git_bash(interactive)` → `_resolve_windows_git_bash()` (upstream `_find_bash`) → `install.ps1 -Ensure git` → persist `HERMES_GIT_BASH_PATH` User-scope via `hermes_cli.windows_env` | a fork-only `_ensure_git_bash()` in `_downstream_cli.py`: `pm.shell.bash()`; when `None` on Windows, `pm.ensure("git", explicit=True)` then `pm.shell.bash()` again; POSIX unchanged (`shutil.which("bash")` is what `pm.shell.bash()` returns there). **No env-var persistence:** `pm.shell.bash()` finds the store-staged bash first, so a pm-installed Git needs no `HERMES_GIT_BASH_PATH` to be found by a fresh process; writing it was the second door (rule 10 — upstream's resolver already reads the env var when an operator sets it, and `hermes_cli/uninstall.py` still clears it for legacy installs). §5 Q3 lets the owner keep the persistence for one release; the launcher does not depend on it — it reads `git_bash_path` off the JSON and stores it itself. |
| `_DEP_CHECKS` → the JSON `deps` map keyed `node/browser/ripgrep/ffmpeg/git/git-bash` | the same keys, computed as `pm.installed_package(pm_name) is not None` (`browser` → `agent-browser`, `git-bash` → `pm.shell.bash() is not None`, `git` → `shutil.which("git") or pm.installed_package("git")`). Keys unchanged so `hermes.postinstall/1` stays `/1`. |
| the `hermes_cli.dep_ensure` import in `cmd_postinstall` | `import pm` at the top of `cmd_postinstall` (the function-local import style the file already uses; `pm` is a top-level upstream package the plugin may import — rule 3's fence is about fork EDITS to upstream files, and this is a public upstream API). |

The `scripts/install.ps1` fork hunk that added `git` / `git-bash` to `-Ensure` (ledger row `scripts/install.ps1`,
"…`git`/`git-bash` in `--ensure`") loses its only caller with `dep_ensure` and is not re-applied (§3 takes
upstream's installer wholesale). `hermes_cli/windows_env.py` (fork-only) loses its `set_user_env` /
`broadcast_environment_change` caller from postinstall; it keeps its other callers (`hermes_cli/path_setup.py`)
and is not deleted in this merge.

**Tests.**
- `tests/hermes_cli/test_postinstall_noninteractive.py` (fork-only) is re-seated, not rewritten: `_patch_common`
  monkeypatches `pm.ensure` with a recorder (`lambda name, **kw: calls.append((name, kw.get("explicit")))`),
  `pm.installed_package` with `lambda name, **kw: None`, and `pm.shell.bash` with the constant path the
  `ensure_git_bash` stub returns today; the four existing cases keep their assertions with the calls list
  becoming `[("node", True), ("agent-browser", True), ("ripgrep", True), ("ffmpeg", True)]`. That is the
  relationship the launcher depends on — postinstall asks pm, by these names, as an explicit install — and the
  JSON-final-line and sandboxed-shim cases are unchanged. Killing mutation to record: drop `explicit=True` from
  one `pm.ensure` call — the calls-list assertion reds.
- `tests/hermes_cli/test_dep_ensure_downstream.py` (fork-only; four `ensure_git_bash` cases against the deleted
  module) is replaced by cases against the new `_ensure_git_bash` in `_downstream_cli`: POSIX no-op returns
  `pm.shell.bash()`; Windows resolves without installing when `pm.shell.bash()` answers; Windows falls back to
  `pm.ensure("git", explicit=True)` and re-resolves; Windows returns `None` when pm cannot provision. Same four
  guarantees, pm's names.
- `tests/tools/test_find_bash_windows.py` (fork-only): the one case importing `_resolve_windows_git_bash`
  (`test_wsl_stub_only_returns_none` in `TestFindWindowsGitBash`) loses its subject; the guarantee (System32
  stub rejected) is now upstream's `pm.shell.windows_bash_candidates` and is exercised by upstream's own tests,
  so the case is deleted — the sibling `test_find_bash_raises_on_wsl_stub_only` keeps pinning `_find_bash`
  through pm.
- The hermetic harness sets `HERMES_DISABLE_LAZY_INSTALLS`; no test in this set may reach a real `pm.ensure`,
  which the recorder monkeypatch guarantees. `tests/_downstream/hermes_cli_conftest/fences.py`'s
  agent-browser-probe fence names `hermes_cli.dep_ensure` in its `_AGENT_BROWSER_PROBE_BINDINGS` tuple; that
  entry must be removed or the autouse fixture reds on the missing module for every `tests/hermes_cli` test.

**Does the `dep_ensure` ledger row retire?** Yes — the file is gone; its "PR candidate (G2): `ensure_git_bash`
provisioning, git/git-bash dep checks, `-NoProfile -NonInteractive` + stdin DEVNULL for install.ps1" has no
upstream target left (pm replaced the install-script spawn entirely). Nothing of it is carried forward.
