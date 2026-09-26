"""Executable documentation: real parser syntax, complete traversal and drift detection."""
from __future__ import annotations

import argparse
import re
import shlex

import pytest

from scripts.emit_harness_command_directory import (
    REFERENCE, REPO_ROOT, build_tree, check_reference, command_parsers, render,
)

DIRECTORY = REPO_ROOT / "docs/agent-runtime-harness/10-command-directory.md"


@pytest.fixture(scope="module")
def tree():
    return build_tree()


def test_committed_reference_matches_live_parser(tree):
    assert check_reference(REPO_ROOT / REFERENCE, render(tree)), "Regenerate with --write"


def test_operator_examples_parse_without_executing_handlers(tree):
    blocks = re.findall(r"```bash\n(.*?)```", DIRECTORY.read_text(encoding="utf-8"), re.S)
    commands = [line for block in blocks for line in block.splitlines()
                if line.startswith("hermes ")]
    assert commands, "No operator examples found"
    for command in commands:
        args = tree.parse_args(shlex.split(command)[1:])
        assert callable(args.func), command
        # Deliberately never call args.func: these include durable writes.


def test_every_canonical_command_is_indexed_once(tree):
    reference = render(tree)
    paths = [path for path, _, _ in command_parsers(tree)]
    assert len(paths) == len(set(paths))
    for path in paths:
        assert reference.count("\n## hermes " + " ".join(path) + "\n") == 1
        assert f"](#{'-'.join(('hermes', *path))})" in reference


def test_aliases_hidden_flags_and_nested_commands():
    parser = argparse.ArgumentParser(prog="hermes")
    commands = parser.add_subparsers()
    group = commands.add_parser("group", aliases=["g"])
    leaf = group.add_subparsers().add_parser("read", aliases=["r"])
    leaf.add_argument("--visible", required=True, help="Visible option")
    leaf.add_argument("--secret-internal", help=argparse.SUPPRESS)
    text = render(parser)
    assert text.count("\n## hermes group read\n") == 1
    assert "Aliases: `g`." in text and "Aliases: `r`." in text
    assert "--visible" in text and "--secret-internal" not in text


def test_live_flag_change_and_missing_file_are_detected(tmp_path, capsys):
    parser = argparse.ArgumentParser(prog="hermes")
    leaf = parser.add_subparsers().add_parser("probe")
    target = tmp_path / "reference.md"
    assert not check_reference(target, render(parser))
    target.write_text(render(parser), encoding="utf-8")
    assert check_reference(target, render(parser))
    leaf.add_argument("--new-real-flag", help="New parser option")
    assert not check_reference(target, render(parser))
    assert "--new-real-flag" in capsys.readouterr().err


def test_render_ignores_terminal_width(tree, monkeypatch):
    monkeypatch.setenv("COLUMNS", "40")
    narrow = render(tree)
    monkeypatch.setenv("COLUMNS", "180")
    assert render(tree) == narrow


def test_write_and_check_use_repository_root(tmp_path, monkeypatch, tree):
    from scripts import emit_harness_command_directory as emitter

    root = tmp_path / "checkout"
    root.mkdir()
    monkeypatch.setattr(emitter, "REPO_ROOT", root)
    monkeypatch.setattr(emitter, "build_tree", lambda: tree)
    monkeypatch.chdir(tmp_path)
    assert emitter.main(["--write"]) == 0
    target = root / REFERENCE
    assert target.is_file()
    assert emitter.main(["--check"]) == 0
    target.write_text("stale documentation\n", encoding="utf-8")
    assert emitter.main(["--check"]) == 1


def test_directory_relative_links_resolve():
    for page in (DIRECTORY, REPO_ROOT / REFERENCE):
        text = page.read_text(encoding="utf-8")
        for target in re.findall(r"\]\(([^)]+)\)", text):
            if target.startswith(("#", "https://", "http://")):
                continue
            assert (page.parent / target.split("#", 1)[0]).exists(), target
