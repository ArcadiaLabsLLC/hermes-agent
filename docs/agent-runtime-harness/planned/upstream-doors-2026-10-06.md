# Upstream doors that retire fork hunks (design sheet, lane h-doors, 2026-10-06)

Executes the ledger's `NO DOOR YET` map ([`upstream-footprint-ledger.md`](upstream-footprint-ledger.md)
§ "Door map — 2026-10-01", requests 1–3) for the four doors that retire the most fork hunks in
upstream files. Design only: no code, no PR. Designed against `upstream/main` `a036b13793`
(2026-10-06); fork hunks read at `origin/main` `937eb13354` against merge-base `ee5f49b943`.
Every door keeps today's behaviour when nothing registers: the default is the code upstream runs now.

**Existing upstream coverage, checked 2026-10-06** (`gh pr list` / `gh issue list`, `--state all`,
fourteen PR searches and seven issue searches): none of the four has a PR or issue that adds the
door. The nearest neighbours, and why they are not it:

- #127836 `feat(credentials): /creds + credential tool + encrypted store` — a NEW Fernet KV store for
  task secrets, not a backend behind the existing credential files. Not door 1.
- #44302 (issue) `keychain: credential source for pooled credentials` and the `register_secret_source`
  plugin surface (`agent/secret_sources/`) — read-only ENV-value sources run by `load_hermes_dotenv`;
  they never own a file's read/write/unlink. Door 1 sits beside them, same registrar table.
- #128813 / #110465 — the file-safety secret-store LISTS. Door 1's store policy can cite the same
  names (`agent/file_safety.py::_CREDENTIAL_FILE_NAMES`), nothing more.
- Doors 2, 3, 4: no PR, no issue (searched: optional module, minimal/slim distribution, termux,
  without openai sdk, sdk-free, httpx client, provider access, pluggable credential, provider plugin
  credentials). `pm.ensure_import` and the `_OpenAIProxy` lazy import are the hooks door 4 extends.

**Order** (files retired ÷ upstream non-test diff lines; the measurements are in each section):

| # | door | files retired | upstream diff (non-test) | ratio | PR |
|---|---|---|---|---|---|
| 1 | §A optional-module door | 6 (+1 residue) | ~40 | 0.15 | `feat(dist): module_shipped() — a distribution may omit a tool module` |
| 2 | §B SDK fallback door | 3 | ~35 | 0.086 | `feat(agent): register_sdk_fallback — a client when the provider SDK is absent` |
| 3 | §C secret-file store door | 9 (+ part B: 2 of those for free) | ~145 | 0.062 | `feat(secrets): SecretFileStore — one port behind every credential file` |
| 4 | §D provider-access door | 5 (+5 residue) | ~100 | 0.05 | `feat(providers): ProviderAccess — one owner-scoped port for provider secrets and definitions` |

Door 3 retires the most files and §C part B is a four-line bug-fix PR that can go first on its own.
Each section is one Opus lane: the lane opens the PR on a fork of `NousResearch/hermes-agent` from
`upstream/main`, with the test in the same PR; the fork change lands in the weekly merge that carries
the PR, never before (ADR 0006). The fork's current seam module stays until that merge, then becomes
the registered backend.

---

## A. Optional-module door — `hermes_constants.module_shipped()`

**Ledger rows (6 files, 27 fork lines):** `agent/client_lifecycle.py`, `agent/relay_cwd.py`,
`gateway/run_agent_cache.py`, `hermes_cli/inventory.py`, `tui_gateway/agent_callbacks.py`,
`tui_gateway/session_notifications.py`. Residue: `agent/auxiliary_client.py::_managed_local_netloc`
(a door-2 guard inside a door-4 file). Every hunk is the same shape: `from
agent_runtime.loop_tool_lifecycles import shipped; if not shipped("<module>"): return <nothing>`
before an upstream `from tools.terminal_tool import …` / `from tools.process_registry import …` /
`from hermes_cli.local_runtime… import …` that the phone wheel cannot satisfy.

**Upstream API** — in `hermes_constants.py` (already imported by every one of the six files'
packages; no new import edge):

```python
def mark_modules_omitted(*names: str) -> None:
    """A distribution declares the modules its wheel leaves out (dotted prefixes); idempotent."""

def module_shipped(name: str) -> bool:
    """False when *name* (or a declared prefix of it) was marked omitted, or ``importlib.util.find_spec``
    cannot find it; True otherwise — always True in a full install. Memoised per name."""
```

