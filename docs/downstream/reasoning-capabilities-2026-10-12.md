# First-class Console thinking capabilities — 2026-10-12

The operator approved replacing the model-only boolean and fixed UI ladder with
provider-owned capability facts. `agent_runtime/reasoning_capabilities.py` joins
existing cache-only serving metadata, reference metadata, provider declarations
and native transport vocabularies. The existing next-turn cascade owns route
and inherited effort resolution. Summaries, incremental patches and both operator
model RPC reads expose the same typed value; the legacy boolean remains additive.

Already-fetched catalogs populate the existing disk mirror. Scope includes home,
auth-store revision, endpoint and opaque secret fingerprints. Inspection reads
only; Router's existing provider hook now permits explicitly suppressing its
background warmer. Missing profiles and unreported provider options stay unknown.
Unsupported models are distinct from unknown models. Unmapped provider terms
remain inspectable, without inventing sendable IDs. Codex and Copilot transport
hooks use the same cached serving options, so new catalog models need no UI entry.

The paired Launcher retains the value through its adapter, snapshot, consumer
equality and facts query revision. Focus renders the native steps, with neutral
unreported/default/custom states. Existing mint/charcoal styling, exact commit
IDs, pricing disclosure and Advanced remain. Opening the menu refreshes its
existing conversation facts owner while retaining the confirmed answer.

## Verification

Implementation-complete checkpoint preceded new tests. Focused native model,
patch and capability tests passed 90 assertions before the final Router guard
was added; Launcher capability, Focus, view-model and real app-binding tests
passed 105 tests. Final landing receipts follow below.

Actual killing mutations were applied and restored:

- Ignore serving-catalog facts, collapse cache keys across auth revisions and
  enable background warming during inspection. Native capability suite: exit 1,
  **5 failed, 1 passed**. Failures include missing provider default (`None != high`),
  unmapped support (`unsupported != supported`), leaked account cache (dict was
  expected None), lost Router options, and `['warm'] != []`.
- Launcher mutations and final gate qualification are recorded below after
  restoration.

Native runtime restart and a rebuilt Launcher are required to exercise the new
contract in the running desktop. No claim of live desktop acceptance is made
from widget or RPC tests alone.

## Final focused receipts and guard qualification

- Native model/RPC/patch/cache/transport suite: **279 passed**, 8 files, 57.8 s.
- Native stream/list/patch projection and footprint contract follow-up: **41 passed**,
  4 files. Generator fixtures were refreshed from real constructors and mirrored
  byte-for-byte to the Launcher with their SHA manifest. The approved upstream
  seam budget records 194 -> 202 files, 970 -> 994 deleted lines, heavy unchanged
  at 5; its reason names the operator-approved capability contract.
- Launcher restored capability/Focus/view-model/app-binding suite: **105 passed**.
  Composer model journeys: **14 passed**. Focus and mirrored stream fixtures:
  **28 passed**, including provider descriptions and defaults behind the info door.
- Launcher toolkit: **20 marionette + 1264 MCP tests passed**, one MCP skip;
  package analysis and pinned format checks passed. Architecture retry completed
  **1495 passed, 2 failed**: existing iOS/macOS Podfile lock drift, already queued.
  The first attempt's SDK optimizing-JIT crash remains recorded in the tooling
  queue; no claim of a clean first attempt.

Additional actual killing mutations, all restored:

- Drop app-bound capabilities and force four UI steps: **3 failed, 25 passed**,
  including the real RPC-to-composer join (`supported != null`) and exact native
  options (`low/max` differed from the fixed ladder).
- Guess Medium and accept another provider/model's capabilities: **2 failed,
  3 passed**. Red assertions were `expected null; actual medium` and
  `expected false; actual true` for a foreign route.
- Drop Focus's capability disclosure: **1 failed**; `Thinking support: supported`
  was missing after opening info. Restored Focus/stream suite passed 28.
- Disable the serving-endpoint guard: **1 failed, 6 passed**;
  a foreign endpoint returned `(low, max)` where None was required. Restored native
  suite passed 279.

The first whole-tree fork gate completed 1157 files, including inherited
transport/catalog tests. It exposed stale stream/list goldens, the missing
projection dependency and the explicit seam budget; those were corrected and
passed the 41-test contract follow-up. The inherited TTS requirement failure was
reproduced alone on unchanged main and queued. The PM slow-exit setup still needs
Python 3.14 (this runner is 3.13.15); its existing queue remains authoritative.
The gateway two-root test passed its long-run allowance on this run. Bundle
abnormal-exit/isolation classification and Windows source-check printing were
filed in fork hygiene. A final stable-tree gate/check receipt follows below.

## Stable-tree landing qualification

The second whole-tree fork gate completed **1158 files, 14936 passed, 1 failed,
1 setup error, 62 skipped in 619.2 s**, exit 1. Only the unchanged-main TTS
requirement and Python-version PM setup remain red; both are queued. Three
files were retried alone, so this is a qualified receipt, not a clean first pass.
The shape/projection/list/footprint repairs were green in this gate.

Final source-health follow-up added traceback logging at the two new fail-open
boundaries, defined Router's missing disk TTL, and moved offline defaults into
the existing reasoning sibling to keep the models facade below its prior size.
The Router regression was killed by removing the TTL definition: **1 failed,
7 passed**, actual `NameError: _DISK_TTL_SECONDS is not defined`; restored
reasoning/model/patch/Copilot/fixture/footprint follow-up: **148 passed**, 8 files.
Changed-unit code health against current main: **0 blocking, 0 advisory**;
touched Python Ruff checks passed. The full upstream-reference check remains
non-green (1879 blocking findings across 5077 files, plus existing footgun/tmp/
Ruff guard residue); its Windows printing defect was reproduced and queued.
No broad check is presented as fully green.
