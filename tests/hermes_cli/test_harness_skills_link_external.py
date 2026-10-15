"""`hermes harness skills link-external` — rehomed from core's `hermes skills` (seam Stage 2).

The verb links the shared skills root into external harness dirs (~/.claude,
~/.codex). It is the harness's, so it lives in the harness tree and core's
`hermes skills` parser is back to upstream's bytes.
"""

from __future__ import annotations

import argparse
import json

import hermes_cli.harness as harness
from hermes_cli.harness_parts import skills_commands


def _harness_parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="hermes")
    harness.build_parser(root.add_subparsers(dest="command"))
    return root


def test_the_verb_parses_and_dispatches_to_the_link_handler():
    args = _harness_parser().parse_args(["harness", "skills", "link-external", "--json"])
    assert args.func is skills_commands._cmd_skills_link_external
    assert args.json is True


def test_the_handler_prints_the_link_report(monkeypatch, capsys):
    from agent_runtime import external_skill_links
    from agent_runtime.external_skill_links import LinkReport

    report = LinkReport()
    report.add(external_skill_links.Path("/x/.claude/skills"), "demo", "linked")
    monkeypatch.setattr(external_skill_links, "link_shared_skills_into_external_harnesses", lambda: report)

    assert skills_commands._cmd_skills_link_external(argparse.Namespace(json=True)) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["summary"]["linked"] == 1
    # The linked shared root is resolved from the runtime root, so the envelope
    # says which one answered (test_harness_json_root_observability.py).
    assert payload["resolution"]["store_root"]

    assert skills_commands._cmd_skills_link_external(argparse.Namespace(json=False)) == 0
    assert capsys.readouterr().out.strip() == external_skill_links.format_report(report).strip()


def test_core_skills_parser_no_longer_offers_it():
    from hermes_cli.subcommands.skills import build_skills_parser

    root = argparse.ArgumentParser(prog="hermes")
    build_skills_parser(root.add_subparsers(dest="command"), cmd_skills=lambda args: None)
    skills = next(a for a in root._subparsers._group_actions if isinstance(a, argparse._SubParsersAction))
    verbs = skills.choices["skills"]._subparsers._group_actions[0].choices
    assert "install" in verbs  # positive control: this IS the core skills verb table
    assert "link-external" not in verbs
