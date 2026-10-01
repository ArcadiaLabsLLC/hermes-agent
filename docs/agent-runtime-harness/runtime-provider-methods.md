# `runtime.provider.*` — method contract

The serve RPC methods a client uses to list providers, sign in, refresh, read
usage and sign out. Registered by `agent_runtime/serve_rpc/provider.py`; the
work is `agent_runtime/provider_account.py` and `agent_runtime/provider_signin.py`.
Every method wraps an existing implementation — none adds OAuth or usage logic.
Frames, error codes and the manifest follow [03 — transport and wire](03-transport-and-wire.md).

Every success result carries `contract: 1` (this family's own shape number,
like `runtime.media.*`'s). Adding a method grows the manifest set without
moving `RPC_CONTRACT_VERSION`.

## Methods

| method | tier | params | wraps |
|---|---|---|---|
| `runtime.provider.list` | read | — | `build_provider_visibility()` (`hermes harness providers --json`) |
| `runtime.provider.usage` | read | `provider` | `agent.account_usage.fetch_account_usage`; Nous via `get_nous_portal_account_info` + `build_nous_credits_snapshot` |
| `runtime.provider.signin.begin` | console | `provider`; `flow?`, `profile?` | one `hermes harness auth login <provider> --json --flow <flow>` child (`hermes_cli/provider_browser_login.py` driver table) |
| `runtime.provider.signin.poll` | console | `login_id` | the session the child's NDJSON feeds |
| `runtime.provider.signin.complete` | console | `login_id`, `code` | writes `code` as one line to the child's stdin |
| `runtime.provider.signin.cancel` | console | `login_id` | kills the child |
| `runtime.provider.refresh` | console | `provider`; `credential?` (index, id or label) | `hermes auth refresh` (`auth_refresh_command`) |
| `runtime.provider.signout` | console | `provider` | `hermes auth logout` (`auth_logout_command`) |

`provider` is lower-cased. Unknown params are ignored.

`list`, `usage`, `refresh` and `signout` run on the transport's worker lane
when it has one (`RpcContext.spawn_reply`); the reply arrives on the same `id`.

## Reply budgets

How long a client waits for each method's reply before it treats the call as
lost. Each budget sits past the bound this runtime puts on the work, so a reply
the runtime will still send is never given up on. A change to a bound in the
middle column changes its budget in the same commit; the Launcher reads this
table (`HermesProviderMethod.timeoutFor`).

| method | bound on the work | budget |
|---|---|---|
| `runtime.provider.usage` | every usage fetch in `agent/account_usage.py` is an HTTP call with `timeout=15.0`; Nous reads `hermes_cli/nous_account.py` with `timeout=8` | 20 s |
| `runtime.provider.refresh` | `hermes auth refresh`: token endpoint calls under upstream's HTTP timeouts; no single bound, and a lost reply leaves the outcome unknown | 30 s |
| `runtime.provider.signout` | `hermes auth logout`: as refresh | 30 s |
| `runtime.provider.signin.begin` | spawns the login child and answers in state `starting` without waiting on it | 15 s |
| `runtime.provider.list` | local files only | 10 s |
| `runtime.provider.signin.poll` | in-memory session read | 10 s |
| `runtime.provider.signin.complete` | one line written to the child's stdin | 10 s |
| `runtime.provider.signin.cancel` | kills the child | 10 s |

## Results

**list** — the `hermes.provider_visibility/v2` envelope, unchanged:
`{contract, schema, providers: [{id, credentials: [{index, label, auth_type,
source, selected, health, token_preview}]}], environment?, api_keys?,
auth_logins?, local_llama?, catalog?, block_errors?}`. `catalog` rows are the
real login catalog plus `browser_login: bool` and `browser_login_methods:
[flow…]`. `token_preview` is at most the last four characters.

**usage** —
`{contract, provider, available, source, title, plan, fetched_at,
windows: [{label, used_percent, reset_at, detail}], details: [str],
unavailable_reason}`. Times are ISO-8601. With no usage source for the
provider (or not signed in): `{contract, provider, available: false,
unavailable_reason: "no_usage_source"}`. A Nous portal failure reads
`available: false` with `unavailable_reason` = the exception class name.
The upstream snapshot's `raw` body is never sent.

**signin.\*** — one session view:

```
{contract, login_id, provider, flow, state, needs_code,
 started_at, updated_at,            # epoch seconds
 verification_uri?, user_code?,     # once the provider issued them
 error_code?}                       # on failed / cancelled
```

`flow` is one of the catalog row's `browser_login_methods`: `device_code`,
`browser` (Codex loopback PKCE) or `paste_code` (Anthropic PKCE). `begin`
without `flow` picks `device_code` where offered, else the only method.

| state | meaning | client does |
|---|---|---|
| `starting` | child running, no link yet | poll |
| `awaiting_user` | open `verification_uri`, enter `user_code` (empty for `browser`) | poll |
| `awaiting_code` (`needs_code: true`) | open `verification_uri`; the page shows a `code#state` string | `complete` with it |
| `completing` | code handed to the child | poll |
| `succeeded` | saved to this home's credential store | refresh `list` |
| `failed` | `error_code` ∈ `expired`, `denied`, `browser_busy`, `unsupported_flow`, `unknown_provider`, `login_failed` | offer retry |
| `cancelled` | `cancel` was called (`error_code: "cancelled"`) | — |

A session unfinished after 15 minutes becomes `failed`/`expired` on its next
poll. Finished sessions stay pollable for 10 minutes. One active session per
provider.

**refresh** — `{contract, provider, credential, refreshed: true}`.

**signout** — `{contract, provider, was_signed_in, signed_in}` (booleans read
from `get_auth_status` before and after).

## Errors

`error.data.reason` is the branch point.

| code | reason | from |
|---|---|---|
| -32602 | `provider_required` | every method taking `provider` |
| -32602 | `provider_unsupported` (+`provider`) | `signin.begin`: no sign-in driver |
| -32602 | `flow_unsupported` (+`provider`, `flows`) | `signin.begin` |
| -32602 | `login_id_required` | `signin.poll/complete/cancel` |
| -32602 | `code_invalid` | `signin.complete`: missing, over 2048 chars, or holding CR/LF/NUL |
| -32602 | `provider_unknown` (+`provider`) | `refresh`, `signout` |
| 4001 | `login_not_found` (+`login_id`) | `signin.poll/complete/cancel` |
| 4090 | `login_in_progress` (+`login_id` of the live one) | `signin.begin` |
| 4090 | `login_not_awaiting_code` (+`state`) | `signin.complete` |
| -32000 | `refresh_refused` / `signout_refused` | upstream refused; `message` is its operator text |
| -32000 | `refresh_failed` / `signout_failed` | upstream raised; `message` is the exception class |
| -32000 | `handler_failed` (+`method`, `error_class`) | anything else |

## Credentials

No token, refresh token, API key or provider response body is in any result,
error or log line: results are catalog rows, session state, booleans and
usage windows; failures carry a closed reason or an exception class name,
never `str(exc)`. Tokens exist only inside the sign-in child and the store
upstream's save path writes. The child's stdout is the NDJSON wire of
`provider_browser_login.browser_login_command` (helper prints discarded,
logging disabled, exceptions never serialized); its stderr is discarded.

`signin.complete`'s `code` is the one-time authorization code; it is written
to the child's stdin and never echoed or stored. `verification_uri` and
`user_code` are what the operator must see and are not credentials.

## Anthropic (`paste_code`)

The driver runs upstream's `hermes auth add anthropic --type oauth`
(`run_hermes_oauth_login_pure` → the credential pool) inside the child,
shadowing that module's `print` (to capture the authorize link) and `input`
(to read the pasted code from stdin) for the one call. PKCE, the CSRF state
check, the token exchange and the pool write are upstream's. The browser is
not auto-opened; the client opens `verification_uri`.

## Profiles

`signin.begin`'s `profile` becomes the child's `--profile` (the same resolution
as `hermes harness auth login --profile`); the child otherwise runs under the serve's
`HERMES_HOME`. The other methods act on the serve's own home.

The sign-in child is a subprocess; a profile that cannot spawn one binds a
different runner through `ProviderSignIns(spawn=…)`.
