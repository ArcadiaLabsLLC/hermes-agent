"""W0-G4 — ``hermes_cli.harness`` is a thin namespace: no exec'd parts, no re-export shims.

Plan: ``docs/agent-runtime-harness/planned/downstream-god-file-refactor.md`` §0.4
and §2 Wave 0. Until lane H1 ``_load_command_parts`` ran the command parts with
``exec(compile(...), globals())``, so a test patch on ``harness.<name>`` reached
every part. Each part is now a real module that looks its names up in its own
globals, so a patch on ``harness.X`` that no harness code reads is a no-op that
PASSES. This gate closes that door by construction (it landed
``xfail(strict=True)`` in Wave 0; H1's CHANGE commit made it a plain test).

Both arms read the RUNTIME module, never a spelling:

* no ``_load_command_parts`` attribute, and no ``exec(`` call in any fork file
  under ``hermes_cli/``;
* every callable ``hermes_cli.harness`` binds is defined there or is on the
  §0.4 allowlist — READ OR NOT. This is the plan's full form: lane H1 had
  narrowed it to "or is read as a global by harness.py's own code" while the
  verb bodies still lived in the file; lane H2 moved them out and restored it.
  The entry reaches the parser tree through its MODULE, and modules are not
  callables, so ``func=`` targets need no exemption.

The logic is ``scripts/god_file_fences.py``'s ``borrowed_callables`` /
``exec_sites``.
"""

from __future__ import annotations

import inspect
import types

from scripts import god_file_fences as fences
from scripts import god_file_probe as probe


def test_the_borrowed_callable_check_reds_a_reexport():
    """Positive control: one borrowed repo callable is caught; allowlisted, local, stdlib and modules are not."""
    fake = types.ModuleType(fences.HARNESS_MODULE)
    fake._cmd_persona_list = probe.fork_production_files  # a repo callable defined elsewhere
    fake.build_parser = probe.fork_production_files  # allowlisted
    fake.local = lambda: None
    fake.local.__module__ = fences.HARNESS_MODULE
    fake.Parameter = inspect.Parameter  # stdlib: not a repo module
    fake.probe = probe  # a part bound as a MODULE: how the entry reaches the tree
    assert fences.borrowed_callables(fake) == ["_cmd_persona_list (from scripts.god_file_probe)"]


def test_a_borrowed_callable_the_harness_reads_is_still_refused():
    """The full form: a READ is not an exemption (H1's narrowed form let it through)."""
    fake = types.ModuleType(fences.HARNESS_MODULE)
    fake.populate_parser = probe.fork_production_files  # read by the entry's own code in H1's head
    assert fences.borrowed_callables(fake) == ["populate_parser (from scripts.god_file_probe)"]


def test_no_part_is_execd_into_the_harness_namespace():
    import hermes_cli.harness as harness

    assert not hasattr(harness, "_load_command_parts")
    assert fences.exec_sites() == []


def test_the_harness_binds_no_borrowed_callable():
    import hermes_cli.harness as harness

    assert fences.borrowed_callables(harness) == []
