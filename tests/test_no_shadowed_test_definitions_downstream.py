"""The fork half of upstream's ``tests/test_no_shadowed_test_definitions.py`` walk.

Upstream's ``test_no_shadowed_definitions_in_test_modules`` parses every ``test_*.py``
under ``tests/`` (~7,000 files): 33.4 s alone, over the 30 s per-test cap under load
(q-chain, 2026-10-18). This runs the SAME check -- upstream's own ``_duplicates_in``
over upstream's own ``_test_modules`` -- through the shared parse
(``scripts/source_cache.py``), and parses only a file whose text spells some
``def <name>`` twice: a shadow needs two definitions of one name, so a file without a
repeated ``def`` name cannot hold one (the pre-filter over-approximates; it never drops
a file the walk would flag). Upstream's walk is skipped by a file row in
``tests/_downstream/id_markers/fork_marks.py``; its other tests still run.

Killing mutation (2026-10-18): make ``_may_shadow`` return ``False`` ->
``test_a_planted_shadow_is_found`` red.
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

import pytest

from scripts import source_cache
from tests import test_no_shadowed_test_definitions as upstream

pytestmark = pytest.mark.gate

_DEF = re.compile(r"\bdef\s+([A-Za-z_]\w*)")


def _may_shadow(text: str) -> bool:
    counts = Counter(_DEF.findall(text))
    return any(n > 1 for name, n in counts.items() if name not in upstream._ALLOWED_REPEATS)


def shadowed_definitions(paths: list[Path], root: Path) -> list[str]:
    problems: list[str] = []
    for path in paths:
        if not _may_shadow(source_cache.source(path)):
            continue
        tree = source_cache.tree(path, keep=False)
        if tree is None:  # pragma: no cover - a broken test file is its own red
            continue
        rel = path.relative_to(root).as_posix()
        problems += upstream._duplicates_in(tree.body, "<module>", rel)
        for node in upstream.ast.walk(tree):
            if isinstance(node, upstream.ast.ClassDef):
                problems += upstream._duplicates_in(node.body, node.name, rel)
    return problems


def test_no_shadowed_definitions_in_test_modules():
    problems = shadowed_definitions(upstream._test_modules(), upstream.REPO_ROOT)
    assert not problems, (
        "A duplicate definition silently deletes the earlier one. Rename or "
        "remove:\n  " + "\n  ".join(problems)
    )


def test_a_planted_shadow_is_found(tmp_path):
    shadow = tmp_path / "test_planted.py"
    shadow.write_text("class T:\n    def test_a(self):\n        pass\n\n    async def test_a(self):\n        pass\n",
                      encoding="utf-8")
    clean = tmp_path / "test_clean.py"
    clean.write_text("def test_a():\n    pass\n\ndef test_b():\n    pass\n", encoding="utf-8")
    assert shadowed_definitions([shadow, clean], tmp_path) == [
        "test_planted.py:5 T.test_a() shadows the definition at line 2"
    ]
    assert not _may_shadow(clean.read_text(encoding="utf-8"))
