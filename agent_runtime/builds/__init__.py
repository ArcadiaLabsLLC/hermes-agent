"""Builds as a first-class ``running_work`` kind — the package map (program rule 16).

Plan: ``docs/agent-runtime-harness/planned/build-running-work-2026-10-04.md`` §9.
Modules, lowest layer first; no module imports one above it (W0-G6)::

    agent_runtime/builds/
      __init__.py          lanes    this map (imports nothing: every consumer names its module)
      unknowns.py          models   the typed-unknown kinds, the bounded/deduped index, evidence redaction
      flutter_argv.py      models   the Flutter argv parser lifted from flutter_build_guard, FlutterCommand

The package ``__init__`` deliberately imports no submodule, so ``import
agent_runtime.builds.flutter_argv`` costs the parser and nothing else.
"""

from __future__ import annotations

__layer__ = "lanes"
