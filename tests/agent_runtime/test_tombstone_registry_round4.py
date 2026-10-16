"""The round-4 coverage audit, moved out of ``test_tombstone_registry.py`` (code-health
FILE_LINES offset, lane h5-deadcode): every top-level test the round-4 deletions removed
must leave no live production subject uncovered. Bodies unchanged.
"""

from __future__ import annotations

import ast
import functools
import hashlib
import json
import os
import subprocess
import warnings
from pathlib import Path

import pytest

from tests import _fork_scope

HERMES_ROOT = Path(__file__).resolve().parents[2]

_ROUND4_COVERAGE_BASE = "4a21f0779"
#: ``git merge-base 4a21f0779 upstream/main`` -- the upstream point the base had
#: merged. Frozen for the same reason: the merge-base cannot be computed without
#: the base. It is an upstream commit, so it resolves wherever upstream is fetched.
_ROUND4_UPSTREAM_MERGED = "126ff7071b6b755055879648f4e859b3187d0fac"
#: Every top-level ``test_*`` at the base that referenced a production symbol,
#: with the ``(module, symbol)`` subjects it referenced. Hash-pinned so a refresh
#: is a reviewable act; see ``fixtures/README.md``.
_ROUND4_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "round4_base_test_references.json"
_ROUND4_FIXTURE_SHA256 = "7714caec75881a47ef52524f851d250e34eab8c03b4f99127048158e2da8b41c"
_PRODUCTION_PACKAGES = ("agent_runtime", "hermes_cli")


def _parsed(source: str) -> ast.Module | None:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", SyntaxWarning)
            return ast.parse(source)
    except (SyntaxError, ValueError):
        return None


