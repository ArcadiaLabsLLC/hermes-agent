"""No fork file leans on an upstream module or name the merged release tag lacks.

Arm ``imports`` of ``scripts/upstream_retirement_scan.py``, read against the PURE tag
(the upstream manifest's base), never the fork tree: in the fork tree a fork edit keeps
a dead upstream name alive. A release merge re-bases the manifest, so this gate reads the
new tag with no edit of its own and names every fork import, ``patch`` target and
``monkeypatch.setattr`` target the release retired.

A finding is fixed, never listed: a fork import of a name upstream retired is a bug on
the path that reads it (the first run found ``auth_noninteractive``'s custom-pool
``set-key`` raising ImportError), and a patch of one is a test that patches nothing.

MUTATION (kill): make ``ImportArm._has`` return ``True`` — the positive controls below
go red (the live tree would also stop seeing a reintroduced retired import).
"""

from __future__ import annotations

import ast

import pytest

from scripts import upstream_retirement_scan as scan

pytestmark = pytest.mark.gate


class _FakeTree:
    """A tree from a dict, shaped like ``scan.Tree``: no git."""

    def __init__(self, files: dict[str, str], ref: str = "fake"):
        self.ref = ref
        self._files = files
        self.paths = frozenset(files)
        self.dirs = frozenset(p.rsplit("/", 1)[0] for p in files if "/" in p)

    def read(self, path: str) -> str | None:
        return self._files.get(path)

    module_path = scan.Tree.module_path


UPSTREAM_AT_TAG = {"pkg/__init__.py": "", "pkg/mod.py": "def kept():\n    pass\n"}
UPSTREAM_AT_FORK_POINT = {"pkg/__init__.py": "", "pkg/mod.py": "def kept():\n    pass\n\ndef retired():\n    pass\n"}


def _findings(fork_source: str, *, head_mod: str | None = None) -> list[scan.Finding]:
    head_files = dict(UPSTREAM_AT_TAG, **{"fork_owned.py": fork_source})
    if head_mod is not None:
        head_files["pkg/mod.py"] = head_mod
    arm = scan.ImportArm(_FakeTree(head_files), _FakeTree(UPSTREAM_AT_TAG),
                         [_FakeTree(UPSTREAM_AT_FORK_POINT)])
    return [f for ref in scan.references("fork_owned.py", ast.parse(fork_source))
            if (f := arm.judge(ref)) is not None]


@pytest.mark.parametrize(
    ("source", "kind", "target"),
    [
        ("from pkg.mod import gone\n", "name-missing", "pkg.mod:gone"),
        ("from unittest import mock\nmock.patch('pkg.mod.gone')\n", "name-missing", "pkg.mod:gone"),
        ("import pkg.mod as m\ndef t(monkeypatch):\n    monkeypatch.setattr(m, 'gone', 1, raising=False)\n",
         "name-missing", "pkg.mod:gone"),
        ("from pkg.vanished import x\n", "name-missing", "pkg:vanished"),
    ],
)
def test_a_fork_reference_the_tag_lacks_is_a_finding(source, kind, target):
    found = _findings(source)
    assert [(f.kind, f.target) for f in found] == [(kind, target)]


def test_a_name_upstream_retired_but_a_fork_edit_keeps_is_retired_not_fork_added():
    head_mod = UPSTREAM_AT_FORK_POINT["pkg/mod.py"]
    found = _findings("from pkg.mod import retired\n", head_mod=head_mod)
    assert [(f.kind, f.target) for f in found] == [("name-retired", "pkg.mod:retired")]


def test_an_upstream_submodule_the_fork_keeps_after_upstream_deleted_it_is_retired():
    history = dict(UPSTREAM_AT_FORK_POINT, **{"pkg/old.py": "x = 1\n"})
    head = dict(UPSTREAM_AT_TAG, **{"pkg/old.py": "x = 1\n", "fork_owned.py": "from pkg.old import x\n"})
    arm = scan.ImportArm(_FakeTree(head), _FakeTree(UPSTREAM_AT_TAG), [_FakeTree(history)])
    found = [arm.judge(ref) for ref in scan.references("fork_owned.py", ast.parse(head["fork_owned.py"]))]
    assert [(f.kind, f.target) for f in found if f] == [("name-retired", "pkg:old")]


def test_names_the_tag_has_or_the_fork_adds_or_that_shadow_a_builtin_are_not_findings():
    head_mod = UPSTREAM_AT_TAG["pkg/mod.py"] + "\ndef fork_added():\n    pass\n"
    source = ("from pkg.mod import kept, fork_added\n"
              "def t(monkeypatch):\n    import pkg.mod as m\n    monkeypatch.setattr(m, 'open', 1, raising=False)\n")
    assert _findings(source, head_mod=head_mod) == []


def test_a_module_that_exports_into_its_own_namespace_is_never_judged_by_parse():
    assert scan.bound_names(ast.parse("_registry.export(globals())\n")) is None
    assert scan.bound_names(ast.parse("for _m in parts:\n    _m.register(sys.modules[__name__])\n")) is None


@pytest.mark.timeout(300)  # parses ~2,500 fork files and their tag modules: 28 s alone on a loaded box, over addopts' 30
def test_no_fork_file_references_an_upstream_name_the_merged_tag_lacks():
    pins = scan.Pins(tag=scan.manifest_base())
    found = scan.scan(["imports"], pins)["imports"]
    assert found == [], "fork references to upstream names the tag lacks:\n" + "\n".join(
        f.render() for f in found)
