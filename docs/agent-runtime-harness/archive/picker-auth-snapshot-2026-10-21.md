> **BUILT** — archived 2026-10-27 from `planned/` (lane w1027j-h-tri-b); landed: `eec6d8db56`, `a67f250323`, `0c619a8b70` (P1-P3), `839662b1dc` (direct reads).
> History, not truth: the domain docs and the queues hold what is current.

# Planned — the model picker reads auth.json once per build: a credential-pool snapshot scope — 2026-10-21

**Owner domain:** operator sessions and the model picker ([03](../03-transport-and-wire.md) §
`runtime.operator.session.models`; `agent_runtime/operator_session_models.py`); upstream-owned
`hermes_cli/inventory.py`, `hermes_cli/model_switch_providers.py`, `agent/credential_pool.py`,
`hermes_cli/auth.py` (the footprint ledger
[upstream-footprint-ledger.md](../planned/upstream-footprint-ledger.md)).
**Status:** IMPLEMENTATION-READY (design lane w1021i-plans). One doc, no code.
**Measured / read:** 2026-10-21 against hermes `origin/main` d087df7035; cProfile of
`tests/agent_runtime/test_operator_session_models.py` (33 tests, 119.8 s wall, 122.2 s profiled).

Row: `RT-PICKER-AUTH-REREAD` (runtime-queue § Upstream-owned). Binding ruling (owner 2026-10-21):
upstream fixes ship on the fork with an idle prepared `up/` branch — never "open a PR" as the fix.

## 1. What is true today — measured, by symbol

| symbol | calls / 50 builds | per build | cum s | share of the 69.5 s a build costs |
|---|---|---|---|---|
| `inventory.build_model_options_payload` | 50 | 1 | 69.5 | 100 % (1.39 s per build) |
| `inventory.build_models_payload` | 50 | 1 | 69.2 | 99.6 % |
| `credential_pool.load_pool` | 4,784 | 96 | 38.9 | 56 % |
| `model_switch_providers._credential_pool_is_usable` | 4,700 | 94 | 37.6 | 54 % — THE caller of `load_pool` |
| `auth._load_auth_store` | 16,431 | 329 | 25.3 | 36 % (1.5 ms each: host-store view + read + parse) |
| `auth.read_credential_pool` | 5,084 | 102 | 16.5 | |
| `credential_pool._seed_from_singletons` | 4,767 | 95 | 12.1 | env / dotenv / file probes per provider |
| `config._load_config_impl` | 8,184 | 164 | 13.2 | |
| `inventory._apply_limits` (the fork-visible `load_pool` caller) | 50 | 1 | 1.4 | 2 % |

So the row's numbers hold (329 auth reads per open, 57 % of the file's wall), and its attribution is
sharpened: the cost is not `_apply_limits` (2 %) but `build_models_payload`'s per-provider
`_credential_pool_is_usable` → `load_pool`, called ~94 times per open — once per provider row, each
re-reading `auth.json`, the pool file, env and dotenv from scratch. `load_pool` is a READ that also
heals (`heal_forked_single_use_oauth_grants`, `_seed_from_*`, `_persist` when `changed`), which is why
upstream never cached it.

The fork's callers: `agent_runtime/operator_session_models.py::operator_model_inventory` and
`_selected_model` (both under `_model_profile(instance)`), `tui_gateway/methods_complete.py`,
`hermes_cli/web_routers/models.py` (upstream).

## 2. Decisions

- `Decided (plan):` **a per-call snapshot scope, opened by the caller, honoured by `load_pool`.**
  `agent_runtime/credential_pool_snapshot.py` (fork-owned, `policy` layer) holds a `ContextVar` of
  `dict[provider, CredentialPool] | None`. Inside `with credential_pool_snapshot():` the first
  `load_pool(p)` runs upstream's full path and memoises the result; later calls for the same provider
  return the memoised pool. Outside the scope nothing changes. The scope is opened by the fork's two
  callers in `operator_session_models.py` (per RPC call) and by `tui_gateway/methods_complete.py`'s
  picker method (one additive `with`, fork seam line). Writes inside a build (`_persist` on `changed`)
  still happen on the first load; a memoised pool is the SAME object, so a second `select` in the same
  build sees the healed entries.
- `Decided (plan):` **the seam in `load_pool` is two additive lines** at the top of
  `agent/credential_pool.py::load_pool` (`memo = _fork_snapshot.get(provider)` / `if memo is not None:
  return memo`) plus the store at the tail — a seam row in the footprint ledger (§ Seams), the same
  shape as the phone-credentials seam in `auth._load_auth_store`. No `_load_auth_store` cache: a dict
  memo there would need a deep copy per call (the callers read-modify-write the returned dict) and
  would save 36 % while the `load_pool` memo saves 56 % and covers the auth reads it causes.
- `Decided (plan):` **the `up/` branch carries the upstream-shaped version:** `load_pool(provider, *,
  snapshot: Mapping | None = None)` threaded from `build_models_payload(..., pool_snapshot=…)` through
  `_credential_pool_is_usable`, the way upstream threads `refresh`. Prepared on `up/picker-pool-snapshot`
  from `upstream/main`, idle, with the measurement in its description; the fork keeps the seam until a
  release merge carries the upstream shape.

## 3. Stages

**P1 — the scope module** (`agent_runtime/credential_pool_snapshot.py`): `credential_pool_snapshot()`
context manager (nested scopes share the outer dict), `snapshot_get(provider)`, `snapshot_put(provider,
pool)`, both no-ops outside a scope. Test (`tests/agent_runtime/test_credential_pool_snapshot.py`):
outside a scope `snapshot_get` is None after `snapshot_put`; inside, put then get returns the object;
the scope is cleared on exit. Killing mutation: make the ContextVar default `{}` instead of `None` →
the "outside a scope" test reds.

**P2 — the seam** (`agent/credential_pool.py::load_pool`, additive): the get at the top, the put
before every `return`. Footprint ledger row. Test (`tests/agent_runtime/test_credential_pool_snapshot.py`):
under a scope, 20 `load_pool("openrouter")` calls read `auth.json` once (count `_load_auth_store` through
a patched wrapper) and return one object; without a scope they read 20×. Killing mutation: drop the put
→ "once" reds.

**P3 — the callers** (`operator_session_models.py` ×2, `tui_gateway/methods_complete.py` ×1): open the
scope around the build. Test: `runtime.operator.session.models` over the test file's fixture reads
`auth.json` ≤ 8 times per call (the non-pool readers: `_get_config_hint_for_unknown_provider`,
`_apply_usage`, the ctx load) — the bar is recorded from the P2 run and ratcheted in the test's
docstring; `tests/agent_runtime/test_operator_session_models.py` wall is re-measured in the commit body
(expected: 120 s → ~55 s). Killing mutation: remove the `with` in `operator_model_inventory` → the
read-count bar reds.

**P4 — the `up/` branch**: `up/picker-pool-snapshot` from `upstream/main`, the threaded-parameter
shape, the test from P2 rewritten against the parameter, the cProfile table in the description. Held
PR row in the footprint ledger (`RT-NATIVE-WORKER-UPSTREAM-BOOT` names the same `model.options` cost
— that row's upstream issue text points at this branch instead of a separate issue).

## 4. Out of scope

`build_models_payload`'s catalog probes and pricing (already cached by upstream); the native worker's
boot-time `model.options` (same cost, same fix — `RT-NATIVE-WORKER-UPSTREAM-BOOT` closes its picker half
when P3 lands and its caller opens the scope; that is one more `with`, filed as that row's note).

## 5. Open rulings

None.
