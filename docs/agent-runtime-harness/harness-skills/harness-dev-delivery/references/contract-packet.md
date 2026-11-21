# Contract packet

Moved out of the preloaded `harness-dev-delivery/SKILL.md` on 2026-11-20 (hermes row
`RT-FU-TWO-SHARED-SKILLS-RUN-OVER-THEIR-PER-TURN-SIZE-LIMIT`): every dev turn paid for this
block; only a cross-stack contract turn reads it. The ordering rule (Backend, then Frontend,
then QA) stays in the skill, section "Cross-stack contract handoff".

Post this in the chat reply so the next agent and the operator both see it. Document the
contract durably too when it is reusable — the `EterniaBackend_brain` note, or the project's
OpenAPI/schema file; inline test fixtures only when the contract is narrow and already obvious
from the tests.

```yaml
contract_owner: backend_dev
consumer: dev
contract_status: proposed|implemented|tested|blocked
endpoint:
  method: GET|POST|PATCH|DELETE
  path: /api/...
  route_name: optional_name
auth:
  required: true|false
  roles:
    - user|admin|owner
request_schema:
  path_params: {}
  query_params: {}
  body: {}
response_schema:
  type: object|array
  fields:
    field_name:
      type: string|number|integer|boolean|object|array|null
      required: true|false
      nullable: true|false
      description: stable semantic meaning
errors:
  - status: 400
    code: validation.some_code
    shape: {detail: string, code: string}
examples:
  happy_path: {}
  empty_state: {}
  validation_error: {}
compatibility:
  additive: true|false
  migration_required: true|false
  frontend_fallback: required|not_required
backend_evidence:
  targeted_tests:
    - command: scripts/test.sh app.tests.ContractTests
      result: PASS|FAIL (exit code, test count)
  full_gate:
    command: scripts/test.sh
    result: PASS|FAIL|not_run:<exact reason>
frontend_unblock_criteria:
  - Contract status is `tested` or explicitly accepted as fixture-frozen.
  - Example payloads are present.
  - Error/null/empty semantics are defined.
```

A command you did not run is not evidence. Backend proof must cover validation/error/null/
empty behavior, not only the happy path — every frontend-visible behavior. Frontend maps
contract fields through domain models/adapters and provider/repository tests using the
packet's fixture payloads, not ad-hoc maps inside widgets.

