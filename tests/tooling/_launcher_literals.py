"""The population the two R10 Launcher-literal fences walk, read once per session.

Shared by ``test_no_launcher_entry_id_literals.py`` (the dotted id) and
``test_no_launcher_tool_name_literals.py`` (the underscore tool name). Population:
every tracked source file (and model-facing prose under the skill and plugin roots)
outside the test trees and ``docs/`` — a test's fake Launcher must name entries, and
docs describe the wire.
"""

from __future__ import annotations

import functools
import subprocess
from pathlib import PurePosixPath

from scripts import god_file_probe as probe

_SOURCE_SUFFIXES = frozenset({
    ".py", ".pyi", ".ts", ".tsx", ".js", ".mjs", ".cjs", ".rs", ".go", ".sh", ".ps1",
    ".yaml", ".yml", ".toml", ".json", ".txt", ".j2", ".jinja", ".tmpl",
})
#: Prose the model reads as instructions: a skill teaching an id is the same leak.
_PROSE_ROOTS = ("skills/", "optional-skills/", "plugins/")
_EXCLUDED_ROOTS = ("docs/", "Harness_Brain/", "website/")
_TEST_DIRS = frozenset({"tests", "tests-js", "__tests__", "test"})


def in_population(path: str) -> bool:
    pure = PurePosixPath(path)
    if path.startswith(_EXCLUDED_ROOTS) or _TEST_DIRS.intersection(pure.parts[:-1]):
        return False
    name = pure.name
    if name.startswith("test_") or name.endswith("_test.py") or ".test." in name or ".spec." in name:
        return False
    return pure.suffix in _SOURCE_SUFFIXES or (pure.suffix == ".md" and path.startswith(_PROSE_ROOTS))


@functools.lru_cache(maxsize=1)
def population_texts() -> tuple[tuple[str, str], ...]:
    """``(path, text)`` for every file in the population, sorted by path."""

    out = subprocess.run(["git", "ls-files", "-z"], cwd=probe.ROOT, capture_output=True, check=True)
    paths = sorted(p for p in out.stdout.decode("utf-8").split("\0")
                   if p and in_population(p) and (probe.ROOT / p).is_file())
    return tuple((p, (probe.ROOT / p).read_text(encoding="utf-8", errors="ignore")) for p in paths)
