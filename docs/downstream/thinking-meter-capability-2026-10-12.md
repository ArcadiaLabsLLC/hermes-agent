# Console thinking meter — GPT-6 capability recognition

The owner reported a composer Agent model panel showing GPT-6 Luna without the
approved thinking-depth meter. Launcher still renders that control when the
native `reasoning_supported` field is true; its write target is a live instance.

`agent_runtime/persona_assignments/profile.py::_model_supports_reasoning_effort`
used the offline Copilot heuristic, which recognises GPT-5 and o-series plus
Astra but not GPT-6 Luna/Sol or GPT-6.1 Sol. The same helper feeds both
`persona_instance_summary` and incremental persona-instance model patches.

The helper now recognises `GPT6_TIER_PREFIXES` and
`NO_DISABLE_TIER_PREFIXES` from the existing canonical transport effort module,
`agent/reasoning_effort.py`. It retains the existing fallback, unknown/empty
behaviour and network-free projection. No Launcher model-name rule, preference,
provider request, effort ladder or default is changed.

## Verification and recorded red

Completed implementation before extending the native tests. The killing mutation
changes the new predicate to `if False and bare.startswith(...)`, leaving the
previous fallback in place. Command:

```powershell
bash scripts/run_tests.sh tests/agent_runtime/test_persona_set_model.py tests/agent_runtime/test_state_patches.py -k "projects_reasoning_fields or gpt6_model_change"
```

Exit 1: eight failures. Six native summary cases (Luna, Luna 900k, Sol, 6.1 Sol,
vendor-prefixed 6.1 Sol 900k and normalised uppercase Luna) fail
`assert plain["reasoning_supported"] is True` with `assert False is True`.
Both model-change cases fail `assert changed["reasoning_supported"] is True`
with the same output. The GPT-5.6 summary positive control passes. Restored the
predicate, then ran both complete named files: 85 passed, zero failed in 19.0s.
The existing GPT-4.1 negative control, persisted/default effort and per-instance
isolation remain covered.

Current Launcher `agent_console_model_focus_test.dart` and
`agent_console_model_switcher_view_model_test.dart`: 77 passed. Existing tests
cover effort visibility, gesture/keyboard writes, labels, Advanced, unsupported
models, scope and native effort IDs. Launcher source remains unchanged.

Raw mutation, focused, Launcher and landing-gate logs are retained in the calling
Codex workspace. Native live acceptance is not claimed; a running serve must load
the updated runtime and publish a fresh snapshot or model patch.

The canonical fork landing gate (`bash scripts/run_tests_bundled.sh tests`) ran
once, exit 1: 1,026 files, 11,361 tests passed, one setup error and 31 skips in
543.8s. The two non-green files are previously recorded: the PM slow-exit
fixture's Python 3.14 requirement against the configured 3.13.15 interpreter,
and the two-roots gateway fixture at the known-red 120-second cap. The latter's
declared-duration control is already qualified in the H01 triage. Cache: 102
files reused, 25 audited cleanly, 924 dependency records; no new failing
assertion. Ruff passed for all three changed Python files. Broad-gate limitations
remain in the fork-hygiene queue.

## Structural follow-up

The immediate repair reuses existing runtime declarations. The wider projection
still uses a model-only Copilot fallback regardless of provider, and Launcher
still has a four-level presentation ladder. A provider-aware capability result
from the resolved next-turn route should advertise support, allowed levels and
default, preserve unknown/inherited states, and avoid network probes during
snapshot construction. Scope is the native summary/patch projection and its
typed Launcher consumer, with route/level/default consistency tests; it owns no
new model resolver or settings store. The runtime queue retains this separate
follow-up.