Default: nothing marked, every module found → every guard is a no-op; the six importers behave as
today. `find_spec` on a package that IS installed costs one cached lookup per name per process.

**Smallest upstream diff (~40 lines non-test):**

| file | edit |
|---|---|
| `hermes_constants.py` | the two functions, a `_OMITTED: set[str]` and a `_SHIPPED: dict[str, bool]` memo (~18 lines) |
| `agent/client_lifecycle.py::ClientLifecycleMixin…kill_processes` | `if not module_shipped("tools.process_registry"): return` before the import (2) |
| `agent/relay_cwd.py::_recorded_cwd` | `if not module_shipped("tools.terminal_tool"): return ""` (2) |
| `gateway/run_agent_cache.py` | `from hermes_cli.providers import LLAMACPP_ALIASES` instead of `hermes_cli.local_runtime.endpoint` — the provider registry already owns the aliases (`hermes_cli/providers.py::LLAMACPP_ALIASES`); no guard needed (1; a one-owner fix even without the door) |
| `hermes_cli/inventory.py::_local_runtime_row` | `if not module_shipped("hermes_cli.local_runtime"): return None` (2) |
| `tui_gateway/agent_callbacks.py::_wire_callbacks` | move the three terminal/sudo imports under `if module_shipped("tools.terminal_tool"):` with the `set_sudo_password_callback` call (6; the fork hunk verbatim minus its import line) |
| `tui_gateway/session_notifications.py::_wire_desktop_sinks`, `::_start_notification_poller` | `if not module_shipped("tools.process_registry"): return` / `return stop` (4) |
| `agent/auxiliary_client.py::_managed_local_netloc` | `if not module_shipped("hermes_cli.local_runtime"): return ""` (2) |

**Test that proves it** — `tests/test_module_shipped.py` (~40 lines): (1) `module_shipped("json")`
is True and `module_shipped("no.such.module")` is False; (2) `mark_modules_omitted("tools.terminal_tool")`
makes `module_shipped("tools.terminal_tool_sudo")` False (prefix) and `relay_cwd._recorded_cwd("k")`
returns `""` without importing `tools.terminal_tool` (assert `"tools.terminal_tool" not in sys.modules`
after a `monkeypatch.delitem` of it); (3) a child interpreter with `sys.modules["tools.process_registry"]
= None` (the stdlib way to make an import fail) runs `_wire_desktop_sinks()` and
`kill_processes()` without `ImportError`. Killing mutation: delete the guard in `_recorded_cwd`; test (2)
reds with `ImportError`.

**Fork change, file by file (lands in the merge that carries the PR):**

