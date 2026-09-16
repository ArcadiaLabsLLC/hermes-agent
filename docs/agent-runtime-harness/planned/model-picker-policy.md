# Model picker provider policy v1

Status: implementation contract; code remains on a feature branch pending joint client/runtime validation. Date: 2026-09-16.

## Audit

`hermes_cli/harness.py::build_provider_visibility` already emits the connectable-provider catalog through a failure-isolated block. `hermes_cli/provider_catalog.py::provider_login_catalog` owns the public descriptor rows and models_dev_id_for owns reference-catalog aliases. These aliases describe metadata, not the models a route supports or the bill an account incurs.

`hermes_cli/models.py::_codex_catalog` already delegates to `hermes_cli/codex_models.py::get_codex_model_ids`; the latter owns forward-compatible/context variants and live versus offline handling of account-gated entries. Consumers must not substitute the public OpenAI API catalog for this route. The no-token path is an offline compatibility catalog, not an entitlement check. Do not add an API request or credential refresh to provider status.

Authentication flow cannot determine billing: an external flow may represent an API key. Publish explicit billing provenance, not a numeric price table or an assertion that a subscription includes every model.

## Additive contract

Each existing provider descriptor may include model_picker:

```json
{
  "schema": "hermes.model_picker_policy/v1",
  "billing_mode": "account",
  "catalog_mode": "compatibility",
  "source": "hermes_cli.codex_models",
  "model_ids": ["example-chat-model"]
}
```

The example is synthetic. Billing modes: catalog/account/local/unknown. Catalog modes: reference/compatibility/unavailable. Compatibility requires a list of nonempty IDs; empty differs from absent. Reference omits model_ids. Optional error is an exception class name only. Never include tokens, account IDs, secret-bearing exception messages, or credential status.

Compatibility means browse curation, never verified account availability. Join reference prices and metadata by exact ID only; no price borrowing for context variants. Missing rates are unknown, not zero. Account routes say Account billing; token numbers say API reference. Local means no remote API charge, not zero operating cost.

## Implementation

Add focused `hermes_cli/model_picker_policy.py`, with no module-time filesystem access. Call it at the descriptor emission seam in provider_catalog.py. Codex calls existing get_codex_model_ids() WITHOUT an access token. Preserve canonical CODEX_HOME behavior and upstream selection safeguards. Do not duplicate DEFAULT_CODEX_MODELS or the forward-compatibility ladder.

Explicitly classify known account-billed routes, including Codex/Copilot and the subscription/external account routes already named here. Catalog is the conservative default for direct provider metadata, not an invoice claim. Do not infer Free/Included from auth or a zero reference price.

Discovery failure emits an unavailable policy with exception-class diagnostic. Other descriptors survive; never widen failure to an unrelated public API list. Harness stays hermes.provider_visibility/v2. No migration, new RPC, state writes, or new cache.

Consumers feature-detect and validate schema/modes; preserve absent/empty/unavailable; retain current selection without inventing a selectable capability; avoid entitlement claims; use the reference catalog with an unverified-provenance warning on older runtimes. Non-agent classification/responsive price rendering are client concerns over catalog metadata, not a new inference gate here.

## Tests and fixture

Shared synthetic fixture: `tests/fixtures/model_picker_policy_v1.json`, copied byte-identically by the client. Exercise provider_login_catalog with controlled descriptors and real policy projection: IDs equal canonical discovery results, API-only IDs are not appended, failures remain local, arbitrary future IDs survive. Assert relationships, not today's model counts/list.

Exercise the canonical no-token path with temporary CODEX_HOME A→B→A, and assert that network/token refresh is not invoked. Malformed discovery must not report success. All homes stay under fixtures.

Run scripts/run_tests.sh on tests/hermes_cli/test_model_picker_policy.py, tests/hermes_cli/test_provider_catalog.py, and existing Codex discovery tests. Never direct whole-directory pytest. Broad validation includes the documented four-directory scope and relevant contract/doc gates. Separate executed results from unrun checks.

## Joint landing

Plan on main first, code on a dedicated feature branch. Client plan: `EterniaLauncher/docs/mission_control/planned/agent-model-picker-catalog-ux.md`; that repository owns UX, clipping tests, and Windows visual proof. Neither code branch merges until both validate. Worker reports issues in bulletpoints and fast-forwards runtime then client only after required gates pass. Never force main or overwrite unrelated work. If one push succeeds and the other fails, stop and report the partial landing.