def _production_imports(tree: ast.AST) -> tuple[dict[str, tuple[str, str]], dict[str, str]]:
    direct: dict[str, tuple[str, str]] = {}
    modules: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith(
            _PRODUCTION_PACKAGES
        ):
            for alias in node.names:
                if alias.name != "*":
                    direct[alias.asname or alias.name] = (node.module, alias.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith(_PRODUCTION_PACKAGES):
                    modules[alias.asname or alias.name.rsplit(".", 1)[-1]] = alias.name
    return direct, modules


def _production_references(
    tree: ast.AST,
    direct: dict[str, tuple[str, str]],
    modules: dict[str, str],
) -> set[tuple[str, str]]:
    references: set[tuple[str, str]] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            if node.id in direct:
                references.add(direct[node.id])
        elif (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id in modules
        ):
            references.add((modules[node.value.id], node.attr))
    return references


def _live_production_symbol(subject: tuple[str, str]) -> bool:
    module_name, symbol = subject
    source_path = HERMES_ROOT / f"{module_name.replace('.', '/')}.py"
    if not source_path.is_file():
        return False
    tree = _parsed(source_path.read_text(encoding="utf-8", errors="replace"))
    return bool(
        tree
        and any(
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            and node.name == symbol
            for node in tree.body
        )
    )


@functools.lru_cache(maxsize=1)
def _covered_production_subjects() -> frozenset[tuple[str, str]]:
    """Every ``(module, symbol)`` any test in the tree references.

    A SECOND full-tree walk, independent of the production render above and
    larger: 2880 files under ``tests/``, 43.9s to parse. It was inline in the
    test below, so that one item carried all of it — the same per-test-budget /
    per-session-cost mismatch, one screen further down the same file, and the
    one that surfaced the moment the first was fixed.
    """

    covered: set[tuple[str, str]] = set()
    for path in (HERMES_ROOT / "tests").rglob("test_*.py"):
        tree = _parsed(path.read_text(encoding="utf-8", errors="replace"))
        if tree is None:
            continue
        direct, modules = _production_imports(tree)
        covered.update(_production_references(tree, direct, modules))
    return frozenset(covered)


# Warmed at import for the same reason as the production render above: the walk
# belongs to the session, not to whichever item reaches it first.
_covered_production_subjects()

#: Snapshotted at import so the guard fails deterministically if the warm goes.
_COVERAGE_CACHE_SIZE_AT_IMPORT = _covered_production_subjects.cache_info().currsize


def test_the_test_tree_walk_is_also_paid_at_import():
    """The second walk's guard, and it exists because the first fix revealed it.

    Fixing ``test_the_scanner_is_not_vacuous`` moved the process death forward to
    here rather than removing it — this file had TWO independent full-tree walks
    billed to two different test items. A guard on only the first would have
    reported success on a file that still could not finish.
    """

    assert _COVERAGE_CACHE_SIZE_AT_IMPORT == 1, (
        "the tests/ tree walk was NOT warmed at module import (cache size at "
        f"import: {_COVERAGE_CACHE_SIZE_AT_IMPORT}). "
        "test_round4_deleted_tests_left_no_live_production_subject_uncovered "
        "then pays ~44s of parsing inside its own item, against the 30s cap — "
        "and --timeout-method=thread kills the process. Restore the warm."
    )
    assert _covered_production_subjects.cache_info().misses == 1, (
        "the tests/ tree was walked more than once: "
        f"{_covered_production_subjects.cache_info()}"
    )
    assert len(_covered_production_subjects()) > 100, (
        "the coverage walk resolved almost nothing; the gate below would pass "
        "vacuously"
    )


#: Set by :func:`_round4_uncovered_subjects` when the frozen fixture is missing,
#: unreadable or not the pinned bytes. Recorded rather than raised: the walk is
#: warmed at module import, so raising here aborts collection of this whole
#: file. The round-4 test names this instead, so the walk's empty result can
#: never be read as "nothing uncovered".
_ROUND4_HISTORY_ERROR: str | None = None


def _historical_test_sources(root: Path, base: str, *, every_file: bool = False) -> dict[str, str]:
    """Read changed pre-existing tests in three Git calls, including partial clones.

    numstat makes Git prefetch missing historical blobs in one batch. A
    name-only diff followed by thousands of git-show processes instead incurs
    one lazy network fetch per missing blob on CI's blob:none checkout.
    Disabling rename detection both avoids similarity work and keeps the old
    side of a moved test in the deleted-test coverage audit.
    """
    paths: list[bytes] = []
    if not every_file:
        diff = subprocess.run(
            ["git", "diff", "--numstat", "--no-renames", "--diff-filter=DMT", "-z",
             base, "HEAD", "--", "tests"],
            cwd=root, check=True, capture_output=True,
        )
        paths = [record.split(b"\t", 2)[2] for record in diff.stdout.split(b"\0") if record]
        if not paths:
            return {}
    tree = subprocess.run(
        ["git", "ls-tree", "-r", "-z", base, "--", "tests"],
        cwd=root, check=True, capture_output=True,
    ).stdout
    objects = {}
    for record in tree.split(b"\0"):
        if record:
            metadata, path = record.split(b"\t", 1)
            _mode, kind, oid = metadata.split()
            if kind == b"blob":
                objects[path] = oid
    if every_file:
        paths = sorted(path for path in objects if path.endswith(b".py"))
    if any(path not in objects for path in paths):
        raise ValueError("Git did not list a historical test blob")
    # Object IDs avoid filename delimiters and work with older Git versions
    # that do not support cat-file's NUL-delimited input option.
    contents = subprocess.run(
        ["git", "cat-file", "--batch"], cwd=root,
        input=b"".join(objects[path] + b"\n" for path in paths),
        check=True, capture_output=True,
    ).stdout
    sources: dict[str, str] = {}
    cursor = 0
    for path in paths:
        boundary = contents.index(b"\n", cursor)
        header = contents[cursor:boundary].split()
        if len(header) != 3 or header[1] != b"blob":
            raise ValueError("Git did not return a historical test blob")
        size = int(header[2])
        cursor = boundary + 1
        end = cursor + size
        if contents[end:end + 1] != b"\n":
            raise ValueError("Git returned a truncated historical test blob")
        sources[path.decode("utf-8")] = contents[cursor:end].decode("utf-8", errors="replace")
        cursor = end + 1
    if cursor != len(contents):
        raise ValueError("Git returned unexpected trailing historical test data")
    return sources


def _base_test_references(root: Path, base: str) -> dict[str, dict[str, list[list[str]]]]:
    """The fixture's generator: every base test's production subjects.

    Needs ``base``'s objects, so it runs only on a clone that still holds the
    pre-fold history; the committed JSON is its output through
    :func:`_serialise_base_test_references`.
    """

    references: dict[str, dict[str, list[list[str]]]] = {}
    for relative, source in _historical_test_sources(root, base, every_file=True).items():
        tree = _parsed(source)
        if tree is None:
            continue
        module_direct, module_imports = _production_imports(tree)
        tests: dict[str, list[list[str]]] = {}
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not node.name.startswith("test_"):
                continue
            local_direct, local_imports = _production_imports(node)
            subjects = _production_references(
                node, module_direct | local_direct, module_imports | local_imports
            )
            if subjects:
                tests[node.name] = sorted([list(subject) for subject in subjects])
        if tests:
            references[relative] = tests
    return references


def _serialise_base_test_references(references: dict[str, dict[str, list[list[str]]]]) -> bytes:
    """One line per test, sorted, so a refresh diffs by test rather than by blob."""

    lines = ["{"]
    for file_index, relative in enumerate(sorted(references)):
        lines.append(f" {json.dumps(relative)}: {{")
        tests = references[relative]
        for test_index, name in enumerate(sorted(tests)):
            comma = "," if test_index < len(tests) - 1 else ""
            subjects = json.dumps(tests[name], separators=(",", ":"))
            lines.append(f"  {json.dumps(name)}: {subjects}{comma}")
        lines.append(" }," if file_index < len(references) - 1 else " }")
    lines.append("}")
    return ("\n".join(lines) + "\n").encode("utf-8")


def _frozen_base_test_references() -> dict[str, dict[str, list[list[str]]]]:
    payload = _ROUND4_FIXTURE.read_bytes()
    digest = hashlib.sha256(payload).hexdigest()
    if digest != _ROUND4_FIXTURE_SHA256:
        raise ValueError(
            f"{_ROUND4_FIXTURE.name} is not the pinned snapshot (sha256 {digest}, "
            f"pinned {_ROUND4_FIXTURE_SHA256})"
        )
    return json.loads(payload)


def _subject_definition_line(subject: tuple[str, str]) -> int | None:
    """1-based line of ``subject``'s top-level definition, or ``None``."""

    module_name, symbol = subject
    source_path = HERMES_ROOT / f"{module_name.replace('.', '/')}.py"
    tree = _parsed(source_path.read_text(encoding="utf-8", errors="replace"))
    for node in tree.body if tree else ():
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name == symbol:
            return node.lineno
    return None


def _top_level_test_names(lines: list[str] | None) -> frozenset[str] | None:
    tree = _parsed("\n".join(lines)) if lines is not None else None
    if tree is None:
        return None
    return frozenset(
        node.name for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    )


@functools.cache
def _upstream_side_test_names(relative: str) -> tuple[frozenset[str] | None, frozenset[str] | None]:
    """``relative``'s top-level test names at the upstream point the base had
    merged, and at the merge base the checkout carries now
    (``_fork_scope.upstream_base``) — ``None`` where that side lacks the file."""

    root = _fork_scope.repo_root()
    then = _fork_scope._git(["cat-file", "blob", f"{_ROUND4_UPSTREAM_MERGED}:{relative}"], cwd=root)
    then_lines = then.decode("utf-8", errors="replace").splitlines() if then is not None else None
    return _top_level_test_names(then_lines), _top_level_test_names(_fork_scope._upstream_text(relative))


def _upstream_retired_its_own_coverage(relative: str, test_name: str, subject: tuple[str, str]) -> bool:
    """Is this lost reference UPSTREAM's loss rather than the fork's?

    True only when all three hold: upstream wrote the subject's definition
    (``_fork_scope.is_fork_authored`` on its ``def`` line), upstream carried
    the deleted test at the point the base had merged, and the merge base the
    checkout carries now (``_fork_scope.upstream_base``) no longer does — upstream retired its own test of its own code, and a merge
    brought the deletion in. The fork's gates police the fork's lines; the fork
    may not re-add an upstream test it would then owe at every merge. Anything
    unresolvable answers False, so the finding stays counted (fail closed).
    """

    if _fork_scope.upstream_blobs() is None:
        return False
    line = _subject_definition_line(subject)
    source = f"{subject[0].replace('.', '/')}.py"
    if line is None or _fork_scope.is_fork_authored(source, line):
        return False
    then, now = _upstream_side_test_names(relative)
    return then is not None and test_name in then and (now is None or test_name not in now)


@functools.lru_cache(maxsize=1)
def _round4_uncovered_subjects() -> tuple[str, ...]:
    """Live production symbols whose last direct test reference a deletion took.

    The current test-tree parse is shared, and historical test contents are
    fetched/read in bulk. Keep this session-scoped work outside item timeouts.
    """
    global _ROUND4_HISTORY_ERROR
    covered = _covered_production_subjects()
    try:
        historical = _frozen_base_test_references()
    except (OSError, ValueError) as exc:
        # Import-time warming must not abort collection of unrelated rows, but
        # the named coverage test below must fail when the base cannot be read.
        _ROUND4_HISTORY_ERROR = (
            f"Cannot read the frozen round-4 base ({_ROUND4_COVERAGE_BASE}): {exc}"
        )
        return ()
    uncovered: list[str] = []
    for relative, base_tests in historical.items():
        current_path = HERMES_ROOT / relative
        current_tree = (
            _parsed(current_path.read_text(encoding="utf-8", errors="replace"))
            if current_path.is_file()
            else None
        )
        current_test_names = {
            node.name
            for node in (current_tree.body if current_tree else ())
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name.startswith("test_")
        }
        for test_name, subjects in base_tests.items():
            if test_name in current_test_names:
                continue
            for module_name, symbol in subjects:
                subject = (module_name, symbol)
                if (
                    _live_production_symbol(subject)
                    and subject not in covered
                    and not _upstream_retired_its_own_coverage(relative, test_name, subject)
                ):
                    uncovered.append(
                        f"{relative}::{test_name} deleted the last direct test "
                        f"reference to {module_name}.{symbol}"
                    )
    return tuple(uncovered)


# Warmed at import, like the two walks above.
_round4_uncovered_subjects()

#: Snapshotted at import so the guard fails deterministically if the warm goes.
_ROUND4_CACHE_SIZE_AT_IMPORT = _round4_uncovered_subjects.cache_info().currsize


def test_round4_deleted_tests_left_no_live_production_subject_uncovered():
    """A removed input vector may not silently erase a live symbol's coverage."""

    # The walk returns () both when nothing is uncovered and when git could not
    # answer at all, so the second case is named before the first is believed.
    assert _ROUND4_HISTORY_ERROR is None, _ROUND4_HISTORY_ERROR

    uncovered = _round4_uncovered_subjects()
    assert uncovered == (), "\n".join(uncovered)


def test_upstreams_own_retired_test_of_its_own_code_is_upstreams_loss():
    """The scope filter removes a real merge-borne deletion (negative arm).

    ``tests/gateway/test_version_command.py`` was upstream's file, upstream
    deleted it, and its subject ``hermes_cli.banner.format_banner_version_label``
    is upstream's definition; the 2026-09-24 merge brought that deletion in.
    """

    if _fork_scope.upstream_blobs() is None:
        pytest.skip("no upstream/main ref: the filter fails closed and counts everything")
    assert _upstream_retired_its_own_coverage(
        "tests/gateway/test_version_command.py",
        "test_gateway_version_command_returns_release_line",
        ("hermes_cli.banner", "format_banner_version_label"),
    )


def test_a_fork_authored_subject_is_never_upstreams_loss():
    """Positive control: the same upstream-retired test, but a subject the fork
    wrote, stays COUNTED — the filter keys on the subject's author."""

    assert not _upstream_retired_its_own_coverage(
        "tests/gateway/test_version_command.py",
        "test_gateway_version_command_returns_release_line",
        ("agent_runtime.profile_home", "configured_head_home"),
    )


def test_a_test_upstream_still_carries_is_the_forks_loss():
    """Positive control: an upstream subject whose test upstream still ships
    was deleted by the FORK, so it stays counted."""

    assert not _upstream_retired_its_own_coverage(
        "tests/hermes_cli/test_curator_status.py",
        "test_this_name_is_no_test_upstream_ever_carried",
        ("hermes_cli.curator", "register_cli"),
    )


def test_the_round4_git_walk_is_also_paid_at_import():
    """The third warm's guard.

    Three independent session-scoped computations in one file, each of which was
    billed to a single test item. This one was never over the cap on the day it
    was written — it is here because its cost grows with every commit to
    ``tests/`` while its base stays pinned.
    """

    assert _ROUND4_CACHE_SIZE_AT_IMPORT == 1, (
        "the round-4 coverage diff was NOT warmed at module import (cache size "
        f"at import: {_ROUND4_CACHE_SIZE_AT_IMPORT}). Historical source parsing is a session cost, not an item cost. Restore the warm."
    )
    assert _round4_uncovered_subjects.cache_info().misses == 1, (
        "the round-4 git walk ran more than once: "
        f"{_round4_uncovered_subjects.cache_info()}"
    )


def test_deleted_test_coverage_follows_defining_module_not_plugin_pointer():
    assert not _live_production_symbol(("hermes_cli.config", "stamp_install_method"))
    assert _live_production_symbol(("hermes_cli.install_method", "stamp_install_method"))


def test_bulk_history_keeps_deleted_and_moved_tests_and_ignores_new_tests(tmp_path):
    def git(*args):
        return subprocess.run(
            ["git", "-c", "core.hooksPath=/dev/null" if os.name != "nt" else "core.hooksPath=NUL", *args],
            cwd=tmp_path, check=True, capture_output=True, text=True,
        ).stdout.strip()

    git("init")
    git("config", "user.name", "History audit fixture")
    git("config", "user.email", "history-fixture@example.invalid")
    tests = tmp_path / "tests"
    tests.mkdir()
    before = {"test_changed.py": "old changed\n", "test_deleted.py": "deleted\n",
              "test moved.py": "moved\n", "test_unicode_é.py": "unicode\n"}
    for name, source in before.items():
        (tests / name).write_text(source, encoding="utf-8", newline="\n")
    git("add", "tests")
    git("commit", "-m", "old tests")
    base = git("rev-parse", "HEAD")
    (tests / "test_changed.py").write_text("new changed\n", encoding="utf-8", newline="\n")
    (tests / "test_deleted.py").unlink()
    (tests / "test moved.py").rename(tests / "test_renamed.py")
    (tests / "test_unicode_é.py").unlink()
    (tests / "test_added.py").write_text("new test\n", encoding="utf-8", newline="\n")
    git("add", "tests")
    git("commit", "-m", "changed tests")
    assert _historical_test_sources(tmp_path, base) == {
        f"tests/{name}": source for name, source in before.items()
    }
    assert _historical_test_sources(tmp_path, "HEAD") == {}
    with pytest.raises(subprocess.CalledProcessError):
        _historical_test_sources(tmp_path, "refs/heads/missing-history")
