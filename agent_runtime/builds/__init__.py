"""Builds as a first-class ``running_work`` kind — the package map (program rule 16).

Plan: ``docs/agent-runtime-harness/planned/build-running-work-2026-10-04.md`` §9.
Modules, lowest layer first; no module imports one above it (W0-G6)::

    agent_runtime/builds/
      __init__.py          lanes    this map (imports nothing: every consumer names its module)
      unknowns.py          models   the typed-unknown kinds, the bounded/deduped index, evidence redaction
      vocabulary.py        models   the build wire enums (stage, source, liveness, outcome, controls, …), one tuple each, the limits
      flutter_argv.py      models   the Flutter argv parser lifted from flutter_build_guard, FlutterCommand
      recognizer_flutter.py policy  FLUTTER_STAGES (forward-only), the Built artifact line, stage-line unknowns
      registry.py          stores   record schema v1, reader rules (liveness/stall/expiry), writer helper, gc, the dir
      liveness.py          stores   progress across snapshots (output chars, CPU seconds) -> liveness, stalling
      history.py           stores   history.jsonl append + the median ETA
      detect.py            lanes    the psutil scan under this machine's bound slots (+ scan cost), serve-only
      sweep.py             lanes    serve tick: stall-fail (agent/announced ONLY), build.ended, history, gc, boot

The package ``__init__`` deliberately imports no submodule, so ``import
agent_runtime.builds.flutter_argv`` costs the parser and nothing else.
"""

from __future__ import annotations

__layer__ = "lanes"
