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

---

# Doors 5–9 (lane h-doors-2, 2026-10-06)

Five more upstream PRs for rows the ledger marks `NO DOOR YET` / `upstream` / `carry`. Design only.
Designed against `upstream/main` `9b38eb1432` (fetched 2026-10-06); fork hunks read at
`origin/main` `ef3e4bb012` against merge-base `ee5f49b943`. Same contract as doors 1–4: every door
keeps today's behaviour when nothing registers, every PR carries its test, the fork change lands in
the weekly merge that carries the PR (ADR 0006).

**Existing upstream coverage, checked 2026-10-06** (`gh search prs` / `gh search issues`, all
states; fifteen queries answered, the search API's rate limit refused the last three — all three
Group Chat spellings; their coverage rests on the fork's own issue below):

- Door 5: **PR #129412** `fix(mcp): tolerate a missing psutil in the Windows tree-kill helper`
  (ours, open, branch `fix/process-identity-psutil-guard`, closes issue #129407) IS the
  `hermes_cli/process_identity.py` hunk verbatim, with its test. The ledger row still reads
  `carry | unreviewed`; it becomes `PR #129412 (open)`. `hermes_constants_scratch.py` has no PR.
  Neighbours that are not it: #133521 (`sample_memory` via psutil), #94507 (photon sidecar reap),
  #44898 (zombie PIDs).
- Door 6: no PR, no issue (queries: mcp notifications message hook, mcp logging callback plugin,
  mcp message_handler, mcp job finished wake, completion_queue formatter). #1794 (closed) is
  dynamic tool discovery; #104299 (merged) is delegate_task result injection.
- Door 7: no PR, no issue (`provider_error`, api error classified terminal result, failure_reason
  provider evidence). #103048 (open, resume on usage-limit reset) reads `reset_at` from the
  classifier for its own purpose and does not touch the terminal result; #82599 (open) is the
  consumer-side symptom (delegate_task reports a 401 as completed) that door 7's block answers.
- Door 8: no PR, no issue (foreground command observe running, live foreground command). #124609
  (kylecap9, open) kills in-flight foreground commands from `tui_gateway/slash_worker.py` through
  the same `_live_foreground` table door 8 widens; it is a consumer, not the door.
- Door 9: **issue #125258** (ours, open, no maintainer comment) names parts 1–4 of the host
  surface and asks the shape question (keyword parameters vs a `RoomHost` protocol). It does NOT
  name the per-message response policy, the independent task batch, the message-aware watermark,
  nor `guidance` / `shared_profiles` / `prompt_bytes` / `conclusion_member_id` on the limits.

**Order** (files retired ÷ upstream non-test diff lines):

| # | door | files retired | upstream diff (non-test) | ratio | PR |
|---|---|---|---|---|---|
| 5 | §F psutil optional | 2 (1 already filed) | ~6 new (+4 in #129412) | 0.2 | adopt #129412 + `fix(scratch): the scratch prune tolerates a missing psutil` |
| 6 | §G MCP session hooks | 3 (+1 partial) | ~30 | 0.10 | `feat(plugins): on_mcp_session / on_mcp_notification / post_mcp_call hooks and a completion-event formatter registry` |
| 7 | §H provider_error on the terminal result | 1 (+1 fork module moves) | ~32 | 0.031 | `feat(agent): terminal turn results carry the classifier's provider_error evidence` |
| 8 | §I live foreground commands | 1 (+1 fork module retires) | ~45 | 0.022 | `feat(terminal): live_foreground_commands() — observe in-flight foreground commands` |
| 9 | §J Group Chat host surface | 5 (+2 fork modules move) | ~400 in three PRs | 0.0125 | `fix(gateway): …settlement` → `feat(gateway): …host-declared limits` → `feat(gateway): …per-message response policy` |

**Placement check (CONTRIBUTING "Third-Party Product Integrations"):** none of the five is a
third-party integration. The one thing that must NOT go upstream is the fork's job-wake content
itself — `tools/mcp_job_wake.py`'s `stagec_qa_mcp_server.qa_build` logger match, the
`eternia.job_wake` capability and the `mcp_jobs.json` checkpoint are the launcher's QA server, a
product of ours. Door 6 sends only the generic hooks; the wake stays a fork plugin. Nothing to drop.

---

## F. psutil optional — `hermes_constants_scratch.py` (+ adopt #129412)

**Ledger rows (2 files, 12 fork lines):** `hermes_constants_scratch.py::_own_lineage` /
`::reap_processes_rooted_in` (8 lines), `hermes_cli/process_identity.py::_kill_process_tree_windows`
(4 lines). Both are the same shape: `try: import psutil / except ImportError: return <nothing>`.
`pyproject.toml` pins psutil as a core dependency (an android git-source pin for 3.13+), and the
tree already guards `import psutil` at twenty-plus sites (`gateway/status.py`, `agent/battery.py`,
`hermes_cli/_subprocess_compat.py`, every other site in `process_identity.py`); these two are the
odd ones out, which is the PR body's whole argument (issue #129407 made it for `process_identity`).

**Upstream API:** none — two guards.

**Smallest upstream diff (~6 lines non-test), branch `fix/scratch-prune-psutil-guard`:**

| file · function | edit |
|---|---|
| `hermes_constants_scratch.py::_own_lineage` | `try: import psutil / except ImportError: return set()` (3) |
| `::reap_processes_rooted_in` | `try: import psutil / except ImportError: return 0` before `root = …` (3) |

`_prune_scratch` (the in-module caller) deletes the doomed directories either way; without psutil
nothing is reaped first, which is what a profile without psutil already gets at the other guarded
sites. The `victims: list[tuple[psutil.Process, str]]` annotation is a local in the guarded body,
not evaluated at import — unchanged.

**Test that proves it** — `tests/test_hermes_constants_scratch_psutil.py` (~25 lines):
`monkeypatch.setitem(sys.modules, "psutil", None)` (the stdlib way to make an import fail);
(1) `_own_lineage()` returns `set()`; (2) `reap_processes_rooted_in(tmp_path, [tmp_path / "x"])`
returns `0` and raises nothing; (3) control: with psutil importable, `_own_lineage()` contains
`os.getpid()`. Killing mutation: delete the guard in `reap_processes_rooted_in`; (2) reds with
`ImportError`. #129412 already carries
`tests/tools/test_mcp_windows_orphan_fix.py::test_ledger_tree_kill_helper_tolerates_missing_psutil`.

**Fork change, file by file:** both hunks become upstream's lines in the merge that carries the
PRs; `tests/scripts/test_bundle_profile_gate.py::test_the_phones_kept_pty_and_psutil_import_sites_are_guarded`
is unchanged (it reads the guard, whoever wrote it); ledger rows `hermes_constants_scratch.py`
and `hermes_cli/process_identity.py` move to `retired by #129412 / #<new>`;
`tests/fixtures/upstream_footprint.json` ratchets down by two. Decision rule for the lane: keep
#129412 as filed (one logical change already under review, closing its own issue) and open the
scratch guard as its own two-site PR; amending #129412 restarts its review for no gain.

**Risk:** low. Reviewer question: "psutil is a hard dependency, why guard?" — same answer
#129407 gave and the tree's own twenty guards embody: packagers building a reduced interpreter,
and the android source pin that a lean install may refuse. No behaviour change with psutil present.

**PR summary (≤10 lines):**
```
fix(scratch): the scratch prune tolerates a missing psutil

hermes_constants_scratch guards nothing: _own_lineage and reap_processes_rooted_in
`import psutil` bare, so an install without psutil (a reduced interpreter; the android
source pin refused) fails the whole scratch prune instead of skipping the reap.
Every other psutil site in the tree is guarded (gateway/status.py, agent/battery.py,
hermes_cli/process_identity.py after #129412). This guards these two the same way:
no psutil, no lineage to protect and nothing reaped; the directories are still pruned.
Test: tests/test_hermes_constants_scratch_psutil.py (sys.modules["psutil"] = None).
```

---

## G. MCP session hooks — `on_mcp_session` / `on_mcp_notification` / `post_mcp_call` + a completion-event formatter registry

**Ledger rows (3 files + the transport's two fork hooks, ~12 fork lines):**
`tools/mcp_tool_handlers.py::_make_tool_handler` (`routing_for_call(kwargs)` on the worker thread,
`observe_call_result(server_name, result, routing)` on the loop thread with the raw
`CallToolResult`), `tools/mcp_tool_health.py::_make_logging_callback._on_log`
(`on_log_notification(self.name, params)`), `tools/process_registry_notifications.py::format_process_notification`
(the `mcp_job_finished` branch), `tools/mcp_tool_transport.py` (`advertise_job_wake(session)` at
the top of `_negotiate_session`; `tee_message_handler` in `_session_kwargs` and
`instrument_session` after `self.session = session` — the progress relay, `tools/mcp_progress_relay.py`).
The transport's `_build_safe_env(…, server_name=, runtime_env=)` line is PR #124210's and stays.
The whole fork half (`tools/mcp_job_wake.py`, `tools/mcp_progress_relay.py`) is a plugin that
needs four capabilities the plugin surface does not expose; CONTRIBUTING's rule for that case is a
PR that widens the generic surface, never a special case.

**Upstream API** — three hook names appended to the hook list in `hermes_cli/plugins.py` (the
`"pre_tool_call", "post_tool_call", …` tuple), dispatched through the existing
`hermes_cli.plugins.invoke_hook` / `has_hook`, plus one registrar:

```python
# hook: on_mcp_session(server_name: str, session: ClientSession, phase: "created" | "ready")
#   "created": the SDK session exists, nothing sent yet (top of _negotiate_session) — a plugin may
#   shape the capability ad or wrap a method; "ready": initialize answered, tools not yet listed.
# hook: on_mcp_notification(server_name: str, method: str, params: Any)
#   every ServerNotification the message_handler sees (after the mcp-2.0 ``.root`` unwrap), and
#   every notifications/message the logging_callback sees (the SDK routes those separately).
# hook: post_mcp_call(server_name: str, tool_name: str, arguments: dict, result: CallToolResult,
#                     call_kwargs: dict)
#   the raw result before rendering/capping, with the registry kwargs the handler was called with
#   (task_id, session routing) — snapshotted on the worker thread, delivered on the MCP loop.

# tools/process_registry_notifications.py
def register_completion_formatter(event_type: str, render: Callable[[dict], str | None]) -> None
    """A renderer for one completion_queue event type; format_process_notification consults it
    first. Re-registering replaces with a WARNING."""
```

Default: no plugin registered a hook → `has_hook` is False at each site and the line costs one
dict lookup; no formatter registered → `format_process_notification` is today's ladder.

**Smallest upstream diff (~30 lines non-test), branch `feat/mcp-session-hooks`:**

| file · function | edit |
|---|---|
| `hermes_cli/plugins.py` hook-name tuple | three names (1) + the hooks table in `website/docs/developer-guide/build-a-hermes-plugin` (docs, 3 rows) |
| `tools/mcp_tool_handlers.py::_make_tool_handler._handler` | `call_kwargs = dict(kwargs)` beside `read_only` (1); in `_call` after `_call_tool_racing_stdio_death`: `if has_hook("post_mcp_call"): invoke_hook("post_mcp_call", server_name=server_name, tool_name=tool_name, arguments=args, result=result, call_kwargs=call_kwargs)` (3) |
| `tools/mcp_tool_health.py::_on_log` | first line of the `try`: `if has_hook("on_mcp_notification"): invoke_hook("on_mcp_notification", server_name=self.name, method="notifications/message", params=params)` (2) |
| `tools/mcp_tool_health.py::_make_message_handler._handler` | after the `payload = getattr(message, "root", message)` unwrap: the same two lines with `method=getattr(payload, "method", "")`, `params=getattr(payload, "params", None)` (2) |
| `tools/mcp_tool_transport.py::_negotiate_session` | first statement: `if has_hook("on_mcp_session"): invoke_hook("on_mcp_session", server_name=self.name, session=session, phase="created")` (2) |
| `::` the method that sets `self.session = session` | after it: the same with `phase="ready"` (2) |
| `tools/process_registry_notifications.py` | `_COMPLETION_FORMATTERS: dict[str, Callable]`, `register_completion_formatter` (~8); `format_process_notification` first line: `if (render := _COMPLETION_FORMATTERS.get(evt_type)) is not None: return render(evt)` (2) |

`invoke_hook` already isolates a raising plugin from the caller (it returns the list of results);
the lane confirms by reading `hermes_cli/plugins.py::invoke_hook` and states it in the PR body.
If review asks for a `ctx.register_completion_formatter`, that is one row in `PluginContext`.

**Test that proves it** — `tests/tools/test_mcp_plugin_hooks.py` (~80 lines), using the MCP test
doubles the existing `tests/tools/test_mcp_*` files already build and a recording hook registered
through the plugin-manager test fixture: (1) a `_make_tool_handler(...)` handler with
`_call_tool_racing_stdio_death` stubbed to return a `CallToolResult` → `post_mcp_call` saw that
same object (`is`), the server name, the raw arguments and `call_kwargs["task_id"]`; (2)
`_make_logging_callback()(params)` → `on_mcp_notification` with `method == "notifications/message"`;
`_make_message_handler()(ProgressNotification(...))` → the same hook with
`"notifications/progress"` and the SDK params object; (3) `_negotiate_session` against a fake
session → phases `["created", "ready"]` in that order, "created" before the fake's `initialize`
was awaited; (4) `register_completion_formatter("x_finished", f)` → `format_process_notification({"type": "x_finished"})`
is `f`'s text, and an unregistered type still renders the stock completion text (the control).
Killing mutation: delete the `post_mcp_call` invoke in `_call`; (1) reds. Second: delete the
formatter consult; (4) reds with the phantom "process exited (exit code ?)" text.

**Fork change, file by file:** the fork lines in the four upstream files delete. `tools/mcp_job_wake.py`
registers from the `eternia-harness` plugin's `register(ctx)`: `post_mcp_call` →
`observe_call_result(server_name, result, routing_for_call(call_kwargs))` (one function now, the
routing read moves off the worker thread because `call_kwargs` is a plain dict — the contextvars
reason for the split is gone), `on_mcp_notification` → `on_log_notification` when
`method == "notifications/message"`, `on_mcp_session` phase `created` → `advertise_job_wake(session)`
(the `_build_capabilities` wrap stays fork-side; the SDK hard-codes `experimental=None`, so no
smaller upstream door exists for the ad), `register_completion_formatter(EVENT_TYPE, format_job_finished)`.
`tools/mcp_progress_relay.py`: `on_mcp_session` phase `ready` → `instrument_session`,
`on_mcp_notification` → the tee's progress fold (the tee wrapper retires). Residue, not this door:
`tools/registry.py`'s `enter_dispatch` / `exit_dispatch` bracket (thread-keyed record; its own
ledger row). Tests `tests/tools/test_mcp_job_wake.py`, `test_mcp_job_wake_turn.py` drive the
hooks instead of patching the seams.

**Risk:** medium-low. (1) The hooks run on the MCP loop thread; a slow plugin stalls that
server's loop — the PR body states the contract (return fast, never await). (2) Review will ask
"why not `post_tool_call`?": it carries the capped handler JSON and the prefixed tool name, not the
server, the raw `CallToolResult` or the routing kwargs (the ledger's reason the fork could not
re-route). (3) Three hooks in one PR is one logical change ("MCP session observability for
plugins"); if review wants it split, `post_mcp_call` + the formatter registry is the half that
retires three of the four files.

**PR summary (≤10 lines):**
```
feat(plugins): on_mcp_session / on_mcp_notification / post_mcp_call hooks, completion formatters

A plugin that wants to act on what an MCP server says — a progress notification for a
long tool call, a "job finished" log event that should wake the agent that started the
job, a capability it wants to advertise at initialize — has no door: the session kwargs,
the logging callback and the raw CallToolResult are all closures inside tools/mcp_tool_*.
This adds three hooks dispatched through the existing invoke_hook (one has_hook check per
site, nothing registered = today's code) and register_completion_formatter so a plugin
can render its own completion_queue event type where the CLI/TUI/gateway drains already
inject [IMPORTANT: …]. Test: tests/tools/test_mcp_plugin_hooks.py.
```

---

## H. Terminal-result evidence — `result["provider_error"]` from the classifier

**Ledger row (1 file, 4 fork lines):** `agent/turn_api_error.py::handle_api_error` — `classified = None`,
`error_context = {}` before `_verdict`, and `attach_provider_failure(result, classified, error_context)`
as `_verdict`'s first line; the helper is the fork-only `agent/provider_failure.py` (28 lines).
`docs/downstream/provider-closeout-2026-10-01.md` § "Terminal evidence": the native classifier's
verdict reaches the terminal result once, at the one choke point every `"return"` passes
(`route_classified_error`'s results, the overflow results, `settle_unrecovered_error`'s
`max_retries_exhausted_result` / `nonretryable_client_error_result`), so no consumer re-classifies
providers or compares summary text. Upstream has an `api_request_error` hook per ATTEMPT
(`agent/api_request_hooks.py::_invoke_api_request_error_hook`) but nothing on the terminal result,
which is what `delegate_task`, the gateway and any host read (#82599 is that gap seen from
`delegate_task`).

**Upstream API** — the fork module as-is, one field:

```python
# agent/provider_failure.py
def attach_provider_failure(result: dict | None, classified: ClassifiedError | None, context: dict) -> None:
    """On a terminal result that ``failed`` and was not ``interrupted``, set
    result["provider_error"] = {"status_code", "provider", "model", "failure_reason",
    + "reason" / "message" / "reset_at" when the classifier's error_context holds a scalar}.
    No-op otherwise (recovered attempt, interrupt, interpreter shutdown: classified is None)."""
```

A dict of scalars only — never the SDK exception, never request headers (the module's own
comment). Default: every terminal result that was classified gains the key; nothing else changes.

**Smallest upstream diff (~32 lines non-test), branch `feat/turn-result-provider-error`:**

| file · function | edit |
|---|---|
| `agent/provider_failure.py` | the fork file (28) |
| `agent/turn_api_error.py::handle_api_error` | `classified = None; error_context = {}` before `_verdict` (2); `attach_provider_failure(result, classified, error_context)` first line of `_verdict` (1); the import (1) |

The two pre-assignments matter: `_verdict` is a closure, Python resolves `classified` at call
time, and the shutdown return runs before `classify_api_error` — without the `None` default that
path raises `NameError`. The PR body says so.

**Test that proves it** — the fork's `tests/agent/test_provider_failure_result.py` moves with the
module (the unit shape: failed+classified → block; interrupted → none; non-scalar context dropped),
plus `tests/agent/test_turn_api_error_provider_error.py` (~45 lines) through `handle_api_error`
itself with the fake agent `tests/agent/test_turn_api_error_stream_parse.py` already builds:
(1) `max_retries=0`, an `api_error` with `status_code=429` and `_extract_api_error_context`
returning `{"reset_at": 1700000000}` → `verdict.action == "return"` and
`verdict.result["provider_error"] == {"status_code": 429, "provider": …, "model": …, "failure_reason": verdict.result["failure_reason"], "reset_at": 1700000000, …}`;
(2) `agent._interrupt_requested = True` → the abort result has no `provider_error`; (3)
`interpreter_shutting_down` patched True → the shutdown result has no `provider_error` and nothing
raised. Killing mutation: delete the `attach_provider_failure` line in `_verdict`; (1) reds with
`KeyError`.

**Fork change, file by file:** `agent/turn_api_error.py`'s hunk becomes upstream's lines;
`agent/provider_failure.py` is upstream's file; `agent_runtime/mission_chat_outcome.py` and
`agent_runtime/profile_runner/errors.py` (the readers) unchanged; ledger row → `retired by #<new>`.

**Risk:** low. The field is additive and scalar; the only reviewer push-back is placement
("put it in `max_retries_exhausted_result`"), answered by the choke-point argument above — three
builders would need the same four lines. Weakness carried into upstream on purpose: `_verdict`
now reads eleven enclosing locals (the fork's own closure signal); it is upstream's existing
shape and not this PR's to fix.

**PR summary (≤10 lines):**
```
feat(agent): terminal turn results carry the classifier's provider_error evidence

handle_api_error classifies every API error (status, provider, model, FailoverReason,
reset_at) and the api_request_error hook sees each attempt — but the terminal result a
caller gets back (delegate_task, the gateway, an embedding host) carries only
failure_reason and a summary string, so consumers re-parse text to learn that a 401 was
auth or a 429 resets at T (#82599). This attaches result["provider_error"], a dict of
scalars from the existing ClassifiedError, at the one point every terminal return passes;
recovered attempts, interrupts and shutdown carry nothing. Test: tests/agent/test_turn_api_error_provider_error.py.
```

---

## I. Live foreground commands — `tools.environments.base.live_foreground_commands()`

**Ledger row (1 file, 5 fork lines):** `tools/environments/base.py::BaseEnvironment.execute._spawn_and_wait`
— `foreground_watch.publish(id(spawned), pid=, command=, timeout=, owner_tid=, output=)` after
`_new_output_collector`, `foreground_watch.retract(id(spawned))` in the `finally`. The consumer is
the fork-only `tools/environments/foreground_watch.py` (`ForegroundCommand`, `snapshot(owner_tid=)`),
read by `agent_runtime/live_turns.py::_foreground_by_tid` so the heartbeat can say which command a
blocked tool call is waiting on, how long, how close to its deadline, and whether it printed
lately. Upstream already keeps the table — `_live_foreground: dict[int, (env, ProcessHandle)]`,
written by `_leave_foreground_spawn`, popped in the same `finally`, read by
`kill_live_foreground_processes` (and by `tests/tools/test_local_interrupt_cleanup.py`, which
inserts a tuple) — it just records nothing an observer could read.

**Upstream API** — in `tools/environments/base.py`:

```python
@dataclass(frozen=True)
class ForegroundCommand:
    key: int; pid: int | None; command: str; started_at: float; elapsed_seconds: float
    timeout_seconds: float | None; owner_tid: int | None; output_chars: int
    seconds_since_output: float | None; tail: str          # tail bounded to 4096 chars

def live_foreground_commands(*, owner_tid: int | None = None) -> list[ForegroundCommand]:
    """Snapshot of the foreground commands in flight in this process, oldest first; read-only —
    nothing here signals or waits on a process (that is the owning turn's interrupt seam)."""
```

and `tools/environments/base_output.py`: the output collector stamps `last_append_mono` in
`append` so `seconds_since_output` is REPORTED, not inferred by sampling (the fork's docstring
calls its own value a lower bound to within the reader's interval; upstream can do better for two
lines).

**Smallest upstream diff (~45 lines non-test), branch `feat/live-foreground-commands`:**

| file · function | edit |
|---|---|
| `base.py` module scope | `class _LiveForeground` (`__slots__`: env, proc, command, started_at, started_mono, timeout, owner_tid, output=None) replacing the tuple; `ForegroundCommand`; `live_foreground_commands` (~30) |
| `::_leave_foreground_spawn(env, spawned, *, command="", timeout=None, owner_tid=None)` | stores a `_LiveForeground` (3) |
| `::execute._spawn_and_wait` | pass `command=command, timeout=effective_timeout, owner_tid=parent_tid` (1); after `_new_output_collector`: `_attach_foreground_output(id(spawned), output)` — under the condition lock, sets `.output` when the entry is still live (4) |
| `::kill_live_foreground_processes` | `live = [(e.env, e.proc) for e in _live_foreground.values()]` at its three reads (3) |
| `base_output.py::_OutputCollector.append` / `__init__` | `self.last_append_mono = time.monotonic()` (2) + a `last_append_mono` read property if the attribute is private (1) |
| `tests/tools/test_local_interrupt_cleanup.py` | the one `setitem` builds a `_LiveForeground` (1, test) |

The `finally` pop that already exists is the retract. Nothing new is written on the command's
own path except one attribute set.

**Test that proves it** — `tests/tools/test_live_foreground_commands.py` (~60 lines): a
`LocalEnvironment().execute(f"{sys.executable} -c \"print('mark', flush=True); import time; time.sleep(5)\"", timeout=30)`
on a worker thread; poll `live_foreground_commands()` (≤5 s) until one entry whose
`output_chars > 0` — (1) `pid` is an int, `command` contains `mark`, `owner_tid` is the worker's
ident, `timeout_seconds == 30`, `0 <= elapsed_seconds`, `tail` contains `mark`,
`seconds_since_output` is a float; (2) `live_foreground_commands(owner_tid=other)` is empty; (3)
the env's interrupt (`kill_live_foreground_processes(now=True)` or the test's own kill) ends the
command and the list is empty after the thread joins; (4) control: before any spawn the list is
empty. Killing mutation: delete `_attach_foreground_output`; (1) reds on `output_chars > 0` /
`tail`. Second: pass no `command=` from `_spawn_and_wait`; (1) reds on `command`.

**Fork change, file by file:** the two `base.py` hunks delete; `tools/environments/foreground_watch.py`
retires with `tests/tools/test_foreground_watch*.py` and `agent_runtime/live_turns.py::_foreground_by_tid`
reads `tools.environments.base.live_foreground_commands` (same field names — the fork's dataclass
is the upstream one minus the sampling bookkeeping); ledger row → `retired by #<new>`;
`tests/fixtures/upstream_footprint.json` down by one.

**Risk:** low-medium. `_live_foreground`'s value shape changes (tuple → record): the lane greps
`upstream/main` for every reader before cutting the PR (today: `kill_live_foreground_processes`
and one test; #124609 — open — reads the table from `tui_gateway/slash_worker.py` through
`kill_live_foreground_processes`, so it is unaffected). `tail` calls `output.render()` under no
lock; the collector already serialises its own state. A reviewer may ask for the reader to live in
`tools/terminal_tool.py`; `base.py` owns the table and the lock, so the reader sits beside them.

**PR summary (≤10 lines):**
```
feat(terminal): live_foreground_commands() — observe in-flight foreground commands

A foreground terminal call blocks its tool thread inside BaseEnvironment.execute; the
only record that it is running is _live_foreground, which holds (env, proc) for the
exit-time kill and nothing an operator surface could read. A silent build and a hung one
look identical for the whole timeout. This records command, start, deadline, owner thread
and the output collector on the existing entry and adds a read-only snapshot reader
(pid, elapsed, timeout, output chars, seconds since output, bounded tail). The output
collector stamps its last append. Nothing signals a process. Test: tests/tools/test_live_foreground_commands.py.
```

---

## J. Group Chat host surface — three PRs under issue #125258

**Ledger rows (5 files, 317 insertions / 62 deletions):** `gateway/hosted_room_discussion.py` (225:
`DiscussionLimits`, `active_member_ids`, the `response` payload field, the independent
`ready_tasks` batch, `published_watermark`, the conclusion round, the omission-notice fix),
`gateway/hosted_rooms.py` (76: `pin_room_history` / `unpin_room_history`, the
`hosted_room_history_pins` table, pinned rooms reclaimed last under the byte budget),
`gateway/hosted_room_policy_checkpoint.py` (16: `max_active_events`, `published_watermark`),
`gateway/hosted_room_driver.py` (16: the `independent` payload field, `independent_members`
overlap admission in `start_task`), `tui_gateway/hosted_room_driver.py` (46:
`request_reconciliation`, `stop_unresolved`, `inspection.active`, the terminal `error`,
`_observe_independent_members`, independent tasks not parking the room). Fork-only modules that
move with the PRs: `gateway/hosted_room_message_intent.py` (`ResponseMode`, `MessageResponse`,
`response_from_payload`, `response_guidance`, `published_watermark`) and
`gateway/hosted_room_parallel_admission.py` (`independent_members`). Plan and evidence:
`chat-first-group-messages.md` (owner-approved 2026-09-29; 225 tests across 12 files).

Issue #125258 asks whether the surface is keyword parameters or a `RoomHost` protocol. Design
answer: keyword parameters carrying one typed value (`DiscussionLimits`), because every consumer
upstream already calls these functions positionally with a default, and a protocol would be a
second object every call site must thread. Three PRs, each one logical change, in acceptance order:

### J1 — `fix(gateway): hosted-room driver settles what it can prove` (branch `fix/hosted-room-driver-settlement`)

**Upstream diff (~22 lines, `tui_gateway/hosted_room_driver.py` only):** `stop_unresolved` →
inactive alone does not settle an unknown attempt (2); `inspection.active or clock < deadline`
keeps the room blocked while the session is provably active (1); `_find_terminal_receipt` carries
`message.get("error")` in the bounded terminal result (1); `request_reconciliation(identity)` —
drop only that task's negative recovery observation and wake (11). The issue's own text calls
these "plain bug fixes … split into their own PR".

**Test:** the fork's `tests/tui_gateway/test_hosted_room_driver_runtime_downstream.py` cases for
the four behaviours move in (~80 test lines). Killing mutation: revert the `stop_unresolved` early
return → the case that holds an unknown attempt open on an inactive session reds (it settles).

### J2 — `feat(gateway): host-declared Group Chat limits, active members, policy budget and history pinning` (branch `feat/hosted-room-host-limits`)

**Upstream API:**

```python
# gateway/hosted_room_discussion.py
@dataclass(frozen=True)
class DiscussionLimits:            # validated in __post_init__, raises DiscussionValidationError
    max_members: int = MAX_DISCUSSION_MEMBERS; max_rounds: int = MAX_DISCUSSION_ROUNDS
    max_messages: int = MAX_DISCUSSION_MESSAGES; prompt_bytes: int = driver.MAX_PROMPT_BYTES
    shared_profiles: bool = False; guidance: str = ""; conclusion_member_id: str | None = None
DEFAULT_LIMITS = DiscussionLimits()
validate_roster(value, *, local_profiles, limits=DEFAULT_LIMITS)
validate_room(value, *, local_profiles, limits=DEFAULT_LIMITS)      # DiscussionRoom gains .limits
decide_next(..., limits=DEFAULT_LIMITS, active_member_ids: Iterable[str] | None = None)
# gateway/hosted_room_policy_checkpoint.py
HostedRoomPolicyCheckpoint(db_path, *, max_active_events=MAX_ACTIVE_POLICY_EVENTS)   # ≤ 1024
# gateway/hosted_rooms.py
def pin_room_history(db_path, *, room_id, expected_gateway_id, expected_epoch) -> None   # typed refusal RoomHistoryRetentionFullError
def unpin_room_history(db_path, *, room_id, expected_gateway_id, expected_epoch) -> bool
```

Default: `DEFAULT_LIMITS` reproduces the six-member / three-round / ten-message policy, no active
subset, the stock checkpoint budget, nothing pinned → every prune order byte-identical.

**Upstream diff (~190 lines):** `hosted_rooms.py` (the fork hunk, 76 — `MAX_RETAINED_ROOM_HISTORIES`,
the error class, the `_DEPENDENT_TABLES` entry, the pinned set in `_prune_disbanded_rooms_locked`
with the stable sort, the two functions), `hosted_room_policy_checkpoint.py` (the budget, 8),
`hosted_room_discussion.py` (`DiscussionLimits` + `DEFAULT_LIMITS`, the `limits=` threading
through `validate_roster` / `validate_room` / `_validated_events` / `decide_next`, `active`
members in mention resolution and prompt peers, the conclusion round and `guidance` in
`_member_prompt`, `prompt_bytes` in place of `driver.MAX_PROMPT_BYTES`, the omission-notice
reserve fix — ~105). NOT in J2: the `response` field, `ready_tasks`, `published_watermark`.

**Test:** the fork's `tests/gateway/test_hosted_rooms_downstream.py` (pin survives the age and
tombstone sweeps; reclaimed last under the byte budget; the typed refusal at the cap; unpin
litter), `test_hosted_room_policy_checkpoint.py` budget cases, and the `test_hosted_room_discussion.py`
limits / active-member / conclusion cases move in. Killing mutation: delete
`candidates.difference_update(pinned)` → the pinned-room-survives-tombstone-cap case reds.

### J3 — `feat(gateway): per-message response policy (discuss / compare / reply) with independent member tasks` (branch `feat/hosted-room-response-policy`)

**Upstream API:** `gateway/hosted_room_message_intent.py` as the fork has it (`ResponseMode`,
`MessageResponse.select(members)` / `.validate_audience`, `response_from_payload(payload, *, error)`,
`response_guidance`, `published_watermark(seen, published, source_payload)`);
`gateway/hosted_room_parallel_admission.py::independent_members(candidate_row, active_rows)`;
the optional `response` key on the user payload (`validate_user_payload` optional set);
`"independent": True` as an optional driver task-payload field requiring `target_member_id`;
`DiscussionDecision.ready_tasks` (the Compare batch, `comparison_turn`).

**Upstream diff (~190 lines):** the two modules (~100), `hosted_room_discussion.py` (the
`response` plumbing, the batch loop, `single_round`, the watermark — ~60),
`gateway/hosted_room_driver.py` (16), `hosted_room_policy_checkpoint.py` (the watermark, 6),
`tui_gateway/hosted_room_driver.py` (`_observe_independent_members`, the three `independent`
guards — ~24).

**Test:** `tests/gateway/test_hosted_room_message_intent.py`, `test_hosted_room_parallel_admission.py`
and the Compare cases of the discussion / driver / runtime tests move in. Killing mutation: make
`independent_members` return `False` → the "two members of one Compare message overlap" case reds
with `InvalidTaskTransitionError`.

**Fork change, file by file (all three):** the five upstream files' hunks become upstream's lines
merge by merge; the two fork-only modules become upstream files; the ledger's four `S3` rows and
the `NO DOOR YET` driver row retire in turn (J1: part of `tui_gateway/hosted_room_driver.py`; J2:
`hosted_rooms.py` whole, the checkpoint's budget, most of the discussion file; J3: the rest).
Request 4 of the door map closes with J3.

**Risk:** medium-high, and it is the reason for three PRs. J1 is bug-fix shaped and small. J2
is additive keyword parameters with a default that reproduces today; its reviewer cost is the
pins table (a new table + a prune-order change, defended by "byte-identical with nothing
pinned", which the test states). J3 changes scheduling (two tasks of one room running at once,
today forbidden by `start_task`); upstream's rule "normal turns stay sequential" is kept
verbatim — only distinct members of the same source message may overlap, and the planner emits
the batch only for `compare`. If J3 is refused, J1 + J2 still retire `hosted_rooms.py` and the
checkpoint budget, and the fork keeps J3's hunks as a smaller, better-fenced seam
(`independent_members` is the single admission site). #125258 gets a comment with the three
titles before the first PR opens (CONTRIBUTING "For larger work, comment on the issue").

**PR summary (≤10 lines, J2):**
```
feat(gateway): host-declared Group Chat limits, active members, policy budget, history pinning

A host that embeds hosted rooms (a desktop multi-agent discussion host) cannot say how
many members, rounds or messages a discussion may have, which admitted members may take
a turn now, how many active policy events the checkpoint may hold, or that a finished
meeting's public log must outlive the deleted-chat sweep. This adds DiscussionLimits
(a frozen, validated value with today's policy as its default) threaded through
validate_room / decide_next, active_member_ids, a max_active_events budget, and
pin_room_history / unpin_room_history (typed refusal at the cap; pinned rooms reclaimed
last under the byte budget; nothing pinned = byte-identical prune order). Issue #125258.
```

---

## K. What h-doors-2 does not decide

- Whether #129412 is amended to carry the scratch guard — the recommendation is a second PR
  (above); the owner may prefer one.
- The job-wake's capability ad (`experimental["eternia.job_wake"]`) has no upstream door smaller
  than wrapping the SDK's `_build_capabilities`; it stays fork-side inside the `on_mcp_session`
  handler. A `client_capabilities` kwarg is an SDK change, not a hermes one.
- `tools/registry.py`'s dispatch bracket for the progress relay is its own ledger row and is not
  retired by door 6.
- Door 9's shape question (keyword parameters vs `RoomHost`) is answered here for the design;
  #125258 has no maintainer reply, and a reply asking for the protocol changes J2's threading,
  not its content.
