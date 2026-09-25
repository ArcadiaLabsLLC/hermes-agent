"""W0-G4 — ``hermes_cli.harness`` is a thin namespace: no exec'd parts, no re-export shims.

Plan: ``docs/agent-runtime-harness/planned/downstream-god-file-refactor.md`` §0.4
and §2 Wave 0. Until lane H1 ``_load_command_parts`` ran the command parts with
``exec(compile(...), globals())``, so a test patch on ``harness.<name>`` reached
every part. Each part is now a real module that looks its names up in its own
globals, so a patch on ``harness.X`` that no harness code reads is a no-op that
PASSES. This gate closes that door by construction (it landed
``xfail(strict=True)`` in Wave 0; H1's CHANGE commit made it a plain test).

Both arms read the RUNTIME module and the compiler's symbol table, never a spelling:

* no ``_load_command_parts`` attribute, and no ``exec(`` call in any fork file
  under ``hermes_cli/``;
* every callable ``hermes_cli.harness`` binds is defined there, or is on the
  §0.4 allowlist, or is read as a global by harness.py's own code. A borrowed
  callable nothing in harness.py reads is a re-export shim. (The Wave 0 draft
  also refused every borrowed callable harness.py's own bodies use; that
  cannot hold while those bodies live there, and it is not the hazard §0.4
  names. The parser wires the parts through their MODULES —
  ``persona_commands._cmd_persona_list`` — so no ``func=`` exemption is needed.)

The logic is ``scripts/god_file_fences.py``'s ``borrowed_callables`` /
``global_reads`` / ``exec_sites``.
"""

from __future__ import annotations

import inspect
import types

from scripts import god_file_fences as fences
from scripts import god_file_probe as probe


def test_the_borrowed_callable_check_reds_a_reexport():
    """Positive control: one borrowed repo callable is caught; allowlisted, local and stdlib are not."""
    fake = types.ModuleType(fences.HARNESS_MODULE)
    fake._cmd_persona_list = probe.fork_production_files  # a repo callable defined elsewhere
    fake.build_parser = probe.fork_production_files  # allowlisted
    fake.local = lambda: None
    fake.local.__module__ = fences.HARNESS_MODULE
    fake.Parameter = inspect.Parameter  # stdlib: not a repo module
    assert fences.borrowed_callables(fake, frozenset()) == ["_cmd_persona_list (from scripts.god_file_probe)"]


def test_a_borrowed_callable_the_module_reads_is_an_import_not_a_shim():
    """Positive control for the reads exemption, and the read set is the compiler's."""
    fake = types.ModuleType(fences.HARNESS_MODULE)
    fake.fork_production_files = probe.fork_production_files
    assert fences.borrowed_callables(fake, frozenset({"fork_production_files"})) == []
    reads = fences.global_reads("scripts/god_file_fences.py")
    assert "fork_production_files" in reads  # read inside exec_sites
    assert "sites" not in reads  # a local, not a global


def test_no_part_is_execd_into_the_harness_namespace():
    import hermes_cli.harness as harness

    assert not hasattr(harness, "_load_command_parts")
    assert fences.exec_sites() == []


def test_the_harness_binds_no_borrowed_callable():
    import hermes_cli.harness as harness

    assert fences.borrowed_callables(harness, fences.global_reads()) == []
