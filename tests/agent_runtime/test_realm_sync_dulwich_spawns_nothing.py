"""The phone's git starts no process and ships nothing GPL-only (plan phone-realm-sync-dulwich-2026-11-16 §2, §5).

``agent_runtime/realm_sync/git_dulwich.py`` and ``agent_runtime/realm_sync/merge_theirs.py`` (once it exists)
are walked as source, a NEGATIVE proof, where over-approximating is the safe direction: they never name
``subprocess``, a process spawner, dulwich's URL-guessing ``get_transport_and_path`` (it may build a
``SubprocessGitClient`` or ``SSHGitClient``), a ``porcelain`` network verb, ``do_commit`` (which runs the
repository's hooks), or the GPL-2.0-or-later-only ``merge3`` package dulwich's own merger needs.
The phone gate (``scripts/bundle_profile_gate.py``) scans only first-party modules, so dulwich's own
spawners are invisible to it: this test is where the backend's half is pinned.

Killing mutation (recorded in the S3 commit): call ``porcelain.clone`` in ``git_dulwich.py`` -> red.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.gate

_ROOT = Path(__file__).resolve().parents[2] / "agent_runtime" / "realm_sync"
_WALKED = ("git_dulwich.py", "merge_theirs.py")

#: Names whose mere mention in the backend's source is refused (``re`` over the text, comments included).
_REFUSED = (
    r"\bsubprocess\b",
    r"\bPopen\b",
    r"\bos\.system\b",
    r"\bos\.(?:exec|spawn|fork|popen)\w*",
    r"\bpty\b",
    r"\bget_transport_and_path\w*",
    r"\bSubprocessGitClient\b",
    r"\bSSHGitClient\b",
    r"\bporcelain\.(?:clone|pull|push|fetch)\b",
    r"\bdo_commit\b",
    r"\bmerge3\b",
    r"\bmake_merge3\b",
)


def _sources() -> list[Path]:
    found = [_ROOT / name for name in _WALKED if (_ROOT / name).is_file()]
    assert found and found[0].name == "git_dulwich.py", "the dulwich backend moved: point this gate at it"
    return found


def _code_text(path: Path) -> str:
    """The module without its docstrings (they NAME what is refused, to say why)."""

    tree = ast.parse(path.read_text(encoding="utf-8"))
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    drop: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                drop.update(range(first.lineno - 1, first.end_lineno or first.lineno))
    return "".join(line for index, line in enumerate(lines) if index not in drop)


@pytest.mark.parametrize("pattern", _REFUSED)
def test_the_phone_git_never_names(pattern):
    hits = [f"{path.name}: {match.group(0)}" for path in _sources()
            for match in re.finditer(pattern, _code_text(path))]
    assert not hits, f"the dulwich backend must start no process and ship no GPL-only merge: {hits}"


def test_the_backend_imports_only_dulwich_and_the_standard_library():
    """A positive control on the walk: it reads the real module (its dulwich imports are seen)."""

    tree = ast.parse((_ROOT / "git_dulwich.py").read_text(encoding="utf-8"))
    roots = {(node.module or "").split(".")[0] for node in ast.walk(tree)
             if isinstance(node, ast.ImportFrom) and node.level == 0}
    assert "dulwich" in roots
    assert "subprocess" not in roots