- the six files + `auxiliary_client._managed_local_netloc`: the fork hunks become upstream's lines
  (same guard, upstream's name) — the diff vanishes; nothing to edit after the merge resolves.
- `agent_runtime/loop_tool_lifecycles.py`: `shipped()` becomes `return module_shipped(name)` (keep the
  name for the fork's own callers: `tests/agent_runtime/test_loop_tool_lifecycles.py`,
  `scripts/bundle_profile_closure.py`); `ensure_lifecycle_placeholders()` calls
  `mark_modules_omitted(*manifest.switched_off_modules)` so placeholders and the upstream guard agree.
- `agent_runtime/bundle_profiles/manifest.py`: `packaging.switched_off_modules` is read at boot and
  handed to `mark_modules_omitted` (today it only feeds the closure script).
- ledger: six rows move from `hook` to `retired by <PR>`; `tests/fixtures/upstream_footprint.json`
  ratchets down by six files.

**Risk:** low. The guards are no-ops in a full install; the only behavioural edit is
`run_agent_cache` reading `LLAMACPP_ALIASES` from `hermes_cli.providers` (a `Tuple`) instead of
`local_runtime.endpoint` (a `frozenset`) — both are only used for membership; the lane greps the
file to confirm. Upstream may ask why a full install needs guards: the answer in the PR body is the
Termux/phone wheel class of install (`scripts/termux/` already exists upstream) and that the guards
cost one memoised lookup.

**PR summary (≤10 lines):**
```
feat(dist): module_shipped() — a distribution may omit a tool module

A subset wheel (Termux, an embedded host) can leave out tools.terminal_tool,
tools.process_registry and hermes_cli.local_runtime. Seven importers outside
those tools' own loading hard-require them. This adds hermes_constants.module_shipped(name)
(find_spec, memoised, or a prefix the distribution declared via mark_modules_omitted)
and guards those seven sites; in a full install every guard is True and nothing changes.
gateway/run_agent_cache.py now reads LLAMACPP_ALIASES from its owner, hermes_cli.providers.
Test: tests/test_module_shipped.py (child interpreter with the module missing).
```

---

## B. SDK fallback door — `process_bootstrap.register_sdk_fallback()`

**Ledger rows (3 files, ~25 fork lines after removing the door-2/3 residue and the held h-conn-pool
block):** `agent/agent_runtime_helpers.py::create_openai_client` (7), `agent/anthropic_adapter.py::_require_sdk`
(6), `agent/auxiliary_client.py::_load_openai_cls` / `::_to_async_client` (12). The fork's switch
`agent.provider_sdks: false` (`hermes_cli/config.py::config_switch`, fork-only) builds
`agent.transports.httpx_client.SdkFreeClient` / `AsyncSdkFreeClient` (chat_completions and
codex_responses wires) and `agent.transports.httpx_anthropic.SDK_FREE_ANTHROPIC` instead of
importing `openai` / `anthropic`.

**Upstream API** — in `agent/process_bootstrap.py`, which already owns the lazy `openai.OpenAI`
import (`_load_openai_cls`, `_OpenAIProxy`):

```python
def register_sdk_fallback(package: str, provider: Callable[[], Any]) -> None:
    """*provider()* returns a module-like object used in place of *package* ("openai" | "anthropic")
    when importing it fails. For "openai" it exposes ``OpenAI`` and ``AsyncOpenAI`` classes taking
    the SDK constructor kwargs; for "anthropic" the names ``agent.anthropic_adapter`` reads
    (``Anthropic``, ``AsyncAnthropic``, the error classes). One registration per package; a second
    replaces it with a WARNING."""

def sdk_fallback(package: str) -> Any | None:
    """The registered fallback object, or None."""

def load_openai_cls() -> type        # public spelling of _load_openai_cls, fallback-aware
def load_async_openai_cls() -> type  # same for openai.AsyncOpenAI
```

Default: nothing registered → `from openai import OpenAI` as today, `ImportError` as today.

**Smallest upstream diff (~35 lines non-test):**

| file | edit |
|---|---|
| `agent/process_bootstrap.py` | `_SDK_FALLBACKS: dict[str, Callable]`; the two functions; `_load_openai_cls`: `except ImportError: fb = sdk_fallback("openai"); if fb is None: raise; return fb.OpenAI`; `load_async_openai_cls` with the same shape (~22) |
| `agent/auxiliary_client.py::_load_openai_cls` | body becomes `return process_bootstrap.load_openai_cls()` (one owner; the duplicate cache goes) (3) |
| `agent/auxiliary_client.py::_to_async_client` | `AsyncOpenAI = process_bootstrap.load_async_openai_cls()` replaces `from openai import AsyncOpenAI` (1) |
| `agent/anthropic_adapter.py::_get_anthropic_sdk` | before `pm.ensure_import("anthropic")`: `if (fb := sdk_fallback("anthropic")) is not None: _anthropic_sdk = fb; return fb` — a registered fallback is never lazily installed over (3) |
| `agent/agent_runtime_helpers.py::create_openai_client` | no edit: `process_bootstrap.OpenAI(**client_kwargs)` resolves through the proxy, `install_served_model_capture` already follows it |

**Test that proves it** — `tests/agent/test_sdk_fallback.py` (~60 lines): `monkeypatch.setitem(sys.modules,
"openai", None)`, reset `process_bootstrap._OPENAI_CLS_CACHE`, register a fallback whose `OpenAI`
records its kwargs; (1) `process_bootstrap.OpenAI(api_key="k", base_url="http://x")` returns the
fallback instance and `isinstance(obj, process_bootstrap.OpenAI)` is True; (2) `auxiliary_client._to_async_client`
on that instance returns the fallback's `AsyncOpenAI`; (3) with `anthropic` blocked the same way and a
fallback registered, `anthropic_adapter._require_sdk("x")` returns it and `pm.ensure_import` was not
called (spy); (4) with nothing registered, (1) raises `ImportError`. Killing mutation: drop the
`except ImportError` branch in `_load_openai_cls`; (1) reds.

**Fork change, file by file:**

- `agent/agent_runtime_helpers.py`: delete the 7-line seam (the proxy does it).
- `agent/anthropic_adapter.py`: delete the 6-line `_require_sdk` seam.
- `agent/auxiliary_client.py`: delete the `_load_openai_cls` branch (upstream's delegation replaces it),
  the `_to_async_client` `except ImportError` and the `sdk_free_async_client` block (the fallback's
  `AsyncOpenAI` is `AsyncSdkFreeClient`, given a sync-client-shaped constructor — see risk). The
  h-conn-pool block stays its own held PR; the `provider_secret` lines go with §D; `_managed_local_netloc`
  with §A.
- `agent/transports/httpx_client.py`: `sdk_free_client()` / `sdk_free_async_client()` / `missing_sdk()`
  / `sdk_import_failure()` retire; a new `register()` at phone-profile boot (`agent_runtime` boot
  hook, where `provider_sdks_enabled()` is read today) calls
  `register_sdk_fallback("openai", lambda: SimpleNamespace(OpenAI=SdkFreeClient, AsyncOpenAI=AsyncSdkFreeClient))`
  and `register_sdk_fallback("anthropic", lambda: SDK_FREE_ANTHROPIC)`. `provider_sdks_enabled()`
  keeps its config spelling and only decides whether to register.
- tests: `tests/agent/transports/test_sdk_free_auxiliary.py` and `test_sdk_free_phone_imports.py`
  drive the registration instead of the switch; `test_httpx_client.py` / `test_httpx_anthropic.py`
  unchanged.

**Risk:** medium-low. (1) `AsyncSdkFreeClient.__init__(sync_client)` takes a sync client today; the
`AsyncOpenAI(**async_kwargs)` path hands SDK kwargs, so the fork's class gains the kwargs
constructor (build a `SdkFreeClient` inside) — fork-side work, ~10 lines. (2) `sdk_free_client`'s
early refusal of non-OpenAI-shaped wires (`SdkFreeWireUnavailable`) becomes a per-call
`AttributeError` on the resource the wire would use; the fork keeps the refusal in its own
`api_mode` resolver if it wants the early message. (3) With the SDK installed AND the switch off, the
fork today still uses the SDK-free client; with the door, the fallback only applies when the import
fails. The phone wheel omits the SDK, so its path is unchanged; the desktop profile loses the ability to
run SDK-free with the SDK present — acceptable (nothing depends on it; `bundled-desktop.yaml` ships the
SDKs). (4) Upstream's objection will be "openai is a hard dependency": the PR body says the door is
inert until a fallback is registered and that `pm.ensure_import("anthropic")` already treats the
Anthropic SDK as optional.

**PR summary (≤10 lines):**
```
feat(agent): register_sdk_fallback — a client when the provider SDK is absent

process_bootstrap already imports openai.OpenAI lazily behind _OpenAIProxy; anthropic_adapter
lazily installs `anthropic`. A host that embeds Hermes without either SDK (a phone wheel) has no
way to supply a client. This adds process_bootstrap.register_sdk_fallback(package, provider):
when `import openai` / `import anthropic` fails and a fallback is registered, the proxy, the
auxiliary client's async twin and _require_sdk use it; a registered fallback is never lazily
installed over. auxiliary_client._load_openai_cls now delegates to process_bootstrap (one cache).
Nothing registered: identical to today, including the ImportError.
Test: tests/agent/test_sdk_fallback.py (sys.modules["openai"] = None).
```

---

## C. Secret-file store door — `agent/secret_files.py::SecretFileStore`

**Ledger rows (9 files, ~45 fork lines):** `agent/anthropic_credentials.py` (`_load_json_if_exists`,
`_atomic_write_private_json`), `agent/credential_sources.py` (`adopt_external_logins_enabled`,
`_remove_hermes_pkce`), `agent/secret_scope.py` (`load_env_file`), `gateway/pairing.py`
(`_load_json_file`, `_save_json_file`, `PairingStore._all_platforms`), `hermes_cli/auth_qwen.py`
(`_read_qwen_cli_tokens`), `hermes_cli/copilot_auth.py` (`_try_gh_cli_token`), `hermes_cli/env_loader.py`
(`_sanitize_env_file_if_needed`, `load_hermes_dotenv`), `hermes_cli/webhook.py` (`_load_subscriptions`,
`_save_subscriptions`), `tools/mcp_oauth.py` (`_read_json`, `_write_json`, `HermesTokenStorage.remove`).
The fork's `agent_runtime/host_store/secret_files.py` answers each with one line: `path = view(path)`
in a reader (unbound: the path itself; bound: a `HostSecretFile` whose `exists/read_text/read_bytes/unlink`
hit the host store), `if bound(): return write_json(...)` in a writer, `with_slotted_platforms` for the
one directory listing, `external_logins_refused()` for the two borrowed-CLI-login sites.

Two of the nine are not file I/O: `copilot_auth._try_gh_cli_token` runs `gh auth token` and
`credential_sources.adopt_external_logins_enabled` is a config read. Those are **part B**.

### Part A — the port (7 files)

**Upstream API** — new `agent/secret_files.py` (~110 lines), beside `agent/secret_sources/`:

```python
class SecretFileStore(ABC):
    """Holds the bytes of a credential file instead of the disk. Paths are the disk paths the
    readers compute today; the store maps them to its own slots. Outside its root it answers
    absent (read) and refuses (write) — the store decides, not the caller."""
    name: str
    @abstractmethod
    def read(self, path: Path) -> bytes | None: ...          # None = absent
    @abstractmethod
    def write(self, path: Path, data: bytes) -> None: ...
    @abstractmethod
    def delete(self, path: Path) -> bool: ...                # True when it held a value
    def list(self, directory: Path, suffix: str) -> list[str]:   # names held under directory
        return []

# registry: ProviderRegistry[SecretFileStore], exported names register_provider / get_provider /
# list_providers (the agent/*_registry.py shape); plugins.py gains one row
# ("register_secret_file_store", "secret_file_store", "agent.secret_files", "agent.secret_files:SecretFileStore", …);
# plugin_isolation.HOST_OBJECT_BASES gains the same base.

def secret_store_bound() -> bool            # a store is registered for the current scope
def secret_path(path: Path) -> Path | SecretFileView   # unbound: path itself; bound: a view
def is_secret_view(obj) -> bool
def read_secret_bytes(path: Path) -> bytes | None       # disk read_bytes, or the store's
def write_secret_bytes(path: Path, data: bytes, *, mode: int = 0o600) -> None
def write_secret_json(path: Path, data: Any, *, mode: int = 0o600, **dump_kwargs) -> None
    # unbound: utils.atomic_json_write(path, data, mode=mode, **dump_kwargs) — today's call
def unlink_secret(path: Path, *, missing_ok: bool = True) -> bool
def list_secret_files(directory: Path, suffix: str) -> list[str]
    # unbound: [f.name[:-len(suffix)] for f in directory.iterdir() if f.name.endswith(suffix)]
    # bound: the disk listing plus store.list(directory, suffix)

class SecretFileView:   # the fork's HostSecretFile: name, exists, is_file, read_bytes, read_text,
                        # write_bytes, write_text, unlink, with_suffix; stat raises; no __fspath__
```

Default (no store): every helper is the one-line disk operation the call site performs today.

**Smallest upstream diff (~145 lines non-test):** the module (~110) + registrar row and isolation
row (~6) + the call sites (~30):

| file · function | edit |
|---|---|
| `agent/anthropic_credentials.py::_load_json_if_exists` | `path = secret_path(path)` (1) |
| `::_atomic_write_private_json` | `write_secret_json(path, payload, mode=0o600)` replaces `atomic_json_write` (1) |
| `agent/credential_sources.py::_remove_hermes_pkce` | `unlink_secret(oauth_file)` replaces `exists()`+`unlink()` (2) |
| `agent/secret_scope.py::load_env_file` | `if secret_store_bound(): return _parse_env_text(_decode_env_bytes(read_secret_bytes(env_path) or b""))` before the fstat-memoised disk path (a store slot has no descriptor) (2) |
| `gateway/pairing.py::_load_json_file` | `path = secret_path(path)` (1) |
| `::_save_json_file` | `write_secret_json(path, data, mode=0o600)` (1) |
| `::PairingStore._all_platforms` | `platforms = list_secret_files(self._dir, tail)` (1) |
| `hermes_cli/auth_qwen.py::_read_qwen_cli_tokens` | `auth_path = secret_path(auth_path)` (1; a bound store outside its root answers absent, which is the fork's refusal) |
| `hermes_cli/env_loader.py::load_hermes_dotenv` | `user_env = secret_path(home_path / ".env")` (1); `_load_dotenv_with_fallback` already reads `path.read_bytes()`, which the view answers |
| `::_sanitize_env_file_if_needed` | `if is_secret_view(path): return` — it rewrites the disk file in place (1) |
| `hermes_cli/webhook.py::_subscriptions_path` | returns `secret_path(...)` (1) |
| `::_save_subscriptions` | `write_secret_json(_subscriptions_path(), subs, mode=_SUBSCRIPTIONS_FILE_MODE)` (1) |
| `tools/mcp_oauth.py::_read_json` | `path = secret_path(path)` (1) |
| `::_write_json` | `if secret_store_bound(): return write_secret_json(path, data, default=str)` before `mkdir_under_hermes_home` / `secure_parent_dir` (a slot has no parent dir) (2) |
| `HermesTokenStorage::remove` | `unlink_secret(p, missing_ok=True)` per path (1) |

**Test that proves it** — `tests/agent/test_secret_file_store.py` (~90 lines): a `DictStore(SecretFileStore)`
registered via a plugin-context stub; (1) unbound: `secret_path(p) is p`, `write_secret_json` lands on disk at
mode 0o600 (POSIX) — the control; (2) bound: `anthropic_credentials._atomic_write_private_json(p, {...})`
leaves NO file at `p` and `_load_json_if_exists(p, "x")` returns the payload; (3) `webhook._save_subscriptions`
then `_load_subscriptions` round-trips through the store; (4) `PairingStore._all_platforms` lists a platform
the store holds and the disk does not; (5) `mcp_oauth.HermesTokenStorage.remove()` empties the store's
slots; (6) `secret_scope.load_env_file(home/".env")` parses the store's bytes with no file on disk;
(7) `env_loader.load_hermes_dotenv` with a bound store publishes `FOO=bar` from the store and
`_sanitize_env_file_if_needed` never opens the path (spy on `Path.open`). Killing mutation: revert
`_atomic_write_private_json` to `atomic_json_write`; (2) reds (plaintext file present).

**Fork change, file by file:** the seven upstream files lose their `_host_secrets` lines entirely;
`agent_runtime/host_store/secret_files.py` becomes `class HostSecretFileStore(SecretFileStore)` over
`agent_runtime.host_store.binding` (`read` = `callbacks.read(slot)`, `write` = `callbacks.write` + the
plaintext sweep, `delete`, `list` = `_known_platform_names()` filtered by `exists`), registered from the
same place `binding.bind()` runs; `view/bound/write_json/with_slotted_platforms/is_view` retire;
`tests/agent_runtime/test_host_store_seam.py` registers the store through the door;
`test_desktop_host_store.py` unchanged. The `OutsideStoreRoot` refusal stays inside the store (read →
None, write → raise), exactly as today.

### Part B — borrowed CLI logins honour `auth.adopt_external_logins` (2 files, bug-fix PR)

Upstream already has `auth.adopt_external_logins` (`agent/credential_sources.py::adopt_external_logins_enabled`,
default True) and consults it for the Claude Code / Codex token files — but NOT for `gh auth token`
(`hermes_cli/copilot_auth.py::_try_gh_cli_token`) nor the `~/.qwen` store (`hermes_cli/auth_qwen.py::_read_qwen_cli_tokens`).
The fork's `external_logins_refused()` at those two sites is the missing consult.

**Upstream diff (4 lines):** `_try_gh_cli_token`: `if not adopt_external_logins_enabled(): return None`
(cache the miss as today); `_read_qwen_cli_tokens`: raise `_qwen_err("… adopt_external_logins is off …",
"qwen_auth_refused")` when disabled. **Test:** `tests/hermes_cli/test_adopt_external_logins.py` — config
`auth: {adopt_external_logins: false}`; `_try_gh_cli_token()` returns None without spawning `gh` (spy on
`subprocess.run`); `_read_qwen_cli_tokens()` raises with the new code. Killing mutation: remove the
copilot line; the spy sees the spawn.

**Fork change:** `agent_runtime/bundle_profiles/bundled-phone.yaml` (and `bundled-desktop.yaml` if the owner
wants it) set `auth.adopt_external_logins: false`; delete the two fork hunks and `external_logins_refused()`;
`credential_sources.adopt_external_logins_enabled`'s fork hunk goes with them (the config carries it).
PR title: `fix(auth): gh and Qwen CLI logins honour auth.adopt_external_logins`.

**Risk (A+B):** medium. The module is new upstream code with a plugin surface, so review is longer
than §A/§B; the reader-side view object is the part a reviewer may push back on (a Path-like that is
not a Path). The defence: `secret_path` returns the real `Path` when unbound, so no upstream caller sees
the view unless a plugin registered a store, and the view's `stat()` raising and missing `__fspath__` are
deliberate (a bound secret never reaches `open()`/`shutil`). `load_env_file`'s fstat memo and
`mcp_oauth._write_json`'s parent-dir hardening are the two sites where "bound" takes a different
branch rather than a wrapped path; both are stated in the PR body. Multiplexed gateways: the registry is
scope-aware like every `agent/*_registry.py`, so a store registers per profile scope.

**PR summary (≤10 lines, part A):**
```
feat(secrets): SecretFileStore — one port behind every credential file

Every credential file (auth store, .anthropic_oauth.json, .env, pairing, webhook subscriptions,
MCP OAuth tokens) is read and written by its own module with pathlib + atomic_json_write. A host
that holds secrets in an OS secure store (keychain, Android Keystore, an embedding app's vault)
has no way in. This adds agent/secret_files.py: a SecretFileStore ABC plugins register
(register_secret_file_store, beside register_secret_source), and six helpers the nine sites call
(secret_path, write_secret_json, unlink_secret, list_secret_files, read_secret_bytes,
secret_store_bound). Nothing registered: each helper is the exact disk call the site made before.
Test: tests/agent/test_secret_file_store.py (no plaintext file when a store is bound).
```

---

## D. Provider-access door — `agent/provider_access.py::ProviderAccess`

**Ledger rows (5 files, ~20 fork lines):** `hermes_cli/model_switch.py::_scoped_key_env`,
`hermes_cli/runtime_provider.py::load_config` (+ the `auto`-on-disabled re-check, a separate bug-fix),
`hermes_cli/runtime_provider_custom.py::_key_env_secret` / `_match_new_style_provider`,
`tui_gateway/methods_config_set.py::_set_model`, `tui_gateway/model_switch.py::_apply_model_switch`.
Residue in `agent/anthropic_credentials.py` (`_getenv`, `_get_hermes_oauth_file`, `_root_hermes_oauth_file`),
`agent/auxiliary_client.py::_scoped_key_env`, `hermes_cli/inventory.py::load_picker_context`,
`hermes_cli/plugins.py` (the `register_provider_access` row) and `hermes_cli/auth.py`. The fork module
`agent/provider_access.py` (fork-only, 70 lines) is already the upstream shape: a `ProviderRegistry`-backed
ABC with `is_bound`, `secret(name)`, `credential_file(name, profile_home)`, `configuration(profile)`
and three readers `provider_secret` / `provider_credential_file` / `provider_configuration`.

**Upstream API** — the fork module as-is, plus one method and one consult site fewer than the fork has:

```python
class ProviderAccess(ABC):
    name: str
    def is_bound(self) -> bool
    def secret(self, name: str) -> str                      # "" = authoritative miss
    def credential_file(self, name: str, profile_home: Path) -> Path
    def configuration(self, profile: dict) -> dict          # projects, never mutates
    def forward_model_switch(self, server, rid, params, session) -> dict | None:  # NEW; default None
        return None

def current_access() -> ProviderAccess | None   # memoised per plugin-manager generation
def provider_secret(name) -> str | None          # None = unbound
def provider_credential_file(name, profile_home) -> Path
def provider_configuration(profile) -> dict
```

Default: no plugin registers → every reader returns the upstream value (`None` / `profile_home / name` /
`profile`), and `forward_model_switch` is never consulted.

**Smallest upstream diff (~100 lines non-test):**

| file · function | edit |
|---|---|
| `agent/provider_access.py` | the fork file, plus `forward_model_switch` and a generation memo on `current_access()` (~75) |
| `hermes_cli/plugins.py::_SCOPED_PROVIDER_REGISTRARS`, `hermes_cli/plugin_isolation.py::HOST_OBJECT_BASES` | one row each (6) |
| `agent/secret_scope.py::get_secret` | first line: `if (bound := provider_secret(name)) is not None: return bound` — ONE consult retires the fork's four (`anthropic_credentials._getenv`, `model_switch._scoped_key_env`, `auxiliary_client._scoped_key_env`, `runtime_provider_custom._key_env_secret`) because all four call `get_secret` next (2) |
| `hermes_cli/runtime_provider_custom.py::_match_new_style_provider` | `api_key = _key_env_secret(entry, f"providers.{ep_name}")` — the fork's one-owner fix, keep (1) |
| `agent/anthropic_credentials.py::_get_hermes_oauth_file`, `::_root_hermes_oauth_file` | `provider_credential_file(".anthropic_oauth.json", home)` (4) |
| `hermes_cli/inventory.py::load_picker_context`, `hermes_cli/runtime_provider.py::load_config`, `tui_gateway/model_switch.py::_apply_model_switch` | `cfg = provider_configuration(load_config())` (3) |
| `tui_gateway/methods_config_set.py::_set_model` | after the `running` stash: `if session.get("_compute_host_active"): if (access := current_access()) and (out := access.forward_model_switch(server, rid, params, session)) is not None: return out; return _stash_pending_model_switch(...)` — upstream's always-defer comment stays true when no access is bound (6) |

Out of scope, separate PR: `runtime_provider.resolve_runtime_provider`'s `_raise_if_provider_disabled`
re-check when `auto` lands on a disabled provider (`fix(providers): auto never resolves to a disabled
provider`, 2 lines + a test).

**Test that proves it** — `tests/agent/test_provider_access.py` exists in the fork (moves upstream with
the module) plus (1) `get_secret("X")` returns the bound access's value and never reads `os.environ`
(set `X` in environ to a different value); (2) `_get_hermes_oauth_file()` returns the access's path;
(3) `load_picker_context()` sees the projected `providers`; (4) `_set_model` with `_compute_host_active`
and a forwarding access returns the forwarder's dict, and with no access stashes (spy on
`_stash_pending_model_switch`). Killing mutation: remove the `get_secret` consult; (1) reds.

**Fork change, file by file:** `agent/provider_access.py` is the upstream file after the merge (the
fork's `register_provider_access` row in `plugins.py` is upstream's); the four `provider_secret` hunks
delete (`anthropic_credentials._getenv`, `model_switch._scoped_key_env`, `auxiliary_client._scoped_key_env`,
`runtime_provider_custom._key_env_secret` — the last keeps the one-owner call); the credential-file and
configuration hunks are upstream's lines; `tui_gateway/methods_config_set.py`'s hunk deletes and
`tui_gateway/compute_model_selection.forward` is called from the fork's `ProviderAccess.forward_model_switch`
(plugin `eternia-harness`). `hermes_cli/auth.py`'s residue is re-read by the lane against the merged tree.

**Risk:** medium. `get_secret` is on every env read, so `current_access()` must be memoised (the fork's
version calls `discover_plugins()` each time; upstream review will reject that — the generation memo is
the fix and the PR says so). The `forward_model_switch` method is a behavioural door in the TUI gateway
(idle compute-host picks reach a live owner); upstream wrote the always-defer rule for a reason, so the
PR body carries the fork's measurement (the checkmark/old-model split) and makes clear the default path is
untouched. Multiplex: "more than one bound authority" raises today; keep.

**PR summary (≤10 lines):**
```
feat(providers): ProviderAccess — one owner-scoped port for provider secrets and definitions

A host that owns the provider relationship (an embedding app with its own auth, a managed
profile) has no single place to supply provider credentials, the credential file the native
readers/writers use, or projected provider definitions; today each is read from env / HERMES_HOME
/ config.yaml at ~10 sites. This adds agent/provider_access.py (ProviderAccess ABC, registered
via register_provider_access, one bound authority per scope) consulted once in
secret_scope.get_secret, at the Anthropic OAuth file path, at the three config projections and,
for idle compute-host sessions, as an optional model-switch forwarder. Unbound: every site reads
what it reads today. Test: tests/agent/test_provider_access.py.
```

---

## E. What this sheet does not decide

- Whether §C part A and §D are one PR (both are plugin-surface rows) — two is the recommendation:
  §C is file I/O, §D is provider ownership, and one reviewer objection must not hold both.
- The ledger's request 3 also names an optional `nemo_relay` binding (`agent/relay_runtime.py`); lane
  h11-fp ruled it CANNOT MOVE (two mechanisms to save 13 lines). Unchanged.
- The h-conn-pool block in `auxiliary_client._CodexCompletionsAdapter.create` is its own held PR.
