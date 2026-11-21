"""hermes' project-folder reader runs every golden case of Eternia's rule spec.

The cases are the vendored mirror ``tests/fixtures/file_tree_spec/cases/*.json`` (written by
``scripts/vendor_launcher_catalog.py --file-tree-spec``); Eternia's reader runs the same
cases in ``test/core/io/project_folder_conformance_test.dart``. The case format is the
mirror's ``cases/README.md``. Row ``MC-PHONE-FILES-BOTH-LOCAL-READERS-FOLLOW-ONE-RULE-SPEC``.

Killing mutations (2026-11-21, w1118a-spec):
- drop the symlink check: ``resolve_within_root`` returns ``actual`` without the prefix
  test -> the five ``*_out_of_the_root`` cases red (a symlink out of the root read, listed
  or searched);
- follow links while walking: ``_walk_project_folder`` drops its ``is_symlink`` branch ->
  ``tree_lists_links_and_never_follows_them`` red;
- drop the ``.gitignore`` read: ``_skip_rules_of`` returns ``SkipRules()`` ->
  ``tree_skips_git_the_skip_list_and_gitignore`` and ``grep_skips_what_tree_skips`` red.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from agent_runtime.project_files import reader
from agent_runtime.project_files.rules import DEFAULT_DEPTH, ProjectFileRefusal

CASES = Path(__file__).resolve().parents[1] / "fixtures" / "file_tree_spec" / "cases"


def _expand(value):
    if isinstance(value, list):
        return [_expand(item) for item in value]
    if not isinstance(value, dict):
        return value
    if "$repeat" in value:
        return value["$repeat"] * value["count"]
    if "$join" in value:
        return "".join(_expand(part) for part in value["$join"])
    return {key: _expand(item) for key, item in value.items()}


def _cases() -> list:
    out = []
    for file in sorted(CASES.glob("*.json")):
        doc = json.loads(file.read_text(encoding="utf-8"))
        for case in doc["cases"]:
            out.append(pytest.param(doc["fixtures"][case["fixture"]], case,
                                    id=f"{file.stem}-{case['name']}"))
    return out


def _write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _build(fixture: dict, temp: Path) -> Path:
    root = temp / "root"
    root.mkdir()
    for path, text in fixture.get("files", {}).items():
        _write(root / path, _expand(text).encode("utf-8"))
    for path, hex_bytes in fixture.get("bytes", {}).items():
        _write(root / path, bytes.fromhex(hex_bytes))
    for path in fixture.get("dirs", []):
        (root / path).mkdir(parents=True, exist_ok=True)
    for series in fixture.get("series", []):
        for index in range(series["count"]):
            name = f"{series['prefix']}{index:0{series['width']}d}{series['suffix']}"
            _write(root / series["dir"] / name, series["text"].encode("utf-8"))
    for path, text in fixture.get("outside", {}).items():
        _write(temp / "outside" / path, _expand(text).encode("utf-8"))
    for path, target in fixture.get("links", {}).items():
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        try:
            os.symlink(target, root / path)
        except (OSError, NotImplementedError):
            pytest.skip("this platform cannot create a symlink")
    return root


def _run(root: Path, request: dict):
    path = request.get("path")
    offset = request.get("offset", 0)
    try:
        if request["verb"] == "tree":
            return reader.tree(str(root), path, depth=request.get("depth", DEFAULT_DEPTH),
                               offset=offset)
        if request["verb"] == "read":
            return reader.read(str(root), path, offset=offset)
        if request["verb"] == "grep":
            return reader.grep(str(root), request["pattern"], path, offset=offset)
    except ProjectFileRefusal as refusal:
        return refusal.code
    raise AssertionError(f"unknown verb {request['verb']!r}")


def test_the_mirror_has_cases():
    assert _cases(), f"{CASES} holds no case"


def test_every_case_name_is_unique():
    names = [param.values[1]["name"] for param in _cases()]
    assert len(set(names)) == len(names), names


@pytest.mark.parametrize(("fixture", "case"), _cases())
def test_spec_case(tmp_path, fixture, case):
    root = _build(fixture, tmp_path)
    got = _run(root, _expand(case["request"]))
    expected = _expand(case["expect"])
    if "refusal" in expected:
        assert got == expected["refusal"], case["about"]
    elif "reply" in expected:
        assert got == expected["reply"], case["about"]
    else:
        assert isinstance(got, dict), got
        assert {key: got.get(key) for key in expected["reply_keys"]} == expected["reply_keys"]
