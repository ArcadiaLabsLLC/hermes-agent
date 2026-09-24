"""W0-G4 — ``hermes_cli.harness`` is a thin namespace: no exec'd parts, no borrowed callables.

Plan: ``docs/agent-runtime-harness/planned/downstream-god-file-refactor.md`` §0.4
and §2 Wave 0. Today ``_load_command_parts`` runs the command parts with
``exec(compile(...), globals())``, so the test patches on ``harness.<name>``
work only because every part's names resolve through harness.py's globals. The
moment a part becomes a real module those patches become no-ops that PASS. This
gate closes that door by construction: it is RED on today's tree, lands
``xfail(strict=True)``, and H1's CHANGE commit removes the markers.

Both arms read the RUNTIME module (a positive guarantee, not a spelling):

* no ``_load_command_parts`` attribute, and no ``exec(`` call in any fork file
  under ``hermes_cli/``;
* every callable ``hermes_cli.harness`` binds is defined there, or is on the
  §0.4 allowlist, or is an argparse ``func=`` target of the built parser that
  lives in a ``hermes_cli.harness_parts`` module.

The logic is ``scripts/god_file_fences.py``'s ``borrowed_callables`` /
``exec_sites``; the positive control below runs it while the live arms are xfail.
"""

from __future__ import annotations

import argparse
import inspect
import types

import pytest

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
    assert fences.borrowed_callables(fake, []) == ["_cmd_persona_list (from scripts.god_file_probe)"]


@pytest.mark.xfail(strict=True, reason="RED until H1: harness.py still exec's its command parts")
def test_no_part_is_execd_into_the_harness_namespace():
    import hermes_cli.harness as harness

    assert not hasattr(harness, "_load_command_parts")
    assert fences.exec_sites() == []


@pytest.mark.xfail(strict=True, reason="RED until H1: harness.py re-binds callables other modules define")
def test_the_harness_binds_no_borrowed_callable():
    import hermes_cli.harness as harness

    parser = argparse.ArgumentParser(prog="harness")
    harness.populate_parser(parser)
    assert fences.borrowed_callables(harness, fences.parser_func_targets(parser)) == []
