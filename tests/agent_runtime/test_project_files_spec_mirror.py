"""The rule spec mirror is generated, never hand-edited, and follows Eternia's spec.

``tests/fixtures/file_tree_spec/`` is written only by ``scripts/vendor_launcher_catalog.py
--file-tree-spec`` from Eternia's ``packages/eternia_file_tree_spec/spec/`` (row
``MC-PHONE-FILES-BOTH-LOCAL-READERS-FOLLOW-ONE-RULE-SPEC``). Its ``PIN.json`` holds each
file's sha256 and one digest over them.

- A hand edit of the mirror reds ``test_the_mirror_matches_its_pin``.
- A case added (or changed) in Eternia reds ``test_the_mirror_follows_the_launcher_spec``
  until it is vendored here, whenever an Eternia checkout is found: ``ETERNIA_LAUNCHER_ROOT``
  (or ``STAGEC_QA_REPO_ROOT``), else the ``EterniaLauncher`` folder beside this checkout.
  With none found the test skips and says so.

Killing mutations (2026-11-21, w1118a-spec): add a space to one mirrored case ->
``test_the_mirror_matches_its_pin`` red naming the file; add a case to the Eternia spec
without vendoring (``ETERNIA_LAUNCHER_ROOT`` at that checkout) ->
``test_the_mirror_follows_the_launcher_spec`` red.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from scripts.vendor_launcher_catalog import (
    FILE_TREE_SPEC, SPEC_PIN, spec_digest, spec_files, vendor_file_tree_spec,
)

pytestmark = pytest.mark.gate

SPEC_IN_LAUNCHER = Path("packages") / "eternia_file_tree_spec" / "spec"


def _pin() -> dict:
    return json.loads((FILE_TREE_SPEC / SPEC_PIN).read_text(encoding="utf-8"))


def _launcher_spec() -> Path | None:
    named = os.environ.get("ETERNIA_LAUNCHER_ROOT") or os.environ.get("STAGEC_QA_REPO_ROOT")
    checkout = Path(named) if named else FILE_TREE_SPEC.parents[2].parent / "EterniaLauncher"
    spec = checkout / SPEC_IN_LAUNCHER
    return spec if (spec / "rules.json").is_file() else None


def test_the_mirror_matches_its_pin():
    pin = _pin()
    assert len(pin["source_commit"]) == 40, pin["source_commit"]
    files = spec_files(FILE_TREE_SPEC)
    edited = sorted(path for path in files.keys() | pin["files"].keys()
                    if files.get(path) != pin["files"].get(path))
    assert not edited, ("the mirror differs from its pin; re-vendor, never hand-edit: "
                        + ", ".join(edited))
    assert spec_digest(files) == pin["sha256"]


def test_the_mirror_follows_the_launcher_spec():
    spec = _launcher_spec()
    if spec is None:
        pytest.skip("no Eternia checkout with the rule spec found (ETERNIA_LAUNCHER_ROOT)")
    assert spec_digest(spec_files(spec)) == _pin()["sha256"], (
        f"Eternia's rule spec at {spec} moved; vendor it: python scripts/vendor_launcher_catalog.py"
        f" --file-tree-spec {spec}")


def test_the_vendor_script_replaces_the_mirror_and_pins_it(tmp_path):
    source = tmp_path / "spec"
    (source / "cases").mkdir(parents=True)
    (source / "rules.json").write_text("{}\n", encoding="utf-8")
    (source / "cases" / "a.json").write_text('{"cases": []}\n', encoding="utf-8")
    out = tmp_path / "mirror"
    (out / "cases").mkdir(parents=True)
    (out / "cases" / "stale.json").write_text("{}", encoding="utf-8")
    first = vendor_file_tree_spec(source, out, "0" * 40)
    assert sorted(first["files"]) == ["cases/a.json", "rules.json"]
    assert not (out / "cases" / "stale.json").exists()
    assert spec_files(out) == first["files"]
    (source / "cases" / "b.json").write_text('{"cases": []}\n', encoding="utf-8")
    assert spec_digest(spec_files(source)) != first["sha256"]
    with pytest.raises(ValueError):
        vendor_file_tree_spec(tmp_path / "nowhere", out, "0" * 40)
